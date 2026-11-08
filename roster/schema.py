"""Master-data CRUD (schema driven): employees, pods, brands, processes, assignments, holidays."""
from __future__ import annotations

import re

from .dates import DOW_NAMES
from .engine import CALENDARS
from .state import uid


def _pod(d, i):
    return next((p["name"] for p in d["pods"] if p["id"] == i), "—")


def _emp(d, i):
    return next((e["name"] for e in d["employees"] if e["id"] == i), "—")


def proc_label(d, p):
    return f"{next((b['name'] for b in d['brands'] if b['id'] == p['brand_id']), '?')} › {p['name']}"


def _brand_staff(r, d):
    pids = {p["id"] for p in d["processes"] if p["brand_id"] == r["id"]}
    return len({a["employee_id"] for a in d["assignments"] if a["role"] != "backup" and a["process_id"] in pids})


def _assign_proc(r, d):
    p = next((x for x in d["processes"] if x["id"] == r["process_id"]), None)
    return proc_label(d, p) if p else "—"


ENTITIES = {
    "employees": {
        "title": "Employees", "prefix": "E", "singular": "employee",
        "cols": [("Name", lambda r, d: r["name"]), ("Pod", lambda r, d: _pod(d, r["pod_id"])), ("Title", lambda r, d: r.get("title") or ""),
                 ("Preferred off", lambda r, d: ", ".join(DOW_NAMES[x] for x in r.get("preferred_off_days") or []) or "—"),
                 ("Offs/wk", lambda r, d: r.get("offs_per_week") or "default"), ("Max brands/day", lambda r, d: r.get("max_brands_per_day") or 3)],
        "fields": lambda d: [
            {"k": "name", "label": "Name", "type": "text", "req": True},
            {"k": "pod_id", "label": "Pod", "type": "select", "options": [(p["id"], p["name"]) for p in d["pods"]], "req": True},
            {"k": "title", "label": "Title", "type": "text"},
            {"k": "preferred_off_days", "label": "Preferred weekly-off day(s) (soft)", "type": "days"},
            {"k": "offs_per_week", "label": "Weekly offs per week", "type": "number", "help": "Leave blank to use the process default (usually 1)."},
            {"k": "max_brands_per_day", "label": "Max brands served in one day", "type": "number", "help": "Above this the validator reports a double-booking."},
        ],
    },
    "pods": {
        "title": "Pods", "prefix": "P", "singular": "pod",
        "cols": [("Pod", lambda r, d: r["name"]), ("Lead", lambda r, d: _emp(d, r.get("lead_id"))),
                 ("Members", lambda r, d: sum(1 for e in d["employees"] if e["pod_id"] == r["id"]))],
        "fields": lambda d: [
            {"k": "name", "label": "Pod name", "type": "text", "req": True},
            {"k": "lead_id", "label": "Pod lead", "type": "select", "options": [("", "— none —")] + [(e["id"], e["name"]) for e in d["employees"]]},
        ],
    },
    "brands": {
        "title": "Brands", "prefix": "B", "singular": "brand",
        "cols": [("Brand", lambda r, d: r["name"]), ("Processes", lambda r, d: ", ".join(p["name"] for p in d["processes"] if p["brand_id"] == r["id"])),
                 ("Staff", _brand_staff)],
        "fields": lambda d: [{"k": "name", "label": "Brand name", "type": "text", "req": True}],
    },
    "processes": {
        "title": "Processes & rules", "prefix": "PR", "singular": "process",
        "cols": [("Brand › Process", lambda r, d: proc_label(d, r)), ("Operating calendar", lambda r, d: CALENDARS.get(r["calendar"], r["calendar"])),
                 ("Min staff", lambda r, d: r["min_staff"]),
                 ("Special days", lambda r, d: "; ".join(f"{s['date']}: {s['min']}" for s in r.get("special_days") or []) or "—"),
                 ("Weekly off", lambda r, d: f"{r.get('offs_per_week') or 1}/wk, {r.get('off_pattern') or 'rotating'}")],
        "fields": lambda d: [
            {"k": "brand_id", "label": "Brand", "type": "select", "options": [(b["id"], b["name"]) for b in d["brands"]], "req": True},
            {"k": "name", "label": "Process name", "type": "text", "req": True},
            {"k": "calendar", "label": "Operating calendar", "type": "select", "options": list(CALENDARS.items()), "req": True},
            {"k": "min_staff", "label": "Minimum staff per operating day", "type": "number", "req": True},
            {"k": "special_days", "label": "Special-day minimums", "type": "special",
             "help": "One per line: YYYY-MM-DD | minimum | note. Overrides the calendar (even on holidays/Sundays)."},
            {"k": "offs_per_week", "label": "Weekly offs per week (default for its staff)", "type": "number"},
            {"k": "off_pattern", "label": "Weekly-off pattern", "type": "select",
             "options": [("rotating", "Rotating (any day, coverage-driven)"), ("fixed", "Fixed (strongly prefer employee’s preferred day)")]},
        ],
    },
    "assignments": {
        "title": "Assignments", "prefix": "A", "singular": "assignment",
        "cols": [("Employee", lambda r, d: _emp(d, r["employee_id"])), ("Brand › Process", _assign_proc), ("Role", lambda r, d: r["role"])],
        "fields": lambda d: [
            {"k": "employee_id", "label": "Employee", "type": "select", "options": [(e["id"], e["name"]) for e in d["employees"]], "req": True},
            {"k": "process_id", "label": "Process", "type": "select", "options": [(p["id"], proc_label(d, p)) for p in d["processes"]], "req": True},
            {"k": "role", "label": "Role", "type": "select",
             "options": [("primary", "Primary (counts toward coverage)"), ("backup", "Backup (first choice for cross-cover)")], "req": True},
        ],
    },
    "holidays": {
        "title": "Public holidays", "prefix": "H", "singular": "holiday",
        "cols": [("Date", lambda r, d: r["date"]), ("Holiday", lambda r, d: r["name"])],
        "fields": lambda d: [{"k": "date", "label": "Date", "type": "date", "req": True}, {"k": "name", "label": "Name", "type": "text", "req": True}],
    },
}


