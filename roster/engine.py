"""Scheduling engine: calendars -> required coverage -> generator -> validator -> fix suggestions.

Pure functions, no web code, no randomness (same input => same roster).

Data shapes (plain dicts):
  employee   {id, name, pod_id, title, preferred_off_days:[0-6], offs_per_week, max_brands_per_day}
  pod        {id, name, lead_id}
  brand      {id, name}
  process    {id, brand_id, name, calendar, min_staff, special_days:[{date,min,note}], offs_per_week, off_pattern}
  assignment {id, employee_id, process_id, role: 'primary'|'backup'}
  holiday    {id, date, name}      leave {id, employee_id, date, type: 'leave'|'compoff', note}
  roster     {month, cells:{emp:{date:status}}, covers:{"date|process":[emp]}, source}
"""
from __future__ import annotations

import copy
import math
from datetime import datetime, timezone

from .dates import dow, label, month_days, week_segments

STATUS = {"W": "Working", "WO": "Weekly off", "L": "Leave", "CO": "Comp-off", "H": "Public holiday"}
CALENDARS = {
    "365": "365 days (incl. holidays)",
    "ALL_EXCL_HOLIDAYS": "Every day except public holidays",
    "MON_SAT": "Mon–Sat (no Sundays / holidays)",
}
MAX_CONSEC = 6  # soft rule: max consecutive working days
DEFAULT_MAX_BRANDS = 3  # max distinct brands one person can serve in a day
COVERAGE_TYPES = ("NO_COVERAGE", "UNDERSTAFFED")


def js_round(x: float) -> int:
    """JavaScript Math.round (half up) – Python's round() is banker's rounding."""
    return math.floor(x + 0.5)


class Ctx:
    """Lookup tables built once per call from the master data."""

    def __init__(self, data: dict):
        self.data = data
        self.holidays = {h["date"]: h["name"] for h in data["holidays"]}
        self.leave = {(l["employee_id"], l["date"]): l["type"] for l in data["leaves"]}
        self.emp = {e["id"]: e for e in data["employees"]}
        self.proc = {p["id"]: p for p in data["processes"]}
        self.brand = {b["id"]: b for b in data["brands"]}
        self.pod = {p["id"]: p for p in data["pods"]}
        self.primaries = {p["id"]: [] for p in data["processes"]}
        self.backups = {p["id"]: [] for p in data["processes"]}
        self.emp_primary = {e["id"]: [] for e in data["employees"]}
        self.emp_backup = {e["id"]: [] for e in data["employees"]}
        for a in data["assignments"]:
            if a["employee_id"] not in self.emp or a["process_id"] not in self.proc:
                continue
            if a.get("role") == "backup":
                self.backups[a["process_id"]].append(a["employee_id"])
                self.emp_backup[a["employee_id"]].append(a["process_id"])
            else:
                self.primaries[a["process_id"]].append(a["employee_id"])
                self.emp_primary[a["employee_id"]].append(a["process_id"])


def required(ctx: Ctx, p: dict, date: str) -> int:
    """People needed on `date` for process p (0 = process does not operate)."""
    for s in p.get("special_days") or []:
        if s["date"] == date:
            return int(s["min"] or 0)
    hol = date in ctx.holidays
    mn = int(p.get("min_staff") or 0)
    cal = p["calendar"]
    if cal == "365":
        return mn
    if cal == "MON_SAT":
        return 0 if (dow(date) == 0 or hol) else mn
    return 0 if hol else mn


def cell_at(cells: dict, e: str, d: str) -> str:
    return cells.get(e, {}).get(d, "W")


def cover_key(date: str, proc_id: str) -> str:
    return f"{date}|{proc_id}"


def offs_per_week(ctx: Ctx, e: str) -> int:
    emp = ctx.emp[e]
    if emp.get("offs_per_week"):
        return int(emp["offs_per_week"])
    first = ctx.proc.get((ctx.emp_primary.get(e) or [None])[0])
    return int((first or {}).get("offs_per_week") or 1)


def off_pattern(ctx: Ctx, e: str) -> str:
    emp = ctx.emp[e]
    if emp.get("off_pattern"):
        return emp["off_pattern"]
    first = ctx.proc.get((ctx.emp_primary.get(e) or [None])[0])
    return (first or {}).get("off_pattern") or "rotating"


