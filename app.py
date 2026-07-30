"""CITIMART™ interactive sales KPI dashboard."""

from __future__ import annotations

import importlib
import hashlib
import logging
import sys
from datetime import datetime
from pathlib import Path

# Make local config/src imports and workbook discovery independent of the folder
# from which Streamlit is launched.
APP_DIRECTORY = Path(__file__).resolve().parent
if str(APP_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(APP_DIRECTORY))

import numpy as np
import pandas as pd
import streamlit as st
import config.kpi_thresholds as kpi_thresholds
import src.charts as charts
import src.color_rules as color_rules
import src.data_loader as data_loader
import src.filter_engine as filter_engine
import src.formatting as formatting
import src.kpi_engine as kpi_engine
import src.pdf_report as pdf_report
import src.ui_components as ui_components

from config.settings import APP_TITLE, STORE_NAMES
from src.comparison_engine import previous_period_bounds
from src.forecast_input import (
    UploadedForecastWorkbook,
    load_uploaded_forecast_workbook,
    prepare_uploaded_forecast_history,
)
from src.forecasting import ForecastResult, train_forecast
from src.tables import to_csv_bytes

# Streamlit can retain older imported modules while rerunning a changed app.py.
# Reload these small modules so their return contracts stay aligned with the UI.
kpi_thresholds = importlib.reload(kpi_thresholds)
gauge_assessment = kpi_thresholds.gauge_assessment
color_rules = importlib.reload(color_rules)
data_loader = importlib.reload(data_loader)
WorkbookData = data_loader.WorkbookData
load_workbook_data = data_loader.load_workbook_data
filter_engine = importlib.reload(filter_engine)
apply_base_filters = filter_engine.apply_base_filters
apply_detail_filters = filter_engine.apply_detail_filters
calendar_period_options = filter_engine.calendar_period_options
dependent_options = filter_engine.dependent_options
kpi_engine = importlib.reload(kpi_engine)
calculate_kpis = kpi_engine.calculate_kpis
kpi_table = kpi_engine.kpi_table
safe_divide = kpi_engine.safe_divide
formatting = importlib.reload(formatting)
currency = formatting.currency
dashboard_table = formatting.dashboard_table
percentage = formatting.percentage
sanitize_filename = formatting.sanitize_filename
charts = importlib.reload(charts)
conversion_funnel = charts.conversion_funnel
conversion_percentage_chart = charts.conversion_percentage_chart
daily_trend = charts.daily_trend
footfall_bills_chart = charts.footfall_bills_chart
forecast_chart = charts.forecast_chart
gauge = charts.gauge
hierarchy_chart = charts.hierarchy_chart
monthly_bridge = charts.monthly_bridge
monthly_sales = charts.monthly_sales
same_day_comparison = charts.same_day_comparison
sales_by_period = charts.sales_by_period
store_scorecard = charts.store_scorecard
target_achievement = charts.target_achievement
weekday_average = charts.weekday_average
yearly_same_month = charts.yearly_same_month
ui_components = importlib.reload(ui_components)
apply_theme = ui_components.apply_theme
chart_table_download = ui_components.chart_table_download
render_gauge_remark = ui_components.render_gauge_remark
render_kpi = ui_components.render_kpi
pdf_report = importlib.reload(pdf_report)
generate_pdf = pdf_report.generate_pdf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# Kept local so Streamlit hot reloads cannot retain an older config module that
# predates this calendar-quarter definition.
QUARTER_DEFINITIONS = {
    "Q1": "January to March",
    "Q2": "April to June",
    "Q3": "July to September",
    "Q4": "October to December",
}

# Increment when WorkbookData's cached return contract changes. This prevents
# Streamlit from restoring objects created before newly required fields existed.
WORKBOOK_CACHE_SCHEMA_VERSION = 2
GAUGE_CARD_HEIGHT = 450
GAUGE_SPECS = (
    ("atv", "ATV", "currency"),
    ("rpv", "RPV", "currency"),
    ("basket_size", "Basket Size", "decimal"),
    ("conversion", "Conversion Rate", "percent"),
    ("achievement", "Target Achievement", "percent"),
)

st.set_page_config(page_title="CITIMART Sales KPI", page_icon="📊", layout="wide")
apply_theme()


@st.cache_data(show_spinner="Inspecting and loading the workbook…")
def cached_workbook(
    path: str,
    modified_time_ns: int,
    file_size: int,
    cache_schema_version: int,
) -> WorkbookData:
    # The version arguments are intentionally part of Streamlit's cache key.
    del modified_time_ns, file_size, cache_schema_version
    return load_workbook_data(path)


@st.cache_data(show_spinner="Validating uploaded forecast workbook…")
def cached_uploaded_forecast_workbook(
    file_bytes: bytes,
    source_name: str,
) -> UploadedForecastWorkbook:
    return load_uploaded_forecast_workbook(file_bytes, source_name)


@st.cache_resource(show_spinner="Evaluating forecasting models chronologically…")
def cached_forecast(
    selected_daily: pd.DataFrame,
    horizon: int,
    source_token: str,
) -> ForecastResult:
    del source_token
    return train_forecast(selected_daily, horizon=horizon)


def reset_filters() -> None:
    prefixes = (
        "store_",
        "date_mode",
        "specific_date",
        "specific_week",
        "specific_month",
        "specific_quarter",
        "date_range",
        "filter_start_date",
        "filter_end_date",
        "divisions",
        "sections",
        "departments",
        "granularity",
        "forecast_horizon",
        "forecast_source",
        "forecast_upload",
        "forecast_apply_view_filters",
        "drill_level",
        "sales_graph",
        "customer_graph",
        "same_day_of_month",
        "select_all_",
        "division_choice_",
        "section_choice_",
        "department_choice_",
    )
    for key in list(st.session_state):
        if key.startswith(prefixes):
            del st.session_state[key]


