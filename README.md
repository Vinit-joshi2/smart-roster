# Smart Roster Management System

A web app that **generates, validates and edits a monthly duty roster** for a multi-brand customer-operations team – and explains clearly when a roster cannot be fully valid, instead of silently producing a bad schedule.

**Stack:** Python 3 · Flask (backend + routing) · Jinja templates with plain **HTML + CSS**  · pytest. No database, no API keys.

- **Live app:** `<paste your deployed URL here>`
- **Approach note:** [APPROACH.md](APPROACH.md)

Sample data: **36 employees · 4 pods · 25 brands (20 single-owner, 5 multi-staff) · 53 processes · 155 assignments · illustrative public holidays, leaves and comp-offs.**

---

## Quick start

Requires Python 3.10+.

```bash
git clone https://github.com/Vinit-joshi2/smart-roster && cd smart-roster
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m pytest -q          # 19 tests (engine + web app)
python app.py                # http://localhost:8080
```

Copy `.env.example` to `.env` only if you want to change `PORT`. There are **no secrets**. Each visitor gets a cookie and their own copy of the data (kept in memory and mirrored to `.state/*.json`); *Reset sample data* in the header restores the original.

### Deploy (public URL)
- **Render (free):** New → *Blueprint* → pick the repo. `render.yaml` already sets the build/start commands (`gunicorn app:app --workers 1 --threads 4`), health check `/healthz` and a generated `SECRET_KEY`.
- **Railway / Fly / any PaaS:** the `Procfile` works as-is.
- **PythonAnywhere:** point the WSGI file at `app:app`.

Keep **one worker**: per-visitor state is held in process memory. (On hosts with ephemeral disks, edits reset on redeploy – the sample data regenerates automatically.)

---

## What the app does (mapped to the brief)

| Requirement | Where |
|---|---|
| A. Master data CRUD (employees, pods, brands, processes, assignments, holidays) | **Setup** tab – forms, validation, cascading deletes |
| B. Configurable rules (calendar type, min staff, special-day minimums, weekly-off pattern) | **Setup → Processes & rules** |
| C. Monthly roster generation (+ explains when impossible) | **Generate roster** button; report banner explains unresolved items |
| D. Conflict detection (mandatory vs soft) | **Issues** tab and the side panel in every roster view |
| E. Views: company / pod / brand / process / employee + manual editing with live validation | **Roster** tab – click any cell to change it; KPIs and issues update on the spot |
| F. Handling changes after generation | **Handle a change** tab – add leave, see the gap, apply a ranked suggestion (or *Auto-repair*) |
| Optional: CSV export, backup suggestions, auto-repair | Header buttons, suggestion cards |

### 90-second demo path
1. Open the app → company view (100% mandatory coverage, cross-cover `+` markers).
2. **Brand** view → *Kaya Naturals*: coverage row shows `2/2` on the Black-Friday special days (a one-person brand that needs two people).
3. **Handle a change → ▶ Demo**: a sole brand owner (*PetPals*, Pod Bravo) takes leave on 17 Nov, when that pod's lead and floater are also on leave → gap shown with cause *Leave clash* → no designated backup is free, so the app ranks same-pod colleagues → **Apply** → blocking issues resolved.
4. Click a roster cell and set a sole owner to *Leave* on a day their brand operates → instant red issue.

---

## The 8 questions

### 1. How did you model the data?
Entities (`roster/sample_data.py`): **Pod** (lead) · **Employee** (pod, preferred off days, offs/week, max brands/day) · **Brand** · **Process** (brand, calendar, min staff, special-day minimums, weekly-off pattern) · **Assignment** (employee ↔ process, role `primary` | `backup`) · **Holiday** · **Leave** (leave | comp-off).

Two deliberate separations:
- **Operating calendar ≠ employee schedule.** `required(process, date)` derives *what the client needs* from the calendar (`365`, `ALL_EXCL_HOLIDAYS`, `MON_SAT`) + special-day override. A roster cell (`W / WO / L / CO / H`) says *what the person does*. The engine's job is to reconcile them.
- **The roster is plain data** (`cells[employee][date]` + explicit `covers["date|process"] = [employees]`). Generator, validator and manual edits all read/write the same structure, so there is one source of truth and one validator.

### 2. How does roster generation and validation work?
`roster/engine.py` – deterministic, no randomness, no dependencies beyond the standard library.

**Generator** (rule-based greedy + repair, not a black box):
1. Fix what cannot move: leave, comp-off, public holidays with no demand.
2. For each Monday–Sunday week, place weekly offs, **most constrained people first**. Each candidate day is scored: coverage deficit (×1000) ≫ preference mismatch ≫ spreading offs across days / consecutive-day limit. Days where nobody needs the person are "free".
3. **Repair pass:** if a gap remains, move an assigned person's off to another day in the same week when that does not create a new gap.
4. **Cross-cover:** any shortfall still left is filled explicitly by the best-ranked available person (designated backup → same brand → same pod → lowest load). Cover shifts are visible (`+`) and logged.
5. Run the validator and produce a report; anything unresolved is stated in plain language.

**Validator** (also runs after every manual edit): recomputes staffing per process per day (working primaries + explicit covers) and checks coverage, double-booking, leave overrides, invalid covers, weekly-off quota, consecutive days, preference misses. Every issue carries severity, whether it is *mandatory*, the date/process/employees, a **cause** (leave clash / weekly-off clash / holiday) and a human-readable message.

