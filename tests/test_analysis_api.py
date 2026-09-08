from datetime import date, datetime, timedelta
from decimal import Decimal
from zipfile import ZipFile
from io import BytesIO
from openpyxl import Workbook
import pytest

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.database.models import (
    AdjustedPrice,
    BenchmarkDaily,
    BrokerSummaryDaily,
    FundamentalQuarterly,
    IndexSummaryDaily,
    IntradayTrade,
    MarketBrokerSummaryDaily,
    MarketEvent,
    MarketNews,
    OHLCVDaily,
    OrderBookSnapshot,
    StockSummaryDaily,
)
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
    session.add(
        MarketBrokerSummaryDaily(
            trade_date=date(2026, 2, 28),
            broker_code="YP",
            broker_name="Test Broker",
            volume=500,
            value=Decimal("2000000"),
            frequency=12,
        )
    )
    session.add(
        StockSummaryDaily(
            symbol="BBCA",
            trade_date=date(2026, 2, 28),
            company_name="Test Bank",
            close=Decimal("7000"),
            value=Decimal("3000000"),
            frequency=20,
            foreign_buy_volume=100,
            foreign_sell_volume=40,
            listed_shares=1000000,
            tradeable_shares=900000,
        )
    )
    session.add(
        IndexSummaryDaily(
            benchmark="COMPOSITE",
            trade_date=date(2026, 2, 28),
            close=Decimal("7000"),
            value=Decimal("5000000"),
            frequency=100,
        )
    )
    session.commit()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app)

    analysis = client.get("/ui/api/analysis?symbols=BBCA&from=2026-02-20&to=2026-03-02")
    assert analysis.status_code == 200
    assert analysis.json()[-1]["ma50"] is not None

    ohlcv_with_ma = client.get("/ui/api/ohlcv?symbols=BBCA&from=2026-02-20&to=2026-03-02")
    assert ohlcv_with_ma.status_code == 200
    assert ohlcv_with_ma.json()[-1]["ma50"] is not None

    broker = client.get("/ui/api/broker-summary?symbol=BBCA")
    assert broker.status_code == 200
    assert broker.json()["top_buyers"][0]["broker_code"] == "YP"

    market_broker = client.get("/ui/api/market-broker-summary?days=1")
    assert market_broker.status_code == 200
    assert market_broker.json()["scope"] == "whole_market"
    assert market_broker.json()["top_by_value"][0]["broker_code"] == "YP"

    csv_response = client.get("/export/analysis.csv?symbols=BBCA&from=2026-02-20&to=2026-03-02")
    assert csv_response.status_code == 200
    assert "ma50" in csv_response.text
    assert "benchmark_status" in csv_response.text

    xlsx_response = client.get("/export/broker-summary.xlsx?symbol=BBCA")
    assert xlsx_response.status_code == 200
    with ZipFile(BytesIO(xlsx_response.content)) as workbook:
        assert "xl/worksheets/sheet2.xml" in workbook.namelist()
        assert b"Test Broker" in workbook.read("xl/worksheets/sheet2.xml")

    market_xlsx = client.get("/export/market-broker-summary.xlsx?days=1")
    assert market_xlsx.status_code == 200
    with ZipFile(BytesIO(market_xlsx.content)) as workbook:
        assert b"Market-wide" in workbook.read("xl/worksheets/sheet1.xml")

    stock_summary = client.get("/ui/api/stock-summary?symbols=BBCA")
    assert stock_summary.status_code == 200
    assert stock_summary.json()[0]["company_name"] == "Test Bank"
    assert stock_summary.json()[0]["market_cap"] == 7000000000.0
    assert stock_summary.json()[0]["free_float_percentage"] == 0.9
    assert client.get("/export/stock-summary.xlsx?symbols=BBCA").status_code == 200
    assert client.get("/export/index-summary.xlsx").status_code == 200

    backtest = client.get(
        "/ui/api/backtest?symbols=BBCA&from=2026-02-20&to=2026-02-24&horizon=1&score_threshold=0&probability_threshold=0"
    )
    assert backtest.status_code == 200
    payload = backtest.json()
    assert payload["signals"] == len(payload["rows"])
    if payload["rows"]:
        returns = [row["forward_return"] for row in payload["rows"]]
        assert payload["average_forward_return"] == pytest.approx(sum(returns) / len(returns))


def test_import_ohlcv_export_csv(session):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app)
    response = client.post(
        "/ui/api/import/ohlcv",
        json={
            "source": "idx-export.csv",
            "content": (
                "symbol,trade_date,currency,open,high,low,close,volume\n"
                "BBCA,2026-08-28,IDR,6425,6525,6400,6475,156445200\n"
            ),
        },
    )
    assert response.status_code == 200
    assert response.json()["rows_loaded"] == 1
    assert session.get(OHLCVDaily, {"symbol": "BBCA", "trade_date": date(2026, 8, 28)}) is not None


def test_symbol_feature_summary_and_excel_import(session):
    upsert_stocks(session, [{"symbol": "BBCA", "active": True}])
    session.add_all(
        [
            OrderBookSnapshot(symbol="BBCA", captured_at=datetime(2026, 8, 28, 9), level=1, bid_price=Decimal("6400"), bid_volume=100, offer_price=Decimal("6450"), offer_volume=80),
            IntradayTrade(symbol="BBCA", traded_at=datetime(2026, 8, 28, 9), sequence=1, price=Decimal("6425"), volume=100, buyer_broker="YP", seller_broker="CC"),
            FundamentalQuarterly(symbol="BBCA", fiscal_year=2026, fiscal_quarter=2, revenue=Decimal("1000"), net_income=Decimal("200")),
            MarketEvent(symbol="BBCA", event_date=date(2026, 8, 28), event_type="RUPS", title="Rapat"),
            MarketNews(symbol="BBCA", published_at=datetime(2026, 8, 28, 8), title="Headline", sentiment_score=Decimal("0.4")),
            AdjustedPrice(symbol="BBCA", trade_date=date(2026, 8, 28), adjustment_factor=Decimal("1"), adjusted_open=Decimal("6400"), adjusted_high=Decimal("6500"), adjusted_low=Decimal("6350"), adjusted_close=Decimal("6450"), adjusted_volume=1000),
        ]
    )
    session.commit()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app)
    summary = client.get("/ui/api/symbol-features?symbol=BBCA&date=2026-08-28")
    assert summary.status_code == 200
    assert summary.json()["order_book"]["levels"] == 1
    assert summary.json()["intraday"]["vwap"] == 6425
    assert summary.json()["fundamentals"]["latest_period"] == "2026-Q2"

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["symbol", "trade_date", "open", "high", "low", "close", "volume"])
    sheet.append(["BBCA", "2026-08-29", 6400, 6500, 6350, 6450, 1000])
    stream = BytesIO()
    workbook.save(stream)
    response = client.post(
        "/ui/api/import-upload/ohlcv",
        files={"upload": ("ohlcv.xlsx", stream.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200
    assert response.json()["rows_loaded"] == 1
