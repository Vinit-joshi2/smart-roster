"""Realistic, fictional sample data: 4 pods, 36 employees, 25 brands (20 single-owner, 5 multi-staff).
Public holidays are illustrative only (verify against your own calendar)."""
from __future__ import annotations

PODS = [
    ("P1", "Pod Alpha", "Aarav Mehta"),
    ("P2", "Pod Bravo", "Kavya Nair"),
    ("P3", "Pod Charlie", "Rohan Desai"),
    ("P4", "Pod Delta", "Sneha Kulkarni"),
]

# per pod: lead, floater, 3 multi-brand staff, 4 single-brand handlers (9 people)
NAMES = {
    "P1": {"floater": "Ishaan Gupta", "multi": ["Priya Sharma", "Rahul Verma", "Ananya Iyer"], "solo": ["Vikram Singh", "Meera Joshi", "Arjun Reddy", "Diya Kapoor"]},
    "P2": {"floater": "Tanvi Patel", "multi": ["Karan Malhotra", "Neha Bansal", "Siddharth Rao"], "solo": ["Pooja Menon", "Aditya Chopra", "Riya Banerjee", "Manish Yadav"]},
    "P3": {"floater": "Harsh Vora", "multi": ["Simran Kaur", "Nikhil Shetty", "Aisha Khan"], "solo": ["Devansh Jain", "Shreya Ghosh", "Kunal Thakur", "Lavanya Pillai"]},
    "P4": {"floater": "Yash Agarwal", "multi": ["Zoya Siddiqui", "Tarun Mishra", "Bhavna Rathore"], "solo": ["Omkar Patil", "Nandini Das", "Varun Bhatt", "Isha Saxena"]},
}

# single-owner brands: 5 per pod. Handler 0 of each pod runs two brands.  process spec: (code, calendar, min_staff)
SOLO_BRANDS = {
    "P1": [
        ("Kaya Naturals", [("CS", "MON_SAT", 1), ("ACC", "ALL_EXCL_HOLIDAYS", 1)]),
        ("UrbanTrek Gear", [("CS", "MON_SAT", 1), ("NDR", "MON_SAT", 1)]),
        ("Bloom & Co", [("CS", "365", 1), ("ACC", "365", 1), ("RET", "ALL_EXCL_HOLIDAYS", 1)]),
        ("FitFuel", [("CS", "ALL_EXCL_HOLIDAYS", 1), ("ACC", "ALL_EXCL_HOLIDAYS", 1)]),
        ("Spice Route Foods", [("CS", "MON_SAT", 1), ("NDR", "MON_SAT", 1), ("RET", "MON_SAT", 1)]),
    ],
    "P2": [
        ("Nimbus Audio", [("CS", "MON_SAT", 1), ("NDR", "ALL_EXCL_HOLIDAYS", 1)]),
        ("Loom & Thread", [("CS", "MON_SAT", 1)]),
        ("PetPals", [("CS", "365", 1), ("NDR", "365", 1)]),
        ("Glow Theory", [("CS", "ALL_EXCL_HOLIDAYS", 1), ("ACC", "ALL_EXCL_HOLIDAYS", 1), ("RET", "MON_SAT", 1)]),
        ("Brew Republic", [("CS", "MON_SAT", 1), ("ACC", "MON_SAT", 1)]),
    ],
    "P3": [
        ("Zenith Watches", [("CS", "MON_SAT", 1), ("ACC", "MON_SAT", 1)]),
        ("Nest Home", [("CS", "MON_SAT", 1)]),
        ("Velvet Cases", [("CS", "ALL_EXCL_HOLIDAYS", 1), ("NDR", "ALL_EXCL_HOLIDAYS", 1)]),
        ("Pixel Play Toys", [("CS", "365", 1), ("ACC", "ALL_EXCL_HOLIDAYS", 1)]),
        ("Aarogya Herbals", [("CS", "MON_SAT", 1), ("RET", "MON_SAT", 1)]),
    ],
    "P4": [
        ("Craft Kulhad", [("CS", "MON_SAT", 1), ("ACC", "MON_SAT", 1)]),
        ("Stride Footwear", [("CS", "MON_SAT", 1), ("NDR", "MON_SAT", 1)]),
        ("Mint Mobiles", [("CS", "ALL_EXCL_HOLIDAYS", 1), ("NDR", "ALL_EXCL_HOLIDAYS", 1), ("ACC", "ALL_EXCL_HOLIDAYS", 1)]),
        ("Oak & Ivory", [("CS", "MON_SAT", 1)]),
        ("Saffron Sweets", [("CS", "365", 1), ("RET", "ALL_EXCL_HOLIDAYS", 1)]),
    ],
}

# multi-staff brands: (name, pod, [(code, calendar, min, [staff idx])]); staff idx indexes the pod's three "multi" employees
MULTI_BRANDS = [
    ("Luxe Beauty Hub", "P1", [("CS", "MON_SAT", 2, [0, 1]), ("ACC", "ALL_EXCL_HOLIDAYS", 1, [0])]),
    ("Haven Furnishings", "P1", [("CS", "MON_SAT", 1, [1, 2]), ("NDR", "ALL_EXCL_HOLIDAYS", 1, [2])]),
    ("Swift Electronics", "P2", [("CS", "MON_SAT", 2, [0, 1, 2]), ("ACC", "ALL_EXCL_HOLIDAYS", 1, [1]), ("NDR", "ALL_EXCL_HOLIDAYS", 1, [2])]),
    ("Trendline Apparel", "P3", [("CS", "ALL_EXCL_HOLIDAYS", 2, [0, 1, 2]), ("RET", "MON_SAT", 1, [0])]),
    ("Veda Wellness", "P4", [("CS", "365", 2, [0, 1, 2]), ("ACC", "ALL_EXCL_HOLIDAYS", 1, [1]), ("NDR", "MON_SAT", 1, [2])]),
]

