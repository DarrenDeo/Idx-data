from datetime import date
from decimal import Decimal

import pytest

from app.downloader.provider import OHLCVRecord
from app.validation.ohlcv import OHLCVValidationError, is_no_trade, validate_batch, validate_ohlcv


def row(**overrides):
    values = {
        "symbol": "BBCA",
        "trade_date": date(2026, 8, 28),
        "open": 8000,
        "high": 8200,
        "low": 7900,
        "close": 8100,
        "volume": 100,
    }
    values.update(overrides)
    return OHLCVRecord(**values)


def test_valid_row_is_normalized():
    result = validate_ohlcv(row(symbol="bbca"))
    assert result.symbol == "BBCA"
    assert result.open == Decimal("8000")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"high": 7999}, "high < open"),
        ({"high": 8099}, "high < close"),
        ({"low": 8001}, "low > open"),
        ({"low": 8101}, "low > close"),
        ({"volume": -1}, "volume < 0"),
        ({"open": "not-a-number"}, "open is not numeric"),
    ],
)
def test_invalid_rules_are_rejected(overrides, message):
    with pytest.raises(OHLCVValidationError, match=message):
        validate_ohlcv(row(**overrides))


def test_batch_separates_error_payloads():
    valid, errors = validate_batch([row(), row(volume=-1)])
    assert len(valid) == 1
    assert errors[0]["symbol"] == "BBCA"


def test_zero_volume_row_is_classified_as_no_trade():
    assert is_no_trade(row(volume=0)) is True
    assert is_no_trade(row(volume="0")) is True
    assert is_no_trade(row(volume=1)) is False
    assert is_no_trade(row(volume="invalid")) is False
