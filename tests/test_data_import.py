from app.data_import import parse_dataset


def test_parse_broker_summary_computes_net_value():
    rows, warnings = parse_dataset(
        "broker-summary",
        "trade_date,symbol,broker_code,broker_name,buy_volume,sell_volume,buy_value,sell_value\n"
        "2026-08-28,BBCA,YP,Test Broker,100,40,1000000,400000\n",
    )

    assert not warnings
    assert len(rows) == 1
    assert rows[0]["symbol"] == "BBCA"
    assert rows[0]["net_value"] == 600000


def test_parse_benchmark_requires_close():
    try:
        parse_dataset("benchmark", "trade_date,benchmark\n2026-08-28,IHSG\n")
    except ValueError as exc:
        assert "missing close" in str(exc)
    else:
        raise AssertionError("expected missing close validation")
