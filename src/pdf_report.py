"""Filtered PDF report composition using ReportLab and optional Kaleido charts."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterable
from xml.sax.saxutils import escape

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

CHART_EXPORT_WIDTH = 1400
CHART_EXPORT_HEIGHT = 700
CHART_PDF_WIDTH = 260 * mm
CHART_PDF_HEIGHT = 130 * mm
TABLE_PDF_WIDTH = 269 * mm

from src.formatting import (
    STATUS_COLUMNS,
    currency,
    dashboard_table,
    drop_unavailable_columns,
    normalize_display_column,
    percentage,
)


def _footer(canvas, document) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#5C6975"))
    canvas.drawString(
        16 * mm,
        10 * mm,
        "CITIMART™ — Results are based on the currently loaded workbook and active filters.",
    )
    canvas.drawRightString(281 * mm, 10 * mm, f"Page {document.page}")
    canvas.restoreState()


def _frame_table(frame: pd.DataFrame, max_rows: int = 25) -> Table:
    source = drop_unavailable_columns(frame.head(max_rows))
    printable = dashboard_table(source)
    status_styles: list[tuple] = []
    status_colors = {
        "Red": colors.HexColor("#C83C3A"),
        "Green": colors.HexColor("#2E8B57"),
        "Yellow": colors.HexColor("#F4B740"),
        "Neutral": colors.HexColor("#1665A8"),
        "N/A": colors.HexColor("#81909C"),
    }
    for column_index, column in enumerate(source.columns):
        normalized_column = normalize_display_column(column)
        if not (
            normalized_column in STATUS_COLUMNS
            or normalized_column.endswith("_color_code")
            or normalized_column.endswith("_status")
        ):
            continue
        for row_index, value in enumerate(source[column], start=1):
            printable.iat[row_index - 1, column_index] = ""
            status_styles.append(
                (
                    "BACKGROUND",
                    (column_index, row_index),
                    (column_index, row_index),
                    status_colors.get(str(value), status_colors["N/A"]),
                )
            )
    for column in printable.columns:
        printable[column] = printable[column].map(
            lambda value: "" if pd.isna(value) else str(value)
        )
    if not len(printable.columns):
        printable = pd.DataFrame({"Status": ["No supported data."]})

    column_weights = []
    for column in printable.columns:
        values = [str(column), *printable[column].astype(str).tolist()]
        longest = max((len(value) for value in values), default=8)
        column_weights.append(max(8, min(longest, 36)))
    total_weight = sum(column_weights) or 1
    column_widths = [
        TABLE_PDF_WIDTH * weight / total_weight for weight in column_weights
    ]
    body_font_size = 6.2 if len(printable.columns) <= 10 else 5.2
    header_style = ParagraphStyle(
        "TableHeader",
        fontName="Helvetica-Bold",
        fontSize=max(body_font_size, 6),
        leading=max(body_font_size + 1, 7),
        textColor=colors.white,
        wordWrap="CJK",
    )
    body_style = ParagraphStyle(
        "TableBody",
        fontName="Helvetica",
        fontSize=body_font_size,
        leading=body_font_size + 1.2,
        textColor=colors.HexColor("#1E2A34"),
        wordWrap="CJK",
    )
    data = [
        [Paragraph(escape(str(column)), header_style) for column in printable.columns]
    ]
    data.extend(
        [
            [
                Paragraph(
                    escape("" if pd.isna(value) else str(value)),
                    body_style,
                )
                for value in row
            ]
            for row in printable.itertuples(index=False, name=None)
        ]
    )
    table = Table(
        data,
        colWidths=column_widths,
        repeatRows=1,
        splitByRow=1,
        hAlign="CENTER",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#12304A")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CBD3DA")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F7F9")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                *status_styles,
            ]
        )
    )
    return table


def _export_chart_images(
    figures: list[tuple[str, go.Figure]],
) -> tuple[list[bytes | None], list[str]]:
    """Batch-render charts, falling back to isolated exports on failure."""
    if not figures:
        return [], []
    try:
        with TemporaryDirectory(prefix="citimart_pdf_") as directory:
            paths = [
                Path(directory) / f"chart_{index:02d}.png"
                for index in range(len(figures))
            ]
            pio.write_images(
                [figure for _, figure in figures],
                paths,
                format="png",
                width=CHART_EXPORT_WIDTH,
                height=CHART_EXPORT_HEIGHT,
                scale=1,
            )
            return [path.read_bytes() for path in paths], []
    except Exception:
        pass

    images: list[bytes | None] = []
    warnings: list[str] = []
    for title, figure in figures:
        try:
            images.append(
                figure.to_image(
                    format="png",
                    width=CHART_EXPORT_WIDTH,
                    height=CHART_EXPORT_HEIGHT,
                    scale=1,
                )
            )
        except Exception as exc:
            images.append(None)
            warnings.append(
                f"{title}: chart image omitted; install a compatible "
                f"Kaleido package ({exc})."
            )
    return images, warnings


def generate_pdf(
    filters: dict[str, str],
    kpis: dict[str, dict[str, object]],
    kpi_comparison: pd.DataFrame,
    comparison_tables: Iterable[tuple[str, pd.DataFrame]],
    forecast_overview: dict[str, str],
    warnings: list[str],
    figures: Iterable[tuple[str, go.Figure]] = (),
) -> tuple[bytes, list[str]]:
    """Return a professionally formatted filtered report and export warnings."""
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=16 * mm,
        title="CITIMART Sales KPI Dashboard Report",
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            "BrandTitle",
            parent=styles["Title"],
            textColor=colors.HexColor("#12304A"),
            fontSize=20,
            alignment=TA_CENTER,
            spaceAfter=8,
        )
    )
    story = [
        Paragraph("CITIMART™ SALES KPI DASHBOARD REPORT", styles["BrandTitle"]),
        Paragraph(
            f"Generated {datetime.now().astimezone():%d-%m-%Y}",
            styles["Normal"],
        ),
        Spacer(1, 5 * mm),
        Paragraph("Active filters", styles["Heading2"]),
        _frame_table(pd.DataFrame({"Filter": filters.keys(), "Selection": filters.values()})),
        Spacer(1, 4 * mm),
        Paragraph("KPI summary", styles["Heading2"]),
    ]
    display_rows = []
    percent_keys = {"conversion", "achievement", "discount_pct"}
    currency_keys = {"net_sales", "gross_sales", "atv", "rpv", "target"}
    for key, payload in kpis.items():
        value = payload.get("value")
        if value is None:
            continue
        if key in percent_keys:
            rendered = percentage(value)
        elif key in currency_keys:
            rendered = currency(value)
        else:
            rendered = f"{round(float(value)):,.0f}"
        display_rows.append(
            {
                "KPI": (
                    "Total Units Sold"
                    if key == "quantity"
                    else key.replace("_", " ").title()
                ),
                "Value": rendered,
                "Formula": payload.get("formula", ""),
                "Color code": payload.get("status", ""),
                "Color rule": payload.get("color_rule", ""),
                "Source": payload.get("source", ""),
            }
        )
    story.extend([_frame_table(pd.DataFrame(display_rows)), PageBreak()])
    story.extend(
        [
            Paragraph("KPI period comparison", styles["Heading1"]),
            _frame_table(kpi_comparison),
        ]
    )

    figure_items = list(figures)
    chart_images, export_warnings = _export_chart_images(figure_items)
    for (title, _), image_bytes in zip(figure_items, chart_images):
        story.append(PageBreak())
        if image_bytes is not None:
            chart_image = Image(
                BytesIO(image_bytes),
                width=CHART_PDF_WIDTH,
                height=CHART_PDF_HEIGHT,
            )
            chart_image.hAlign = "CENTER"
            story.append(
                KeepTogether(
                    [
                        Paragraph(title, styles["Heading1"]),
                        Spacer(1, 2 * mm),
                        chart_image,
                    ]
                )
            )
        else:
            story.extend(
                [
                    Paragraph(title, styles["Heading1"]),
                    Paragraph(
                        "Chart image unavailable. The corresponding table is included where available.",
                        styles["Italic"],
                    ),
                ]
            )

    for title, frame in comparison_tables:
        story.extend(
            [
                PageBreak(),
                Paragraph(title, styles["Heading1"]),
                Spacer(1, 2 * mm),
            ]
        )
        story.append(
            _frame_table(frame)
            if not frame.empty
            else Paragraph("No supported data.", styles["Italic"])
        )

    story.append(PageBreak())
    story.append(Paragraph("Forecast model overview", styles["Heading1"]))
    story.append(_frame_table(pd.DataFrame({"Item": forecast_overview.keys(), "Value": forecast_overview.values()})))
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph("Data-quality warnings", styles["Heading1"]))
    combined_warnings = warnings + export_warnings
    if combined_warnings:
        for warning in combined_warnings:
            story.append(Paragraph(f"• {warning}", styles["Normal"]))
    else:
        story.append(Paragraph("No material warnings for the active report.", styles["Normal"]))
    document.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue(), export_warnings
