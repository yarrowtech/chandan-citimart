"""Reusable Streamlit presentation components."""

from __future__ import annotations

from html import escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.formatting import count, currency, dashboard_table, percentage
from src.tables import to_csv_bytes


def apply_theme() -> None:
    st.markdown(
        """
        <style>
        .stApp { background: #F4F7F9; }
        .block-container { max-width: 1600px; padding-top: 1.1rem; }
        h1, h2, h3 { color: #12304A; }
        .kpi-card {
            position: relative; overflow: hidden;
            background: linear-gradient(145deg, #FFFFFF 0%, #F8FBFD 100%);
            border: 1px solid #DCE3E8; border-radius: 14px;
            padding: 12px 14px; box-shadow: 0 3px 12px rgba(18,48,74,.07);
            min-height: 132px; display: flex; flex-direction: column;
            box-sizing: border-box; transition: transform .18s ease,
            box-shadow .18s ease, border-color .18s ease;
            outline: none;
        }
        .kpi-card::before {
            content: ""; position: absolute; inset: 0 auto 0 0; width: 4px;
            background: #81909C;
        }
        .kpi-card[data-status="green"]::before { background: #2E8B57; }
        .kpi-card[data-status="yellow"]::before { background: #F4B740; }
        .kpi-card[data-status="red"]::before { background: #C83C3A; }
        .kpi-card[data-status="neutral"]::before { background: #1665A8; }
        .kpi-card:hover, .kpi-card:focus {
            transform: translateY(-3px); border-color: #9FB7C8;
            box-shadow: 0 10px 24px rgba(18,48,74,.14);
        }
        .kpi-label {
            color: #344A5E; font-size: .86rem; font-weight: 650; min-height: 19px;
        }
        .kpi-value {
            font-size: clamp(1.25rem, 1.65vw, 1.65rem); white-space: nowrap;
            color: #17242D; font-weight: 700; margin-top: 1px;
        }
        .kpi-delta {
            align-self: flex-start; min-height: 17px; font-size: .68rem;
            line-height: 17px; margin-top: 2px; padding: 0 6px;
            border-radius: 999px; background: #EEF3F6;
        }
        .kpi-formula {
            color: #65737E; font-size: .65rem; line-height: 1.18;
            min-height: 25px; margin-top: 2px;
        }
        .kpi-formula strong { color: #425466; font-weight: 650; }
        .kpi-delta-up { color: #2E8B57; }
        .kpi-delta-down { color: #C83C3A; }
        .kpi-status {
            margin-top: auto; padding-top: 5px; color: #51606C;
            font-size: .66rem; font-weight: 650; text-transform: uppercase;
            letter-spacing: .04em;
        }
        .kpi-status .status-dot { width: 8px; height: 8px; margin-right: 0; }
        .kpi-estimated-tag { color: #B5790B; font-weight: 650; text-transform: none; letter-spacing: 0; }
        .kpi-progress {
            height: 4px; border-radius: 999px; background: #E7EDF1;
            overflow: hidden; margin-top: 4px;
        }
        .kpi-progress span {
            display: block; height: 100%; border-radius: inherit;
            background: #1665A8;
        }
        .kpi-card[data-status="green"] .kpi-progress span { background: #2E8B57; }
        .kpi-card[data-status="yellow"] .kpi-progress span { background: #F4B740; }
        .kpi-card[data-status="red"] .kpi-progress span { background: #C83C3A; }
        .filter-panel {
            background: white; border: 1px solid #DCE3E8; border-radius: 14px;
            padding: .8rem 1rem; position: sticky; top: 3.5rem;
        }
        .st-key-filter_panel { position: sticky; top: 3.75rem; z-index: 3; }
        .brand-bar {
            background: linear-gradient(110deg,#12304A,#1665A8);
            color: white; border-radius: 14px; padding: 18px 22px; margin-bottom: 14px;
        }
        .brand-title { font-size: 1.55rem; font-weight: 750; letter-spacing: .02em; }
        .brand-subtitle { opacity: .88; font-size: .9rem; margin-top: 4px; }
        .na-box {
            background: #FFF8E8; border-left: 4px solid #F4B740; border-radius: 7px;
            padding: 10px 12px; color: #5A4A20; margin: 6px 0;
        }
        .gauge-remark {
            min-height: 92px; border-radius: 9px; padding: 10px 12px;
            margin: 0 2px 4px; font-size: .86rem; line-height: 1.35;
        }
        .status-dot {
            display: inline-block; width: 13px; height: 13px; border-radius: 50%;
            margin-right: 7px; vertical-align: -1px; box-shadow: 0 0 0 2px rgba(0,0,0,.05);
        }
        .status-green { background: #2E8B57; }
        .status-yellow { background: #F4B740; }
        .status-red { background: #C83C3A; }
        .status-neutral { background: #1665A8; }
        .status-na { background: #81909C; }
        .gauge-green { background: #E7F5EC; border-left: 4px solid #2E8B57; color: #195B38; }
        .gauge-yellow { background: #FFF6D8; border-left: 4px solid #F4B740; color: #6A5311; }
        .gauge-red { background: #FBE7E6; border-left: 4px solid #C83C3A; color: #7A2725; }
        .gauge-neutral { background: #E8F1FA; border-left: 4px solid #1665A8; color: #123F66; }
        .gauge-na { background: #EEF2F5; border-left: 4px solid #81909C; color: #4C5963; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_kpi(
    label: str,
    payload: dict[str, object],
    kind: str = "currency",
    delta: float | None = None,
) -> None:
    st.markdown(
        kpi_card_html(label, payload, kind, delta),
        unsafe_allow_html=True,
    )


def kpi_card_html(
    label: str,
    payload: dict[str, object],
    kind: str = "currency",
    delta: float | None = None,
) -> str:
    """Build a KPI card with its color code structurally inside the card."""
    value = payload.get("value")
    status = str(payload.get("status") or "N/A")
    status_class = {
        "Green": "status-green",
        "Yellow": "status-yellow",
        "Red": "status-red",
        "Neutral": "status-neutral",
    }.get(status, "status-na")
    status_key = (
        status.casefold()
        if status in {"Green", "Yellow", "Red", "Neutral"}
        else "na"
    )
    source_text = str(payload.get("source") or "")
    color_rule = str(payload.get("color_rule") or "")
    if color_rule:
        source_text = f"{source_text}. Colour rule: {color_rule}".strip(". ")
    formula = escape(str(payload.get("formula") or "Not specified"))
    if value is None:
        rendered = "N/A"
        delta_html = '<div class="kpi-delta"></div>'
        message = str(
            payload.get("message") or "Required source field not available"
        )
        source_text = f"{source_text}. {message}".strip(". ")
    else:
        rendered = {
            "currency": currency,
            "percent": percentage,
            "count": count,
            "decimal": lambda item: count(round(item), 0),
        }[kind](value)
        if delta is None:
            delta_html = '<div class="kpi-delta"></div>'
        else:
            delta_class = "kpi-delta-up" if delta >= 0 else "kpi-delta-down"
            direction = "▲" if delta >= 0 else "▼"
            delta_html = (
                f'<div class="kpi-delta {delta_class}">'
                f"{direction} {escape(f'{abs(delta):.0%} vs previous period')}</div>"
            )
    progress_html = ""
    if value is not None and kind == "percent":
        progress = max(0.0, min(float(value), 1.0)) * 100
        progress_html = (
            f'<div class="kpi-progress" aria-label="{progress:.0f}% of reference scale">'
            f'<span style="width:{progress:.1f}%"></span></div>'
        )
    source = escape(source_text)
    estimated_tag = (
        ' <span class="kpi-estimated-tag">· Estimated</span>'
        if payload.get("estimated")
        else ""
    )
    return (
        f'<div class="kpi-card" data-status="{status_key}" title="{source}" '
        f'tabindex="0" role="group" aria-label="{escape(label)}: {escape(str(rendered))}">'
        f'<div class="kpi-label">{escape(label)}</div>'
        f'<div class="kpi-value">{escape(str(rendered))}</div>'
        f"{delta_html}"
        f"{progress_html}"
        f'<div class="kpi-formula"><strong>Formula:</strong> {formula}</div>'
        '<div class="kpi-status">'
        f'<span class="status-dot {status_class}" '
        f'aria-label="{escape(status)}"></span> {escape(status)}'
        f"{estimated_tag}</div></div>"
    )


def render_gauge_remark(status: str, remark: str) -> None:
    """Render a compact gauge remark with status-consistent coloring."""
    status_class = {
        "Green": "gauge-green",
        "Yellow": "gauge-yellow",
        "Red": "gauge-red",
        "Neutral": "gauge-neutral",
        "N/A": "gauge-na",
    }.get(status, "gauge-na")
    dot_class = {
        "Green": "status-green",
        "Yellow": "status-yellow",
        "Red": "status-red",
        "Neutral": "status-neutral",
        "N/A": "status-na",
    }.get(status, "status-na")
    st.markdown(
        (
            f'<div class="gauge-remark {status_class}">'
            f'<span class="status-dot {dot_class}" '
            f'aria-label="{escape(status)}"></span>{escape(remark)}</div>'
        ),
        unsafe_allow_html=True,
    )


def chart_table_download(
    figure: go.Figure,
    table: pd.DataFrame,
    key: str,
    filename: str,
    height: int | None = None,
) -> None:
    chart_tab, table_tab = st.tabs(["Chart", "Table"])
    with chart_tab:
        st.plotly_chart(
            figure,
            width="stretch",
            key=f"{key}_chart",
            config={"displaylogo": False},
        )
    with table_tab:
        if table.empty:
            st.info("No table data for the active filters.")
        else:
            display = dashboard_table(table)
            st.dataframe(display, width="stretch", hide_index=True)
            st.download_button(
                "Download filtered CSV",
                data=to_csv_bytes(display),
                file_name=filename,
                mime="text/csv",
                key=f"{key}_download",
            )
