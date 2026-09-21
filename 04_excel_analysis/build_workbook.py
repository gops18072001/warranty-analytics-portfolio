"""
Builds Warranty_Analysis.xlsx from warranty.db.

The point of this workbook is that it contains *formulas*, not pasted values.
Every figure on the scorecard, trend and Pareto sheets is a live SUMIFS /
COUNTIFS / AVERAGE against the Batch_Data sheet, so a reviewer can click any
cell and see how it was derived - and so the workbook re-computes if the
underlying extract is refreshed.

Only the Batch_Data sheet holds hard numbers, and those come straight out of
SQL. Everything downstream is derived in Excel, which is how this would be
built on the job.

Run:  python3 build_workbook.py
"""

import sqlite3
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.formatting.rule import CellIsRule, ColorScaleRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HERE = Path(__file__).resolve().parent
DB = HERE.parent / "01_sql_warranty_analytics" / "warranty.db"
OUT = HERE / "Warranty_Analysis.xlsx"

NAVY = "1F3864"
LIGHT = "D9E1F2"
GREY = "F2F2F2"

HEAD_FILL = PatternFill("solid", fgColor=NAVY)
HEAD_FONT = Font(color="FFFFFF", bold=True, size=10)
TITLE_FONT = Font(color=NAVY, bold=True, size=14)
NOTE_FONT = Font(color="595959", size=9, italic=True)
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def header(ws, row, labels, widths=None):
    for i, label in enumerate(labels, start=1):
        c = ws.cell(row=row, column=i, value=label)
        c.fill, c.font = HEAD_FILL, HEAD_FONT
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = BOX
    if widths:
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[row].height = 28


def title(ws, text, note=None):
    ws["A1"] = text
    ws["A1"].font = TITLE_FONT
    if note:
        ws["A2"] = note
        ws["A2"].font = NOTE_FONT


con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
wb = Workbook()

# ---------------------------------------------------------------- Batch_Data
# One row per production batch with its claims rolled up. This is the only
# sheet with hard numbers; it is the SQL extract everything else points at.
ws = wb.active
ws.title = "Batch_Data"

rows = con.execute(
    """
    SELECT b.batch_id,
           b.production_date,
           substr(b.production_date, 1, 7) AS month,
           p.plant_name,
           s.supplier_name,
           s.tier,
           c.component_name,
           c.category,
           b.vehicle_model,
           b.units_produced,
           COUNT(w.claim_id)                     AS claims,
           COALESCE(SUM(w.claim_cost_inr), 0)    AS claim_cost_inr
    FROM production_batches b
    JOIN plants     p ON p.plant_id     = b.plant_id
    JOIN suppliers  s ON s.supplier_id  = b.supplier_id
    JOIN components c ON c.component_id = b.component_id
    LEFT JOIN warranty_claims w ON w.batch_id = b.batch_id
    GROUP BY b.batch_id
    ORDER BY b.production_date
    """
).fetchall()

COLS = ["Batch ID", "Production Date", "Month", "Plant", "Supplier", "Tier",
        "Component", "Category", "Vehicle Model", "Units Produced",
        "Claims", "Claim Cost (INR)"]
header(ws, 1, COLS, widths=[10, 15, 9, 20, 20, 7, 24, 14, 15, 14, 9, 16])
for r in rows:
    ws.append(list(r))

N = len(rows)
LAST = N + 1
for row in ws.iter_rows(min_row=2, max_row=LAST, min_col=10, max_col=12):
    for c in row:
        c.number_format = "#,##0"
ws.freeze_panes = "A2"
ws.auto_filter.ref = f"A1:L{LAST}"

D = "Batch_Data"
UNITS = f"{D}!$J$2:$J${LAST}"
CLAIMS = f"{D}!$K$2:$K${LAST}"
COST = f"{D}!$L$2:$L${LAST}"
SUP = f"{D}!$E$2:$E${LAST}"
MONTH = f"{D}!$C$2:$C${LAST}"
PLANT = f"{D}!$D$2:$D${LAST}"

# -------------------------------------------------------- Supplier_Scorecard
ws = wb.create_sheet("Supplier_Scorecard")
title(ws, "Supplier Scorecard",
      "Every cell below is a SUMIFS against Batch_Data. Nothing is pasted.")
header(ws, 4,
       ["Supplier", "Tier", "Units Produced", "Claims", "Claim Cost (INR)",
        "Claim Rate", "Cost per Unit (INR)", "vs Fleet Avg (pp)", "Status"],
       widths=[22, 8, 16, 12, 18, 11, 18, 17, 14])