def read_form(entity: str, form, d: dict, row_id: str):
    """Parse the submitted form. Returns (row, error)."""
    E = ENTITIES[entity]
    existing = next((r for r in d[entity] if r["id"] == row_id), None) if row_id else None
    row = dict(existing) if existing else {"id": uid(E["prefix"])}
    for f in E["fields"](d):
        k = f["k"]
        if f["type"] == "days":
            row[k] = sorted(int(x) for x in form.getlist(k) if x.isdigit())
        elif f["type"] == "number":
            raw = (form.get(k) or "").strip()
            try:
                row[k] = int(float(raw)) if raw != "" else None
            except ValueError:
                return None, f"{f['label']} must be a number."
        elif f["type"] == "special":
            out = []
            for line in (form.get(k) or "").splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = [x.strip() for x in line.split("|")]
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[0] or "") or len(parts) < 2 or not re.fullmatch(r"\d+", parts[1]):
                    return None, f'Special day line not understood: "{line}"'
                out.append({"date": parts[0], "min": int(parts[1]), "note": parts[2] if len(parts) > 2 else ""})
            row[k] = out
        else:
            row[k] = (form.get(k) or "").strip()
        if f.get("req") and row[k] in ("", None):
            return None, f"{f['label']} is required."
    if entity == "assignments" and any(a["id"] != row["id"] and a["employee_id"] == row["employee_id"] and a["process_id"] == row["process_id"] for a in d["assignments"]):
        return None, "This employee is already assigned to that process."
    if entity == "processes":
        row["offs_per_week"] = row.get("offs_per_week") or 1
        row["off_pattern"] = row.get("off_pattern") or "rotating"
    if entity == "employees" and not row.get("max_brands_per_day"):
        row["max_brands_per_day"] = 3
    return row, None


def remove_row(d: dict, entity: str, row_id: str) -> None:
    """Delete with cascades so no dangling references remain."""
    d[entity] = [r for r in d[entity] if r["id"] != row_id]
    if entity == "employees":
        d["assignments"] = [a for a in d["assignments"] if a["employee_id"] != row_id]
        d["leaves"] = [l for l in d["leaves"] if l["employee_id"] != row_id]
        for p in d["pods"]:
            if p.get("lead_id") == row_id:
                p["lead_id"] = ""
    elif entity == "pods":
        fallback = d["pods"][0]["id"] if d["pods"] else ""
        for e in d["employees"]:
            if e["pod_id"] == row_id:
                e["pod_id"] = fallback
    elif entity == "brands":
        gone = {p["id"] for p in d["processes"] if p["brand_id"] == row_id}
        d["processes"] = [p for p in d["processes"] if p["brand_id"] != row_id]
        d["assignments"] = [a for a in d["assignments"] if a["process_id"] not in gone]
    elif entity == "processes":
        d["assignments"] = [a for a in d["assignments"] if a["process_id"] != row_id]
