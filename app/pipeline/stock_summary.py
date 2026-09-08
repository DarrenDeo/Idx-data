"""Persistence helpers for the complete public IDX Stock Summary payload."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.downloader.provider import OHLCVRecord


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    parsed = _decimal(value)
    return int(parsed) if parsed is not None else None


def stock_summary_row(record: OHLCVRecord) -> dict[str, Any]:
    """Map IDX's raw row into a typed persistence row.

    Trading-info responses do not always include the extra fields.  Missing
    values therefore remain NULL rather than being guessed.
    """

    raw = record.raw or {}
    return {
        "symbol": record.symbol.upper(),
        "trade_date": record.trade_date,
        "company_name": raw.get("StockName") or raw.get("NamaEmiten"),
        "previous": _decimal(raw.get("Previous")),
        "open_price": _decimal(raw.get("OpenPrice", record.open)),
        "first_trade": _decimal(raw.get("FirstTrade")),
        "high": _decimal(raw.get("High", record.high)),
        "low": _decimal(raw.get("Low", record.low)),
        "close": _decimal(raw.get("Close", record.close)),
        "change": _decimal(raw.get("Change")),
        "volume": _integer(raw.get("Volume", record.volume)),
        "value": _decimal(raw.get("Value")),
        "frequency": _integer(raw.get("Frequency")),
        "foreign_buy_volume": _integer(raw.get("ForeignBuy")),
        "foreign_sell_volume": _integer(raw.get("ForeignSell")),
        "non_regular_volume": _integer(raw.get("NonRegularVolume")),
        "non_regular_value": _decimal(raw.get("NonRegularValue")),
        "non_regular_frequency": _integer(raw.get("NonRegularFrequency")),
        "listed_shares": _integer(raw.get("ListedShares")),
        "tradeable_shares": _integer(raw.get("TradebleShares", raw.get("TradableShares"))),
        "weight_for_index": _decimal(raw.get("WeightForIndex")),
        "index_individual": _decimal(raw.get("IndexIndividual")),
        "source": record.source,
        "raw_payload": raw or None,
    }


def foreign_flow_row(record: OHLCVRecord) -> dict[str, Any] | None:
    raw = record.raw or {}
    if "ForeignBuy" not in raw and "ForeignSell" not in raw:
        return None
    return {
        "symbol": record.symbol.upper(),
        "trade_date": record.trade_date,
        "foreign_buy_volume": _integer(raw.get("ForeignBuy")),
        "foreign_sell_volume": _integer(raw.get("ForeignSell")),
        # IDX's public Stock Summary exposes foreign volume here, not a
        # separate buy/sell value. Keep value NULL until an official value feed
        # is available instead of multiplying by close and presenting an
        # estimate as fact.
        "foreign_buy_value": None,
        "foreign_sell_value": None,
        "foreign_net_value": None,
        "foreign_average_buy": None,
        "foreign_average_sell": None,
        "source": record.source,
    }
