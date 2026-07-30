# CITIMART™ Sales KPI Dashboard Report

A production-oriented Streamlit dashboard that profiles `salesdata.xlsx`, detects its
schema through configurable aliases, keeps sales detail separate from store-day
operational facts, calculates supported retail KPIs, validates forecasting models
chronologically, and exports the active filtered view as PDF/CSV.

## Current workbook findings

The supplied workbook contains `NM1`, `NM2`, `HB1`, `HB2`, `CHW1`, and `CHW2`.
`NM` is treated as the workbook's New Market prefix alias for the configured `NW`
store code.

- The `1` sheets are division/section/department detail with date, bill quantity,
  net amount, and gross amount.
- The `2` sheets are one-row-per-store-date summaries. NM2, HB2, and CHW2 include
  CitiMart's manual `SALE_TARGET`, sales, footfall, NOB, ATV, RPV, conversion,
  achievement, and basket size.
- HB1 contains Hatibagan sales detail and the updated HB2 contains meaningful
  store-day sales, footfall, and NOB. Hatibagan is therefore active in report
  calculations, Detailed Tables, Data Quality, and generated PDFs.
- Detail and store-day facts are never many-to-many merged. Only a validated
  one-to-one `store_code + date` reconciliation is used.
- January detail totals are materially lower than the daily summary for NM and CHW.
  Overall KPIs use the daily summary; hierarchy-filtered sales use detail and the
  dashboard warns about this scope change.
- Product, SKU, brand, category, cost/COGS, promotion flag, and transaction
  ID do not exist in the current workbook. Unsupported cards and empty fields are
  omitted rather than fabricated.
- Red-font subtotal/calculation rows are excluded because valid fact records must
  contain a usable date.

The Data Quality tab contains live sheet dimensions, detected mappings, retained
rows, date ranges, invalid values, potential duplicate-line counts, reconciliation
variance, warnings, and KPI availability.

## Features

- Wide retail-management layout with a sticky right-side filter panel
- Explicit source-data reload control for workbook corrections made while the app is running
- Multi-store, date, and dependent division/section/department filters
- Dynamic schema aliases and automatic future sheet/store detection
- Integer/rounded dashboard values, explicit percentage suffixes, and DD-MM-YYYY dates
- Calendar quarters: Q1 January–March, Q2 April–June, Q3 July–September,
  Q4 October–December
- Hover/focus KPI cards, previous comparable-period deltas, gauges, scorecards,
  and KPI table
- Net/gross and division-wise sales, separate Footfall vs NoB and conversion
  percentage charts with table view, monthly bridge,
  daily/weekday, target, same-day, same-month, hierarchy, discount-association,
  and forecast views
- Chart/table tabs and downloads of the currently filtered data
- Chronological validation of seasonal naive, moving average, Ridge, Random Forest,
  and histogram gradient boosting models
- Filtered ReportLab PDF with division performance table and optional chart images
- Missing-field-safe calculations and data-quality reporting
- Modular source and automated calculation/loader/filter/forecast tests

## Folder structure

```text
.
├── app.py
├── salesdata.xlsx
├── requirements.txt
├── requirement.txt
├── .streamlit/
│   └── config.toml
├── assets/
├── reports/                  # PDF export scratch space (git-ignored)
├── config/
│   ├── __init__.py
│   ├── settings.py
│   ├── column_aliases.py
│   └── kpi_thresholds.py
├── src/
│   ├── data_loader.py
│   ├── data_cleaner.py
│   ├── schema_detector.py
│   ├── filter_engine.py
│   ├── kpi_engine.py
│   ├── comparison_engine.py
│   ├── forecasting.py
│   ├── forecast_input.py
│   ├── color_rules.py
│   ├── charts.py
│   ├── tables.py
│   ├── formatting.py
│   ├── pdf_report.py
│   └── ui_components.py
└── tests/
    ├── conftest.py
    ├── test_data_loader.py
    ├── test_filters.py
    ├── test_forecast_input.py
    ├── test_forecasting.py
    ├── test_kpi_engine.py
    └── test_pdf_report.py
```

## Prerequisites and installation

- Python 3.11 or later
- Windows, macOS, or Linux
- The updated workbook placed beside `app.py` as `salesdata.xlsx`

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Run tests:

```powershell
pytest
```

The source workbook is read-only from the application's perspective and is never
renamed or modified.

## Filters and source scope

The default view includes every available store and the entire workbook date range.
When all divisions, sections, and departments are selected, store-day summary sales drive
headline KPIs. Quantity is sourced exclusively from `SUM_OF_BILL_QUANTITY` in the
store-day summary sheets. When a division, section, or department subset is active, sales
come from the detail fact and stay exact.

Footfall, NOB, target, and units are never captured per division/section/department in
this workbook, so under a hierarchy filter they are **estimated**: each store-day's total
is prorated by that day's share of net sales held by the filtered selection
(`src/kpi_engine.py:prorate_daily_by_hierarchy_share`). ATV, RPV, basket size, conversion,
and target achievement are then recomputed from the exact filtered net sales divided by
that estimate. Every estimated card, gauge, table row, and PDF line is labelled
"Estimated"; net sales, gross sales, and discount stay exact throughout.

The selected division also controls net/gross sales charts, monthly and daily
sales trends, same-period comparisons, store sales scorecards, footfall/NoB and
conversion charts, target achievement, and forecasting.
The Sales Performance tab includes a ranked division table with net sales, gross
sales, discount, detail quantity, sales days, average daily sales, share, and rank.

## KPI formulas

