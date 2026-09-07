"""Small, explicit CSV import helpers for optional benchmark/flow datasets."""

from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import Any


MAX_IMPORT_ROWS = 100_000


def _value(row: dict[str, str], *names: str) -> str | None:
    lowered = {str(key).strip().lower(): value for key, value in row.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return None


def _date(row: dict[str, str], *names: str) -> date:
    value = _value(row, *names)
    if not value:
        raise ValueError(f"missing {names[0]}")
    text = value.split("T", 1)[0][:10]
    return datetime.strptime(text, "%Y-%m-%d").date()


def _decimal(row: dict[str, str], *names: str) -> Decimal | None:
    value = _value(row, *names)
    if value is None:
        return None
    try:
        return Decimal(value.replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError(f"{names[0]} is not numeric") from exc


def _integer(row: dict[str, str], *names: str) -> int | None:
    value = _value(row, *names)
    if value is None:
        return None
    try:
        return int(Decimal(value.replace(",", "")))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{names[0]} is not an integer") from exc


def _rows(content: str) -> list[dict[str, str]]:
    reader = csv.DictReader(StringIO(content.lstrip("\ufeff")))
    if not reader.fieldnames:
        raise ValueError("CSV harus memiliki header")
    rows = list(reader)
    if not rows:
        raise ValueError("CSV tidak memiliki data")
    if len(rows) > MAX_IMPORT_ROWS:
        raise ValueError(f"CSV melebihi batas {MAX_IMPORT_ROWS:,} baris")
    return rows


def parse_dataset(dataset: str, content: str, source: str = "import") -> tuple[list[dict[str, Any]], list[str]]:
    """Parse a supported dataset and return valid rows plus human-readable errors."""

    dataset = dataset.lower().strip()
    if dataset not in {"benchmark", "foreign-flow", "broker-summary"}:
        raise ValueError("dataset harus benchmark, foreign-flow, atau broker-summary")
    parsed: list[dict[str, Any]] = []
    errors: list[str] = []
    for number, row in enumerate(_rows(content), start=2):
        try:
            trade_date = _date(row, "trade_date", "date", "tanggal")
            if dataset == "benchmark":
                benchmark = (_value(row, "benchmark", "symbol", "index") or "IHSG").upper()
                close = _decimal(row, "close", "last", "closing_price")
                if close is None:
                    raise ValueError("missing close")
                parsed.append(
                    {
                        "benchmark": benchmark,
                        "trade_date": trade_date,
                        "open": _decimal(row, "open"),
                        "high": _decimal(row, "high"),
                        "low": _decimal(row, "low"),
                        "close": close,
                        "volume": _integer(row, "volume"),
                        "source": source,
                    }
                )
            elif dataset == "foreign-flow":
                symbol = (_value(row, "symbol", "ticker", "kode_emiten") or "").upper()
                if not symbol:
                    raise ValueError("missing symbol")
                buy_value = _decimal(row, "foreign_buy_value", "buy_value")
                sell_value = _decimal(row, "foreign_sell_value", "sell_value")
                net_value = _decimal(row, "foreign_net_value", "net_value")
                if net_value is None and (buy_value is not None or sell_value is not None):
                    net_value = (buy_value or Decimal(0)) - (sell_value or Decimal(0))
                parsed.append(
                    {
                        "symbol": symbol,
                        "trade_date": trade_date,
                        "foreign_buy_volume": _integer(row, "foreign_buy_volume", "buy_volume"),
                        "foreign_sell_volume": _integer(row, "foreign_sell_volume", "sell_volume"),
                        "foreign_buy_value": buy_value,
                        "foreign_sell_value": sell_value,
                        "foreign_net_value": net_value,
                        "foreign_average_buy": _decimal(row, "foreign_average_buy", "buy_average"),
                        "foreign_average_sell": _decimal(row, "foreign_average_sell", "sell_average"),
                        "source": source,
                    }
                )
            else:
                symbol = (_value(row, "symbol", "ticker", "kode_emiten") or "").upper()
                broker = (_value(row, "broker_code", "broker", "kode_broker") or "").upper()
                if not symbol or not broker:
                    raise ValueError("missing symbol or broker_code")
                buy_value = _decimal(row, "buy_value", "buy_amount")
                sell_value = _decimal(row, "sell_value", "sell_amount")
                net_value = _decimal(row, "net_value")
                if net_value is None and (buy_value is not None or sell_value is not None):
                    net_value = (buy_value or Decimal(0)) - (sell_value or Decimal(0))
                buy_volume = _integer(row, "buy_volume")
                sell_volume = _integer(row, "sell_volume")
                parsed.append(
                    {
                        "symbol": symbol,
                        "trade_date": trade_date,
                        "broker_code": broker,
                        "broker_name": _value(row, "broker_name", "name"),
                        "buy_volume": buy_volume,
                        "sell_volume": sell_volume,
                        "buy_value": buy_value,
                        "sell_value": sell_value,
                        "buy_average": _decimal(row, "buy_average", "avg_buy"),
                        "sell_average": _decimal(row, "sell_average", "avg_sell"),
                        "net_volume": _integer(row, "net_volume"),
                        "net_value": net_value,
                        "buy_frequency": _integer(row, "buy_frequency", "buy_freq"),
                        "sell_frequency": _integer(row, "sell_frequency", "sell_freq"),
                        "source": source,
                    }
                )
        except (ValueError, TypeError) as exc:
            errors.append(f"baris {number}: {exc}")
    if not parsed and errors:
        raise ValueError(errors[0])
    return parsed, errors[:20]