PROCESS_NAMES = {"CS": "Customer Support", "ACC": "Abandoned Cart Conversion", "NDR": "NDR", "RET": "Retention"}
PREFS = [[0], [0], [6], [0, 6], [2], [0], [3], [0, 6], [5], [0]]
DEFAULT_MONTH = "2026-11"


def build_sample_data() -> dict:
    pods, employees, brands, processes, assignments = [], [], [], [], []
    n = {"e": 0, "b": 0, "p": 0, "a": 0}

    def add_emp(name, pod_id, **extra):
        n["e"] += 1
        eid = f"E{n['e']:02d}"
        row = {"id": eid, "name": name, "pod_id": pod_id, "preferred_off_days": list(PREFS[(n["e"] - 1) % len(PREFS)]),
               "max_brands_per_day": 3, "offs_per_week": None, "title": ""}
        row.update(extra)
        employees.append(row)
        return eid

    def assign(emp_id, proc_id, role="primary"):
        n["a"] += 1
        assignments.append({"id": f"A{n['a']:03d}", "employee_id": emp_id, "process_id": proc_id, "role": role})

    def add_proc(brand_id, code, calendar, mn):
        n["p"] += 1
        pid = f"PR{n['p']:03d}"
        processes.append({"id": pid, "brand_id": brand_id, "name": PROCESS_NAMES[code], "calendar": calendar, "min_staff": mn,
                          "special_days": [], "offs_per_week": 1, "off_pattern": "fixed" if calendar == "MON_SAT" else "rotating"})
        return pid

    staff = {}
    for pod_id, pod_name, lead in PODS:
        lead_id = add_emp(lead, pod_id, title="Pod Lead", preferred_off_days=[0])
        pods.append({"id": pod_id, "name": pod_name, "lead_id": lead_id})
        nm = NAMES[pod_id]
        floater = add_emp(nm["floater"], pod_id, title="Floater / backup")
        multi = [add_emp(x, pod_id, title="Associate") for x in nm["multi"]]
        solo = [add_emp(x, pod_id, title="Associate") for x in nm["solo"]]
        staff[pod_id] = {"lead": lead_id, "floater": floater, "multi": multi, "solo": solo}

    backups = []
    for pod_id, _, _ in PODS:
        s = staff[pod_id]
        for i, (name, procs) in enumerate(SOLO_BRANDS[pod_id]):
            n["b"] += 1
            bid = f"B{n['b']:02d}"
            brands.append({"id": bid, "name": name})
            owner = s["solo"][max(0, i - 1)]  # brand 0 and 1 -> handler 0 (two brands)
            for code, cal, mn in procs:
                pid = add_proc(bid, code, cal, mn)
                assign(owner, pid)
                backups += [(s["floater"], pid), (s["lead"], pid)]
    for name, pod_id, procs in MULTI_BRANDS:
        n["b"] += 1
        bid = f"B{n['b']:02d}"
        brands.append({"id": bid, "name": name})
        for code, cal, mn, idxs in procs:
            pid = add_proc(bid, code, cal, mn)
            for k in idxs:
                assign(staff[pod_id]["multi"][k], pid)
            backups.append((staff[pod_id]["floater"], pid))
    for e, p in backups:
        assign(e, p, "backup")

    by_name = {e["name"]: e["id"] for e in employees}
    next(e for e in employees if e["name"] == "Karan Malhotra")["offs_per_week"] = 2  # 5-day week

    # sale days: single-owner brands that need 2 people => forces cross-cover
    kaya = next(p for p in processes if p["name"] == "Customer Support" and p["brand_id"] == "B01")
    kaya["special_days"] = [{"date": "2026-11-27", "min": 2, "note": "Black Friday sale"}, {"date": "2026-11-28", "min": 2, "note": "Black Friday sale"}]
    pet = next(p for p in processes if p["name"] == "Customer Support" and p["brand_id"] == "B08")
    pet["special_days"] = [{"date": "2026-11-27", "min": 2, "note": "Black Friday sale"}]

    holidays = [(d, nm) for d, nm in [
        ("2026-10-02", "Gandhi Jayanti"), ("2026-10-20", "Dussehra"), ("2026-11-08", "Diwali"), ("2026-11-24", "Guru Nanak Jayanti"),
        ("2026-12-25", "Christmas"), ("2027-01-01", "New Year's Day"), ("2027-01-26", "Republic Day")]]
    holidays = [{"id": f"H{i + 1}", "date": d, "name": nm} for i, (d, nm) in enumerate(holidays)]

    def lv(i, who, date, typ, note):
        return {"id": f"LV{i}", "employee_id": by_name[who], "date": date, "type": typ, "note": note}

    leaves = [
        lv(1, "Priya Sharma", "2026-11-11", "leave", "Family function"),
        lv(2, "Priya Sharma", "2026-11-12", "leave", "Family function"),
        lv(3, "Karan Malhotra", "2026-11-16", "leave", "Medical"),
        lv(4, "Zoya Siddiqui", "2026-11-19", "compoff", "Worked Diwali weekend"),
        lv(5, "Simran Kaur", "2026-11-25", "leave", "Travel"),
        lv(6, "Simran Kaur", "2026-11-26", "leave", "Travel"),
        lv(7, "Kavya Nair", "2026-11-17", "leave", "Pod lead leave (backup unavailable)"),
        lv(8, "Tanvi Patel", "2026-11-17", "leave", "Floater leave (same day)"),
    ]
    return {"pods": pods, "employees": employees, "brands": brands, "processes": processes,
            "assignments": assignments, "holidays": holidays, "leaves": leaves}
