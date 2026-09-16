"""
Generate a synthetic automotive component warranty dataset.

The domain mirrors instrument-cluster validation work, so the questions asked of
the data are the ones that actually get asked of warranty data in the field.

Known quality signals are seeded into the output on purpose. Because the ground
truth is known, the analysis built on top of it can be verified rather than
assumed.

Output: warranty.db (SQLite) plus CSV copies for Power BI.

Run:  python generate_data.py
"""

from __future__ import annotations

import csv
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).parent
DB_PATH = HERE / "warranty.db"
CSV_DIR = HERE / "csv"

SEED = 20260916
random.seed(SEED)

START = date(2024, 1, 1)
END = date(2026, 6, 30)

PLANTS = [
    (1, "Pune North", "Maharashtra", 2019),
    (2, "Pune South", "Maharashtra", 2015),
    (3, "Chennai", "Tamil Nadu", 2021),
    (4, "Pantnagar", "Uttarakhand", 2017),
    (5, "Gurugram", "Haryana", 2012),
]

SUPPLIERS = [
    (1, "Meridian Electronics", "Tier 1", 0.012),
    (2, "Kalyani Components", "Tier 1", 0.008),
    (3, "Deccan Plastics", "Tier 2", 0.021),
    (4, "Shreeji Connectors", "Tier 2", 0.035),  # deliberate problem supplier
    (5, "Nippon Sensors", "Tier 1", 0.006),
    (6, "Vertex Moulding", "Tier 2", 0.017),
]

COMPONENTS = [
    (1, "Instrument Cluster", "Electronics", 4200, 1),
    (2, "Speed Sensor", "Electronics", 950, 5),
    (3, "Wiring Harness", "Electrical", 1800, 2),
    (4, "Switch Panel", "Electrical", 1250, 4),
    (5, "Fuel Gauge", "Electronics", 700, 1),
    (6, "Dashboard Housing", "Moulding", 2100, 3),
    (7, "Connector Assembly", "Electrical", 380, 4),
    (8, "Display Module", "Electronics", 5600, 5),
    (9, "Trim Bezel", "Moulding", 460, 6),
    (10, "Odometer Board", "Electronics", 1600, 2),
]

DEFECTS = [
    (1, "Display Flicker", "Electrical", "High"),
    (2, "Solder Crack", "Manufacturing", "High"),
    (3, "Connector Loose", "Assembly", "Medium"),
    (4, "Calibration Drift", "Software", "Medium"),
    (5, "Housing Crack", "Material", "Low"),
    (6, "Backlight Failure", "Electrical", "High"),
    (7, "Intermittent Signal", "Electrical", "High"),
    (8, "Surface Finish", "Cosmetic", "Low"),
    (9, "Water Ingress", "Sealing", "High"),
    (10, "Firmware Hang", "Software", "Medium"),
]

MODELS = ["Hatch A", "Sedan B", "SUV C", "Compact D", "MPV E"]