| KPI | Formula/source |
|---|---|
| Net sales | Sum of summary `SALE`; detail `NET_AMOUNT` under hierarchy filters |
| Gross sales | Sum of detail `GROSS_AMOUNT` where supported |
| NOB | Sum of pre-aggregated daily `NOB`; never detail-row count |
| ATV | Net sales ÷ NOB |
| Revenue per visitor | Net sales ÷ footfall |
| Total Units Sold | Sum of `SUM_OF_BILL_QUANTITY` from NM2, HB2, and CHW2 |
| Basket size | `SUM_OF_BILL_QUANTITY` ÷ NOB |
| Conversion | NOB ÷ footfall |
| Target achievement | Net sales ÷ target |
| Target | Sum of CitiMart's manual `SALE_TARGET` |
| Discount | Gross sales − net sales |

Safe division returns N/A for missing or zero denominators.

KPI colour bands are loaded from the workbook's `COLOUR FORMATTING`
worksheet:

- ATV: red below ₹900; yellow from ₹900 through ₹1,100; green above ₹1,100
- RPV: red below ₹500; yellow from ₹500 through ₹700; green above ₹700
- Basket Size: red below 2; yellow from 2 through 5; green above 5
- Conversion: red below 45%; yellow from 45% through 55%; green above 55%
- Achievement: red below 80%; yellow from 80% through 100%; green above 100%

Cards, gauges, scorecards, tables, charts, and PDF exports use these workbook
rules. KPIs without an instruction in the worksheet are shown as Neutral.

## Forecasting methodology

Daily net sales are preferred. Sparse data falls back to weekly or monthly
aggregation. Features include calendar fields, lag 1/7/14/28, and past-only rolling
7/14/28 averages. All rolling values start from `sales.shift(1)`, preventing future
leakage. Models are compared on the final chronological holdout using MAE, RMSE,
MAPE, WAPE, and R². The selected model has the lowest supported holdout RMSE, with
future values produced recursively. The displayed error band is an approximate
validation-RMSE band, not a probabilistic guarantee.

The Forecast controls allow either **Current dashboard view** or **Upload XLSX**.
Uploaded workbooks must contain at least one worksheet with `DATE` and a recognized
sales column such as `SALE`, `NET SALES`, `NET AMOUNT`, `SALES AMOUNT`, or `REVENUE`.
The app supports both the paired CITIMART sheet format and a normal single-sheet
history file. By default the complete uploaded history is used. Enable **Apply
current dashboard filters** only when the upload contains compatible store and
DIVISION/SECTION/DEPARTMENT fields.

The forecast cache key includes the selected daily history, source workbook identity,
active scope, and forecast horizon.

## PDF generation

Choose filters, then click **Generate PDF Report** in the right panel. The PDF
contains filter context, KPIs, comparison tables, forecast overview, warnings,
branding, footer, and page numbers. Click **Download PDF** when generation finishes.
The export includes every available KPI gauge plus net/gross sales, monthly and
daily sales, target achievement, division sales, Footfall vs NoB, conversion,
and forecast charts. Each chart receives a dedicated landscape page. Kaleido
renders the charts in one batch; if a specific image export is unavailable, the
PDF still generates with its tables and a clear warning.

## Adding Hatibagan or future stores

Hatibagan is active in the current workbook. If a future workbook contains an
empty/incomplete HB1 or HB2 pair, Hatibagan is reported as skipped and does not
affect totals. Supplying valid detail and store-day sales reactivates it
automatically.

For a future store:

1. Add its store code/name and accepted sheet prefixes in `config/settings.py`.
2. Use the established `1` detail and `2` daily-summary suffixes, or extend
   `src/schema_detector.py` if the relationship differs.
3. Add new header synonyms to `config/column_aliases.py`.
4. Restart Streamlit; years, dates, hierarchy values, and stores are detected
   dynamically.

Manual worksheet renaming is not required.

## Troubleshooting

- **Workbook not found:** place `salesdata.xlsx` beside `app.py`.
- **A KPI is not shown:** inspect Data Quality → KPI Availability and Detected Schemas.
- **Charts show "Estimated" under hierarchy filters:** the current workbook has no
  footfall/NOB/target broken out by division/section/department, so those measures are
  prorated by the filtered selection's net-sales share instead of measured directly. Net
  sales, gross sales, and discount are always exact.
- **PDF chart image omitted:** reinstall compatible Plotly/Kaleido versions with
  `pip install -r requirements.txt`; table content is still included.
- **Forecast not trained:** widen the date filter. Daily forecasting requires at
  least 60 daily observations and enough rows after lag creation.
- **Uploaded forecast not trained:** confirm that the XLSX has usable `DATE` and
  `SALE`/`NET SALES` values and enough distinct dates. Disable current-view filtering
  if the uploaded history uses a different date range.
- **Large future workbooks:** the modular loader can later be backed by Parquet,
  DuckDB, or Polars without changing KPI/chart contracts.

## Known limitations

The current source lacks transaction IDs, product/SKU/brand/category,
COGS, time-of-day, and promotion flags. Consequently, profit KPIs, product and
brand rankings, promotion causality, and time filters are intentionally omitted
until those fields are added.
Exact duplicate-looking detail rows are reported but not dropped because, without a
transaction/SKU key, identical purchases may be legitimate.

Footfall, NOB, target, and units also have no true per-division/section/department
source in this workbook. Under a hierarchy filter, `src/kpi_engine.py` estimates
them by prorating each store-day's total by the filtered selection's share of that
day's net sales, and labels every such value "Estimated" wherever it is shown (cards,
gauges, tables, charts, PDF). These figures are a sales-weighted approximation, not a
measured count — treat them accordingly for decisions that need exact bill- or
footfall-level accuracy. Getting exact values would require the POS export to include
a bill/transaction ID and per-division footfall capture, which the source workbook
does not currently provide.