def seg_quota(length: int, offs: int) -> int:
    if length >= 7:
        return offs
    if length >= 4:
        return max(1, js_round(offs * length / 7))
    return 0


def cap_of(emp: dict) -> int:
    return int(emp.get("max_brands_per_day") or DEFAULT_MAX_BRANDS)


def staffing(ctx: Ctx, cells: dict, covers: dict, p: dict, date: str) -> dict:
    """Who is staffing process p on date (working primaries + working explicit covers)."""
    staff: list[str] = []
    reasons = []
    for e in ctx.primaries.get(p["id"], []):
        s = cell_at(cells, e, date)
        if s == "W":
            staff.append(e)
        else:
            reasons.append({"employee_id": e, "status": s})
    cv = covers.get(cover_key(date, p["id"]), [])
    for e in cv:
        if e in ctx.emp and cell_at(cells, e, date) == "W" and e not in staff:
            staff.append(e)
    prim = ctx.primaries.get(p["id"], [])
    return {"staff": staff, "reasons": reasons, "covered": [e for e in cv if e not in prim]}


def brand_load(ctx: Ctx, cells: dict, covers: dict, e: str, date: str) -> set:
    """Distinct brands an employee must serve on a date (own operating processes + covers)."""
    out: set = set()
    if cell_at(cells, e, date) != "W":
        return out
    for pid in ctx.emp_primary.get(e, []):
        p = ctx.proc[pid]
        if required(ctx, p, date) > 0:
            out.add(p["brand_id"])
    for k, lst in covers.items():
        if k.split("|")[0] == date and e in lst:
            p = ctx.proc.get(k.split("|")[1])
            if p:
                out.add(p["brand_id"])
    return out


def loads_for_date(ctx: Ctx, cells: dict, covers: dict, date: str) -> dict:
    """Brands each employee serves on `date`, computed in one pass."""
    out = {e: set() for e in ctx.emp}
    for e in ctx.emp:
        if cell_at(cells, e, date) != "W":
            continue
        for pid in ctx.emp_primary.get(e, []):
            p = ctx.proc[pid]
            if required(ctx, p, date) > 0:
                out[e].add(p["brand_id"])
    prefix = date + "|"
    for k, lst in covers.items():
        if not k.startswith(prefix):
            continue
        p = ctx.proc.get(k.split("|")[1])
        if not p:
            continue
        for e in lst:
            if e in out and cell_at(cells, e, date) == "W":
                out[e].add(p["brand_id"])
    return out


def find_gaps(ctx: Ctx, days: list[str], cells: dict, covers: dict) -> list[dict]:
    gaps = []
    for p in ctx.data["processes"]:
        if not ctx.primaries.get(p["id"]):
            continue
        for d in days:
            req = required(ctx, p, d)
            if req <= 0:
                continue
            n = len(staffing(ctx, cells, covers, p, d)["staff"])
            if n < req:
                gaps.append({"p": p, "date": d, "need": req - n})
    return gaps


def rank_covers(ctx: Ctx, cells: dict, covers: dict, p: dict, date: str) -> list[dict]:
    """Rank people who could cover process p on `date`. Designated backups first."""
    staff = staffing(ctx, cells, covers, p, date)["staff"]
    first_primary = (ctx.primaries.get(p["id"]) or [None])[0]
    pod_of_proc = ctx.emp[first_primary]["pod_id"] if first_primary else None
    loads = loads_for_date(ctx, cells, covers, date)
    out = []
    for emp in ctx.data["employees"]:
        if emp["id"] in staff:
            continue
        status = cell_at(cells, emp["id"], date)
        leave_fixed = (emp["id"], date) in ctx.leave
        if not (status == "W" or (status == "H" and not leave_fixed)):
            continue
        load = loads[emp["id"]] if status == "W" else set()
        adds = 0 if p["brand_id"] in load else 1
        if len(load) + adds > cap_of(emp):
            continue
        score = 0
        reasons = []
        if emp["id"] in ctx.backups.get(p["id"], []):
            score += 50
            reasons.append("Designated backup for this process")
        if any(ctx.proc[pid]["brand_id"] == p["brand_id"] for pid in ctx.emp_primary.get(emp["id"], [])):
            score += 40
            reasons.append("Already works on this brand")
        if pod_of_proc and emp["pod_id"] == pod_of_proc:
            score += 20
            reasons.append("Same pod")
        score += (cap_of(emp) - len(load) - adds) * 3
        reasons.append(
            f"Serving {len(load)} brand(s) that day (max {cap_of(emp)})" if status == "W" else "On public holiday – would earn a comp-off"
        )
        if status == "H":
            score -= 30
        out.append({"employee_id": emp["id"], "score": score, "reasons": reasons, "status": status})
    out.sort(key=lambda c: (-c["score"], c["employee_id"]))
    return out


