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

-- Yearly range partitioning is deliberately deferred until the fact table grows
-- toward the specification's ~50M-row threshold. Retrofitting it earlier would
-- add operational complexity without improving the expected ~4.5M-row workload.
