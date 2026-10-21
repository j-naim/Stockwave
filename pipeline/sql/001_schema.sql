-- Stockwave: tickers and daily prices.

-- tracked stocks and benchmarks.
CREATE TABLE IF NOT EXISTS tickers (
    symbol        text        PRIMARY KEY,
    name          text,
    sector        text        NOT NULL,
    is_benchmark  boolean     NOT NULL DEFAULT false,
    first_date    date,
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- daily stock prices and adjustments.
CREATE TABLE IF NOT EXISTS prices (
    symbol        text             NOT NULL REFERENCES tickers (symbol) ON DELETE CASCADE,
    trade_date    date             NOT NULL,
    open          numeric(14, 4),
    high          numeric(14, 4),
    low           numeric(14, 4),
    close         numeric(14, 4)   NOT NULL CHECK (close > 0),
    volume        bigint,
    adj_open      double precision,
    adj_high      double precision,
    adj_low       double precision,
    adj_close     double precision NOT NULL CHECK (adj_close > 0),
    adj_volume    double precision,
    div_cash      numeric(12, 6)   NOT NULL DEFAULT 0,
    split_factor  numeric(12, 6)   NOT NULL DEFAULT 1,
    source        text             NOT NULL DEFAULT 'tiingo',
    ingested_at   timestamptz      NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, trade_date)
);

-- speed up date-based queries.
CREATE INDEX IF NOT EXISTS prices_trade_date_idx ON prices (trade_date);

-- track data imports
CREATE TABLE IF NOT EXISTS ingest_runs (
    id             bigserial   PRIMARY KEY,
    symbol         text        NOT NULL,
    mode           text        NOT NULL CHECK (mode IN ('full', 'incremental')),
    started_at     timestamptz NOT NULL DEFAULT now(),
    finished_at    timestamptz,
    rows_upserted  integer,
    status         text        NOT NULL DEFAULT 'running'
                               CHECK (status IN ('running', 'ok', 'error')),
    error          text
);

-- calc. daily and trailing returns computed with window functions.

CREATE OR REPLACE VIEW returns_daily AS
SELECT
    symbol,
    trade_date,
    adj_close,
    ln(adj_close / lag(adj_close)     OVER w)     AS log_ret_1d,
    adj_close / lag(adj_close)     OVER w - 1     AS ret_1d,
    adj_close / lag(adj_close, 5)  OVER w - 1     AS ret_5d,
    adj_close / lag(adj_close, 10) OVER w - 1     AS ret_10d
FROM prices
WINDOW w AS (PARTITION BY symbol ORDER BY trade_date);
