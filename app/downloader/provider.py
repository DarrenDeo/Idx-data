from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.config import Settings, settings
from app.downloader.api_client import AsyncIDXClient


@dataclass(slots=True)
class SymbolRecord:
    symbol: str
    company_name: str | None = None
    sector: str | None = None
    sub_sector: str | None = None
    listing_date: date | None = None
    active: bool = True


@dataclass(slots=True)
class OHLCVRecord:
    symbol: str
    trade_date: date
    open: Decimal | int | float | str
    high: Decimal | int | float | str
    low: Decimal | int | float | str
    close: Decimal | int | float | str
    volume: int | str
    source: str = "idx_public"
    raw: dict[str, Any] | None = None


@dataclass(slots=True)
class MarketBrokerSummaryRecord:
    """One broker's total market activity for a trading session.

    IDX's public broker-summary endpoint is market-wide.  It reports total
    volume, value, and frequency for each broker; it does not identify a
    buyer/seller side or a particular stock.
    """

    trade_date: date
    broker_code: str
    broker_name: str | None
    volume: int | str
    value: Decimal | int | float | str
    frequency: int | str
    source: str = "idx_public"
    raw: dict[str, Any] | None = None


@dataclass(slots=True)
class IndexSummaryRecord:
    benchmark: str
    trade_date: date
    previous: Decimal | int | float | str | None
    highest: Decimal | int | float | str | None
    lowest: Decimal | int | float | str | None
    close: Decimal | int | float | str
    change: Decimal | int | float | str | None
    number_of_stock: int | str | None
    volume: int | str | None
    value: Decimal | int | float | str | None
    frequency: int | str | None
    source: str = "idx_public"
    raw: dict[str, Any] | None = None


@dataclass(slots=True)
class CorporateActionRecord:
    symbol: str
    ex_date: date
    action_type: str
    ratio: Decimal | None = None
    source_id: str = ""
    raw: dict[str, Any] | None = None


