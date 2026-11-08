"""View-models: turn state into plain structures the Jinja templates render (no HTML here)."""
from __future__ import annotations

from .dates import DOW_NAMES, day_num, dow, label, month_days
from .engine import COVERAGE_TYPES, STATUS, Ctx, required, suggest_fixes
from .schema import proc_label

TYPE_LABEL = {"NO_COVERAGE": "No coverage", "UNDERSTAFFED": "Understaffed", "CONFIG_NO_STAFF": "Config", "CONFIG_SHORT": "Config",
              "INVALID_COVER": "Invalid cover", "LEAVE_OVERRIDE": "Leave overridden", "DOUBLE_BOOKING": "Double-booking",
              "WEEKLY_OFF_SHORT": "Weekly off", "MAX_CONSEC": "Consecutive days", "PREF_MISSED": "Preference", "COVER_USED": "Cross-cover"}
CAUSE_LABEL = {"leave": "Leave clash", "weekly_off": "Weekly-off clash", "holiday": "Holiday"}


def emp_name(s, eid):
    return next((e["name"] for e in s["data"]["employees"] if e["id"] == eid), eid)


def view_options(s, vtype):
    d = s["data"]
    if vtype == "pod":
        return [(p["id"], p["name"]) for p in d["pods"]]
    if vtype == "brand":
        return [(b["id"], b["name"]) for b in d["brands"]]
    if vtype == "process":
        return [(p["id"], proc_label(d, p)) for p in d["processes"]]
    if vtype == "employee":
        return [(e["id"], e["name"]) for e in d["employees"]]
    return []


def normalize_view(s, vtype, vid):
    if vtype not in ("company", "pod", "brand", "process", "employee"):
        vtype = "company"
    opts = view_options(s, vtype)
    if opts and vid not in {o[0] for o in opts}:
        vid = opts[0][0]
    if not opts:
        vid = ""
    return vtype, vid


def scope_info(s, vtype, vid):
    d = s["data"]
    ctx = Ctx(d)
    pids: list[str] = []
    if vtype == "brand":
        pids = [p["id"] for p in d["processes"] if p["brand_id"] == vid]
    elif vtype == "process":
        pids = [vid]
    elif vtype == "pod":
        for p in d["processes"]:
            first = (ctx.primaries.get(p["id"]) or [None])[0]
            if first and ctx.emp[first]["pod_id"] == vid:
                pids.append(p["id"])
    if vtype == "company":
        emps = d["employees"]
    elif vtype == "pod":
        emps = [e for e in d["employees"] if e["pod_id"] == vid]
    else:
        ids = {a["employee_id"] for a in d["assignments"] if a["process_id"] in pids}
        for k, lst in (s["roster"].get("covers") or {}).items():
            if k.split("|")[1] in pids:
                ids.update(lst)
        emps = [e for e in d["employees"] if e["id"] in ids]
    return emps, pids


def err_cells(s):
    out = set()
    for i in (s["validation"] or {}).get("issues", []):
        if i["severity"] != "error" or not i.get("date"):
            continue
        for e in i.get("employee_ids") or ([i["employee_id"]] if i.get("employee_id") else []):
            out.add((e, i["date"]))
    return out


def day_headers(s, days):
    hol = {h["date"]: h["name"] for h in s["data"]["holidays"]}
    return [{"date": d, "num": day_num(d), "letter": DOW_NAMES[dow(d)][0], "sun": dow(d) == 0, "hol": d in hol,
             "title": label(d) + (f" – {hol[d]}" if d in hol else "")} for d in days]


