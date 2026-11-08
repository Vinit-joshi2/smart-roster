import copy

from roster.engine import (Ctx, apply_fix, auto_repair, generate, required, set_cell, suggest_fixes, validate)
from roster.sample_data import DEFAULT_MONTH, build_sample_data

DAY = "2026-11-10"


def errors(v):
    return [i for i in v["issues"] if i["severity"] == "error"]


def owner_of_brand(d, brand_id):
    pid = next(p["id"] for p in d["processes"] if p["brand_id"] == brand_id)
    return next(a["employee_id"] for a in d["assignments"] if a["process_id"] == pid and a["role"] == "primary")


def test_sample_data_meets_the_brief():
    d = build_sample_data()
    assert len(d["employees"]) >= 30 and len(d["brands"]) == 25
    per_brand = []
    for b in d["brands"]:
        pids = {p["id"] for p in d["processes"] if p["brand_id"] == b["id"]}
        per_brand.append(len({a["employee_id"] for a in d["assignments"] if a["role"] == "primary" and a["process_id"] in pids}))
    assert sum(1 for n in per_brand if n == 1) == 20
    assert sum(1 for n in per_brand if 2 <= n <= 3) == 5


def test_operating_calendars():
    ctx = Ctx(build_sample_data())
    p = lambda cal: {"id": "x", "calendar": cal, "min_staff": 1, "special_days": [{"date": "2026-11-20", "min": 2}]}  # noqa: E731
    assert required(ctx, p("365"), "2026-11-08") == 1  # Diwali still operates
    assert required(ctx, p("ALL_EXCL_HOLIDAYS"), "2026-11-08") == 0
    assert required(ctx, p("ALL_EXCL_HOLIDAYS"), "2026-11-15") == 1  # Sunday
    assert required(ctx, p("MON_SAT"), "2026-11-15") == 0
    assert required(ctx, p("MON_SAT"), "2026-11-14") == 1
    assert required(ctx, p("MON_SAT"), "2026-11-20") == 2  # special-day override


def test_generation_is_deterministic_and_fully_covered():
    a = generate(build_sample_data(), DEFAULT_MONTH)
    b = generate(build_sample_data(), DEFAULT_MONTH)
    assert a["roster"]["cells"] == b["roster"]["cells"] and a["roster"]["covers"] == b["roster"]["covers"]
    assert a["validation"]["summary"]["coverage_pct"] == 100
    assert errors(a["validation"]) == []


def test_every_employee_gets_a_weekly_off():
    g = generate(build_sample_data(), DEFAULT_MONTH)
    assert not [i for i in g["validation"]["issues"] if i["type"] == "WEEKLY_OFF_SHORT"]


def test_no_double_booking_or_invalid_cover():
    g = generate(build_sample_data(), DEFAULT_MONTH)
    assert not [i for i in g["validation"]["issues"] if i["type"] in ("DOUBLE_BOOKING", "INVALID_COVER", "LEAVE_OVERRIDE")]


def test_change_handling_solo_owner_leave_gap_suggestion_fix():
    d = build_sample_data()
    g = generate(d, DEFAULT_MONTH)
    owner = owner_of_brand(d, "B02")  # UrbanTrek Gear
    assert g["roster"]["cells"][owner][DAY] == "W"
    d2 = copy.deepcopy(d)
    d2["leaves"].append({"id": "X", "employee_id": owner, "date": DAY, "type": "leave"})
    roster = set_cell(g["roster"], owner, DAY, "L")["roster"]
    v = validate(d2, roster)
    gap = next(i for i in v["issues"] if i["type"] == "NO_COVERAGE" and i["date"] == DAY and i["brand_id"] == "B02")
    assert "leave" in gap["cause"]
    sug = suggest_fixes(d2, roster, gap)
    assert sug and sug[0]["kind"] == "cover"
    fixed = apply_fix(roster, sug[0])
    left = [i for i in validate(d2, fixed)["issues"] if i["type"] in ("NO_COVERAGE", "UNDERSTAFFED") and i["brand_id"] == "B02" and i["date"] == DAY]
    assert left == []


def test_unsatisfiable_case_is_reported_not_hidden():
    d = build_sample_data()
    d["assignments"] = [a for a in d["assignments"] if a["role"] != "backup"]
    next(p for p in d["processes"] if p["brand_id"] == "B02")["special_days"] = [{"date": DAY, "min": 50}]
    g = generate(d, DEFAULT_MONTH)
    assert g["report"]["ok"] is False
    assert any(i["type"] == "CONFIG_SHORT" and i["severity"] == "error" for i in g["validation"]["issues"])
    assert g["validation"]["summary"]["coverage_pct"] < 100
    assert "Could not satisfy" in " ".join(g["report"]["lines"])


def test_manual_edit_overriding_leave_is_flagged_live():
    d = build_sample_data()
    g = generate(d, DEFAULT_MONTH)
    e = next(l["employee_id"] for l in d["leaves"] if l["date"] == "2026-11-11")
    assert g["roster"]["cells"][e]["2026-11-11"] == "L"
    roster = set_cell(g["roster"], e, "2026-11-11", "W")["roster"]
    assert any(i["type"] == "LEAVE_OVERRIDE" and i["employee_id"] == e for i in validate(d, roster)["issues"])


def test_double_booking_is_flagged():
    d = build_sample_data()
    g = generate(d, DEFAULT_MONTH)
    floater = next(e["id"] for e in d["employees"] if e["title"] == "Floater / backup")
    r = copy.deepcopy(g["roster"])
    r["cells"][floater][DAY] = "W"
    for b in ("B01", "B02", "B03", "B04"):
        pid = next(p["id"] for p in d["processes"] if p["brand_id"] == b)
        r["covers"].setdefault(f"{DAY}|{pid}", []).append(floater)
    assert any(i["type"] == "DOUBLE_BOOKING" and i["employee_id"] == floater for i in validate(d, r)["issues"])


def test_auto_repair_resolves_repairable_gaps():
    d = build_sample_data()
    g = generate(d, DEFAULT_MONTH)
    owner = owner_of_brand(d, "B04")
    roster = set_cell(g["roster"], owner, DAY, "L")["roster"]
    d2 = copy.deepcopy(d)
    d2["leaves"].append({"id": "Y", "employee_id": owner, "date": DAY, "type": "leave"})
    before = len(errors(validate(d2, roster)))
    assert before > 0
    assert len(errors(auto_repair(d2, roster)["validation"])) < before


def test_other_months_generate():
    for m in ("2026-12", "2027-02"):
        g = generate(build_sample_data(), m)
        assert g["validation"]["summary"]["coverage_pct"] > 90, m
