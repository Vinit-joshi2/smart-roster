# Approach note – Smart Roster Management System

**Problem framing.** This is a constraint-satisfaction problem, not a calendar UI. Clients need people on specific days (the *operating calendar*); people need rest (*weekly offs, leave, comp-offs*). The system's job is to bridge the two and to be honest when it can't.

**Architecture.** A Python/Flask app. All scheduling logic lives in one pure, deterministic module (`roster/engine.py`): `required()` turns calendars + special days into per-day demand; `generate()` builds a roster; `validate()` audits *any* roster (generated or hand-edited); `suggest_fixes()/apply_fix()/auto_repair()` close gaps. Flask routes only call these functions and hand view-models to Jinja templates, so the generator and the live validator can never disagree. The UI is plain HTML + CSS rendered on the server – no JavaScript, no database.

**Key decisions and trade-offs.**
1. *Validator first.* One validator is the single source of truth; the generator is judged by it. Manual edits are allowed and flagged rather than blocked.
2. *Rule-based greedy + repair instead of a solver.* At this size (36 people, ~1,500 required slots) it solves in ~50 ms, is explainable (every choice is a cost term) and has no native dependencies. The trade-off is no global optimality guarantee; OR-Tools CP-SAT is the documented path for larger scale.
3. *Cross-cover is explicit data.* A backup covering a brand is a visible, removable assignment – not a hidden count – so double-booking is checkable and managers see who is stretched.
4. *Mandatory vs soft.* Coverage and leave integrity are mandatory; preferences, consecutive days and spread are soft. Coverage wins and the sacrificed soft rule is reported.
5. *Honesty over silence.* Structurally impossible setups (minimum > staff, no backups) and unfillable gaps are reported with causes (leave clash, weekly-off clash) and options.
6. *Server-rendered UI.* Every action is a form post + redirect, so the app works without JS and each state is a shareable URL (view, selected cell, expanded issue).

**Verification.** 19 pytest tests: 11 on the engine (calendars, determinism, 100% coverage on the sample month, weekly-off quotas, double-booking, leave overrides, solo-owner-on-leave change flow, an infeasible configuration, other months) and 8 end-to-end through Flask's test client (pages, change flow, live edits, CRUD validation, open-redirect guard, exports, session isolation). The engine output was also cross-checked cell-for-cell against the first JavaScript implementation for three months.

**Assumptions** are listed in the README (weekly-rest definition, load per distinct brand, holiday/comp-off handling, boundary weeks).
