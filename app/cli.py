from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date
from typing import Any, Coroutine

from app.config import settings
from app.database.connection import SessionLocal, engine
from app.database.models import Base
from app.database.queries import active_symbols
from app.downloader.provider import IDXProvider
from app.pipeline.adjustments import rebuild_adjusted_prices
from app.pipeline.backfill import backfill_ohlcv
from app.pipeline.corporate_actions import sync_corporate_actions
from app.pipeline.daily import daily_market_update
from app.pipeline.incremental import incremental_update
from app.pipeline.symbols import sync_symbols


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _run_async(coroutine: Coroutine[Any, Any, Any]) -> Any:
    try:
        return asyncio.run(coroutine)
    except KeyboardInterrupt:
        logging.getLogger(__name__).warning("Operation cancelled by user")
        raise SystemExit(130) from None


async def _run_with_provider(provider: IDXProvider, coroutine: Coroutine[Any, Any, Any]) -> Any:
    try:
        return await coroutine
    finally:
        await provider.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="idx-platform")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db")
    sub.add_parser("sync-symbols")

    backfill = sub.add_parser("backfill")
    backfill.add_argument("--symbols", nargs="+")
    backfill.add_argument("--start", type=_date, required=True)
    backfill.add_argument("--end", type=_date, default=date.today())

    incremental = sub.add_parser("incremental")
    incremental.add_argument("--end", type=_date, default=date.today())

    daily = sub.add_parser("daily")
    daily.add_argument("--end", type=_date, default=date.today())

    actions = sub.add_parser("corporate-actions")
    actions.add_argument("--symbols", nargs="+")
    actions.add_argument("--start", type=_date, required=True)
    actions.add_argument("--end", type=_date, required=True)

    adjust = sub.add_parser("adjust")
    adjust.add_argument("symbols", nargs="+")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if args.command == "init-db":
        Base.metadata.create_all(engine)
        return

    provider = IDXProvider()
    with SessionLocal() as session:
        if args.command == "sync-symbols":
            print(_run_async(_run_with_provider(provider, sync_symbols(session, provider))))
        elif args.command == "backfill":
            print(
                _run_async(
                    _run_with_provider(
                        provider,
                        backfill_ohlcv(
                            session,
                            provider,
                            args.symbols,
                            args.start,
                            args.end,
                            concurrency=settings.idx_concurrency,
                        ),
                    )
                )
            )
        elif args.command == "incremental":
            print(
                _run_async(
                    _run_with_provider(
                        provider,
                        incremental_update(
                            session, provider, args.end, concurrency=settings.idx_concurrency
                        ),
                    )
                )
            )
        elif args.command == "daily":
            print(
                _run_async(
                    _run_with_provider(
                        provider,
                        daily_market_update(
                            session, provider, args.end, concurrency=settings.idx_concurrency
                        ),
                    )
                )
            )
        elif args.command == "corporate-actions":
            symbols = args.symbols or [stock.symbol for stock in active_symbols(session)]
            print(
                _run_async(
                    _run_with_provider(
                        provider,
                        sync_corporate_actions(
                            session,
                            provider,
                            symbols,
                            args.start,
                            args.end,
                            concurrency=settings.idx_concurrency,
                        ),
                    )
                )
            )
        elif args.command == "adjust":
            print({symbol: rebuild_adjusted_prices(session, symbol) for symbol in args.symbols})


if __name__ == "__main__":
    main()
