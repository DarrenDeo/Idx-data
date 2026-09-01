from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb


def stage_rows_to_parquet(rows: list[dict[str, Any]], output_path: str | Path) -> Path:
    """Optional DuckDB stage for inspection/batch exchange; never the source of truth."""
    import pandas as pd

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(":memory:")
    try:
        frame = pd.DataFrame(rows)
        connection.register("ohlcv_stage", frame)
        connection.execute("COPY ohlcv_stage TO ? (FORMAT PARQUET)", [str(target)])
    finally:
        connection.close()
    return target

