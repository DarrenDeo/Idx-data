from datetime import date

import pytest

from app.database.models import MarketBrokerSummaryDaily
from app.pipeline.market_broker import backfill_market_broker_summary


class StaticMarketBrokerProvider:
    async def get_market_broker_summary(self, trade_date):
        return [
            type(
                "Record",
                (),
                {
                    "trade_date": trade_date,
                    "broker_code": "YP",
                    "broker_name": "Yapindo Sekuritas",
                    "volume": 100,
                    "value": 250,
                    "frequency": 4,
                    "source": "idx_public",
                },
            )()
        ]


@pytest.mark.asyncio
async def test_market_broker_pipeline_upserts_each_weekday(session):
    result = await backfill_market_broker_summary(
        session,
        StaticMarketBrokerProvider(),
        date(2026, 8, 24),
        date(2026, 8, 28),
    )
    assert result == {"rows_loaded": 5, "rows_rejected": 0, "dates_failed": 0}
    rows = session.query(MarketBrokerSummaryDaily).all()
    assert len(rows) == 5
    assert rows[0].broker_code == "YP"