suppliers = con.execute(
    "SELECT supplier_name, tier FROM suppliers ORDER BY supplier_name"
).fetchall()

first = 5
for i, s in enumerate(suppliers):
    r = first + i
    ws.cell(r, 1, s["supplier_name"])
    ws.cell(r, 2, s["tier"])
    ws.cell(r, 3, f'=SUMIF({SUP},$A{r},{UNITS})').number_format = "#,##0"
    ws.cell(r, 4, f'=SUMIF({SUP},$A{r},{CLAIMS})').number_format = "#,##0"
    ws.cell(r, 5, f'=SUMIF({SUP},$A{r},{COST})').number_format = "#,##0"
    ws.cell(r, 6, f'=IFERROR($D{r}/$C{r},0)').number_format = "0.00%"
    ws.cell(r, 7, f'=IFERROR($E{r}/$C{r},0)').number_format = "#,##0.00"
    ws.cell(r, 8, f'=($F{r}-$F${first + len(suppliers) + 1})*100').number_format = "+0.00;-0.00"
    ws.cell(r, 9, f'=IF($F{r}>$F${first + len(suppliers) + 1}*1.5,"Investigate",'
                  f'IF($F{r}>$F${first + len(suppliers) + 1},"Watch","OK"))')
    for col in range(1, 10):
        ws.cell(r, col).border = BOX

tot = first + len(suppliers)
ws.cell(tot, 1, "FLEET TOTAL").font = Font(bold=True)
ws.cell(tot, 3, f"=SUM(C{first}:C{tot - 1})").number_format = "#,##0"
ws.cell(tot, 4, f"=SUM(D{first}:D{tot - 1})").number_format = "#,##0"
ws.cell(tot, 5, f"=SUM(E{first}:E{tot - 1})").number_format = "#,##0"
ws.cell(tot, 6, f"=D{tot}/C{tot}").number_format = "0.00%"
ws.cell(tot, 7, f"=E{tot}/C{tot}").number_format = "#,##0.00"
for col in range(1, 10):
    ws.cell(tot, col).fill = PatternFill("solid", fgColor=LIGHT)
    ws.cell(tot, col).font = Font(bold=True)
    ws.cell(tot, col).border = BOX

# Fleet average claim rate, referenced by the variance and status columns.
avg = tot + 1
ws.cell(avg, 1, "Fleet average claim rate").font = Font(bold=True)
ws.cell(avg, 6, f"=$F${tot}").number_format = "0.00%"
ws.cell(avg, 6).font = Font(bold=True, color=NAVY)

rng = f"F{first}:F{tot - 1}"
ws.conditional_formatting.add(rng, ColorScaleRule(
    start_type="min", start_color="C6EFCE",
    mid_type="percentile", mid_value=50, mid_color="FFEB9C",
    end_type="max", end_color="FFC7CE"))
ws.conditional_formatting.add(f"I{first}:I{tot - 1}", CellIsRule(
    operator="equal", formula=['"Investigate"'],
    fill=PatternFill("solid", fgColor="FFC7CE"), font=Font(color="9C0006", bold=True)))

chart = BarChart()
chart.type = "col"
chart.title = "Claim rate by supplier"
chart.y_axis.title = "Claim rate"
chart.height, chart.width = 8, 16
chart.add_data(Reference(ws, min_col=6, min_row=4, max_row=tot - 1), titles_from_data=True)
chart.set_categories(Reference(ws, min_col=1, min_row=first, max_row=tot - 1))
chart.legend = None
ws.add_chart(chart, f"A{avg + 3}")

# ------------------------------------------------------------ Monthly_Trend
ws = wb.create_sheet("Monthly_Trend")
title(ws, "Monthly Claim Trend",
      "Claim rate with a 3-month moving average. Read the last few months with "
      "care: recent batches have had less time to fail, so their rate is "
      "understated (right-censoring).")
header(ws, 4, ["Month", "Units Produced", "Claims", "Claim Rate",
               "3-Month Moving Avg"], widths=[12, 16, 12, 12, 20])

months = [r[0] for r in con.execute(
    f"SELECT DISTINCT substr(production_date,1,7) AS m FROM production_batches ORDER BY m")]

first = 5
for i, m in enumerate(months):
    r = first + i
    ws.cell(r, 1, m)
    ws.cell(r, 2, f'=SUMIF({MONTH},$A{r},{UNITS})').number_format = "#,##0"
    ws.cell(r, 3, f'=SUMIF({MONTH},$A{r},{CLAIMS})').number_format = "#,##0"
    ws.cell(r, 4, f'=IFERROR($C{r}/$B{r},0)').number_format = "0.00%"
    if i >= 2:
        ws.cell(r, 5, f'=AVERAGE($D{r - 2}:$D{r})').number_format = "0.00%"
    for col in range(1, 6):
        ws.cell(r, col).border = BOX
