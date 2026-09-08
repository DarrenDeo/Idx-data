CREATE TABLE IF NOT EXISTS stocks (
    symbol VARCHAR(16) PRIMARY KEY,
    company_name TEXT,
    sector TEXT,
    sub_sector TEXT,
    listing_date DATE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ohlcv_daily (
    symbol VARCHAR(16) NOT NULL REFERENCES stocks(symbol) ON DELETE CASCADE,
    trade_date DATE NOT NULL,
    open NUMERIC(18,2) NOT NULL,
    high NUMERIC(18,2) NOT NULL,
    low NUMERIC(18,2) NOT NULL,
    close NUMERIC(18,2) NOT NULL,
    volume BIGINT NOT NULL,
    source VARCHAR(50) NOT NULL DEFAULT 'idx_public',
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_symbol_date
ON ohlcv_daily (symbol, trade_date DESC);

CREATE TABLE IF NOT EXISTS stock_summary_daily (
    symbol VARCHAR(16) NOT NULL REFERENCES stocks(symbol) ON DELETE CASCADE,
    trade_date DATE NOT NULL,
    company_name TEXT,
    previous NUMERIC(18,4),
    open_price NUMERIC(18,4),
    first_trade NUMERIC(18,4),
    high NUMERIC(18,4),
    low NUMERIC(18,4),
    close NUMERIC(18,4),
    change NUMERIC(18,4),
    volume BIGINT,
    value NUMERIC(24,4),
    frequency BIGINT,
    foreign_buy_volume BIGINT,
    foreign_sell_volume BIGINT,
    non_regular_volume BIGINT,
    non_regular_value NUMERIC(24,4),
    non_regular_frequency BIGINT,
    listed_shares BIGINT,
    tradeable_shares BIGINT,
    weight_for_index NUMERIC(24,8),
    index_individual NUMERIC(18,8),
    source VARCHAR(50) NOT NULL DEFAULT 'idx_public',
    raw_payload JSONB,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_stock_summary_symbol_date
ON stock_summary_daily (symbol, trade_date DESC);

CREATE TABLE IF NOT EXISTS benchmark_daily (
    benchmark VARCHAR(32) NOT NULL,
    trade_date DATE NOT NULL,
    open NUMERIC(18,4),
    high NUMERIC(18,4),
    low NUMERIC(18,4),
    close NUMERIC(18,4) NOT NULL,
    volume BIGINT,
    source VARCHAR(50) NOT NULL DEFAULT 'import',
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (benchmark, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_benchmark_date
ON benchmark_daily (benchmark, trade_date DESC);

CREATE TABLE IF NOT EXISTS index_summary_daily (
    benchmark VARCHAR(32) NOT NULL,
    trade_date DATE NOT NULL,
    previous NUMERIC(18,4),
    highest NUMERIC(18,4),
    lowest NUMERIC(18,4),
    close NUMERIC(18,4) NOT NULL,
    change NUMERIC(18,4),
    number_of_stock INTEGER,
    volume BIGINT,
    value NUMERIC(24,4),
    frequency BIGINT,
    source VARCHAR(50) NOT NULL DEFAULT 'idx_public',
    raw_payload JSONB,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (benchmark, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_index_summary_date
ON index_summary_daily (benchmark, trade_date DESC);

CREATE TABLE IF NOT EXISTS foreign_flow_daily (
    symbol VARCHAR(16) NOT NULL,
    trade_date DATE NOT NULL,
    foreign_buy_volume BIGINT,
    foreign_sell_volume BIGINT,
    foreign_buy_value NUMERIC(24,4),
    foreign_sell_value NUMERIC(24,4),
    foreign_net_value NUMERIC(24,4),
    foreign_average_buy NUMERIC(18,4),
    foreign_average_sell NUMERIC(18,4),
    source VARCHAR(50) NOT NULL DEFAULT 'import',
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_foreign_flow_date
ON foreign_flow_daily (symbol, trade_date DESC);

CREATE TABLE IF NOT EXISTS broker_summary_daily (
    symbol VARCHAR(16) NOT NULL,
    trade_date DATE NOT NULL,
    broker_code VARCHAR(16) NOT NULL,
    broker_name TEXT,
    buy_volume BIGINT,
    sell_volume BIGINT,
    buy_value NUMERIC(24,4),
    sell_value NUMERIC(24,4),
    buy_average NUMERIC(18,4),
    sell_average NUMERIC(18,4),
    net_volume BIGINT,
    net_value NUMERIC(24,4),
    buy_frequency BIGINT,
    sell_frequency BIGINT,
    source VARCHAR(50) NOT NULL DEFAULT 'import',
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, trade_date, broker_code)
);

CREATE INDEX IF NOT EXISTS idx_broker_summary_symbol_date
ON broker_summary_daily (symbol, trade_date DESC);

CREATE TABLE IF NOT EXISTS market_broker_summary_daily (
    trade_date DATE NOT NULL,
    broker_code VARCHAR(16) NOT NULL,
    broker_name TEXT,
    volume BIGINT,
    value NUMERIC(24,4),
    frequency BIGINT,
    source VARCHAR(50) NOT NULL DEFAULT 'idx_public',
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (trade_date, broker_code)
);

CREATE INDEX IF NOT EXISTS idx_market_broker_summary_date
ON market_broker_summary_daily (trade_date DESC);

CREATE TABLE IF NOT EXISTS corporate_actions (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(16) NOT NULL REFERENCES stocks(symbol) ON DELETE CASCADE,
    ex_date DATE NOT NULL,
    action_type VARCHAR(50) NOT NULL,
    ratio NUMERIC(24,10),
    source_id VARCHAR(100) NOT NULL DEFAULT '',
    raw_payload JSONB,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_corporate_action UNIQUE (symbol, ex_date, action_type, source_id)
);

CREATE TABLE IF NOT EXISTS data_errors (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(16),
    trade_date DATE,
    error_message TEXT NOT NULL,
    raw_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS etl_runs (
    id BIGSERIAL PRIMARY KEY,
    job_name VARCHAR(100) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL DEFAULT 'RUNNING',
    rows_loaded BIGINT NOT NULL DEFAULT 0,
    rows_rejected BIGINT NOT NULL DEFAULT 0,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS adjusted_prices (
    symbol VARCHAR(16) NOT NULL,
    trade_date DATE NOT NULL,
    adjustment_factor NUMERIC(24,10) NOT NULL,
    adjusted_open NUMERIC(18,4) NOT NULL,
    adjusted_high NUMERIC(18,4) NOT NULL,
    adjusted_low NUMERIC(18,4) NOT NULL,
    adjusted_close NUMERIC(18,4) NOT NULL,
    adjusted_volume BIGINT NOT NULL,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, trade_date)
);

CREATE TABLE IF NOT EXISTS order_book_snapshots (
    symbol VARCHAR(16) NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    level INTEGER NOT NULL,
    bid_price NUMERIC(18,4),
    bid_volume BIGINT,
    offer_price NUMERIC(18,4),
    offer_volume BIGINT,
    indicative_price NUMERIC(18,4),
    source VARCHAR(50) NOT NULL DEFAULT 'import',
    raw_payload JSONB,
    PRIMARY KEY (symbol, captured_at, level)
);

CREATE INDEX IF NOT EXISTS idx_order_book_symbol_time
ON order_book_snapshots (symbol, captured_at DESC);

CREATE TABLE IF NOT EXISTS intraday_trades (
    symbol VARCHAR(16) NOT NULL,
    traded_at TIMESTAMPTZ NOT NULL,
    sequence INTEGER NOT NULL DEFAULT 0,
    price NUMERIC(18,4) NOT NULL,
    volume BIGINT NOT NULL,
    buyer_broker VARCHAR(16),
    seller_broker VARCHAR(16),
    source VARCHAR(50) NOT NULL DEFAULT 'import',
    raw_payload JSONB,
    PRIMARY KEY (symbol, traded_at, sequence)
);

CREATE INDEX IF NOT EXISTS idx_intraday_symbol_time
ON intraday_trades (symbol, traded_at DESC);

CREATE TABLE IF NOT EXISTS fundamentals_quarterly (
    symbol VARCHAR(16) NOT NULL,
    fiscal_year INTEGER NOT NULL,
    fiscal_quarter INTEGER NOT NULL,
    report_date DATE,
    revenue NUMERIC(28,4),
    ebitda NUMERIC(28,4),
    net_income NUMERIC(28,4),
    operating_cash_flow NUMERIC(28,4),
    capex NUMERIC(28,4),
    cash NUMERIC(28,4),
    debt NUMERIC(28,4),
    shares_outstanding BIGINT,
    segment_revenue JSONB,
    major_ownership JSONB,
    source VARCHAR(50) NOT NULL DEFAULT 'import',
    raw_payload JSONB,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, fiscal_year, fiscal_quarter)
);

CREATE TABLE IF NOT EXISTS market_events (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(16),
    event_date DATE NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    title TEXT,
    status VARCHAR(30),
    source_id VARCHAR(100) NOT NULL DEFAULT '',
    source VARCHAR(50) NOT NULL DEFAULT 'import',
    raw_payload JSONB,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_market_events_symbol_date
ON market_events (symbol, event_date DESC);

CREATE TABLE IF NOT EXISTS market_news (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(16),
    published_at TIMESTAMPTZ NOT NULL,
    title TEXT NOT NULL,
    publisher TEXT,
    url TEXT,
    sentiment_score NUMERIC(8,5),
    sentiment_label VARCHAR(20),
    source VARCHAR(50) NOT NULL DEFAULT 'import',
    raw_payload JSONB
);

-- Yearly range partitioning is deliberately deferred until the fact table grows
-- toward the specification's ~50M-row threshold. Retrofitting it earlier would
-- add operational complexity without improving the expected ~4.5M-row workload.
