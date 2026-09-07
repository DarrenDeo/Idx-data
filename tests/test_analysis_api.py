from datetime import date, timedelta
from decimal import Decimal
from zipfile import ZipFile
from io import BytesIO

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.database.models import BenchmarkDaily, BrokerSummaryDaily
from app.database.queries import upsert_ohlcv, upsert_stocks
from app.database.connection import get_db


def test_analysis_endpoint_and_exports(session):
    upsert_stocks(session, [{"symbol": "BBCA", "active": True}])
    rows = []
    for index in range(60):
        day = date(2026, 1, 2) + timedelta(days=index)
        rows.append(
            {
                "symbol": "BBCA",
                "trade_date": day,
                "open": Decimal(100 + index),
                "high": Decimal(102 + index),
                "low": Decimal(99 + index),
                "close": Decimal(101 + index),
                "volume": 1000 + index,
                "source": "test",
            }
        )
    upsert_ohlcv(session, rows)
    session.add_all(
        [
            BenchmarkDaily(benchmark="IHSG", trade_date=date(2026, 2, 28), close=Decimal("7000")),
            BenchmarkDaily(benchmark="IHSG", trade_date=date(2026, 2, 27), close=Decimal("6990")),
        ]
    )
    session.add(
        BrokerSummaryDaily(
            symbol="BBCA",
            trade_date=date(2026, 2, 28),
            broker_code="YP",
            broker_name="Test Broker",
            buy_volume=100,
            sell_volume=40,
            buy_value=Decimal("1000000"),
            sell_value=Decimal("400000"),
        )
    )
    session.commit()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app)

    analysis = client.get("/ui/api/analysis?symbols=BBCA&from=2026-02-20&to=2026-03-02")
    assert analysis.status_code == 200
    assert analysis.json()[-1]["ma50"] is not None

    broker = client.get("/ui/api/broker-summary?symbol=BBCA")
    assert broker.status_code == 200
    assert broker.json()["top_buyers"][0]["broker_code"] == "YP"

    csv_response = client.get("/export/analysis.csv?symbols=BBCA&from=2026-02-20&to=2026-03-02")
    assert csv_response.status_code == 200
    assert "ma50" in csv_response.text

    xlsx_response = client.get("/export/broker-summary.xlsx?symbol=BBCA")
    assert xlsx_response.status_code == 200
    with ZipFile(BytesIO(xlsx_response.content)) as workbook:
        assert "xl/worksheets/sheet2.xml" in workbook.namelist()
        assert b"Test Broker" in workbook.read("xl/worksheets/sheet2.xml")
