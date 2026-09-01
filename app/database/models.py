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
