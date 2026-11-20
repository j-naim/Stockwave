-- Model output. Each nightly run replaces the previous run's forecasts and
-- scores. model_runs keeps the history of every run.

CREATE TABLE IF NOT EXISTS model_runs (
    id            bigserial   PRIMARY KEY,
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    data_through  date,
    n_origins     integer,
    n_forecasts   integer,
    status        text        NOT NULL DEFAULT 'running'
                              CHECK (status IN ('running', 'ok', 'error')),
    error         text
);

-- Returns are cumulative log returns over `horizon` trading days.
-- actual is null for forward forecasts (is_backtest = false).
CREATE TABLE IF NOT EXISTS forecasts (
    run_id        bigint           NOT NULL REFERENCES model_runs (id) ON DELETE CASCADE,
    symbol        text             NOT NULL REFERENCES tickers (symbol) ON DELETE CASCADE,
    model         text             NOT NULL,
    origin_date   date             NOT NULL,
    horizon       smallint         NOT NULL CHECK (horizon > 0),
    target_date   date             NOT NULL,
    is_backtest   boolean          NOT NULL,
    origin_price  double precision NOT NULL,
    mean          double precision NOT NULL,
    sd            double precision NOT NULL,
    q025          double precision NOT NULL,
    q10           double precision NOT NULL,
    q25           double precision NOT NULL,
    q50           double precision NOT NULL,
    q75           double precision NOT NULL,
    q90           double precision NOT NULL,
    q975          double precision NOT NULL,
    actual        double precision,
    PRIMARY KEY (run_id, symbol, model, origin_date, horizon)
);

CREATE INDEX IF NOT EXISTS forecasts_lookup_idx
    ON forecasts (symbol, model, horizon, origin_date);

-- symbol = 'ALL' holds the scores pooled across tickers.
CREATE TABLE IF NOT EXISTS forecast_scores (
    run_id        bigint           NOT NULL REFERENCES model_runs (id) ON DELETE CASCADE,
    symbol        text             NOT NULL,
    model         text             NOT NULL,
    horizon       smallint         NOT NULL,
    n             integer          NOT NULL,
    mae_bps       double precision,
    mase          double precision,
    hit_rate      double precision,
    base_rate     double precision,
    cov50         double precision,
    cov80         double precision,
    cov95         double precision,
    pinball_bps   double precision,
    PRIMARY KEY (run_id, symbol, model, horizon)
);

CREATE TABLE IF NOT EXISTS vol_scores (
    run_id        bigint           NOT NULL REFERENCES model_runs (id) ON DELETE CASCADE,
    symbol        text             NOT NULL,
    model         text             NOT NULL,
    n             integer          NOT NULL,
    qlike         double precision,
    qlike_vs_rw   double precision,
    PRIMARY KEY (run_id, symbol, model)
);

-- Diebold-Mariano tests against the random walk, pooled across tickers.
CREATE TABLE IF NOT EXISTS dm_tests (
    run_id         bigint           NOT NULL REFERENCES model_runs (id) ON DELETE CASCADE,
    model          text             NOT NULL,
    horizon        smallint         NOT NULL,
    loss           text             NOT NULL,
    n_dates        integer          NOT NULL,
    mean_diff_bps  double precision,
    dm_stat        double precision,
    p_value        double precision,
    PRIMARY KEY (run_id, model, horizon, loss)
);

CREATE OR REPLACE VIEW latest_run AS
SELECT * FROM model_runs
WHERE status = 'ok'
ORDER BY finished_at DESC
LIMIT 1;

-- Forward forecasts from the latest close, with bands converted to prices.
CREATE OR REPLACE VIEW forward_forecasts AS
SELECT
    f.symbol, f.model, f.origin_date, f.target_date, f.horizon, f.origin_price,
    f.origin_price * exp(f.q025) AS px_q025,
    f.origin_price * exp(f.q10)  AS px_q10,
    f.origin_price * exp(f.q25)  AS px_q25,
    f.origin_price * exp(f.q50)  AS px_q50,
    f.origin_price * exp(f.q75)  AS px_q75,
    f.origin_price * exp(f.q90)  AS px_q90,
    f.origin_price * exp(f.q975) AS px_q975
FROM forecasts f
JOIN latest_run r ON r.id = f.run_id
WHERE NOT f.is_backtest
  AND f.origin_date = r.data_through;