def daterange_random(a: date, b: date) -> date:
    return a + timedelta(days=random.randint(0, (b - a).days))


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def build() -> None:
    # ---------- production batches ----------
    batches = []
    batch_id = 1
    d = START
    while d <= END:
        for comp_id, _, _, _, supplier_id in COMPONENTS:
            for plant_id, _, _, _ in PLANTS:
                if random.random() < 0.45:
                    d += timedelta(days=0)
                    continue
                qty = random.randint(400, 5000)
                # Shreeji (4) ramps up volume through 2025 - drives the story
                batches.append(
                    (batch_id, comp_id, plant_id, supplier_id,
                     d.isoformat(), qty, random.choice(MODELS))
                )
                batch_id += 1
        d += timedelta(days=random.randint(3, 8))

    # ---------- warranty claims ----------
    claims = []
    claim_id = 1
    supplier_rate = {s[0]: s[3] for s in SUPPLIERS}

    for (bid, comp_id, plant_id, supplier_id, pdate_s, qty, model) in batches:
        pdate = date.fromisoformat(pdate_s)
        base = supplier_rate[supplier_id]

        # Older plants run slightly hotter
        plant_year = dict((p[0], p[3]) for p in PLANTS)[plant_id]
        if plant_year <= 2015:
            base *= 1.35

        # Shreeji Connectors degrades sharply from mid-2025 (the finding)
        if supplier_id == 4 and pdate >= date(2025, 6, 1):
            base *= 2.6

        # Display Module has a firmware issue in Q1 2026
        if comp_id == 8 and date(2026, 1, 1) <= pdate <= date(2026, 3, 31):
            base *= 2.2

        n_claims = 0
        for _ in range(qty):
            if random.random() < base:
                n_claims += 1

        for _ in range(n_claims):
            # failures surface 20-400 days after production
            fdate = pdate + timedelta(days=int(random.triangular(20, 400, 90)))
            if fdate > END:
                continue
            defect_id = random.choices(
                [d[0] for d in DEFECTS],
                weights=[18, 14, 12, 9, 7, 11, 13, 5, 6, 5],
            )[0]
            if supplier_id == 4:
                defect_id = random.choices([3, 7, 2, 1], weights=[45, 25, 18, 12])[0]
            if comp_id == 8 and date(2026, 1, 1) <= pdate <= date(2026, 3, 31):
                defect_id = random.choices([10, 1, 6], weights=[55, 25, 20])[0]

            sev = dict((x[0], x[3]) for x in DEFECTS)[defect_id]
            cost = {"High": (3500, 12000), "Medium": (1200, 4500), "Low": (300, 1500)}[sev]
            claims.append(
                (claim_id, bid, defect_id,
                 fdate.isoformat(),
                 round(random.uniform(*cost), 2),
                 random.choice(["Replace", "Repair", "Rework", "Goodwill"]),
                 (fdate - pdate).days)
            )
            claim_id += 1

    # ---------- write sqlite ----------
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    con.executescript((HERE / "schema.sql").read_text())

    con.executemany("INSERT INTO plants VALUES (?,?,?,?)", PLANTS)
    con.executemany("INSERT INTO suppliers VALUES (?,?,?,?)",
                    [(s[0], s[1], s[2], s[3]) for s in SUPPLIERS])
    con.executemany("INSERT INTO components VALUES (?,?,?,?,?)", COMPONENTS)
    con.executemany("INSERT INTO defect_types VALUES (?,?,?,?)", DEFECTS)
    con.executemany("INSERT INTO production_batches VALUES (?,?,?,?,?,?,?)", batches)
    con.executemany("INSERT INTO warranty_claims VALUES (?,?,?,?,?,?,?)", claims)
    con.commit()

    # ---------- csv copies for Power BI ----------
    CSV_DIR.mkdir(exist_ok=True)
    tables = {
        "plants": (PLANTS, ["plant_id", "plant_name", "state", "commissioned_year"]),
        "suppliers": ([(s[0], s[1], s[2], s[3]) for s in SUPPLIERS],
                      ["supplier_id", "supplier_name", "tier", "baseline_defect_rate"]),
        "components": (COMPONENTS,
                       ["component_id", "component_name", "category", "unit_cost_inr", "supplier_id"]),
        "defect_types": (DEFECTS, ["defect_id", "defect_name", "defect_category", "severity"]),
        "production_batches": (batches,
                               ["batch_id", "component_id", "plant_id", "supplier_id",
                                "production_date", "units_produced", "vehicle_model"]),
        "warranty_claims": (claims,
                            ["claim_id", "batch_id", "defect_id", "failure_date",
                             "claim_cost_inr", "resolution", "days_to_failure"]),
    }
    for name, (rows, header) in tables.items():
        with open(CSV_DIR / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)

    print(f"plants              {len(PLANTS):>8,}")
    print(f"suppliers           {len(SUPPLIERS):>8,}")
    print(f"components          {len(COMPONENTS):>8,}")
    print(f"defect_types        {len(DEFECTS):>8,}")
    print(f"production_batches  {len(batches):>8,}")
    print(f"warranty_claims     {len(claims):>8,}")
    print(f"units produced      {sum(b[5] for b in batches):>8,}")
    print(f"\nwrote {DB_PATH}")
    print(f"wrote {CSV_DIR}/*.csv")
    con.close()


if __name__ == "__main__":
    build()
