from app.data_import import parse_dataset


def test_parse_all_optional_feature_datasets():
    rows, errors = parse_dataset(
        "stock-summary",
        "symbol,trade_date,company_name,close,value,frequency,foreign_buy_volume,foreign_sell_volume\n"
        "BBCA,2026-08-31,Bank,6500,1000000,10,20,5\n",
    )
    assert not errors and rows[0]["foreign_buy_volume"] == 20

    rows, _ = parse_dataset(
        "index-summary",
        "benchmark,trade_date,close,value,frequency\nCOMPOSITE,2026-08-31,7000,10,2\n",
    )
    assert rows[0]["benchmark"] == "COMPOSITE"

    rows, _ = parse_dataset(
        "order-book",
        "symbol,captured_at,level,bid_price,bid_volume,offer_price,offer_volume\nBBCA,2026-08-31T09:00:00,1,6400,100,6450,80\n",
    )
    assert rows[0]["level"] == 1

    rows, _ = parse_dataset(
        "fundamentals",
        "symbol,fiscal_year,fiscal_quarter,revenue,net_income\nBBCA,2026,2,1000,200\n",
    )
    assert rows[0]["fiscal_quarter"] == 2

    rows, _ = parse_dataset(
        "events",
        "symbol,event_date,event_type,title\nBBCA,2026-08-31,RUPS,Rapat\n",
    )
    assert rows[0]["event_type"] == "RUPS"

    rows, _ = parse_dataset(
        "news",
        "symbol,published_at,title\nBBCA,2026-08-31T09:00:00,Headline\n",
    )
    assert rows[0]["title"] == "Headline"