mlast = first + len(months) - 1

line = LineChart()
line.title = "Claim rate by production month"
line.y_axis.title = "Claim rate"
line.height, line.width = 9, 20
line.add_data(Reference(ws, min_col=4, max_col=5, min_row=4, max_row=mlast), titles_from_data=True)
line.set_categories(Reference(ws, min_col=1, min_row=first, max_row=mlast))
ws.add_chart(line, f"G{first}")

# ------------------------------------------------------------------ Pareto
# Component x defect cost needs claim-level detail, so this one is aggregated
# in SQL. The cumulative % column is still a live formula.
ws = wb.create_sheet("Pareto_Cost_Drivers")
title(ws, "Pareto - where the warranty money goes",
      "Cumulative % is a running SUM formula; sorted descending by cost.")
header(ws, 4, ["Component", "Defect", "Claims", "Claim Cost (INR)",
               "% of Total", "Cumulative %"], widths=[24, 24, 10, 18, 12, 14])

pareto = con.execute(
    """
    SELECT c.component_name, d.defect_name,
           COUNT(*) AS claims, SUM(w.claim_cost_inr) AS cost
    FROM warranty_claims w
    JOIN production_batches b ON b.batch_id = w.batch_id
    JOIN components c ON c.component_id = b.component_id
    JOIN defect_types d ON d.defect_id = w.defect_id
    GROUP BY c.component_name, d.defect_name
    ORDER BY cost DESC
    LIMIT 20
    """
).fetchall()

first = 5
for i, p in enumerate(pareto):
    r = first + i
    ws.cell(r, 1, p["component_name"])
    ws.cell(r, 2, p["defect_name"])
    ws.cell(r, 3, p["claims"]).number_format = "#,##0"
    ws.cell(r, 4, p["cost"]).number_format = "#,##0"
    ws.cell(r, 5, f'=$D{r}/SUM($D${first}:$D${first + len(pareto) - 1})').number_format = "0.0%"
    ws.cell(r, 6, f'=SUM($E${first}:$E{r})').number_format = "0.0%"
    for col in range(1, 7):
        ws.cell(r, col).border = BOX
plast = first + len(pareto) - 1

bar = BarChart()
bar.type = "col"
bar.title = "Top cost drivers (component / defect)"
bar.height, bar.width = 9, 20
bar.add_data(Reference(ws, min_col=4, min_row=4, max_row=plast), titles_from_data=True)
bar.set_categories(Reference(ws, min_col=1, min_row=first, max_row=plast))
bar.legend = None
ws.add_chart(bar, f"H{first}")

# ------------------------------------------------------------------- README
ws = wb.create_sheet("README", 0)
ws.column_dimensions["A"].width = 100
lines = [
    ("Warranty Analysis Workbook", TITLE_FONT),
    ("", None),
    ("Source: warranty.db (SQLite), built by projects/01_sql_warranty_analytics.", None),
    ("The data is SYNTHETIC - generated with a fixed seed to mirror the structure of", None),
    ("automotive warranty data, with known issues planted so the analysis can be", None),
    ("verified against ground truth. It is not real manufacturer data.", None),
    ("", None),
    ("Sheets", Font(bold=True, color=NAVY, size=11)),
    ("  Batch_Data            One row per production batch, claims rolled up. The SQL", None),
    ("                        extract. The only sheet containing hard numbers.", None),
    ("  Supplier_Scorecard    SUMIFS by supplier, claim rate vs fleet average,", None),
    ("                        conditional formatting, status flag.", None),
    ("  Monthly_Trend         Claim rate by production month with a 3-month moving", None),
    ("                        average and a line chart.", None),
    ("  Pareto_Cost_Drivers   Top 20 component/defect pairs by cost, with cumulative %.", None),
    ("", None),
    ("Note on reading the trend", Font(bold=True, color=NAVY, size=11)),
    ("  The most recent months look better than they are. A batch produced last month", None),
    ("  has had weeks to fail, not years, so its claim rate is understated. Judge a", None),
    ("  batch only once it has had comparable time in the field.", None),
    ("", None),
    ("Rebuild:  python3 build_workbook.py", NOTE_FONT),
]
for i, (text, font) in enumerate(lines, start=1):
    c = ws.cell(i, 1, text)
    if font:
        c.font = font

wb.save(OUT)
print(f"wrote {OUT}  ({OUT.stat().st_size/1024:.0f} KB, {N:,} batch rows)")
