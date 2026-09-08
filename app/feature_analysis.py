"""Feature summaries for optional level-2, intraday, fundamental, and event data."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


def _number(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def summarize_order_book(rows: Iterable[Any]) -> dict[str, Any]:
    values = list(rows)
    if not values:
        return {"status": "no-data", "levels": 0, "imbalance": None, "spread": None}
    latest_capture = max(
        (getattr(row, "captured_at", None) for row in values),
        default=None,
    )
    if latest_capture is not None:
        values = [row for row in values if getattr(row, "captured_at", None) == latest_capture]
    best = sorted(values, key=lambda row: getattr(row, "level", 0))
    first = best[0]
    bid = _number(getattr(first, "bid_price", None))
    offer = _number(getattr(first, "offer_price", None))
    bid_volume = sum(_number(getattr(row, "bid_volume", None)) or 0.0 for row in values)
    offer_volume = sum(_number(getattr(row, "offer_volume", None)) or 0.0 for row in values)
    total = bid_volume + offer_volume
    return {"status": "ready", "levels": len(values), "best_bid": bid, "best_offer": offer, "spread": offer - bid if bid is not None and offer is not None else None, "bid_volume": bid_volume, "offer_volume": offer_volume, "imbalance": (bid_volume - offer_volume) / total if total else None}


def summarize_intraday(rows: Iterable[Any]) -> dict[str, Any]:
    values = list(rows)
    if not values:
        return {"status": "no-data", "trades": 0, "vwap": None, "volume": 0}
    volume = sum(int(getattr(row, "volume", 0) or 0) for row in values)
    notional = sum((_number(getattr(row, "price", None)) or 0.0) * int(getattr(row, "volume", 0) or 0) for row in values)
    buyer_volume: defaultdict[str, int] = defaultdict(int)
    seller_volume: defaultdict[str, int] = defaultdict(int)
    for row in values:
        buyer = getattr(row, "buyer_broker", None)
        seller = getattr(row, "seller_broker", None)
        if buyer:
            buyer_volume[str(buyer)] += int(getattr(row, "volume", 0) or 0)
        if seller:
            seller_volume[str(seller)] += int(getattr(row, "volume", 0) or 0)
    return {"status": "ready", "trades": len(values), "volume": volume, "vwap": notional / volume if volume else None, "top_buyers": sorted(buyer_volume.items(), key=lambda item: item[1], reverse=True)[:5], "top_sellers": sorted(seller_volume.items(), key=lambda item: item[1], reverse=True)[:5]}


def summarize_fundamentals(rows: Iterable[Any]) -> dict[str, Any]:
    values = sorted(rows, key=lambda row: (getattr(row, "fiscal_year", 0), getattr(row, "fiscal_quarter", 0)))
    if not values:
        return {"status": "no-data", "quarters": 0}
    latest = values[-1]
    revenue = _number(getattr(latest, "revenue", None))
    net_income = _number(getattr(latest, "net_income", None))
    debt = _number(getattr(latest, "debt", None))
    cash = _number(getattr(latest, "cash", None))
    return {"status": "ready", "quarters": len(values), "latest_period": f"{latest.fiscal_year}-Q{latest.fiscal_quarter}", "revenue": revenue, "net_income": net_income, "net_margin": net_income / revenue if revenue else None, "debt": debt, "cash": cash, "net_debt": debt - cash if debt is not None and cash is not None else None}


def summarize_events(rows: Iterable[Any]) -> dict[str, Any]:
    values = list(rows)
    return {"status": "ready" if values else "no-data", "count": len(values), "types": sorted({str(getattr(row, "event_type", "")) for row in values})}
