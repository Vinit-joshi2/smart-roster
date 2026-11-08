"""Smart Roster – Flask backend. Server-rendered HTML + CSS, no JavaScript.
Run:  python app.py   (or)   gunicorn app:app
"""
from __future__ import annotations

import csv
import io
import os
import re
from urllib.parse import urlencode, urlsplit

from flask import Flask, Response, abort, g, make_response, redirect, render_template, request

from roster import state as store
from roster.dates import DOW_NAMES, label, month_days, month_label, range_days
from roster.engine import (CALENDARS, COVERAGE_TYPES, MAX_CONSEC, STATUS, Ctx, apply_fix, apply_leave_to_roster, auto_repair, generate,
                           remove_cover, required, set_cell, suggest_fixes)
from roster.schema import ENTITIES, proc_label, read_form, remove_row
from roster.views import emp_name, employee_view, grid_view, normalize_view, scoped_issues, view_options, decorate_issue

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-not-secret")  # no sessions/flash used; kept for extensions
TABS = [("roster", "Roster"), ("issues", "Issues"), ("changes", "Handle a change"), ("setup", "Setup (master data)"), ("rules", "Rules & assumptions")]


# ------------------------------------------------------------------ session plumbing
@app.before_request
def load_state():
    g.sid, g.s, g.new = store.get(request.cookies.get("sid"))


@app.after_request
def set_cookie(resp):
    if getattr(g, "new", False):
        resp.set_cookie("sid", g.sid, max_age=60 * 60 * 24 * 90, httponly=True, samesite="Lax")
    return resp


def here(**over):
    """Current URL with some query params replaced (None removes)."""
    args = {k: request.args.getlist(k) for k in request.args}
    for k, v in over.items():
        if v is None:
            args.pop(k, None)
        else:
            args[k] = v if isinstance(v, list) else [v]
    qs = urlencode([(k, x) for k, vs in args.items() for x in vs])
    return request.path + ("?" + qs if qs else "")


def safe_next(default="/roster"):
    n = request.form.get("next") or default
    u = urlsplit(n)
    return n if not u.netloc and not u.scheme and n.startswith("/") else default


def back(toast: str = "", anchor: str = ""):
    if toast:
        g.s["toast"] = toast
    store.save(g.sid, g.s)
    return redirect(safe_next() + anchor)


def errs() -> int:
    return g.s["validation"]["summary"]["errors"] if g.s.get("validation") else 0


@app.context_processor
def inject():
    s = g.s
    return {"s": s, "here": here, "TABS": TABS, "STATUS": STATUS, "label": label, "month_label": month_label, "CALENDARS": CALENDARS,
            "MAX_CONSEC": MAX_CONSEC, "DOW_NAMES": DOW_NAMES, "emp_name": lambda e: emp_name(s, e), "ENTITIES": ENTITIES, "next_url": request.full_path.rstrip("?"),
            "toast": s.pop("toast", "") if request.method == "GET" else ""}


def page(template, tab, **ctx):
    return render_template(template, tab=tab, **ctx)


# ------------------------------------------------------------------ pages
@app.get("/")
def index():
    return redirect("/roster")


@app.get("/roster")
def roster_page():
    s = g.s
    vtype, vid = normalize_view(s, request.args.get("type", "company"), request.args.get("id", ""))
    open_ids = set(request.args.getlist("open"))
    ctx = {"vtype": vtype, "vid": vid, "options": view_options(s, vtype), "stale": s["roster"]["month"] != s["month"]}
    if not ctx["stale"]:
        if vtype == "employee":
            ctx["emp_view"] = employee_view(s, vid)
        else:
            ctx["grid"] = grid_view(s, vtype, vid)
        ctx["issue_total"], ctx["issues"] = scoped_issues(s, vtype, vid, open_ids)
        menu = request.args.get("menu", "")
        if "|" in menu:
            e, d = menu.split("|", 1)
            if any(x["id"] == e for x in s["data"]["employees"]) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
                ctx["menu"] = {"e": e, "d": d, "name": emp_name(s, e), "label": label(d),
                               "has_leave": any(l["employee_id"] == e and l["date"] == d for l in s["data"]["leaves"])}
    return page("roster.html", "roster", **ctx)


