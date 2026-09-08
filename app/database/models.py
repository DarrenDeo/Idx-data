from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


pk_type = BigInteger().with_variant(Integer, "sqlite")


class Stock(Base):
    __tablename__ = "stocks"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    company_name: Mapped[str | None] = mapped_column(Text)
    sector: Mapped[str | None] = mapped_column(Text)
    sub_sector: Mapped[str | None] = mapped_column(Text)
    listing_date: Mapped[date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class OHLCVDaily(Base):
    __tablename__ = "ohlcv_daily"

    symbol: Mapped[str] = mapped_column(
        String(16), ForeignKey("stocks.symbol", ondelete="CASCADE"), primary_key=True
    )
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="idx_public")
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


Index("idx_symbol_date", OHLCVDaily.symbol, OHLCVDaily.trade_date.desc())


class StockSummaryDaily(Base):
    """The complete daily stock-summary payload published by IDX.

    ``ohlcv_daily`` remains the validated candle fact table.  This companion
    table keeps the other fields IDX publishes (value, frequency, foreign
    volume, listed shares, and the raw response) so analytics do not have to
    reconstruct them from a lossy OHLCV export.
    """

    __tablename__ = "stock_summary_daily"

    symbol: Mapped[str] = mapped_column(
        String(16), ForeignKey("stocks.symbol", ondelete="CASCADE"), primary_key=True
    )
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    company_name: Mapped[str | None] = mapped_column(Text)
    previous: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    open_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    first_trade: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    high: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    low: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    close: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    change: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    value: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    frequency: Mapped[int | None] = mapped_column(BigInteger)
    foreign_buy_volume: Mapped[int | None] = mapped_column(BigInteger)
    foreign_sell_volume: Mapped[int | None] = mapped_column(BigInteger)
    non_regular_volume: Mapped[int | None] = mapped_column(BigInteger)
    non_regular_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    non_regular_frequency: Mapped[int | None] = mapped_column(BigInteger)
    listed_shares: Mapped[int | None] = mapped_column(BigInteger)
    tradeable_shares: Mapped[int | None] = mapped_column(BigInteger)
    weight_for_index: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    index_individual: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="idx_public")
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


Index("idx_stock_summary_symbol_date", StockSummaryDaily.symbol, StockSummaryDaily.trade_date.desc())


class BenchmarkDaily(Base):
    """Daily close data for IHSG or another benchmark/index."""

    __tablename__ = "benchmark_daily"

    benchmark: Mapped[str] = mapped_column(String(32), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    high: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    low: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    close: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    volume: Mapped[int | None] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="import")
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


Index("idx_benchmark_date", BenchmarkDaily.benchmark, BenchmarkDaily.trade_date.desc())


class IndexSummaryDaily(Base):
    """Raw daily index summary from IDX (IHSG, sector indexes, LQ45, etc.)."""

    __tablename__ = "index_summary_daily"

    benchmark: Mapped[str] = mapped_column(String(32), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    previous: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    highest: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    lowest: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    close: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    change: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    number_of_stock: Mapped[int | None] = mapped_column(Integer)
    volume: Mapped[int | None] = mapped_column(BigInteger)
    value: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    frequency: Mapped[int | None] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="idx_public")
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


Index("idx_index_summary_date", IndexSummaryDaily.benchmark, IndexSummaryDaily.trade_date.desc())


class ForeignFlowDaily(Base):
    """Optional daily foreign investor flow imported from a licensed source."""

    __tablename__ = "foreign_flow_daily"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    foreign_buy_volume: Mapped[int | None] = mapped_column(BigInteger)
    foreign_sell_volume: Mapped[int | None] = mapped_column(BigInteger)
    foreign_buy_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    foreign_sell_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    foreign_net_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    foreign_average_buy: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    foreign_average_sell: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="import")
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


Index("idx_foreign_flow_date", ForeignFlowDaily.symbol, ForeignFlowDaily.trade_date.desc())


class BrokerSummaryDaily(Base):
    """Per-symbol broker activity imported from an approved broker-data source."""

    __tablename__ = "broker_summary_daily"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    broker_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    broker_name: Mapped[str | None] = mapped_column(Text)
    buy_volume: Mapped[int | None] = mapped_column(BigInteger)
    sell_volume: Mapped[int | None] = mapped_column(BigInteger)
    buy_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    sell_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    buy_average: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    sell_average: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    net_volume: Mapped[int | None] = mapped_column(BigInteger)
    net_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    buy_frequency: Mapped[int | None] = mapped_column(BigInteger)
    sell_frequency: Mapped[int | None] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="import")
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


Index(
    "idx_broker_summary_symbol_date",
    BrokerSummaryDaily.symbol,
    BrokerSummaryDaily.trade_date.desc(),
)


