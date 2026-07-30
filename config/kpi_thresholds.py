"""KPI colour rules shared by cards, gauges, tables, charts, and PDFs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


PERCENTAGE_KPIS = {"conversion", "achievement"}
CURRENCY_KPIS = {"atv", "rpv"}


@dataclass(frozen=True)
class KPIColorRule:
    """Red/Yellow/Green bands sourced from the workbook."""

    metric: str
    label: str
    lower_bound: float
    upper_bound: float
    red_text: str
    yellow_text: str
    green_text: str
    source: str = "COLOUR FORMATTING"

    def status(self, value: float | None) -> str:
        if value is None:
            return "N/A"
        if value < self.lower_bound:
            return "Red"
        if value <= self.upper_bound:
            return "Yellow"
        return "Green"

    @property
    def description(self) -> str:
        return (
            f"Red {self.red_text}; Yellow {self.yellow_text}; "
            f"Green {self.green_text}"
        )


DEFAULT_KPI_COLOR_RULES: dict[str, KPIColorRule] = {
    "atv": KPIColorRule(
        "atv", "ATV", 900.0, 1100.0, "< 900", "900 to 1100", "> 1100"
    ),
    "rpv": KPIColorRule(
        "rpv", "RPV", 500.0, 700.0, "< 500", "500 to 700", "> 700"
    ),
    "basket_size": KPIColorRule(
        "basket_size", "BUSKET SIZE", 2.0, 5.0, "< 2", "2 to 5", "> 5"
    ),
    "conversion": KPIColorRule(
        "conversion",
        "CONVERSION PERCENTAGE",
        0.45,
        0.55,
        "< 45%",
        "45% to 55%",
        "> 55%",
    ),
    "achievement": KPIColorRule(
        "achievement",
        "ACHIEVEMNET PERCENTAGE",
        0.80,
        1.00,
        "< 80%",
        "80% to 100%",
        "> 100",
    ),
}

# Compatibility aliases used by existing chart call sites.
ATV_TARGET = DEFAULT_KPI_COLOR_RULES["atv"].lower_bound
CONVERSION_TARGET = DEFAULT_KPI_COLOR_RULES["conversion"].lower_bound
CONVERSION_GREEN = DEFAULT_KPI_COLOR_RULES["conversion"].upper_bound
ACHIEVEMENT_WARNING = DEFAULT_KPI_COLOR_RULES["achievement"].lower_bound
ACHIEVEMENT_TARGET = DEFAULT_KPI_COLOR_RULES["achievement"].upper_bound


def status_for(
    metric: str,
    value: float | None,
    rules: Mapping[str, KPIColorRule] | None = None,
) -> str:
    active_rules = DEFAULT_KPI_COLOR_RULES if rules is None else rules
    rule = active_rules.get(metric)
    if value is None:
        return "N/A"
    return rule.status(value) if rule else "Neutral"


def atv_status(value: float | None) -> str:
    return status_for("atv", value)


def rpv_status(value: float | None) -> str:
    return status_for("rpv", value)


def basket_size_status(value: float | None) -> str:
    return status_for("basket_size", value)


def conversion_status(value: float | None) -> str:
    return status_for("conversion", value)


def achievement_status(value: float | None) -> str:
    return status_for("achievement", value)


def _formatted_threshold(metric: str, value: float) -> str:
    if metric in PERCENTAGE_KPIS:
        return f"{value:.0%}"
    if metric in CURRENCY_KPIS:
        return f"₹{value:,.0f}"
    return f"{value:,.1f}".rstrip("0").rstrip(".")


def gauge_assessment(
    metric: str,
    value: float | None,
    rule: KPIColorRule | None = None,
) -> tuple[str, str]:
    """Return a status and worksheet-aligned management remark."""
    if value is None:
        return "N/A", "Unavailable for the active filters or source scope."
    selected = rule or DEFAULT_KPI_COLOR_RULES.get(metric)
    if selected is None:
        return "Neutral", "No colour rule is defined in COLOUR FORMATTING."

    status = selected.status(value)
    lower = _formatted_threshold(metric, selected.lower_bound)
    upper = _formatted_threshold(metric, selected.upper_bound)
    if status == "Red":
        return status, f"Below {lower}. Worksheet rule: {selected.red_text}."
    if status == "Yellow":
        return (
            status,
            f"Within the {lower} to {upper} watch band. "
            f"Green requires {selected.green_text}.",
        )
    return status, f"Green band achieved. Worksheet rule: {selected.green_text}."