@app.get("/issues")
def issues_page():
    s = g.s
    sev = request.args.getlist("sev") if "go" in request.args else ["error", "warning"]
    q = request.args.get("q", "").strip().lower()
    open_ids = set(request.args.getlist("open"))
    issues = [i for i in s["validation"]["issues"] if i["severity"] in sev and (not q or q in i["message"].lower())]
    counts = {k: sum(1 for i in s["validation"]["issues"] if i["severity"] == k) for k in ("error", "warning", "info")}
    return page("issues.html", "issues", sev=sev, q=request.args.get("q", ""), counts=counts, total=len(issues),
                items=[decorate_issue(s, i, open_ids) for i in issues[:150]])


@app.get("/changes")
def changes_page():
    s = g.s
    lc = s.get("last_change")
    remaining = []
    if lc:
        remaining = [decorate_issue(s, i, {i["id"]}) for i in s["validation"]["issues"] if i["id"] in lc["ids"]]
    leaves = sorted(s["data"]["leaves"], key=lambda l: l["date"])
    return page("changes.html", "changes", lc=lc, remaining=remaining, leaves=leaves, default_day=s["month"] + "-10")


@app.get("/setup")
def setup_page():
    s = g.s
    entity = request.args.get("entity", "employees")
    if entity not in ENTITIES:
        entity = "employees"
    E = ENTITIES[entity]
    rows = [{"id": r["id"], "cells": [str(c[1](r, s["data"])) for c in E["cols"]]} for r in s["data"][entity]]
    form = None
    edit = request.args.get("edit")
    if edit:
        row = next((r for r in s["data"][entity] if r["id"] == edit), None) if edit != "new" else None
        if edit == "new" or row:
            fields = []
            for f in E["fields"](s["data"]):
                v = (row or {}).get(f["k"])
                if f["type"] == "special":
                    v = "\n".join(f"{x['date']} | {x['min']} | {x.get('note', '')}" for x in v or [])
                if v is None:
                    v = 1 if f["k"] == "min_staff" and not row else ""
                fields.append({**f, "value": v})
            form = {"entity": entity, "id": "" if edit == "new" else edit, "fields": fields, "title": ("Edit " if row else "Add ") + E["singular"]}
    return page("setup.html", "setup", entity=entity, E=E, rows=rows, form=form)


@app.get("/rules")
def rules_page():
    return page("rules.html", "rules")


# ------------------------------------------------------------------ actions
def regenerate(month: str):
    s = g.s
    res = generate(s["data"], month)
    s.update(month=month, roster=res["roster"], report=res["report"], validation=res["validation"], stale_note="", last_change=None)
    return res


@app.post("/generate")
def generate_action():
    month = request.form.get("month", g.s["month"])
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        return back("Pick a valid month.")
    res = regenerate(month)
    sm = res["validation"]["summary"]
    return back(f"Roster generated: 100% mandatory coverage, {sm['covers']} cross-cover shift(s)." if res["report"]["ok"]
                else f"Roster generated with {sm['errors']} blocking issue(s) – see explanation.")


def edit_roster(new_roster, msg=""):
    s = g.s
    before = errs()
    s["roster"] = new_roster
    store.revalidate(s)
    delta = errs() - before
    tail = f"⚠ +{delta} blocking issue(s)." if delta > 0 else f"✓ {-delta} blocking issue(s) resolved." if delta < 0 else "No change in blocking issues."
    return f"{msg + ' ' if msg else ''}{tail}"


@app.post("/autorepair")
def autorepair_action():
    r = auto_repair(g.s["data"], g.s["roster"])
    return back(edit_roster(r["roster"], f"Auto-repair applied {len(r['applied'])} fix(es)."))


@app.post("/reset")
def reset_action():
    g.s = store.reset(g.sid)
    return back("Sample data restored and roster regenerated.")


