from datetime import date
from decimal import Decimal

import pytest

from app.database.models import BenchmarkDaily, IndexSummaryDaily
from app.pipeline.index_summary import backfill_index_summary, benchmark_backfill_start
from app.downloader.provider import IndexSummaryRecord


class StaticIndexProvider:
    async def get_index_summary(self, trade_date):
        return [
            IndexSummaryRecord(
                benchmark="COMPOSITE",
                trade_date=trade_date,
                previous=Decimal("6900"),
                highest=Decimal("7010"),
                lowest=Decimal("6880"),
                close=Decimal("7000"),
                change=Decimal("100"),
                number_of_stock=900,
                volume=1000,
                value=Decimal("2000000"),
                frequency=100,
            )
        ]


def test_benchmark_backfill_start_includes_history_buffer():
    assert benchmark_backfill_start(date(2026, 9, 7)) == date(2026, 7, 9)


@pytest.mark.asyncio
async def test_index_summary_persists_detail_and_compatibility_benchmark(session):
    result = await backfill_index_summary(session, StaticIndexProvider(), date(2026, 8, 28), date(2026, 8, 28))
    assert result["rows_loaded"] == 1
    assert session.query(IndexSummaryDaily).count() == 1
    assert session.query(BenchmarkDaily).filter_by(benchmark="IHSG").count() == 1