def grid_view(s, vtype, vid):
    d = s["data"]
    roster = s["roster"]
    days = month_days(roster["month"])
    emps, pids = scope_info(s, vtype, vid)
    ec = err_cells(s)
    cells = roster["cells"]
    cover_by: dict = {}
    for k, lst in (roster.get("covers") or {}).items():
        dt, pid = k.split("|")
        p = next((x for x in d["processes"] if x["id"] == pid), None)
        for e in lst:
            cover_by.setdefault((e, dt), []).append(proc_label(d, p) if p else pid)

    def row(e):
        out = []
        for dt in days:
            st = cells.get(e["id"], {}).get(dt, "W")
            cv = cover_by.get((e["id"], dt))
            out.append({"date": dt, "status": st, "text": "" if st == "W" else st, "err": (e["id"], dt) in ec, "cov": bool(cv),
                        "title": f"{e['name']} · {label(dt)} · {STATUS[st]}" + (f" · covering {', '.join(cv)}" if cv else "")})
        return {"emp": e, "cells": out}

    groups = []
    if vtype == "company":
        for p in d["pods"]:
            members = [e for e in emps if e["pod_id"] == p["id"]]
            if members:
                groups.append({"name": p["name"], "rows": [row(e) for e in members]})
        orphans = [e for e in emps if not any(p["id"] == e["pod_id"] for p in d["pods"])]
        if orphans:
            groups.append({"name": "", "rows": [row(e) for e in orphans]})
    else:
        groups.append({"name": "", "rows": [row(e) for e in emps]})

    cov_rows, cov_title = [], ""
    if pids:
        cov_title = "Coverage (staffed / required)"
        cv = s["validation"]["coverage"]
        for pid in pids:
            p = next(x for x in d["processes"] if x["id"] == pid)
            cs = []
            for dt in days:
                c = cv.get(pid, {}).get(dt)
                if not c or c["req"] <= 0:
                    cs.append({"cls": "na", "text": "–", "title": ""})
                else:
                    ok = len(c["staff"]) >= c["req"]
                    cs.append({"cls": "ok" if ok else "gap", "text": f"{len(c['staff'])}/{c['req']}",
                               "title": f"{label(dt)}: " + (", ".join(emp_name(s, x) for x in c["staff"]) or "nobody")})
            cov_rows.append({"name": proc_label(d, p), "cells": cs})
    else:
        cov_title = "Coverage gaps per day (all brands)"
        gaps: dict = {}
        for i in s["validation"]["issues"]:
            if i["type"] in COVERAGE_TYPES:
                gaps[i["date"]] = gaps.get(i["date"], 0) + 1
        cov_rows.append({"name": "Unfilled process-days", "cells": [{"cls": "gap" if gaps.get(dt) else "ok", "text": gaps.get(dt) or "✓", "title": ""} for dt in days]})
    return {"days": day_headers(s, days), "groups": groups, "cov_title": cov_title, "cov_rows": cov_rows, "ncols": len(days) + 1}


def employee_view(s, eid):
    d = s["data"]
    e = next((x for x in d["employees"] if x["id"] == eid), None)
    if not e:
        return None
    roster = s["roster"]
    days = month_days(roster["month"])
    ctx = Ctx(d)
    pe = s["validation"]["stats"]["per_emp"].get(eid, {})
    ec = err_cells(s)
    covers = roster.get("covers") or {}
    tiles = []
    for dt in days:
        st = roster["cells"].get(eid, {}).get(dt, "W")
        serving = []
        if st == "W":
            for pid in ctx.emp_primary.get(eid, []):
                if required(ctx, ctx.proc[pid], dt) > 0:
                    serving.append(proc_label(d, ctx.proc[pid]))
            for k, lst in covers.items():
                if k.startswith(dt + "|") and eid in lst:
                    serving.append("↗ " + proc_label(d, ctx.proc[k.split("|")[1]]) + " (cover)")
        tiles.append({"date": dt, "num": day_num(dt), "dow": DOW_NAMES[dow(dt)], "status": st, "label": STATUS[st], "err": (eid, dt) in ec,
                      "holiday": ctx.holidays.get(dt), "serving": serving})
    return {"emp": e, "pe": pe, "tiles": tiles, "lead": (7 + dow(days[0]) - 1) % 7,
            "pod": next((p["name"] for p in d["pods"] if p["id"] == e["pod_id"]), ""),
            "primary": [proc_label(d, ctx.proc[pid]) for pid in ctx.emp_primary.get(eid, [])], "backup_n": len(ctx.emp_backup.get(eid, []))}


def decorate_issue(s, issue, open_ids):
    """Add UI info (labels, ranked fixes when expanded)."""
    gap = issue["type"] in COVERAGE_TYPES
    is_open = issue["id"] in open_ids
    out = dict(issue)
    out["type_label"] = TYPE_LABEL.get(issue["type"], issue["type"])
    out["cause_labels"] = [CAUSE_LABEL.get(c, c) for c in issue.get("cause") or []]
    out["gap"] = gap
    out["open"] = is_open
    out["fixes"] = suggest_fixes(s["data"], s["roster"], issue)[:5] if gap and is_open else []
    out["date_label"] = label(issue["date"]) if issue.get("date") else ""
    out["cover_key"] = f"{issue['date']}|{issue['process_id']}" if issue["type"] == "COVER_USED" else ""
    return out


def scoped_issues(s, vtype, vid, open_ids):
    emps, pids = scope_info(s, vtype, vid)
    eset = {e["id"] for e in emps}
    base = [i for i in s["validation"]["issues"] if i["severity"] != "info"]
    if vtype == "employee":
        lst = [i for i in base if i.get("employee_id") == vid or vid in (i.get("employee_ids") or [])]
    elif vtype == "company":
        lst = base
    else:
        lst = [i for i in base if (i.get("process_id") in pids) or (i.get("employee_id") and i["employee_id"] in eset)]
    return len(lst), [decorate_issue(s, i, open_ids) for i in lst[:12]]