# --------------------------------------------------------------------------- generator
def generate(data: dict, month: str, auto_cover: bool = True) -> dict:
    ctx = Ctx(data)
    days = month_days(month)
    segs = week_segments(days)
    idx = {d: i for i, d in enumerate(days)}
    cells: dict = {}
    covers: dict = {}
    gen_off: set = set()  # (emp, date) weekly offs chosen by the generator (movable)

    # 1) fixed inputs: leave / comp-off / public holidays with no demand
    for emp in data["employees"]:
        row = cells[emp["id"]] = {}
        for d in days:
            lv = ctx.leave.get((emp["id"], d))
            if lv:
                row[d] = "CO" if lv == "compoff" else "L"
            elif d in ctx.holidays and not any(required(ctx, ctx.proc[pid], d) > 0 for pid in ctx.emp_primary[emp["id"]]):
                row[d] = "H"
            else:
                row[d] = "W"

    # 2) order: most constrained first; pure backups last
    def slack(e: str) -> int:
        ps = ctx.emp_primary.get(e, [])
        if not ps:
            return 9999
        out = []
        for pid in ps:
            p = ctx.proc[pid]
            max_req = max(required(ctx, p, d) for d in days)
            out.append(len(ctx.primaries[pid]) - max_req)
        return min(out)

    order = sorted(data["employees"], key=lambda e: (slack(e["id"]), e["name"]))
    first_len = len(segs[0])
    st = {
        "off_on_date": {d: 0 for d in days},
        "def_on": {},
        "last_off": {e["id"]: (first_len - 1 if first_len < 4 else -1) for e in data["employees"]},
    }

    def cost(e: str, date: str):
        emp = ctx.emp[e]
        c = 0.0
        demand = False
        has_deficit = False
        for pid in ctx.emp_primary[e]:
            p = ctx.proc[pid]
            req = required(ctx, p, date)
            if req <= 0:
                continue
            demand = True
            avail = sum(1 for o in ctx.primaries[pid] if o != e and cell_at(cells, o, date) == "W")
            deficit = max(0, req - avail)
            if deficit:
                has_deficit = True
            c += 1000 * deficit + 10 + 6 / (1 + max(0, avail - req))
        for pid in ctx.emp_backup[e]:
            p = ctx.proc[pid]
            req = required(ctx, p, date)
            if req <= 0:
                continue
            prim = sum(1 for o in ctx.primaries[pid] if cell_at(cells, o, date) == "W")
            need = max(0, req - prim)
            if need > 0:
                others = sum(1 for b in ctx.backups[pid] if b != e and cell_at(cells, b, date) == "W")
                c += 300 * max(0, need - others)
        if not demand:
            c -= 20
        c += 2 * st["off_on_date"][date]
        if has_deficit:
            c += 40 * st["def_on"].get(f"{emp['pod_id']}|{date}", 0)
        pref = emp.get("preferred_off_days") or []
        if pref and dow(date) not in pref:
            c += 40 if off_pattern(ctx, e) == "fixed" else 8
        # consecutive working days just before `date`
        j = idx[date] - 1
        while j > st["last_off"][e] and cell_at(cells, e, days[j]) == "W":
            j -= 1
        working = idx[date] - j - 1
        if working > MAX_CONSEC:
            c += 25 * (working - MAX_CONSEC)
        if working < 2:
            c += 15
        return c, has_deficit

    # 3) weekly offs, week by week
    for seg in segs:
        for emp in order:
            e = emp["id"]
            fixed_rest = sum(1 for d in seg if cells[e][d] in ("L", "CO"))  # holidays do not replace the weekly off
            need = max(0, seg_quota(len(seg), offs_per_week(ctx, e)) - fixed_rest)
            while need > 0:
                need -= 1
                cands = [d for d in seg if cells[e][d] == "W"]
                if not cands:
                    break
                best = None
                for d in cands:
                    c, hd = cost(e, d)
                    if best is None or c < best[1]:
                        best = (d, c, hd)
                d, _, hd = best
                cells[e][d] = "WO"
                gen_off.add((e, d))
                st["off_on_date"][d] += 1
                st["last_off"][e] = idx[d]
                if hd:
                    k = f"{emp['pod_id']}|{d}"
                    st["def_on"][k] = st["def_on"].get(k, 0) + 1

    # 4) repair: try moving a weekly off away from a gap day within the same week
    def local_score(e: str, dates: list[str]) -> int:
        s = 0
        for pid in ctx.emp_primary[e]:
            p = ctx.proc[pid]
            for d in dates:
                req = required(ctx, p, d)
                if req > 0:
                    s += max(0, req - len(staffing(ctx, cells, covers, p, d)["staff"]))
        return s

    for _ in range(4):
        moved = False
        for g in find_gaps(ctx, days, cells, covers):
            seg = next(s for s in segs if g["date"] in s)
            for e in ctx.primaries[g["p"]["id"]]:
                if cell_at(cells, e, g["date"]) != "WO" or (e, g["date"]) not in gen_off:
                    continue
                for d2 in seg:
                    if cells[e][d2] != "W":
                        continue
                    before = local_score(e, [g["date"], d2])
                    cells[e][g["date"]] = "W"
                    cells[e][d2] = "WO"
                    if local_score(e, [g["date"], d2]) < before:
                        gen_off.discard((e, g["date"]))
                        gen_off.add((e, d2))
                        moved = True
                        break
                    cells[e][g["date"]] = "WO"
                    cells[e][d2] = "W"
                if moved:
                    break
            if moved:
                break
        if not moved:
            break

    # 5) cross-cover for what is still short (designated backups first)
    cover_log = []
    if auto_cover:
        gaps = sorted(find_gaps(ctx, days, cells, covers), key=lambda g: (g["date"], g["p"]["id"]))
        for g in gaps:
            for _ in range(g["need"]):
                ranked = rank_covers(ctx, cells, covers, g["p"], g["date"])
                if not ranked:
                    break
                best = ranked[0]
                covers.setdefault(cover_key(g["date"], g["p"]["id"]), []).append(best["employee_id"])
                if best["status"] == "H":
                    cells[best["employee_id"]][g["date"]] = "W"
                cover_log.append({"date": g["date"], "process_id": g["p"]["id"], "employee_id": best["employee_id"]})

    roster = {"month": month, "cells": cells, "covers": covers, "generated_at": datetime.now(timezone.utc).isoformat(), "source": "generated"}
    validation = validate(data, roster)
    errors = [i for i in validation["issues"] if i["severity"] == "error"]
    return {"roster": roster, "validation": validation, "report": _build_report(errors, cover_log)}