### 3. How do single-employee and multi-employee brands differ?
- **Single-owner brand (80% of sample):** the owner serves *all* its processes on a day. Any off on an operating day is an unavoidable gap, so the engine first prefers days the brand is closed (e.g. Sunday for `MON_SAT`), and otherwise leans on designated backups (pod lead / floater).
- **Multi-staff brand:** each process lists its own staff, with minimums > 1 (e.g. *Swift Electronics* CS needs 2 of 3 people Mon–Sat). Offs are **staggered**; overlapping staff (one person on two of Alpha's brands) are counted once per brand toward their daily brand-load limit.

### 4. What happens if the only employee of a brand is unavailable?
This is the central case. The validator reports `NO_COVERAGE` with the cause (*"Aditya Chopra (leave)"*). The app then ranks who can cover and **why**: designated backup, already on this brand, same pod, how many brands they already serve that day, public-holiday call-ins marked as *would earn a comp-off*. One click applies the cover (a single cover also closes sibling processes of the same brand that day). If nobody is eligible, the app says so explicitly and suggests structural options (add a backup, relax minimums, reschedule leave) – it never fakes coverage.

### 5. How are conflicts handled?
- **Mandatory (blocking, red):** coverage gaps, understaffing, double-booking (more brands than the person's limit), rostering someone during approved leave, covers by someone who isn't working, structurally impossible config (min staff > assigned people with no backups).
- **Soft (warnings/info):** preferred off day missed, > 6 consecutive working days, missing weekly off, cross-cover used.
- **Coverage always wins** over soft rules; the soft rule is then reported (e.g. a two-person brand forces one person to work 9 days straight because both are needed Mon–Sat).
- Manual edits are never refused – they are **validated immediately** and the delta ("⚠ +2 blocking issues" / "✓ 3 resolved") is shown in a toast.

### 6. What is automated and what is manual?
**Automated:** operating-day maths, weekly offs, repair, cross-cover, validation, impact of a new leave, ranked fix suggestions, *Auto-repair*, CSV export.
**Manual (by design):** approving leave, choosing between suggestions, overriding any cell, editing master data, deciding what to do when the report says it is impossible. Comp-off *scheduling* is not automated (earned comp-offs are shown per employee).

### 7. How would this scale to 2× employees and brands?
Measured on this machine (generate + validate one month):

| Size | Employees / processes | Time |
|---|---|---|
| 1× (sample) | 36 / 53 | ~50 ms |
| 2× | 72 / 106 | ~170 ms |
| 4× | 144 / 212 | ~0.5 s |
| 8× | 288 / 424 | ~1.8 s |

So 2× is instant. Beyond that: replace in-memory/JSON state with Postgres (`employees`, `processes`, `assignments`, `leaves`, `roster_cells`, `covers`), run generation in a background worker (Celery/RQ) so requests never block, generate **per pod** in parallel (pods are nearly independent), and swap the greedy step for an **OR-Tools CP-SAT** model for the hard-constrained core while keeping the validator unchanged as the arbiter.

### 8. What would you do with one more week?
1. Postgres + auth with roles (manager / pod lead), approval workflow for leave and roster publish.
2. CP-SAT optimiser with weekly-off *fairness* (weekend offs, holiday duty) across months, using last month's tail to avoid boundary effects.
3. Automatic comp-off scheduling and leave balances.
4. Incremental re-generation after a change that touches only the affected week/pod (keeping manual edits "pinned").
5. LLM-written conflict summaries for managers (the structured issue data is already suitable); notifications to affected people.
6. Audit log, undo/redo, Excel export with formatting, browser e2e tests in CI.

---

## Assumptions (the brief leaves gaps)
- Weekly rest is per Monday–Sunday week, default **1 off**, configurable per process/employee. Leave and comp-off days count as rest for that week; public holidays do **not** replace the weekly off.
- Weeks shorter than 4 days at the month boundary get no quota and are ignored by the consecutive-days check.
- A person can serve all processes of a brand on one day; load is measured in **distinct brands** (default max 3).
- `MON_SAT` excludes Sundays and public holidays; `ALL_EXCL_HOLIDAYS` excludes only holidays; `365` operates every day. A special-day minimum overrides the calendar.
- Someone working a public holiday earns a comp-off (shown, not auto-scheduled).
- Backups count toward coverage only when explicitly assigned as a cover (visible and removable).
- Holidays in the sample data are illustrative – edit them in Setup.

## Project layout
```
app.py                 Flask routes (pages + POST actions, CSV export, /healthz)
roster/engine.py       calendars, generator, validator, suggestions, auto-repair (pure functions)
roster/dates.py        date helpers
roster/sample_data.py  36 employees / 25 brands / holidays / leaves
roster/schema.py       master-data CRUD definitions and form parsing
roster/state.py        per-visitor state (memory + JSON mirror)
roster/views.py        view-models for the templates
templates/             Jinja HTML (base, roster, issues, changes, setup, rules)
static/style.css       all styling
tests/                 test_engine.py (11) + test_app.py (8)
demo/record_demo.py    optional: re-records the captioned demo video
```