@app.post("/cell")
def cell_action():
    s, d = g.s, g.s["data"]
    e, dt, st = request.form.get("e", ""), request.form.get("d", ""), request.form.get("status", "")
    if st not in STATUS or not any(x["id"] == e for x in d["employees"]) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", dt):
        abort(400)
    if request.form.get("cancel_leave"):
        d["leaves"] = [l for l in d["leaves"] if not (l["employee_id"] == e and l["date"] == dt)]
        return back(edit_roster(set_cell(s["roster"], e, dt, "W")["roster"], "Leave cancelled."), f"#c-{e}-{dt}")
    if st in ("L", "CO") and not any(l["employee_id"] == e and l["date"] == dt for l in d["leaves"]):
        d["leaves"].append({"id": store.uid("LV"), "employee_id": e, "date": dt, "type": "compoff" if st == "CO" else "leave", "note": "Added from roster"})
    res = set_cell(s["roster"], e, dt, st)
    extra = f" Removed {res['removed_covers']} cover assignment(s)." if res["removed_covers"] else ""
    return back(edit_roster(res["roster"], f"{emp_name(s, e)} → {STATUS[st]} on {label(dt)}.{extra}"), f"#c-{e}-{dt}")


@app.post("/fix")
def fix_action():
    s = g.s
    issue = next((i for i in s["validation"]["issues"] if i["id"] == request.form.get("issue")), None)
    fix = next((f for f in suggest_fixes(s["data"], s["roster"], issue) if f["id"] == request.form.get("fix")), None)
    if not fix:
        return back("That suggestion is no longer valid.")
    return back(edit_roster(apply_fix(s["roster"], fix), f"Applied: {fix['title']}."))


@app.post("/cover/remove")
def cover_remove():
    return back(edit_roster(remove_cover(g.s["roster"], request.form.get("key", ""), request.form.get("e", "")), "Cover removed."))


def add_leave(emp_id, start, end, typ, note):
    s, d = g.s, g.s["data"]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", start or "") or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end or "") or end < start:
        return "Choose a valid date range."
    days = range_days(start, end)
    if len(days) > 62:
        return "Date range too long (max 62 days)."
    before = {i["id"] for i in s["validation"]["issues"]}
    r = s["roster"]
    for dt in days:
        if any(l["employee_id"] == emp_id and l["date"] == dt for l in d["leaves"]):
            continue
        rec = {"id": store.uid("LV"), "employee_id": emp_id, "date": dt, "type": typ, "note": note or ""}
        d["leaves"].append(rec)
        if dt.startswith(r["month"]):
            r = apply_leave_to_roster(r, rec)["roster"]
    s["roster"] = r
    store.revalidate(s)
    new = [i for i in s["validation"]["issues"] if i["id"] not in before and i["severity"] == "error"]
    rng = start if start == end else f"{start} → {end}"
    s["last_change"] = {"title": f"{emp_name(s, emp_id)} – {'comp-off' if typ == 'compoff' else 'leave'} {rng}", "ids": [i["id"] for i in new]}
    return f"⚠ {len(new)} coverage gap(s) created – suggestions below." if new else "✓ Leave absorbed with no coverage impact."


@app.post("/leave/add")
def leave_add():
    f = request.form
    typ = f.get("type") if f.get("type") in ("leave", "compoff") else "leave"
    return back(add_leave(f.get("employee_id"), f.get("from"), f.get("to") or f.get("from"), typ, f.get("note")))