def preserve_search_selection(key: str, options: list[str]) -> list[str]:
    """Keep valid search selections; an empty selection represents all values."""
    if key not in st.session_state:
        st.session_state[key] = []
    else:
        st.session_state[key] = [value for value in st.session_state[key] if value in options]
    return st.session_state[key]


def delta_ratio(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return safe_divide(current - previous, abs(previous))


# Resolve from this file rather than the process working directory or a cached
# settings import. This remains stable when Streamlit is launched elsewhere.
workbook_path = APP_DIRECTORY / "salesdata.xlsx"
if not workbook_path.exists():
    st.error(
        "salesdata.xlsx was not found at "
        f"`{workbook_path}`. Place it beside this app.py file, then restart Streamlit."
    )
    st.stop()

workbook_stat = workbook_path.stat()
try:
    data = cached_workbook(
        str(workbook_path),
        workbook_stat.st_mtime_ns,
        workbook_stat.st_size,
        WORKBOOK_CACHE_SCHEMA_VERSION,
    )
except Exception as exc:
    st.exception(exc)
    st.stop()

# A running Streamlit server can retain a pre-upgrade object until its next
# cache miss. Hydrate the new fields defensively so hot reloads never crash.
if not hasattr(data, "kpi_color_rules"):
    rules, rule_source, rule_warnings = color_rules.load_color_rules(
        workbook_path
    )
    data.kpi_color_rules = rules
    data.color_rule_source = rule_source
    data.warnings.extend(
        warning for warning in rule_warnings if warning not in data.warnings
    )
elif not hasattr(data, "color_rule_source"):
    data.color_rule_source = None

if not data.available_stores:
    st.error("No usable store records were detected in the workbook.")
    st.stop()

all_dates = pd.concat(
    [
        frame["date"]
        for frame in (data.daily, data.detail)
        if not frame.empty and "date" in frame
    ],
    ignore_index=True,
).dropna()
minimum_date = all_dates.min().date()
maximum_date = all_dates.max().date()

main_column, filter_column = st.columns([4.5, 1.35], gap="large")

with filter_column:
    with st.container(key="filter_panel", border=True):
        st.subheader("Filters")
        if st.button("Reload source data", width="stretch"):
            cached_workbook.clear()
            cached_forecast.clear()
            st.rerun()
        if st.button("↺ Reset All Filters", width="stretch", type="primary"):
            reset_filters()
            st.rerun()

        st.markdown("**Stores**")
        available_store_keys = [
            f"store_{code}" for code in data.available_stores
        ]
        for code in data.available_stores:
            st.session_state.setdefault(f"store_{code}", True)
        store_selection_restored = False
        if available_store_keys and not any(
            bool(st.session_state.get(key)) for key in available_store_keys
        ):
            # Restore a valid selection before checkbox widgets are instantiated.
            st.session_state[available_store_keys[0]] = True
            store_selection_restored = True

        selected_stores: list[str] = []
        for code, name in STORE_NAMES.items():
            available = code in data.available_stores
            key = f"store_{code}"
            if key not in st.session_state:
                st.session_state[key] = available
            checked = st.checkbox(
                name,
                key=key,
                disabled=not available,
                help=None if available else "Data not currently available",
            )
            if checked and available:
                selected_stores.append(code)
        if not selected_stores:
            # Defensive fallback for an unexpected widget-state race.
            selected_stores = [data.available_stores[0]]
        if store_selection_restored:
            st.warning("At least one available store must remain selected.")

        date_mode = st.radio(
            "Date selection",
            [
                "All available dates",
                "Specific date",
                "Specific week",
                "Specific month",
                "Specific quarter",
                "Specific date range",
            ],
            key="date_mode",
        )
        if date_mode == "Specific date":
            selected_date = st.date_input(
                "Date (DD-MM-YYYY)",
                value=maximum_date,
                min_value=minimum_date,
                max_value=maximum_date,
                format="DD-MM-YYYY",
                key="specific_date",
            )
            start_date = end_date = selected_date
        elif date_mode == "Specific week":
            week_options = calendar_period_options(all_dates, "week")
            selected_week = st.selectbox(
                "Week (Monday to Sunday)",
                options=week_options,
                index=len(week_options) - 1,
                format_func=lambda option: option.label,
                key="specific_week",
            )
            start_date = selected_week.start_date
            end_date = selected_week.end_date
        elif date_mode == "Specific month":
            month_options = calendar_period_options(all_dates, "month")
            selected_month = st.selectbox(
                "Month",
                options=month_options,
                index=len(month_options) - 1,
                format_func=lambda option: option.label,
                key="specific_month",
            )
            start_date = selected_month.start_date
            end_date = selected_month.end_date
        elif date_mode == "Specific quarter":
            quarter_options = calendar_period_options(all_dates, "quarter")
            selected_quarter = st.selectbox(
                "Quarter",
                options=quarter_options,
                index=len(quarter_options) - 1,
                format_func=lambda option: option.label,
                key="specific_quarter",
            )
            start_date = selected_quarter.start_date
            end_date = selected_quarter.end_date
        elif date_mode == "Specific date range":
            start_column, end_column = st.columns(2)
            with start_column:
                start_date = st.date_input(
                    "Start Date",
                    value=minimum_date,
                    min_value=minimum_date,
                    max_value=maximum_date,
                    format="DD-MM-YYYY",
                    key="filter_start_date",
                )
            # If the start moves beyond the prior end, restore a valid end before
            # the End Date widget is instantiated.
            if (
                "filter_end_date" in st.session_state
                and st.session_state["filter_end_date"] < start_date
            ):
                st.session_state["filter_end_date"] = start_date
            with end_column:
                end_date = st.date_input(
                    "End Date",
                    value=maximum_date,
                    min_value=start_date,
                    max_value=maximum_date,
                    format="DD-MM-YYYY",
                    key="filter_end_date",
                )
        else:
            start_date, end_date = minimum_date, maximum_date

        division_options, _, _ = dependent_options(
            data.detail, selected_stores, start_date, end_date
        )
        preserve_search_selection("divisions", division_options)
        searched_divisions = st.multiselect(
            "Search DIVISION",
            options=division_options,
            key="divisions",
            placeholder="All divisions — type to search",
            help="Leave empty to include every available division.",
        )
        selected_divisions = searched_divisions or division_options
        st.caption(
            "All divisions"
            if not searched_divisions
            else f"{len(searched_divisions)} division(s) selected"
        )
        division_header = (
            "All divisions"
            if not searched_divisions
            else (
                ", ".join(searched_divisions)
                if len(searched_divisions) <= 3
                else f"{len(searched_divisions)} divisions selected"
            )
        )

        _, section_options, _ = dependent_options(
            data.detail,
            selected_stores,
            start_date,
            end_date,
            divisions=selected_divisions,
        )
        preserve_search_selection("sections", section_options)
        searched_sections = st.multiselect(
            "Search SECTION",
            options=section_options,
            key="sections",
            placeholder="All sections — type to search",
            help="Leave empty to include every section available for the selected divisions.",
        )
        selected_sections = searched_sections or section_options
        st.caption(
            "All sections"
            if not searched_sections
            else f"{len(searched_sections)} section(s) selected"
        )
        _, _, department_options = dependent_options(
            data.detail,
            selected_stores,
            start_date,
            end_date,
            divisions=selected_divisions,
            sections=selected_sections,
        )
        preserve_search_selection("departments", department_options)
        searched_departments = st.multiselect(
            "Search DEPARTMENT",
            options=department_options,
            key="departments",
            placeholder="All departments — type to search",
            help="Leave empty to include every department available for the selected sections.",
        )
        selected_departments = searched_departments or department_options
        st.caption(
            "All departments"
            if not searched_departments
            else f"{len(searched_departments)} department(s) selected"
        )

        granularity = st.selectbox(
            "Chart granularity",
            ["Month", "Year", "Quarter", "Week", "Day"],
            key="granularity",
        )
        if granularity == "Quarter":
            st.caption(
                " · ".join(
                    f"{quarter}: {months}"
                    for quarter, months in QUARTER_DEFINITIONS.items()
                )
            )
        horizon = st.slider(
            "Forecast horizon (days)",
            min_value=7,
            max_value=90,
            value=30,
            step=1,
            key="forecast_horizon",
        )
        st.markdown("**Forecast data**")
        forecast_source_mode = st.radio(
            "Forecast data source",
            ["Current dashboard view", "Upload XLSX"],
            key="forecast_source",
            help=(
                "Use the filtered dashboard history, or upload a new workbook containing "
                "DATE and SALE/NET SALES columns."
            ),
        )
        uploaded_forecast_file = None
        apply_uploaded_view_filters = False
        if forecast_source_mode == "Upload XLSX":
            uploaded_forecast_file = st.file_uploader(
                "Upload forecasting workbook",
                type=["xlsx"],
                key="forecast_upload",
                help=(
                    "The workbook may use the CITIMART paired-sheet format or a regular "
                    "worksheet with DATE and SALE/NET SALES columns."
                ),
            )
            apply_uploaded_view_filters = st.checkbox(
                "Apply current dashboard filters",
                value=False,
                key="forecast_apply_view_filters",
                help=(
                    "When enabled, the current date, store, DIVISION, SECTION, and "
                    "DEPARTMENT scope is applied where matching fields exist."
                ),
            )
            st.caption(
                "Without this option, the model uses the complete history found in the "
                "uploaded workbook."
            )

filtered_daily = apply_base_filters(
    data.daily, selected_stores, start_date, end_date
)
filtered_detail = apply_detail_filters(
    data.detail,
    selected_stores,
    start_date,
    end_date,
    divisions=selected_divisions,
    sections=selected_sections,
    departments=selected_departments,
)
division_filtered = set(selected_divisions) != set(division_options)
section_filtered = set(selected_sections) != set(section_options)
department_filtered = set(selected_departments) != set(department_options)
hierarchy_filtered = (
    division_filtered or section_filtered or department_filtered
)
filtered_sales = filtered_detail if hierarchy_filtered else filtered_daily

period_start = pd.Timestamp(start_date)
period_end = pd.Timestamp(end_date)
previous_start, previous_end = previous_period_bounds(period_start, period_end)
previous_daily = apply_base_filters(
    data.daily,
    selected_stores,
    previous_start.date(),
    previous_end.date(),
)
previous_detail = apply_detail_filters(
    data.detail,
    selected_stores,
    previous_start.date(),
    previous_end.date(),
    divisions=selected_divisions,
    sections=selected_sections,
    departments=selected_departments,
)

current_kpis = calculate_kpis(
    filtered_daily,
    filtered_detail,
    hierarchy_filtered,
    color_rules=data.kpi_color_rules,
)
previous_kpis = calculate_kpis(
    previous_daily,
    previous_detail,
    hierarchy_filtered,
    color_rules=data.kpi_color_rules,
)
comparison = kpi_table(current_kpis, previous_kpis)

forecast_result: ForecastResult | None = None
forecast_error: str | None = None
forecast_warnings: list[str] = []
forecast_input = pd.DataFrame(columns=["date", "net_sales"])
forecast_source_label = "Current dashboard view"
forecast_scope_description = (
    "filtered division/section/department detail"
    if hierarchy_filtered
    else "filtered store-day summary"
)
forecast_data_refresh = datetime.fromtimestamp(data.workbook_mtime).astimezone().strftime(
    "%d-%m-%Y"
)
try:
    if forecast_source_mode == "Upload XLSX":
        if uploaded_forecast_file is None:
            raise ValueError("Upload an XLSX workbook to train the forecast.")
        uploaded_bytes = uploaded_forecast_file.getvalue()
        uploaded_workbook = cached_uploaded_forecast_workbook(
            uploaded_bytes,
            uploaded_forecast_file.name,
        )
        upload_history = prepare_uploaded_forecast_history(
            uploaded_workbook,
            apply_view_filters=apply_uploaded_view_filters,
            start_date=start_date if apply_uploaded_view_filters else None,
            end_date=end_date if apply_uploaded_view_filters else None,
            selected_store_codes=(
                selected_stores
                if apply_uploaded_view_filters
                and set(selected_stores) != set(data.available_stores)
                else None
            ),
            divisions=(
                selected_divisions
                if apply_uploaded_view_filters and division_filtered
                else None
            ),
            sections=(
                selected_sections
                if apply_uploaded_view_filters and section_filtered
                else None
            ),
            departments=(
                selected_departments
                if apply_uploaded_view_filters and department_filtered
                else None
            ),
        )
        forecast_input = upload_history.daily
        forecast_warnings = upload_history.warnings
        forecast_source_label = f"Uploaded XLSX: {upload_history.source_name}"
        forecast_scope_description = (
            f"{upload_history.source_rows:,} source rows from "
            f"{', '.join(upload_history.sheets_used)}; "
            f"{upload_history.date_min:%d-%m-%Y}–{upload_history.date_max:%d-%m-%Y}"
        )
        if upload_history.filters_applied:
            forecast_scope_description += "; current dashboard filters applied"
        forecast_data_refresh = "Uploaded in current session"
        forecast_source_token = hashlib.sha256(uploaded_bytes).hexdigest()
    else:
        forecast_input = (
            filtered_sales[["date", "net_sales"]]
            .groupby("date", as_index=False)["net_sales"]
            .sum()
        )
        forecast_source_token = (
            f"default:{data.workbook_mtime}:"
            f"{','.join(sorted(selected_stores))}:{start_date}:{end_date}:"
            f"{','.join(selected_divisions)}:{','.join(selected_sections)}:"
            f"{','.join(selected_departments)}"
        )
    forecast_result = cached_forecast(
        forecast_input,
        horizon,
        forecast_source_token,
    )
except (ValueError, TypeError, OSError) as exc:
    forecast_error = str(exc)

sales_figure, sales_table = sales_by_period(filtered_sales, granularity)
monthly_figure, monthly_table = monthly_sales(filtered_sales)
division_figure, division_table = hierarchy_chart(filtered_detail, "division")
scorecard_table = store_scorecard(
    filtered_sales,
    sales_only=hierarchy_filtered,
    color_rules=data.kpi_color_rules,
)
if forecast_result:
    forecast_figure, forecast_table = forecast_chart(forecast_result)
else:
    forecast_figure = None
    forecast_table = pd.DataFrame()

selected_store_names = [STORE_NAMES[code] for code in selected_stores]
refresh_time = datetime.fromtimestamp(data.workbook_mtime).astimezone()
forecast_overview = {
    "Forecast source": forecast_source_label,
    "Data refreshed": forecast_data_refresh,
    "Sales scope": forecast_scope_description,
    "Method": forecast_result.explanation if forecast_result else (forecast_error or "Insufficient data"),
}
if forecast_result:
    forecast_overview.update(
        {
            "Selected model": forecast_result.model_name,
            "Frequency": forecast_result.frequency,
            "Training range": (
                f"{forecast_result.training_start:%d-%m-%Y}–"
                f"{forecast_result.training_end:%d-%m-%Y}"
            ),
            "Horizon": f"{horizon} periods",
            "Validation MAE": currency(forecast_result.metrics["MAE"]),
            "Validation RMSE": currency(forecast_result.metrics["RMSE"]),
            "Validation MAPE": percentage(forecast_result.metrics["MAPE"]),
        }
    )

with filter_column:
    with st.container(border=True):
        st.markdown("**Filtered PDF report**")
        if st.button("Generate PDF Report", width="stretch"):
            with st.spinner("Composing the filtered PDF…"):
                figures = []
                for key, label, kind in GAUGE_SPECS:
                    if (
                        current_kpis[key]["available"]
                        and key in data.kpi_color_rules
                    ):
                        figures.append(
                            (
                                f"{label} Gauge",
                                gauge(
                                    current_kpis[key]["value"],
                                    label,
                                    data.kpi_color_rules[key],
                                    kind,
                                    previous_kpis[key]["value"],
                                ),
                            )
                        )

                figures.extend(
                    [
                        ("Net vs Gross Sales", sales_figure),
                        (
                            "Monthly Sales, Target and Achievement",
                            monthly_figure,
                        ),
                    ]
                )
                if not division_table.empty:
                    figures.append(("Sales by Division", division_figure))

                report_daily_figure, report_daily_table = daily_trend(
                    filtered_sales
                )
                if not report_daily_table.empty:
                    figures.append(("Daily Sales Trend", report_daily_figure))

                report_target_source = (
                    filtered_daily
                    if not hierarchy_filtered
                    else filtered_daily.iloc[0:0]
                )
                report_target_figure, report_target_table = target_achievement(
                    report_target_source,
                    data.kpi_color_rules.get("achievement"),
                )
                if not report_target_table.empty:
                    figures.append(
                        (
                            "Target Achievement by Month",
                            report_target_figure,
                        )
                    )

                report_customer_source = (
                    filtered_daily
                    if not hierarchy_filtered
                    else filtered_daily.iloc[0:0]
                )
                report_foot_figure, report_customer_table = (
                    footfall_bills_chart(report_customer_source)
                )
                report_conversion_figure, report_conversion_table = (
                    conversion_percentage_chart(
                        report_customer_source,
                        data.kpi_color_rules.get("conversion"),
                    )
                )
                if not report_customer_table.empty:
                    figures.append(
                        ("Footfall vs NoB", report_foot_figure)
                    )
                if not report_conversion_table.empty:
                    figures.append(
                        (
                            "Conversion Percentage",
                            report_conversion_figure,
                        )
                    )
                if forecast_figure is not None:
                    figures.append(("Forecast", forecast_figure))
                report_filters = {
                    "Stores": ", ".join(selected_store_names),
                    "Date coverage": f"{start_date:%d-%m-%Y}–{end_date:%d-%m-%Y}",
                    "Forecast source": forecast_source_label,
                    "Divisions": "All" if not division_filtered else ", ".join(selected_divisions),
                    "Sections": "All" if not section_filtered else ", ".join(selected_sections),
                    "Departments": "All" if not department_filtered else ", ".join(selected_departments),
                    "Skipped worksheets/stores": (
                        ", ".join([*data.skipped_sheets, *data.skipped_stores])
                        or "None"
                    ),
                }
                pdf_bytes, pdf_warnings = generate_pdf(
                    report_filters,
                    current_kpis,
                    comparison,
                    [
                        ("Division performance", division_table),
                        ("Store scorecard", scorecard_table),
                        ("Monthly performance", monthly_table),
                        ("Daily sales trend", report_daily_table),
                        (
                            "Footfall, NoB and conversion",
                            report_customer_table,
                        ),
                        ("Forecast values", forecast_table),
                    ],
                    forecast_overview,
                    [*data.warnings, *forecast_warnings],
                    figures,
                )
                st.session_state["generated_pdf"] = pdf_bytes
                st.session_state["pdf_warnings"] = pdf_warnings
        if "generated_pdf" in st.session_state:
            st.download_button(
                "Download PDF",
                data=st.session_state["generated_pdf"],
                file_name=sanitize_filename(
                    f"citimart_kpi_{start_date}_{end_date}.pdf"
                ),
                mime="application/pdf",
                width="stretch",
            )
            for warning in st.session_state.get("pdf_warnings", []):
                st.caption(warning)

with main_column:
    model_line = (
        f"{forecast_result.model_name} · {forecast_result.frequency} · "
        f"RMSE {currency(forecast_result.metrics['RMSE'])}"
        if forecast_result
        else f"Forecast unavailable · {forecast_error or 'insufficient data'}"
    )
    st.markdown(
        f"""
        <div class="brand-bar">
          <div class="brand-title">{APP_TITLE}</div>
          <div class="brand-subtitle">
            {len(selected_stores)} active store(s) · Reporting period:
            {start_date:%d-%m-%Y}–{end_date:%d-%m-%Y} · Workbook refreshed:
            {refresh_time:%d-%m-%Y %H:%M}
          </div>
          <div class="brand-subtitle">DIVISION: {division_header}</div>
          <div class="brand-subtitle">Forecast: {model_line}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if hierarchy_filtered:
        if forecast_source_mode == "Upload XLSX":
            filter_message = (
                " with the current filters applied."
                if apply_uploaded_view_filters
                else " without dashboard filters."
            )
            st.warning(
                "Division/section/department filters are active. Sales views use the filtered "
                f"detail fact; the forecast uses the uploaded workbook{filter_message} "
                "Operational KPI cards are hidden because store-day measures cannot be "
                "attributed safely to hierarchy rows."
            )
        else:
            st.warning(
                "Division/section/department filters are active. All sales views and the "
                "forecast use the filtered detail fact. Operational KPI cards are hidden "
                "because store-day measures cannot be attributed safely to hierarchy rows."
            )
    for warning in data.warnings[:3]:
        st.caption(f"Data note: {warning}")

    tabs = st.tabs(
        [
            "Executive Overview",
            "Sales Performance",
            "Customer & Conversion",
            "Division Analysis",
            "Discount Analysis",
            "Forecast",
            "Detailed Tables",
            "Data Quality",
        ]
    )

    with tabs[0]:
        st.subheader("Executive KPI Summary")
        if data.color_rule_source:
            st.caption(
                f"KPI colours are controlled by workbook worksheet: "
                f"{data.color_rule_source}."
            )
        cards = [
            ("Total Net Sales", "net_sales", "currency"),
            ("Total Gross Sales", "gross_sales", "currency"),
            ("Sales Target", "target", "currency"),
            ("Total Footfall", "footfall", "count"),
            ("Number of Bills", "transactions", "count"),
            ("Total Units Sold", "quantity", "count"),
            ("ATV", "atv", "currency"),
            ("Revenue / Visitor", "rpv", "currency"),
            ("Basket Size", "basket_size", "decimal"),
            ("Conversion", "conversion", "percent"),
            ("Target Achievement", "achievement", "percent"),
        ]
        available_cards = [
            card for card in cards if current_kpis[card[1]]["available"]
        ]
        for row_start in range(0, len(available_cards), 4):
            row_cards = available_cards[row_start : row_start + 4]
            card_columns = st.columns(len(row_cards), gap="medium")
            for column, (label, key, kind) in zip(
                card_columns, row_cards
            ):
                with column:
                    render_kpi(
                        label,
                        current_kpis[key],
                        kind,
                        delta_ratio(
                            current_kpis[key]["value"],
                            previous_kpis[key]["value"],
                        ),
                    )

        st.markdown("#### KPI Summary Table")
        st.dataframe(
            dashboard_table(comparison),
            width="stretch",
            hide_index=True,
            height=360,
        )
        st.download_button(
            "Download KPI CSV",
            to_csv_bytes(dashboard_table(comparison)),
            "filtered_kpis.csv",
            "text/csv",
        )

        st.markdown("#### KPI Gauges")
        gauge_specs = [
            spec
            for spec in GAUGE_SPECS
            if current_kpis[spec[0]]["available"]
            and spec[0] in data.kpi_color_rules
        ]
        if gauge_specs:
            for row_start in range(0, len(gauge_specs), 2):
                row_specs = gauge_specs[row_start : row_start + 2]
                gauge_columns = st.columns(2, gap="large")
                for column, (key, label, kind) in zip(
                    gauge_columns, row_specs
                ):
                    rule = data.kpi_color_rules[key]
                    with column:
                        with st.container(
                            border=True,
                            height=GAUGE_CARD_HEIGHT,
                            key=f"gauge_card_{key}",
                        ):
                            st.plotly_chart(
                                gauge(
                                    current_kpis[key]["value"],
                                    label,
                                    rule,
                                    kind,
                                    previous_kpis[key]["value"],
                                ),
                                width="stretch",
                                key=f"overview_{key}_gauge",
                                config={
                                    "displayModeBar": False,
                                    "displaylogo": False,
                                },
                            )
                            status, remark = gauge_assessment(
                                key,
                                current_kpis[key]["value"],
                                rule,
                            )
                            render_gauge_remark(status, remark)

        st.subheader("Store Scorecards and Rankings")
        if scorecard_table.empty:
            st.info("No comparable store data.")
        else:
            st.dataframe(
                dashboard_table(scorecard_table),
                width="stretch",
                hide_index=True,
            )

    with tabs[1]:
        sales_graph = st.selectbox(
            "Select Sales Performance graph",
            [
                "Net vs Gross Sales",
                "Sales by Division",
                "Sales Movement Bridge",
                "Monthly Sales, Target and Achievement",
                "Daily Sales Trend",
                "Target Achievement by Month",
                "Monthly Same-Day Comparison",
                "Yearly Same-Month Comparison",
            ],
            key="sales_graph",
        )
        if sales_graph == "Net vs Gross Sales":
            st.caption(f"Current period grouping: {granularity}")
            chart_table_download(
                sales_figure,
                sales_table,
                "sales_period",
                "filtered_net_gross_sales.csv",
            )
        elif sales_graph == "Sales by Division":
            st.caption(
                "Division sales use NET_AMOUNT from the detail worksheets for the "
                "selected stores, dates, sections, and departments."
            )
            chart_table_download(
                division_figure,
                division_table,
                "division_sales",
                "filtered_division_sales.csv",
            )
        elif sales_graph == "Sales Movement Bridge":
            bridge_figure, bridge_table = monthly_bridge(filtered_sales)
            chart_table_download(
                bridge_figure,
                bridge_table,
                "monthly_bridge",
                "filtered_monthly_bridge.csv",
            )
        elif sales_graph == "Monthly Sales, Target and Achievement":
            chart_table_download(
                monthly_figure,
                monthly_table,
                "monthly_sales",
                "filtered_monthly_sales.csv",
            )
        elif sales_graph == "Daily Sales Trend":
            daily_figure, daily_table = daily_trend(filtered_sales)
            chart_table_download(
                daily_figure,
                daily_table,
                "daily_trend",
                "filtered_daily_sales.csv",
            )
        elif sales_graph == "Target Achievement by Month":
            target_source = (
                filtered_daily
                if not hierarchy_filtered
                else filtered_daily.iloc[0:0]
            )
            target_figure, target_table = target_achievement(
                target_source,
                data.kpi_color_rules.get("achievement"),
            )
            chart_table_download(
                target_figure,
                target_table,
                "target_month",
                "filtered_target_achievement.csv",
            )
        elif sales_graph == "Monthly Same-Day Comparison":
            selected_day = st.selectbox(
                "Day of month",
                options=list(range(1, 32)),
                format_func=lambda day: f"Day {day}",
                key="same_day_of_month",
            )
            full_history_daily = apply_base_filters(
                data.daily,
                selected_stores,
                minimum_date,
                maximum_date,
            )
            full_history_detail = apply_detail_filters(
                data.detail,
                selected_stores,
                minimum_date,
                maximum_date,
                divisions=selected_divisions,
                sections=selected_sections,
                departments=selected_departments,
            )
            same_day_source = (
                full_history_detail if hierarchy_filtered else full_history_daily
            )
            if not same_day_source.empty:
                st.caption(
                    "Sales on the same day-of-month across "
                    f"{same_day_source['date'].min():%b-%Y}–"
                    f"{same_day_source['date'].max():%b-%Y}; full history, "
                    "independent of the date filter."
                )
            same_day_figure, same_day_table = same_day_comparison(
                same_day_source, selected_day
            )
            chart_table_download(
                same_day_figure,
                same_day_table,
                "same_day",
                "filtered_same_day_comparison.csv",
            )
        else:
            yoy_figure, yoy_table = yearly_same_month(filtered_sales)
            chart_table_download(
                yoy_figure,
                yoy_table,
                "yearly_month",
                "filtered_yearly_same_month.csv",
            )

    with tabs[2]:
        st.subheader("Footfall vs NoB")
        customer_source = (
            filtered_daily
            if not hierarchy_filtered
            else filtered_daily.iloc[0:0]
        )
        foot_figure, foot_table = footfall_bills_chart(customer_source)
        conversion_figure, conversion_table = conversion_percentage_chart(
            customer_source,
            data.kpi_color_rules.get("conversion"),
        )
        customer_chart_tab, customer_table_tab = st.tabs(["Charts", "Table"])
        with customer_chart_tab:
            foot_column, conversion_column = st.columns(2, gap="large")
            with foot_column:
                st.plotly_chart(
                    foot_figure,
                    width="stretch",
                    key="footfall_nob_chart",
                    config={"displaylogo": False},
                )
            with conversion_column:
                st.plotly_chart(
                    conversion_figure,
                    width="stretch",
                    key="conversion_percentage_chart",
                    config={"displaylogo": False},
                )
        with customer_table_tab:
            customer_table = (
                foot_table if not foot_table.empty else conversion_table
            )
            if customer_table.empty:
                st.info("No customer data for the active filters.")
            else:
                display_customer_table = dashboard_table(customer_table)
                st.dataframe(
                    display_customer_table, width="stretch", hide_index=True
                )
                st.download_button(
                    "Download Footfall / NoB CSV",
                    to_csv_bytes(display_customer_table),
                    "filtered_footfall_nob_conversion.csv",
                    "text/csv",
                    key="customer_table_download",
                )

        st.markdown("#### Additional customer analysis")
        customer_graph = st.selectbox(
            "Select an additional view",
            ["Conversion Funnel", "Average Sales by Day of Week"],
            key="customer_graph",
        )
        if customer_graph == "Conversion Funnel":
            funnel_figure, funnel_table = conversion_funnel(customer_source)
            chart_table_download(
                funnel_figure,
                funnel_table,
                "conversion_funnel",
                "filtered_conversion_funnel.csv",
            )
        else:
            weekday_figure, weekday_table = weekday_average(filtered_sales)
            chart_table_download(
                weekday_figure,
                weekday_table,
                "weekday_average",
                "filtered_weekday_average.csv",
            )

    with tabs[3]:
        hierarchy_levels = [
            level
            for level in (
                "division",
                "section",
                "department",
                "category",
                "subcategory",
                "brand",
                "product",
            )
            if level in filtered_detail and filtered_detail[level].notna().any()
        ]
        if hierarchy_levels:
            drill_level = st.selectbox(
                "Drill-down level",
                hierarchy_levels,
                key="drill_level",
                format_func=str.title,
            )
            st.caption(f"Breadcrumb: All Stores → {drill_level.title()}")
            hierarchy_figure, hierarchy_table = hierarchy_chart(filtered_detail, drill_level)
            chart_table_download(
                hierarchy_figure,
                hierarchy_table,
                "hierarchy",
                f"filtered_{drill_level}.csv",
            )
        else:
            st.info("No supported hierarchy field is available.")

    with tabs[4]:
        if {"gross_sales", "net_sales"}.issubset(filtered_detail):
            impact = filtered_detail.copy()
            impact["Discount status"] = np.where(
                impact["gross_sales"] > impact["net_sales"], "Discounted", "Not discounted"
            )
            impact_table = (
                impact.groupby("Discount status", as_index=False)
                .agg(
                    net_sales=("net_sales", "sum"),
                    gross_sales=("gross_sales", "sum"),
                )
            )
            impact_table["discount"] = (
                impact_table["gross_sales"] - impact_table["net_sales"]
            )
            impact_table["discount_pct"] = (
                impact_table["discount"]
                / impact_table["gross_sales"].replace(0, np.nan)
            )
            for column in ("net_sales", "gross_sales", "discount"):
                impact_table[column] = impact_table[column].round(0)
            import plotly.express as px

            impact_figure = px.bar(
                impact_table,
                x="Discount status",
                y="net_sales",
                color="Discount status",
                title="Discounted vs Non-Discounted Sales Association",
            )
            chart_table_download(
                impact_figure,
                impact_table,
                "discount_impact",
                "filtered_discount_impact.csv",
            )
            st.caption(
                "This is an association based on gross amount exceeding net amount; it is "
                "not a causal promotion-uplift estimate."
            )

    with tabs[5]:
        st.info(f"Forecast source: {forecast_source_label}")
        st.caption(f"Training input: {forecast_scope_description}")
        for warning in forecast_warnings[:5]:
            st.caption(f"Upload note: {warning}")
        if forecast_result:
            st.markdown(
                f"**{forecast_result.model_name}** · Training "
                f"{forecast_result.training_start:%d-%m-%Y}–"
                f"{forecast_result.training_end:%d-%m-%Y} · "
                f"MAE {currency(forecast_result.metrics['MAE'])} · "
                f"RMSE {currency(forecast_result.metrics['RMSE'])} · "
                f"MAPE {percentage(forecast_result.metrics['MAPE'])}"
            )
            st.caption(forecast_result.explanation)
            chart_table_download(
                forecast_figure,
                forecast_table,
                "forecast",
                "filtered_sales_forecast.csv",
            )
            st.subheader("Candidate Model Validation")
            st.dataframe(
                dashboard_table(forecast_result.candidate_metrics),
                width="stretch",
                hide_index=True,
            )
            with st.expander("Forecast training data"):
                st.caption(
                    f"{len(forecast_input):,} daily observations used after aggregation."
                )
                st.dataframe(
                    dashboard_table(forecast_input.tail(30)),
                    width="stretch",
                    hide_index=True,
                )
                st.download_button(
                    "Download forecast training history",
                    to_csv_bytes(dashboard_table(forecast_input)),
                    "forecast_training_history.csv",
                    "text/csv",
                )
        else:
            st.warning(f"Forecast not trained: {forecast_error}")

    with tabs[6]:
        if data.skipped_sheets or data.skipped_stores:
            st.info(
                "Skipped from report calculations: "
                + ", ".join([*data.skipped_stores, *data.skipped_sheets])
            )
        st.subheader("Store-Day Fact (Store and Date Scope)")
        if hierarchy_filtered:
            st.caption(
                "DIVISION, SECTION, and DEPARTMENT do not exist in the store-day "
                "worksheets, so this table is not hierarchy-filtered. Use the detail "
                "table below for the active DIVISION analysis."
            )
        st.dataframe(dashboard_table(filtered_daily), width="stretch", hide_index=True)
        st.download_button(
            "Download filtered store-day CSV",
            to_csv_bytes(dashboard_table(filtered_daily)),
            "filtered_store_day_fact.csv",
            "text/csv",
        )
        st.subheader("Filtered Division/Section/Department Detail")
        detail_display = filtered_detail.rename(
            columns={"quantity": "detail_bill_quantity_including_returns"}
        )
        st.dataframe(
            dashboard_table(detail_display.head(10000)),
            width="stretch",
            hide_index=True,
        )
        if len(filtered_detail) > 10000:
            st.caption("Preview limited to 10,000 rows; the download contains all filtered rows.")
        st.download_button(
            "Download filtered detail CSV",
            to_csv_bytes(dashboard_table(detail_display)),
            "filtered_sales_detail.csv",
            "text/csv",
        )

    with tabs[7]:
        st.subheader("Workbook Profile")
        profile_summary = pd.DataFrame(
            [
                {"Metric": "Worksheets loaded", "Value": ", ".join(data.loaded_sheets)},
                {"Metric": "Worksheets skipped", "Value": ", ".join(data.skipped_sheets) or "None"},
                {"Metric": "Stores skipped", "Value": ", ".join(data.skipped_stores) or "None"},
                {
                    "Metric": "KPI colour rules",
                    "Value": (
                        f"{data.color_rule_source} "
                        f"({len(data.kpi_color_rules)} rules)"
                        if data.color_rule_source
                        else "Not available — KPI colours are neutral"
                    ),
                },
                {"Metric": "Detail rows retained", "Value": f"{len(data.detail):,}"},
                {"Metric": "Store-day rows retained", "Value": f"{len(data.daily):,}"},
                {
                    "Metric": "Available divisions",
                    "Value": f"{data.detail['division'].nunique():,}"
                    if "division" in data.detail
                    else "0",
                },
                {
                    "Metric": "Division values",
                    "Value": ", ".join(
                        sorted(
                            data.detail["division"].dropna().astype(str).unique(),
                            key=str.casefold,
                        )
                    )
                    if "division" in data.detail
                    else "None",
                },
                {
                    "Metric": "Date range",
                    "Value": f"{minimum_date:%d-%m-%Y}–{maximum_date:%d-%m-%Y}",
                },
                {
                    "Metric": "Available stores",
                    "Value": ", ".join(STORE_NAMES[code] for code in data.available_stores),
                },
            ]
        )
        st.dataframe(dashboard_table(profile_summary), width="stretch", hide_index=True)
        st.subheader("Worksheet-Level Quality")
        st.dataframe(dashboard_table(data.sheet_quality), width="stretch", hide_index=True)
        st.subheader("Detected Schemas")
        inspection_rows = []
        for inspection in data.inspections:
            inspection_rows.append(
                {
                    "worksheet": inspection["name"],
                    "dimensions": f"{inspection['rows']} × {inspection['columns']}",
                    "store": inspection["store_code"],
                    "role": inspection["role"],
                    "headers": ", ".join(inspection["headers"]),
                    "detected_mapping": ", ".join(
                        f"{key} ← {value}"
                        for key, value in inspection["mapping"].items()
                    ),
                }
            )
        st.dataframe(
            dashboard_table(pd.DataFrame(inspection_rows)),
            width="stretch",
            hide_index=True,
        )
        st.subheader("Warnings and KPI Availability")
        for warning in data.warnings:
            st.warning(warning)
        availability = pd.DataFrame(
            [
                {
                    "KPI": (
                        "Total Units Sold"
                        if key == "quantity"
                        else key.replace("_", " ").title()
                    ),
                    "Available": payload["available"],
                    "Color code": payload["status"],
                    "Color rule": payload["color_rule"],
                    "Source": payload["source"],
                    "Message": payload["message"],
                }
                for key, payload in current_kpis.items()
                if payload["available"]
            ]
        )
        st.dataframe(dashboard_table(availability), width="stretch", hide_index=True)