class MarketBrokerSummaryDaily(Base):
    """Public IDX broker totals for the whole market, per trading session."""

    __tablename__ = "market_broker_summary_daily"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    broker_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    broker_name: Mapped[str | None] = mapped_column(Text)
    volume: Mapped[int | None] = mapped_column(BigInteger)
    value: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    frequency: Mapped[int | None] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="idx_public")
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


Index(
    "idx_market_broker_summary_date",
    MarketBrokerSummaryDaily.trade_date.desc(),
)


class CorporateAction(Base):
    __tablename__ = "corporate_actions"
    __table_args__ = (
        UniqueConstraint("symbol", "ex_date", "action_type", "source_id", name="uq_corporate_action"),
    )

    id: Mapped[int] = mapped_column(pk_type, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(
        String(16), ForeignKey("stocks.symbol", ondelete="CASCADE"), nullable=False
    )
    ex_date: Mapped[date] = mapped_column(Date, nullable=False)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    ratio: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    source_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DataError(Base):
    __tablename__ = "data_errors"

    id: Mapped[int] = mapped_column(pk_type, primary_key=True, autoincrement=True)
    symbol: Mapped[str | None] = mapped_column(String(16))
    trade_date: Mapped[date | None] = mapped_column(Date)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ETLRun(Base):
    __tablename__ = "etl_runs"

    id: Mapped[int] = mapped_column(pk_type, primary_key=True, autoincrement=True)
    job_name: Mapped[str] = mapped_column(String(100), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="RUNNING")
    rows_loaded: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    rows_rejected: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)


class AdjustedPrice(Base):
    __tablename__ = "adjusted_prices"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    adjustment_factor: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    adjusted_open: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    adjusted_high: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    adjusted_low: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    adjusted_close: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    adjusted_volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OrderBookSnapshot(Base):
    """Optional level-2 snapshots imported from a licensed/live feed."""

    __tablename__ = "order_book_snapshots"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    level: Mapped[int] = mapped_column(Integer, primary_key=True)
    bid_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    bid_volume: Mapped[int | None] = mapped_column(BigInteger)
    offer_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    offer_volume: Mapped[int | None] = mapped_column(BigInteger)
    indicative_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="import")
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)


Index("idx_order_book_symbol_time", OrderBookSnapshot.symbol, OrderBookSnapshot.captured_at.desc())


class IntradayTrade(Base):
    """Optional tick/trade-by-trade data; not exposed by the public OHLCV feed."""

    __tablename__ = "intraday_trades"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    traded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, default=0)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    buyer_broker: Mapped[str | None] = mapped_column(String(16))
    seller_broker: Mapped[str | None] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="import")
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)


Index("idx_intraday_symbol_time", IntradayTrade.symbol, IntradayTrade.traded_at.desc())


class FundamentalQuarterly(Base):
    """Quarterly fundamentals imported from an issuer or licensed provider."""

    __tablename__ = "fundamentals_quarterly"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    fiscal_quarter: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_date: Mapped[date | None] = mapped_column(Date)
    revenue: Mapped[Decimal | None] = mapped_column(Numeric(28, 4))
    ebitda: Mapped[Decimal | None] = mapped_column(Numeric(28, 4))
    net_income: Mapped[Decimal | None] = mapped_column(Numeric(28, 4))
    operating_cash_flow: Mapped[Decimal | None] = mapped_column(Numeric(28, 4))
    capex: Mapped[Decimal | None] = mapped_column(Numeric(28, 4))
    cash: Mapped[Decimal | None] = mapped_column(Numeric(28, 4))
    debt: Mapped[Decimal | None] = mapped_column(Numeric(28, 4))
    shares_outstanding: Mapped[int | None] = mapped_column(BigInteger)
    segment_revenue: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    major_ownership: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="import")
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MarketEvent(Base):
    """Corporate/event calendar used to flag event-driven returns."""

    __tablename__ = "market_events"

    id: Mapped[int] = mapped_column(pk_type, primary_key=True, autoincrement=True)
    symbol: Mapped[str | None] = mapped_column(String(16))
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(30))
    source_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="import")
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


Index("idx_market_events_symbol_date", MarketEvent.symbol, MarketEvent.event_date.desc())


class MarketNews(Base):
    """Optional news/sentiment records; no sentiment is invented when absent."""

    __tablename__ = "market_news"

    id: Mapped[int] = mapped_column(pk_type, primary_key=True, autoincrement=True)
    symbol: Mapped[str | None] = mapped_column(String(16))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    publisher: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    sentiment_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    sentiment_label: Mapped[str | None] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="import")
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