@app.post("/leave/demo")
def leave_demo():
    """Pick a sole-owner brand and put its owner on leave on the hardest day (pod backups unavailable)."""
    s, d = g.s, g.s["data"]
    ctx = Ctx(d)
    days = month_days(s["roster"]["month"])
    one_owner = []
    for b in d["brands"]:
        pids = [p["id"] for p in d["processes"] if p["brand_id"] == b["id"]]
        if len({e for pid in pids for e in ctx.primaries.get(pid, [])}) == 1:
            one_owner.append(b)
    best = None
    for dt in days[16:] + days[:16]:
        for b in one_owner:
            pr = [p for p in d["processes"] if p["brand_id"] == b["id"]]
            owner = ctx.primaries[pr[0]["id"]][0]
            owns_only = all(ctx.proc[x]["brand_id"] == b["id"] for x in ctx.emp_primary.get(owner, []))
            if (s["roster"]["cells"].get(owner, {}).get(dt) != "W" or not owns_only or not any(required(ctx, p, dt) > 0 for p in pr)
                    or any(l["employee_id"] == owner and l["date"] == dt for l in d["leaves"])):
                continue
            free = sum(1 for e in ctx.backups.get(pr[0]["id"], []) if s["roster"]["cells"].get(e, {}).get(dt) == "W")
            score = free * 100 - days.index(dt) + (-1000 if dt == days[16] else 0)
            if best is None or score < best[0]:
                best = (score, owner, dt, b)
    if not best:
        return back("No suitable day found for the demo.", "")
    _, owner, dt, b = best
    return back(add_leave(owner, dt, dt, "leave", f"Demo: sole owner of {b['name']} is unwell"))


@app.post("/leave/delete")
def leave_delete():
    s, d = g.s, g.s["data"]
    lid = request.form.get("id")
    l = next((x for x in d["leaves"] if x["id"] == lid), None)
    d["leaves"] = [x for x in d["leaves"] if x["id"] != lid]
    if l and l["date"].startswith(s["roster"]["month"]):
        s["roster"] = set_cell(s["roster"], l["employee_id"], l["date"], "W")["roster"]
    store.revalidate(s)
    return back("Leave cancelled; roster re-validated.")


@app.post("/row/save")
def row_save():
    s = g.s
    entity = request.form.get("entity")
    if entity not in ENTITIES:
        abort(400)
    row, error = read_form(entity, request.form, s["data"], request.form.get("id", ""))
    if error:
        g.s["toast"] = error
        return redirect(safe_next())
    lst = s["data"][entity]
    i = next((k for k, r in enumerate(lst) if r["id"] == row["id"]), -1)
    if i >= 0:
        lst[i] = row
    else:
        lst.append(row)
    s["stale_note"] = "Master data changed. The current roster was re-validated; regenerate to rebuild it with the new data."
    store.revalidate(s)
    return redirect_setup(entity, f"{ENTITIES[entity]['singular'].capitalize()} saved.")


@app.post("/row/delete")
def row_delete():
    s = g.s
    entity = request.form.get("entity")
    if entity not in ENTITIES:
        abort(400)
    remove_row(s["data"], entity, request.form.get("id", ""))
    s["stale_note"] = "Master data changed. The current roster was re-validated; regenerate to rebuild it with the new data."
    store.revalidate(s)
    return redirect_setup(entity, f"{ENTITIES[entity]['singular'].capitalize()} deleted.")


def redirect_setup(entity, msg):
    g.s["toast"] = msg
    store.save(g.sid, g.s)
    return redirect(f"/setup?entity={entity}")


# ------------------------------------------------------------------ exports
@app.get("/export/roster.csv")
def export_roster():
    s = g.s
    days = month_days(s["roster"]["month"])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Employee", "Pod"] + [label(d) for d in days])
    pods = {p["id"]: p["name"] for p in s["data"]["pods"]}
    for e in s["data"]["employees"]:
        w.writerow([e["name"], pods.get(e["pod_id"], "")] + [s["roster"]["cells"].get(e["id"], {}).get(d, "W") for d in days])
    return Response(buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=roster-{s['roster']['month']}.csv"})


@app.get("/export/issues.csv")
def export_issues():
    s = g.s
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Severity", "Type", "Date", "Message"])
    for i in s["validation"]["issues"]:
        w.writerow([i["severity"], i["type"], i.get("date", ""), i["message"]])
    return Response(buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=issues-{s['roster']['month']}.csv"})


@app.get("/healthz")
def healthz():
    return {"ok": True}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=os.environ.get("FLASK_DEBUG") == "1")