def _build_report(errors: list[dict], cover_log: list[dict]) -> dict:
    structural = [i for i in errors if i["type"].startswith("CONFIG")]
    gaps = [i for i in errors if i["type"] in COVERAGE_TYPES]
    lines = []
    if not errors:
        lines.append("All mandatory coverage rules are satisfied.")
    else:
        lines.append(f"Could not satisfy every mandatory rule: {len(errors)} blocking issue(s) remain.")
    if cover_log:
        lines.append(f"{len(cover_log)} shift(s) were filled by cross-cover (designated backups first).")
    lines.extend(s["message"] for s in structural)
    if gaps:
        lines.append(f"{len(gaps)} coverage gap(s) have no eligible person left – see the Issues tab for who is unavailable and why.")
    return {"ok": not errors, "lines": lines, "cover_log": cover_log}


# --------------------------------------------------------------------------- validator
def validate(data: dict, roster: dict) -> dict:
    ctx = Ctx(data)
    days = month_days(roster["month"])
    segs = week_segments(days)
    cells = roster.get("cells") or {}
    covers = roster.get("covers") or {}
    issues: list[dict] = []
    coverage: dict = {}

    def nm(e: str) -> str:
        return ctx.emp[e]["name"] if e in ctx.emp else e

    def proc_name(p: dict) -> str:
        return f"{ctx.brand.get(p['brand_id'], {}).get('name', '?')} › {p['name']}"

    def add(i: dict):
        i.setdefault("mandatory", i["severity"] == "error")
        issues.append(i)

    stats = {"required_slots": 0, "satisfied_slots": 0, "per_emp": {}}

    # structural checks
    for p in data["processes"]:
        prim = ctx.primaries.get(p["id"], [])
        bk = ctx.backups.get(p["id"], [])
        max_req = max([0] + [required(ctx, p, d) for d in days])
        if not prim:
            if max_req > 0:
                add({"id": f"CONFIG_NO_STAFF|{p['id']}", "type": "CONFIG_NO_STAFF", "severity": "error", "process_id": p["id"], "brand_id": p["brand_id"],
                     "message": f"{proc_name(p)} has no employee assigned, so it can never be covered. Assign at least one person."})
        elif len(prim) < max_req:
            tail = " – it relies on cross-cover from backups" if bk else " and has no backup, so those days cannot be met"
            add({"id": f"CONFIG_SHORT|{p['id']}", "type": "CONFIG_SHORT", "severity": "warning" if bk else "error", "process_id": p["id"], "brand_id": p["brand_id"],
                 "message": f"{proc_name(p)} needs up to {max_req} people on some days but only {len(prim)} assigned{tail}."})

    # coverage per process per day
    for p in data["processes"]:
        coverage[p["id"]] = {}
        prim = ctx.primaries.get(p["id"], [])
        for d in days:
            req = required(ctx, p, d)
            s = staffing(ctx, cells, covers, p, d)
            coverage[p["id"]][d] = {"req": req, "staff": s["staff"], "reasons": s["reasons"], "covered": s["covered"]}
            if req <= 0:
                continue
            stats["required_slots"] += req
            stats["satisfied_slots"] += min(req, len(s["staff"]))
            if len(s["staff"]) < req and prim:
                kinds = []
                for r in s["reasons"]:
                    k = "weekly_off" if r["status"] == "WO" else "holiday" if r["status"] == "H" else "leave"
                    if k not in kinds:
                        kinds.append(k)
                who = ", ".join(f"{nm(r['employee_id'])} ({STATUS.get(r['status'], r['status']).lower()})" for r in s["reasons"])
                typ = "UNDERSTAFFED" if s["staff"] else "NO_COVERAGE"
                have = f"only {len(s['staff'])}" if s["staff"] else "nobody"
                tail = f" – unavailable: {who}" if who else " (not enough people assigned)"
                add({"id": f"{typ}|{p['id']}|{d}", "type": typ, "severity": "error", "date": d, "process_id": p["id"], "brand_id": p["brand_id"],
                     "need": req, "have": len(s["staff"]), "cause": kinds, "employee_ids": [r["employee_id"] for r in s["reasons"]],
                     "message": f"{proc_name(p)} needs {req} on {label(d)} but {have} is working{tail}."})
            if s["covered"]:
                add({"id": f"COVER_USED|{p['id']}|{d}", "type": "COVER_USED", "severity": "info", "date": d, "process_id": p["id"], "brand_id": p["brand_id"],
                     "employee_ids": s["covered"], "message": f"{proc_name(p)} on {label(d)} is covered by {', '.join(nm(e) for e in s['covered'])} (cross-cover)."})

    # invalid covers
    for k, lst in covers.items():
        d, pid = k.split("|")
        p = ctx.proc.get(pid)
        for e in lst:
            if e not in ctx.emp or not p:
                continue
            s = cell_at(cells, e, d)
            if s != "W":
                add({"id": f"INVALID_COVER|{k}|{e}", "type": "INVALID_COVER", "severity": "error", "date": d, "process_id": pid, "brand_id": p["brand_id"], "employee_id": e,
                     "message": f"{nm(e)} is assigned to cover {proc_name(p)} on {label(d)} but is marked {STATUS.get(s, s)}."})

    # per-employee rules
    for emp in data["employees"]:
        e = emp["id"]
        pe = stats["per_emp"][e] = {"work": 0, "off": 0, "leave": 0, "co": 0, "holiday_work": 0, "weekend_offs": 0, "covers": 0, "brands_max": 0}
        run = 0
        pref_miss = []
        pref = emp.get("preferred_off_days") or []
        for i, d in enumerate(days):
            s = cell_at(cells, e, d)
            if s == "W":
                pe["work"] += 1
                run += 1
                if d in ctx.holidays:
                    pe["holiday_work"] += 1
            else:
                if s == "WO":
                    pe["off"] += 1
                if s == "L":
                    pe["leave"] += 1
                if s == "CO":
                    pe["co"] += 1
                if s in ("WO", "H") and dow(d) in (0, 6):
                    pe["weekend_offs"] += 1
                if s == "WO" and pref and dow(d) not in pref:
                    pref_miss.append(d)
            if s != "W" or i == len(days) - 1:
                run_adj = run
                if run_adj == i + (1 if s == "W" else 0) and len(segs[0]) < 4:  # run started at month start
                    run_adj -= len(segs[0])
                if s == "W" and i == len(days) - 1 and len(segs[-1]) < 4:
                    run_adj -= len(segs[-1])
                if run_adj > MAX_CONSEC:
                    end = days[i - (0 if s == "W" else 1)]
                    add({"id": f"MAX_CONSEC|{e}|{d}", "type": "MAX_CONSEC", "severity": "warning", "employee_id": e, "date": end,
                         "message": f"{nm(e)} works {run_adj} days in a row ending {label(end)} (recommended max {MAX_CONSEC})."})
                run = 0
            lv = ctx.leave.get((e, d))
            if lv and s != ("CO" if lv == "compoff" else "L"):
                add({"id": f"LEAVE_OVERRIDE|{e}|{d}", "type": "LEAVE_OVERRIDE", "severity": "error", "employee_id": e, "date": d,
                     "message": f"{nm(e)} has an approved {'comp-off' if lv == 'compoff' else 'leave'} on {label(d)} but is rostered as {STATUS.get(s, s)}."})
            if s == "W":
                load = brand_load(ctx, cells, covers, e, d)
                pe["brands_max"] = max(pe["brands_max"], len(load))
                if len(load) > cap_of(emp):
                    names = ", ".join(ctx.brand[b]["name"] for b in sorted(load) if b in ctx.brand)
                    add({"id": f"DOUBLE_BOOKING|{e}|{d}", "type": "DOUBLE_BOOKING", "severity": "error", "employee_id": e, "date": d,
                         "message": f"{nm(e)} is double-booked on {label(d)}: serving {len(load)} brands ({names}), limit is {cap_of(emp)}."})
        for seg in segs:
            quota = seg_quota(len(seg), offs_per_week(ctx, e))
            rest = sum(1 for d in seg if cell_at(cells, e, d) != "W")
            if rest < quota:
                add({"id": f"WEEKLY_OFF_SHORT|{e}|{seg[0]}", "type": "WEEKLY_OFF_SHORT", "severity": "warning", "employee_id": e, "date": seg[0],
                     "message": f"{nm(e)} has no weekly off in the week of {label(seg[0])} (needs {quota})."})
        if pref_miss:
            names = "/".join(["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][x] for x in pref)
            add({"id": f"PREF_MISSED|{e}", "type": "PREF_MISSED", "severity": "info", "employee_id": e, "dates": pref_miss,
                 "message": f"{nm(e)}: weekly off missed the preferred day ({names}) on {len(pref_miss)} week(s): {', '.join(label(x) for x in pref_miss)}."})
        pe["covers"] = sum(1 for lst in covers.values() if e in lst)

    rank = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: (rank[i["severity"]], i.get("date", ""), i["id"]))
    count = lambda sev: sum(1 for i in issues if i["severity"] == sev)  # noqa: E731
    summary = {
        "errors": count("error"),
        "warnings": count("warning"),
        "infos": count("info"),
        "coverage_pct": round(stats["satisfied_slots"] / stats["required_slots"] * 1000) / 10 if stats["required_slots"] else 100,
        "required_slots": stats["required_slots"],
        "satisfied_slots": stats["satisfied_slots"],
        "covers": sum(len(v) for v in covers.values()),
    }
    return {"issues": issues, "coverage": coverage, "stats": stats, "summary": summary}


# --------------------------------------------------------------------------- suggestions
def suggest_fixes(data: dict, roster: dict, issue: dict | None) -> list[dict]:
    """Ways to close a coverage-gap issue: move a weekly off, or cross-cover by someone."""
    if not issue or issue["type"] not in COVERAGE_TYPES:
        return []
    ctx = Ctx(data)
    days = month_days(roster["month"])
    cells = roster["cells"]
    covers = roster.get("covers") or {}
    p = ctx.proc[issue["process_id"]]
    date = issue["date"]
    out = []
    seg = next(s for s in week_segments(days) if date in s)

    # (a) move a weekly off of an assigned person to another day that week
    for e in ctx.primaries.get(p["id"], []):
        if cell_at(cells, e, date) != "WO":
            continue
        for d2 in seg:
            if cell_at(cells, e, d2) != "W" or (e, d2) in ctx.leave:
                continue
            safe = True
            for pid in ctx.emp_primary[e]:
                q = ctx.proc[pid]
                req = required(ctx, q, d2)
                if req > 0 and len([x for x in staffing(ctx, cells, covers, q, d2)["staff"] if x != e]) < req:
                    safe = False
            if not safe:
                continue
            prefs = ctx.emp[e].get("preferred_off_days") or []
            pref_ok = not prefs or dow(d2) in prefs
            out.append({"id": f"swap|{e}|{date}|{d2}", "kind": "swap_off", "employee_id": e, "date": date, "to_date": d2, "process_id": p["id"],
                        "score": 70 + (5 if pref_ok else 0),
                        "title": f"Move {ctx.emp[e]['name']}'s weekly off from {label(date)} to {label(d2)}",
                        "reasons": ["No new gap on the new day", "Matches preferred off day" if pref_ok else "Not their preferred off day"]})
            break

    # (b) cross-cover (also closes gaps on sibling processes of the same brand that day)
    siblings = [
        q["id"] for q in data["processes"]
        if q["brand_id"] == p["brand_id"] and ctx.primaries.get(q["id"]) and required(ctx, q, date) > len(staffing(ctx, cells, covers, q, date)["staff"])
    ]
    for c in rank_covers(ctx, cells, covers, p, date)[:5]:
        out.append({"id": f"cover|{c['employee_id']}|{date}|{p['id']}", "kind": "cover", "employee_id": c["employee_id"], "date": date, "process_id": p["id"],
                    "process_ids": siblings or [p["id"]], "score": c["score"], "status": c["status"],
                    "title": f"{ctx.emp[c['employee_id']]['name']} covers {ctx.brand[p['brand_id']]['name']} › {p['name']} on {label(date)}",
                    "reasons": c["reasons"]})
    out.sort(key=lambda f: -f["score"])
    return out


def apply_fix(roster: dict, fix: dict) -> dict:
    r = copy.deepcopy(roster)
    r.setdefault("covers", {})
    if fix["kind"] == "swap_off":
        r["cells"][fix["employee_id"]][fix["date"]] = "W"
        r["cells"][fix["employee_id"]][fix["to_date"]] = "WO"
    elif fix["kind"] == "cover":
        for pid in fix.get("process_ids") or [fix["process_id"]]:
            lst = r["covers"].setdefault(cover_key(fix["date"], pid), [])
            if fix["employee_id"] not in lst:
                lst.append(fix["employee_id"])
        if r["cells"][fix["employee_id"]].get(fix["date"]) == "H":
            r["cells"][fix["employee_id"]][fix["date"]] = "W"
    r["source"] = "edited"
    return r


def auto_repair(data: dict, roster: dict) -> dict:
    """Greedy auto-repair for blocking gaps using the best suggestion each time."""
    r = roster
    applied = []
    for _ in range(200):
        v = validate(data, r)
        gap = next((i for i in v["issues"] if i["type"] in COVERAGE_TYPES and suggest_fixes(data, r, i)), None)
        if not gap:
            break
        fix = suggest_fixes(data, r, gap)[0]
        r = apply_fix(r, fix)
        applied.append(fix)
    return {"roster": r, "applied": applied, "validation": validate(data, r)}


# --------------------------------------------------------------------------- manual edits
def set_cell(roster: dict, e: str, d: str, status: str) -> dict:
    r = copy.deepcopy(roster)
    r["cells"].setdefault(e, {})[d] = status
    removed = 0
    if status != "W":
        for k in list(r.get("covers", {})):
            if k.split("|")[0] != d:
                continue
            before = len(r["covers"][k])
            r["covers"][k] = [x for x in r["covers"][k] if x != e]
            removed += before - len(r["covers"][k])
            if not r["covers"][k]:
                del r["covers"][k]
    r["source"] = "edited"
    return {"roster": r, "removed_covers": removed}


def remove_cover(roster: dict, key: str, e: str) -> dict:
    r = copy.deepcopy(roster)
    r["covers"][key] = [x for x in r["covers"].get(key, []) if x != e]
    if not r["covers"][key]:
        del r["covers"][key]
    r["source"] = "edited"
    return r


def apply_leave_to_roster(roster: dict, leave: dict) -> dict:
    return set_cell(roster, leave["employee_id"], leave["date"], "CO" if leave["type"] == "compoff" else "L")