class MarketDataProvider(abc.ABC):
    supports_daily_bulk_backfill = False

    @abc.abstractmethod
    async def get_symbols(self) -> list[SymbolRecord]: ...

    @abc.abstractmethod
    async def get_ohlcv(self, symbol: str, start_date: date, end_date: date) -> list[OHLCVRecord]: ...

    @abc.abstractmethod
    async def get_daily_market_data(self, trade_date: date) -> list[OHLCVRecord]: ...

    async def get_market_broker_summary(
        self, trade_date: date
    ) -> list[MarketBrokerSummaryRecord]:
        """Return the public, market-wide broker summary for one session."""
        raise NotImplementedError

    async def get_index_summary(self, trade_date: date) -> list[IndexSummaryRecord]:
        """Return IDX index summary rows for one session when supported."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_corporate_actions(
        self, symbol: str, start_date: date, end_date: date
    ) -> list[CorporateActionRecord]: ...


def _parse_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if "T" in text:
        text = text.split("T", 1)[0]
    return datetime.strptime(text[:10], "%Y-%m-%d").date()


def _ratio_from_payload(item: dict[str, Any]) -> Decimal | None:
    for key in ("Ratio", "Rasio", "ratio"):
        value = item.get(key)
        if value not in (None, ""):
            try:
                ratio = Decimal(str(value))
                return ratio if ratio > 0 else None
            except InvalidOperation:
                return None
    return None


class IDXProvider(MarketDataProvider):
    """Public IDX provider based on current `/primary` endpoint behavior.

    IDX may block particular hosts. Callers can swap this implementation without
    changing persistence or pipeline code.
    """

    supports_daily_bulk_backfill = True

    def __init__(self, client: AsyncIDXClient | None = None, config: Settings = settings) -> None:
        self.client = client or AsyncIDXClient(
            base_url=config.idx_base_url,
            concurrency=config.idx_concurrency,
            timeout=config.idx_request_timeout,
            total_timeout=config.idx_total_timeout,
            max_retries=config.idx_max_retries,
            request_delay=config.idx_request_delay,
        )

    async def close(self) -> None:
        await self.client.close()

    async def get_symbols(self) -> list[SymbolRecord]:
        payload = await self.client.get_json(
            "/ListedCompany/GetCompanyProfiles", params={"start": 0, "length": 9999}
        )
        data = payload.get("data", []) if isinstance(payload, dict) else []
        return [
            SymbolRecord(
                symbol=str(item["KodeEmiten"]).strip().upper(),
                company_name=item.get("NamaEmiten"),
                listing_date=_parse_date(item["TanggalPencatatan"])
                if item.get("TanggalPencatatan")
                else None,
            )
            for item in data
            if item.get("KodeEmiten")
        ]

    @staticmethod
    def parse_ohlcv_item(item: dict[str, Any]) -> OHLCVRecord:
        symbol = item.get("StockCode") or item.get("KodeEmiten") or item.get("code")
        trade_date = item.get("Date") or item.get("Tanggal") or item.get("date")
        if not symbol or not trade_date:
            raise ValueError("provider row lacks symbol or date")
        return OHLCVRecord(
            symbol=str(symbol).strip().upper(),
            trade_date=_parse_date(trade_date),
            open=item.get("OpenPrice", item.get("open")),
            high=item.get("High", item.get("high")),
            low=item.get("Low", item.get("low")),
            close=item.get("Close", item.get("close")),
            volume=item.get("Volume", item.get("volume")),
            raw=item,
        )

    async def get_ohlcv(self, symbol: str, start_date: date, end_date: date) -> list[OHLCVRecord]:
        symbol = symbol.upper()
        start = 0
        page_size = 1000
        records: list[OHLCVRecord] = []
        while True:
            payload = await self.client.get_json(
                "/ListedCompany/GetTradingInfoSS",
                params={"code": symbol, "start": start, "length": page_size},
            )
            raw_rows = payload.get("replies", []) if isinstance(payload, dict) else []
            for item in raw_rows:
                record = self.parse_ohlcv_item(item)
                if start_date <= record.trade_date <= end_date:
                    records.append(record)
            if len(raw_rows) < page_size:
                break
            start += page_size
        return sorted(records, key=lambda row: row.trade_date)

    async def get_daily_market_data(self, trade_date: date) -> list[OHLCVRecord]:
        payload = await self.client.get_json(
            "/TradingSummary/GetStockSummary",
            params={"date": trade_date.strftime("%Y%m%d"), "start": 0, "length": 9999},
        )
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        return [self.parse_ohlcv_item(item) for item in rows]

    @staticmethod
    def parse_index_summary_item(item: dict[str, Any], trade_date: date) -> IndexSummaryRecord:
        benchmark = (
            item.get("IndexCode") or item.get("IndexName") or item.get("KodeIndeks")
            or item.get("code") or item.get("index")
        )
        if not benchmark:
            raise ValueError("index summary row lacks index code")
        row_date = item.get("Date") or item.get("Tanggal") or item.get("date")
        parsed_date = _parse_date(row_date) if row_date else trade_date
        return IndexSummaryRecord(
            benchmark=str(benchmark).strip().upper(),
            trade_date=parsed_date,
            previous=item.get("Previous", item.get("previous")),
            highest=item.get("Highest", item.get("High", item.get("highest"))),
            lowest=item.get("Lowest", item.get("Low", item.get("lowest"))),
            close=item.get("Close", item.get("close")),
            change=item.get("Change", item.get("change")),
            number_of_stock=item.get("NumberOfStock", item.get("NumberOfStocks")),
            volume=item.get("Volume", item.get("volume")),
            value=item.get("Value", item.get("value")),
            frequency=item.get("Frequency", item.get("frequency")),
            raw=item,
        )

    async def get_index_summary(self, trade_date: date) -> list[IndexSummaryRecord]:
        payload = await self.client.get_json(
            "/TradingSummary/GetIndexSummary",
            params={"date": trade_date.strftime("%Y%m%d"), "start": 0, "length": 9999},
        )
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        records: list[IndexSummaryRecord] = []
        for item in rows:
            try:
                records.append(self.parse_index_summary_item(item, trade_date))
            except ValueError:
                continue
        return records

    @staticmethod
    def parse_market_broker_item(
        item: dict[str, Any],
        trade_date: date,
    ) -> MarketBrokerSummaryRecord:
        broker_code = (
            item.get("IDFirm")
            or item.get("BrokerCode")
            or item.get("KodeBroker")
            or item.get("FirmCode")
        )
        if not broker_code:
            raise ValueError("broker summary row lacks broker code")
        row_date = item.get("Date") or item.get("Tanggal") or item.get("date")
        parsed_date = _parse_date(row_date) if row_date else trade_date
        raw_volume = item.get("Volume", item.get("volume", 0)) or 0
        raw_value = item.get("Value", item.get("value", 0)) or 0
        raw_frequency = item.get("Frequency", item.get("frequency", 0)) or 0
        try:
            volume = int(float(raw_volume))
        except (TypeError, ValueError):
            volume = 0
        try:
            value = Decimal(str(raw_value))
        except (InvalidOperation, TypeError, ValueError):
            value = Decimal(0)
        try:
            frequency = int(float(raw_frequency))
        except (TypeError, ValueError):
            frequency = 0
        return MarketBrokerSummaryRecord(
            trade_date=parsed_date,
            broker_code=str(broker_code).strip().upper(),
            broker_name=(
                item.get("FirmName")
                or item.get("BrokerName")
                or item.get("NamaBroker")
            ),
            volume=volume,
            value=value,
            frequency=frequency,
            raw=item,
        )

    async def get_market_broker_summary(
        self, trade_date: date
    ) -> list[MarketBrokerSummaryRecord]:
        payload = await self.client.get_json(
            "/TradingSummary/GetBrokerSummary",
            params={"date": trade_date.strftime("%Y%m%d"), "start": 0, "length": 9999},
        )
        rows = []
        if isinstance(payload, dict):
            rows = payload.get("data") or payload.get("replies") or []
        result = [self.parse_market_broker_item(item, trade_date) for item in rows]
        return sorted(result, key=lambda row: row.value, reverse=True)

    async def get_corporate_actions(
        self, symbol: str, start_date: date, end_date: date
    ) -> list[CorporateActionRecord]:
        payload = await self.client.get_json(
            "/ListingActivity/GetIssuedHistory",
            params={"kodeEmiten": symbol.upper(), "start": 0, "length": 9999},
        )
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        result: list[CorporateActionRecord] = []
        for item in rows:
            date_value = item.get("TanggalPencatatan") or item.get("Date")
            if not date_value:
                continue
            action_date = _parse_date(date_value)
            if start_date <= action_date <= end_date:
                result.append(
                    CorporateActionRecord(
                        symbol=str(item.get("KodeEmiten") or symbol).upper(),
                        ex_date=action_date,
                        action_type=str(item.get("JenisTindakan") or item.get("caType") or "UNKNOWN"),
                        ratio=_ratio_from_payload(item),
                        source_id=str(item.get("id") or item.get("ID") or ""),
                        raw=item,
                    )
                )
        return result
