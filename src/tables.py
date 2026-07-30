"""Table export helpers."""

from __future__ import annotations

import pandas as pd


def to_csv_bytes(frame: pd.DataFrame) -> bytes:
    """Encode the currently filtered table as UTF-8 with Excel-friendly BOM."""
    return frame.to_csv(index=False).encode("utf-8-sig")


def with_grand_total(frame: pd.DataFrame, label_column: str) -> pd.DataFrame:
    """Append a numeric grand-total row when useful."""
    if frame.empty or label_column not in frame:
        return frame
    row: dict[str, object] = {label_column: "Grand Total"}
    for column in frame.select_dtypes(include="number"):
        row[column] = frame[column].sum(min_count=1)
    return pd.concat([frame, pd.DataFrame([row])], ignore_index=True)

