"""Small, explicit CSV import helpers for optional benchmark/flow datasets."""

from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO, StringIO
from pathlib import PurePath
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


def _datetime(row: dict[str, str], *names: str) -> datetime:
    value = _value(row, *names)
    if not value:
        raise ValueError(f"missing {names[0]}")
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{names[0]} is not a valid datetime") from exc


def _json_value(row: dict[str, str], *names: str) -> dict[str, Any] | None:
    value = _value(row, *names)
    if value is None:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{names[0]} is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{names[0]} must be a JSON object")
    return parsed


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


def parse_uploaded_file(
    dataset: str,
    filename: str,
    content: bytes,
    source: str = "import",
) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse a CSV or Excel upload through the same strict dataset contract.

    Excel is converted to CSV in memory before validation, so the existing
    column aliases and row-level warnings are identical for both formats.
    The workbook is never written to disk.
    """

    suffix = PurePath(filename or "").suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        try:
            from openpyxl import load_workbook

            def normal_header(value: Any) -> str:
                header = re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")
                return {
                    "tanggal": "trade_date",
                    "date": "trade_date",
                    "index": "benchmark",
                    "kode_emiten": "symbol",
                    "broker": "broker_code",
                    "avg_buy": "buy_average",
                    "avg_sell": "sell_average",
                }.get(header, header)

            workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
            values: list[tuple[Any, ...]] | None = None
            required = {
                "ohlcv": {"symbol", "trade_date", "open", "high", "low", "close", "volume"},
                "stock-summary": {"symbol", "trade_date"},
                "index-summary": {"benchmark", "trade_date", "close"},
                "benchmark": {"benchmark", "trade_date", "close"},
                "foreign-flow": {"symbol", "trade_date"},
                "broker-summary": {"symbol", "trade_date", "broker_code"},
                "order-book": {"symbol", "captured_at", "level"},
                "intraday-trades": {"symbol", "traded_at", "price", "volume"},
                "fundamentals": {"symbol", "fiscal_year", "fiscal_quarter"},
                "events": {"event_date", "event_type"},
                "news": {"published_at", "title"},
            }.get(dataset.lower(), set())
            for sheet in workbook.worksheets:
                sheet_values = list(sheet.iter_rows(values_only=True))
                for header_index, candidate in enumerate(sheet_values[:20]):
                    headers = {normal_header(value) for value in candidate if value not in (None, "")}
                    if required.issubset(headers):
                        values = sheet_values[header_index:]
                        break
                if values is not None:
                    break
            if not values:
                raise ValueError("Excel tidak memiliki header dataset yang sesuai")
            values = [
                tuple(
                    normal_header(value)
                    if value not in (None, "")
                    else ""
                    for value in values[0]
                ),
                *values[1:],
            ]
            output = StringIO(newline="")
            writer = csv.writer(output)
            writer.writerows(values)
            text = output.getvalue()
            workbook.close()
        except Exception as exc:  # pragma: no cover - engine-specific message
            raise ValueError(f"Excel tidak dapat dibaca: {exc}") from exc
        if text.count("\n") <= 1:
            raise ValueError("Excel tidak memiliki data")
    elif suffix == ".xls":
        raise ValueError("Excel legacy .xls belum didukung; simpan sebagai .xlsx")
    else:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("CSV harus menggunakan UTF-8") from exc
    return parse_dataset(dataset, text, source)


def parse_dataset(dataset: str, content: str, source: str = "import") -> tuple[list[dict[str, Any]], list[str]]:
    """Parse a supported dataset and return valid rows plus human-readable errors."""

    dataset = dataset.lower().strip()
    supported = {
        "ohlcv", "benchmark", "index-summary", "stock-summary", "foreign-flow",
        "broker-summary", "order-book", "intraday-trades", "fundamentals", "events", "news",
    }
    if dataset not in supported:
        raise ValueError("dataset tidak didukung")
    parsed: list[dict[str, Any]] = []
    errors: list[str] = []
    for number, row in enumerate(_rows(content), start=2):
        try:
            trade_date = (
                _date(row, "event_date" if dataset == "events" else "trade_date", "date", "tanggal")
                if dataset in {"ohlcv", "benchmark", "index-summary", "stock-summary", "foreign-flow", "broker-summary", "events"}
                else None
            )
            if dataset == "ohlcv":
                symbol = (_value(row, "symbol", "ticker", "kode_emiten", "code") or "").upper()
                if not symbol:
                    raise ValueError("missing symbol")
                open_price = _decimal(row, "open")
                high = _decimal(row, "high")
                low = _decimal(row, "low")
                close = _decimal(row, "close", "last", "closing_price")
                volume = _integer(row, "volume")
                if None in (open_price, high, low, close, volume):
                    raise ValueError("OHLCV membutuhkan open, high, low, close, dan volume")
                if high < open_price or high < close or low > open_price or low > close:
                    raise ValueError("candle OHLCV tidak valid: high/low tidak mencakup open/close")
                if volume < 0:
                    raise ValueError("volume tidak boleh negatif")
                parsed.append(
                    {
                        "symbol": symbol,
                        "trade_date": trade_date,
                        "open": open_price,
                        "high": high,
                        "low": low,
                        "close": close,
                        "volume": volume,
                        "source": source,
                    }
                )
            elif dataset in {"benchmark", "index-summary"}:
                benchmark = (_value(row, "benchmark", "symbol", "index") or "IHSG").upper()
                close = _decimal(row, "close", "last", "closing_price")
                if close is None:
                    raise ValueError("missing close")
                if dataset == "benchmark":
                    parsed.append({"benchmark": benchmark, "trade_date": trade_date, "open": _decimal(row, "open"), "high": _decimal(row, "high"), "low": _decimal(row, "low"), "close": close, "volume": _integer(row, "volume"), "source": source})
                else:
                    parsed.append({"benchmark": benchmark, "trade_date": trade_date, "previous": _decimal(row, "previous"), "highest": _decimal(row, "highest", "high"), "lowest": _decimal(row, "lowest", "low"), "close": close, "change": _decimal(row, "change"), "number_of_stock": _integer(row, "number_of_stock", "number_of_stocks"), "volume": _integer(row, "volume"), "value": _decimal(row, "value"), "frequency": _integer(row, "frequency"), "source": source, "raw_payload": None})
            elif dataset == "stock-summary":
                symbol = (_value(row, "symbol", "ticker", "stock_code", "kode_emiten") or "").upper()
                if not symbol:
                    raise ValueError("missing symbol")
                parsed.append({
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "company_name": _value(row, "company_name", "stock_name", "nama_emiten"),
                    "previous": _decimal(row, "previous"),
                    "open_price": _decimal(row, "open_price", "open"),
                    "first_trade": _decimal(row, "first_trade"),
                    "high": _decimal(row, "high"),
                    "low": _decimal(row, "low"),
                    "close": _decimal(row, "close"),
                    "change": _decimal(row, "change"),
                    "volume": _integer(row, "volume"),
                    "value": _decimal(row, "value"),
                    "frequency": _integer(row, "frequency"),
                    "foreign_buy_volume": _integer(row, "foreign_buy_volume", "foreign_buy"),
                    "foreign_sell_volume": _integer(row, "foreign_sell_volume", "foreign_sell"),
                    "non_regular_volume": _integer(row, "non_regular_volume"),
                    "non_regular_value": _decimal(row, "non_regular_value"),
                    "non_regular_frequency": _integer(row, "non_regular_frequency"),
                    "listed_shares": _integer(row, "listed_shares"),
                    "tradeable_shares": _integer(row, "tradeable_shares", "tradable_shares"),
                    "weight_for_index": _decimal(row, "weight_for_index"),
                    "index_individual": _decimal(row, "index_individual"),
                    "source": source,
                    "raw_payload": None,
                })
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
            elif dataset == "broker-summary":
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
            elif dataset == "order-book":
                symbol = (_value(row, "symbol", "ticker") or "").upper()
                if not symbol:
                    raise ValueError("missing symbol")
                parsed.append({"symbol": symbol, "captured_at": _datetime(row, "captured_at", "timestamp", "datetime"), "level": _integer(row, "level") or 1, "bid_price": _decimal(row, "bid_price"), "bid_volume": _integer(row, "bid_volume"), "offer_price": _decimal(row, "offer_price", "ask_price"), "offer_volume": _integer(row, "offer_volume", "ask_volume"), "indicative_price": _decimal(row, "indicative_price"), "source": source, "raw_payload": None})
            elif dataset == "intraday-trades":
                symbol = (_value(row, "symbol", "ticker") or "").upper()
                if not symbol:
                    raise ValueError("missing symbol")
                price = _decimal(row, "price", "trade_price")
                volume = _integer(row, "volume")
                if price is None or volume is None:
                    raise ValueError("intraday trade membutuhkan price dan volume")
                parsed.append({"symbol": symbol, "traded_at": _datetime(row, "traded_at", "timestamp", "datetime"), "sequence": _integer(row, "sequence") or 0, "price": price, "volume": volume, "buyer_broker": _value(row, "buyer_broker", "buyer"), "seller_broker": _value(row, "seller_broker", "seller"), "source": source, "raw_payload": None})
            elif dataset == "fundamentals":
                symbol = (_value(row, "symbol", "ticker") or "").upper()
                fiscal_year = _integer(row, "fiscal_year", "year")
                fiscal_quarter = _integer(row, "fiscal_quarter", "quarter")
                if not symbol or fiscal_year is None or fiscal_quarter is None:
                    raise ValueError("fundamental membutuhkan symbol, fiscal_year, dan fiscal_quarter")
                parsed.append({"symbol": symbol, "fiscal_year": fiscal_year, "fiscal_quarter": fiscal_quarter, "report_date": _date(row, "report_date", "date", "tanggal") if _value(row, "report_date", "date", "tanggal") else None, "revenue": _decimal(row, "revenue"), "ebitda": _decimal(row, "ebitda"), "net_income": _decimal(row, "net_income"), "operating_cash_flow": _decimal(row, "operating_cash_flow"), "capex": _decimal(row, "capex"), "cash": _decimal(row, "cash"), "debt": _decimal(row, "debt"), "shares_outstanding": _integer(row, "shares_outstanding"), "segment_revenue": _json_value(row, "segment_revenue"), "major_ownership": _json_value(row, "major_ownership"), "source": source, "raw_payload": None})
            elif dataset == "events":
                symbol = (_value(row, "symbol", "ticker") or "").upper() or None
                event_type = _value(row, "event_type", "type")
                if not event_type:
                    raise ValueError("missing event_type")
                parsed.append({"symbol": symbol, "event_date": trade_date, "event_type": event_type, "title": _value(row, "title", "name"), "status": _value(row, "status"), "source_id": _value(row, "source_id", "id") or "", "source": source, "raw_payload": None})
            elif dataset == "news":
                title = _value(row, "title", "headline")
                if not title:
                    raise ValueError("missing title")
                parsed.append({"symbol": (_value(row, "symbol", "ticker") or "").upper() or None, "published_at": _datetime(row, "published_at", "timestamp", "datetime"), "title": title, "publisher": _value(row, "publisher", "source_name"), "url": _value(row, "url", "link"), "sentiment_score": _decimal(row, "sentiment_score"), "sentiment_label": _value(row, "sentiment_label"), "source": source, "raw_payload": None})
        except (ValueError, TypeError) as exc:
            errors.append(f"baris {number}: {exc}")
    if not parsed and errors:
        raise ValueError(errors[0])
    return parsed, errors[:20]

