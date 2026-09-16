# Warranty & Quality Dashboard — Power BI build spec

Three pages over the same six CSVs produced by project 01.

This document and `measures.dax` are the source of truth for the report: page
layout, the field behind every visual, the model relationships, and all 14 DAX
measures.

---

## 1. Load

`Get Data → Text/CSV` for each file in `../01_sql_warranty_analytics/csv/`:

```
plants.csv  suppliers.csv  components.csv
defect_types.csv  production_batches.csv  warranty_claims.csv
```

In **Transform Data**, set types before loading:

| Column | Type |
|---|---|
| `production_date`, `failure_date` | Date |
| `units_produced`, `claims`, `days_to_failure` | Whole number |
| `claim_cost_inr`, `baseline_defect_rate` | Decimal number |

## 2. Model (Model view)

Build a star. Drag to create these one-to-many relationships:

```
plants[plant_id]           1 → *  production_batches[plant_id]
suppliers[supplier_id]     1 → *  production_batches[supplier_id]
components[component_id]   1 → *  production_batches[component_id]
production_batches[batch_id] 1 → * warranty_claims[batch_id]
defect_types[defect_id]    1 → *  warranty_claims[defect_id]
```

Add a date table so time intelligence works, then mark it as a date table
(`Table tools → Mark as date table → Date`):

```dax
DimDate =
ADDCOLUMNS (
    CALENDAR ( DATE ( 2024, 1, 1 ), DATE ( 2026, 12, 31 ) ),
    "Year",      YEAR ( [Date] ),
    "MonthNum",  MONTH ( [Date] ),
    "Month",     FORMAT ( [Date], "MMM yyyy" ),
    "Quarter",   "Q" & QUARTER ( [Date] ) & " " & YEAR ( [Date] )
)
```

Relate `DimDate[Date] 1 → * warranty_claims[failure_date]`. Sort the `Month`
column by `MonthNum` (`Column tools → Sort by column`) or the axis orders
alphabetically.

## 3. Measures

Import `measures.dax` — create a blank table called `_Measures` and paste each
one in. All 14 are in that file with comments.

## 4. Pages

### Page 1 — Executive Summary

**KPI cards** across the top: `Total Units Produced`, `Total Claims`,
`Claim Rate %`, `Total Warranty Cost`, `Cost per Unit`.

| Visual | Type | Fields |
|---|---|---|
| Claims trend | Line | Axis `DimDate[Month]`, values `Total Claims` and `Claims 3M Moving Avg` |
| Cost by supplier | Stacked bar | Axis `suppliers[supplier_name]`, value `Total Warranty Cost`, legend `defect_types[severity]` |
| Claim rate by plant | Clustered bar | Axis `plants[plant_name]`, value `Claim Rate %` |
| Severity split | Donut | Legend `defect_types[severity]`, value `Total Claims` |

**Slicers** (top right): `DimDate[Year]`, `suppliers[tier]`, `components[category]`.

### Page 2 — Supplier Scorecard

| Visual | Type | Fields |
|---|---|---|
| Scorecard | Table | `supplier_name`, `tier`, `Total Units Produced`, `Total Claims`, `Claim Rate %`, `Cost per Unit`, `Claim Rate vs Prev Quarter` |
| Quarterly trend | Line | Axis `DimDate[Quarter]`, values `Claim Rate %`, legend `supplier_name` |
| Cost Pareto | Line and stacked column | Axis `component_name`, column `Total Warranty Cost`, line `Cumulative Cost %` |

Conditional formatting on `Claim Rate %` in the table: `Format → Cell elements
→ Background color → Rules`. Green below 1%, amber 1–2.5%, red above 2.5%.
Shreeji Connectors should light up red — that is the finding the page exists
to make unmissable.

### Page 3 — Defect Detail

| Visual | Type | Fields |
|---|---|---|
| Component × defect | Matrix | Rows `component_name`, columns `defect_name`, values `Total Claims`, heat-map background |
| Time to failure | Column | Axis `days_to_failure` binned by 30, value `Total Claims`, legend `severity` |
| Exception list | Table | `batch_id`, `production_date`, `component_name`, `supplier_name`, `Claim Rate %`, filtered to `Claim Rate %` > 5% |
| Defect category | Treemap | Group `defect_category`, value `Total Warranty Cost` |

Wire `production_batches[vehicle_model]` as a slicer and enable cross-filtering
so clicking a defect filters the batch list.

---

## What the dashboard should show when finished

If the model is correct, these four findings fall out of it. They are worth
checking as a validation step:

1. **Shreeji Connectors is the problem.** 4.8% claim rate against a 1.8% fleet
   average, and 52% of total warranty cost from 20% of units.
2. **It degraded, it was not always bad.** ~4.0% through 2024, then 5.9% in
   2025-Q2 and 9.7% in 2025-Q3 — a step change, not drift. Something happened
   in mid-2025.
3. **Older plants run hotter.** Gurugram (2012) at 2.13% versus Chennai (2021)
   at 1.61% — about a third more claims per unit.
4. **Connector-related defects dominate.** `Intermittent Signal`, `Solder
   Crack` and `Connector Loose` on Connector Assembly and Switch Panel are the
   top six cost pairs, over half of all warranty spend.

**The last two quarters must not be reported as an improvement.** Claims arrive
20–400 days after production, so recent batches have not had time to fail. Every
supplier looks like it is improving in 2026-Q2; none of them is. Page 2 carries a
note to that effect, and the comparison visuals filter to batches at least 180
days old.
