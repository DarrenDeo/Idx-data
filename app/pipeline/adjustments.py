from __future__ import annotations

from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database.models import AdjustedPrice, CorporateAction, OHLCVDaily

SPLIT_TYPES = {"stock split", "stocksplit", "reverse split", "reversestock", "bonus share", "sahambonus"}


def rebuild_adjusted_prices(session: Session, symbol: str) -> int:
    """Materialize adjusted prices using only explicit positive split-like ratios.

    Rights issues are intentionally excluded because a correct adjustment also
    needs subscription-price terms that the public payload may not provide.
    """
    symbol = symbol.upper()
    actions = list(
        session.scalars(
            select(CorporateAction)
            .where(CorporateAction.symbol == symbol, CorporateAction.ratio.is_not(None))
            .order_by(CorporateAction.ex_date)
        )
    )
    usable = [
        action
        for action in actions
        if action.ratio and action.ratio > 0 and action.action_type.lower().replace("_", " ") in SPLIT_TYPES
    ]
    prices = list(
        session.scalars(
            select(OHLCVDaily).where(OHLCVDaily.symbol == symbol).order_by(OHLCVDaily.trade_date)
        )
    )
    session.execute(delete(AdjustedPrice).where(AdjustedPrice.symbol == symbol))
    for price in prices:
        factor = Decimal("1")
        for action in usable:
            if action.ex_date > price.trade_date:
                factor *= Decimal(action.ratio)
        session.add(
            AdjustedPrice(
                symbol=symbol,
                trade_date=price.trade_date,
                adjustment_factor=factor,
                adjusted_open=Decimal(price.open) / factor,
                adjusted_high=Decimal(price.high) / factor,
                adjusted_low=Decimal(price.low) / factor,
                adjusted_close=Decimal(price.close) / factor,
                adjusted_volume=int(Decimal(price.volume) * factor),
            )
        )
    session.commit()
    return len(prices)

