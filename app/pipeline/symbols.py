from __future__ import annotations

from sqlalchemy.orm import Session

from app.database.queries import finish_etl_run, start_etl_run, upsert_stocks
from app.downloader.provider import MarketDataProvider
from app.monitoring import record_etl_result


async def sync_symbols(session: Session, provider: MarketDataProvider) -> int:
    run = start_etl_run(session, "sync_symbols")
    try:
        records = await provider.get_symbols()
        loaded = upsert_stocks(
            session,
            [
                {
                    "symbol": item.symbol,
                    "company_name": item.company_name,
                    "sector": item.sector,
                    "sub_sector": item.sub_sector,
                    "listing_date": item.listing_date,
                    "active": item.active,
                }
                for item in records
            ],
        )
        finish_etl_run(session, run, status="SUCCESS", rows_loaded=loaded)
        session.commit()
        record_etl_result("sync_symbols", "SUCCESS", loaded)
        return loaded
    except Exception as exc:
        session.rollback()
        run = start_etl_run(session, "sync_symbols")
        finish_etl_run(session, run, status="FAILED", rows_loaded=0, error_message=str(exc))
        session.commit()
        record_etl_result("sync_symbols", "FAILED", 0)
        raise
