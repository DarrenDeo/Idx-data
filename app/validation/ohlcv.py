from __future__ import annotations

import json
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
from typing import Any

from app.downloader.provider import OHLCVRecord


class OHLCVValidationError(ValueError):
    pass


def is_no_trade(record: OHLCVRecord) -> bool:
    """Return true for an IDX market row that has no executed share volume."""

    try:
        return int(record.volume) == 0
    except (TypeError, ValueError):
        return False


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise OHLCVValidationError(f"{field} is not numeric") from exc
    if not result.is_finite():
        raise OHLCVValidationError(f"{field} must be finite")
    return result


def validate_ohlcv(record: OHLCVRecord) -> OHLCVRecord:
    open_price = _decimal(record.open, "open")
    high = _decimal(record.high, "high")
    low = _decimal(record.low, "low")
    close = _decimal(record.close, "close")
    try:
        volume = int(record.volume)
    except (TypeError, ValueError) as exc:
        raise OHLCVValidationError("volume is not an integer") from exc

    errors: list[str] = []
    if high < open_price:
        errors.append("high < open")
    if high < close:
        errors.append("high < close")
    if low > open_price:
        errors.append("low > open")
    if low > close:
        errors.append("low > close")
    if volume < 0:
        errors.append("volume < 0")
    if errors:
        raise OHLCVValidationError("; ".join(errors))

    return OHLCVRecord(
        symbol=record.symbol.upper(),
        trade_date=record.trade_date,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        source=record.source,
        raw=record.raw,
    )


def validate_batch(records: list[OHLCVRecord]) -> tuple[list[OHLCVRecord], list[dict[str, Any]]]:
    valid: list[OHLCVRecord] = []
    errors: list[dict[str, Any]] = []
    for record in records:
        try:
            valid.append(validate_ohlcv(record))
        except OHLCVValidationError as exc:
            errors.append(
                {
                    "symbol": record.symbol,
                    "trade_date": record.trade_date,
                    "error_message": str(exc),
                    "raw_payload": json.loads(json.dumps(record.raw or asdict(record), default=str)),
                }
            )
    return valid, errors
