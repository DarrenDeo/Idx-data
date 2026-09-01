from datetime import date

import pytest

from app.downloader.provider import IDXProvider


class FakeClient:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    async def get_json(self, endpoint, params=None):
        self.calls.append((endpoint, params))
        return self.payloads.pop(0)


def test_parse_provider_ohlcv_response():
    parsed = IDXProvider.parse_ohlcv_item(
        {
            "StockCode": "BBCA",
            "Date": "2026-08-28T00:00:00",
            "OpenPrice": 8000,
            "High": 8200,
            "Low": 7900,
            "Close": 8100,
            "Volume": 12345,
        }
    )
    assert parsed.symbol == "BBCA"
    assert parsed.trade_date == date(2026, 8, 28)
    assert parsed.volume == 12345


@pytest.mark.asyncio
async def test_symbol_response_parsing():
    provider = IDXProvider(
        client=FakeClient(
            [
                {
                    "data": [
                        {
                            "KodeEmiten": "BBCA",
                            "NamaEmiten": "Bank Central Asia Tbk",
                            "TanggalPencatatan": "2000-05-31T00:00:00",
                        }
                    ]
                }
            ]
        )
    )
    records = await provider.get_symbols()
    assert records[0].symbol == "BBCA"
    assert records[0].listing_date == date(2000, 5, 31)


@pytest.mark.asyncio
async def test_historical_response_is_range_filtered():
    client = FakeClient(
        [
            {
                "replies": [
                    {
                        "StockCode": "BBCA",
                        "Date": "2026-08-27T00:00:00",
                        "OpenPrice": 1,
                        "High": 2,
                        "Low": 1,
                        "Close": 2,
                        "Volume": 3,
                    },
                    {
                        "StockCode": "BBCA",
                        "Date": "2026-08-28T00:00:00",
                        "OpenPrice": 2,
                        "High": 3,
                        "Low": 2,
                        "Close": 3,
                        "Volume": 4,
                    },
                ]
            }
        ]
    )
    provider = IDXProvider(client=client)
    rows = await provider.get_ohlcv("BBCA", date(2026, 8, 28), date(2026, 8, 28))
    assert [row.trade_date for row in rows] == [date(2026, 8, 28)]
    assert client.calls[0][0] == "/ListedCompany/GetTradingInfoSS"

