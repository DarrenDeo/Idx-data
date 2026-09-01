import csv
from datetime import date
from decimal import Decimal
from io import BytesIO, StringIO
from zipfile import ZipFile

from fastapi.testclient import TestClient

import app.api.main as api_main
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


def test_dashboard_displays_overview_and_filtered_data(session):
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
    client = TestClient(app)

    page = client.get("/")
    assert page.status_code == 200
    assert "Market Data Dashboard" in page.text
    assert "Sinkronkan simbol" in page.text
    assert "Jalankan backfill" in page.text

    overview = client.get("/ui/api/overview").json()
    assert overview["total_rows"] == 1
    assert overview["total_symbols"] == 1
    assert overview["latest_date"] == "2026-08-28"

    rows = client.get(
        "/ui/api/ohlcv?symbols=BBCA&from=2026-08-24&to=2026-08-28"
    ).json()
    assert rows[0]["symbol"] == "BBCA"
    assert rows[0]["close"] == "6475.00"


def test_dashboard_builds_only_validated_cli_jobs(session, monkeypatch):
    captured = []

    def fake_start(name, command):
        captured.append((name, command))
        return {"id": "test", "name": name, "command": " ".join(command), "status": "RUNNING"}

    monkeypatch.setattr(api_main.job_manager, "start", fake_start)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app)

    daily = client.post("/ui/api/jobs/daily", json={"end": "2026-08-31"})
    assert daily.status_code == 202
    assert captured[-1][1] == ["idx-platform", "daily", "--end", "2026-08-31"]

    invalid = client.post(
        "/ui/api/jobs/backfill",
        json={"symbols": "BBCA", "start": "2026-08-31", "end": "2026-08-01"},
    )
    assert invalid.status_code == 422

    valid = client.post(
        "/ui/api/jobs/backfill",
        json={
            "symbols": "bbca, BBRI",
            "start": "2026-08-24",
            "end": "2026-08-28",
        },
    )
    assert valid.status_code == 202
    assert captured[-1][1] == [
        "idx-platform",
        "backfill",
        "--symbols",
        "BBCA",
        "BBRI",
        "--start",
        "2026-08-24",
        "--end",
        "2026-08-28",
    ]
