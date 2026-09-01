import csv
from datetime import date
from decimal import Decimal
from io import BytesIO, StringIO
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.database.connection import get_db
from app.database.queries import upsert_ohlcv, upsert_stocks


def test_required_api_endpoints(session):
    upsert_stocks(
        session,
        [{"symbol": "BBCA", "company_name": "Bank Central Asia Tbk", "active": True}],
    )
    upsert_ohlcv(
        session,
        [
            {
                "symbol": "BBCA",
                "trade_date": date(2026, 8, 28),
                "open": Decimal("8000"),
                "high": Decimal("8200"),
                "low": Decimal("7900"),
                "close": Decimal("8100"),
                "volume": 100,
                "source": "test",
            }
        ],
    )
    session.commit()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app)

    assert client.get("/health").status_code == 200
    assert client.get("/symbols").json()[0]["symbol"] == "BBCA"
    assert client.get("/ohlcv/BBCA?from=2026-08-01").json()[0]["volume"] == 100
    assert client.get("/latest").json()[0]["trade_date"] == "2026-08-28"
    assert client.get("/etl-runs").status_code == 200
    assert client.get("/docs").status_code == 200


def test_ohlcv_rejects_inverted_range(session):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    response = TestClient(app).get("/ohlcv/BBCA?from=2026-08-30&to=2026-08-01")
    assert response.status_code == 422


def test_excel_export_downloads_valid_workbook(session):
    upsert_stocks(
        session,
        [{"symbol": "BBCA", "company_name": "Bank Central Asia Tbk", "active": True}],
    )
    upsert_ohlcv(
        session,
        [
            {
                "symbol": "BBCA",
                "trade_date": date(2026, 8, 28),
                "open": Decimal("6425"),
                "high": Decimal("6525"),
                "low": Decimal("6400"),
                "close": Decimal("6475"),
                "volume": 156445200,
                "source": "test",
            }
        ],
    )
    session.commit()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app)

    response = client.get(
        "/export/ohlcv.xlsx?symbols=BBCA&from=2026-08-24&to=2026-08-28"
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "idx_ohlcv_BBCA_2026-08-24_2026-08-28.xlsx" in response.headers[
        "content-disposition"
    ]
    with ZipFile(BytesIO(response.content)) as workbook:
        assert "xl/worksheets/sheet1.xml" in workbook.namelist()
        assert "xl/worksheets/sheet2.xml" in workbook.namelist()
        assert b"BBCA" in workbook.read("xl/worksheets/sheet2.xml")
        assert b"156445200" in workbook.read("xl/worksheets/sheet2.xml")
        assert b"Change vs Open" in workbook.read("xl/worksheets/sheet2.xml")
        assert b"[$Rp-421]" in workbook.read("xl/styles.xml")


def test_excel_export_page_and_validation(session):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app)

    assert client.get("/export").status_code == 200
    inverted = client.get("/export/ohlcv.xlsx?from=2026-08-30&to=2026-08-01")
    assert inverted.status_code == 422
    assert client.get("/export/ohlcv.xlsx?symbols=INVALID_SYMBOL_TOO_LONG").status_code == 422
    assert client.get("/export/ohlcv.xlsx?symbols=BBCA").status_code == 404


def test_csv_export_opens_in_excel_and_preserves_values(session):
    upsert_stocks(session, [{"symbol": "BBCA", "active": True}])
    upsert_ohlcv(
        session,
        [
            {
                "symbol": "BBCA",
                "trade_date": date(2026, 8, 28),
                "open": Decimal("6425"),
                "high": Decimal("6525"),
                "low": Decimal("6400"),
                "close": Decimal("6475"),
                "volume": 156445200,
                "source": "test",
            }
        ],
    )
    session.commit()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session

    response = TestClient(app).get(
        "/export/ohlcv.csv?symbols=BBCA&from=2026-08-24&to=2026-08-28"
    )

    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert "idx_ohlcv_BBCA_2026-08-24_2026-08-28.csv" in response.headers[
        "content-disposition"
    ]
    rows = list(csv.DictReader(StringIO(response.content.decode("utf-8-sig"))))
    assert rows[0]["symbol"] == "BBCA"
    assert rows[0]["trade_date"] == "2026-08-28"
    assert rows[0]["currency"] == "IDR"
    assert rows[0]["volume"] == "156445200"
