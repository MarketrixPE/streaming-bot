-- Schema inicial de eventos para ClickHouse.
-- Ejecutar manualmente tras primer arranque:
--   docker exec -it clickhouse clickhouse-client -u app --password $CLICKHOUSE_PASSWORD --multiquery < init.sql

CREATE DATABASE IF NOT EXISTS events;

-- Stream events: cada intento de stream emite un row.
CREATE TABLE IF NOT EXISTS events.stream_events
(
    occurred_at      DateTime64(3, 'UTC'),
    account_id       String,
    track_uri        String,
    artist_uri       String,
    playlist_id      String,
    session_id       String,
    proxy_country    LowCardinality(String),
    proxy_ip_hash    String,
    fingerprint_id   String,
    duration_seconds UInt16,
    outcome          LowCardinality(String),  -- counted | partial | skipped | failed
    is_target        UInt8,
    error_message    String DEFAULT '',
    tier             LowCardinality(String),  -- tier_1 | tier_2 | tier_3
    dsp              LowCardinality(String)   -- spotify | soundcloud | deezer | apple | amazon | meta
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(occurred_at)
ORDER BY (dsp, tier, account_id, occurred_at)
TTL occurred_at + INTERVAL 18 MONTH;

-- Behavior events (likes, saves, follows, scrolls, etc.).
CREATE TABLE IF NOT EXISTS events.behavior_events
(
    occurred_at  DateTime64(3, 'UTC'),
    session_id   String,
    account_id   String,
    behavior     LowCardinality(String),
    target_uri   String,
    metadata_json String DEFAULT '',
    dsp          LowCardinality(String)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(occurred_at)
ORDER BY (dsp, account_id, session_id, occurred_at)
TTL occurred_at + INTERVAL 12 MONTH;

-- Account health snapshots (job que corre cada N min para rollups).
CREATE TABLE IF NOT EXISTS events.account_health_snapshots
(
    snapshot_at      DateTime64(3, 'UTC'),
    account_id       String,
    dsp              LowCardinality(String),
    country          LowCardinality(String),
    state            LowCardinality(String),  -- active | quarantined | banned | warming
    streams_24h      UInt32,
    save_rate        Float32,
    skip_rate        Float32,
    queue_rate       Float32,
    anomaly_score    Float32
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(snapshot_at)
ORDER BY (dsp, account_id, snapshot_at)
TTL snapshot_at + INTERVAL 6 MONTH;

-- Royalty observed (cuando llega report de distribuidor / DSP, hacemos
-- cross-check vs streams generados para detectar stripping).
CREATE TABLE IF NOT EXISTS events.royalty_observations
(
    observed_at      DateTime64(3, 'UTC'),
    period_start     Date,
    period_end       Date,
    track_uri        String,
    distributor      LowCardinality(String),
    dsp              LowCardinality(String),
    country          LowCardinality(String),
    streams_reported UInt64,
    revenue_cents    Float64
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(observed_at)
ORDER BY (dsp, distributor, track_uri, period_start);

-- Vista materializada: rollup horario para dashboards rapidos.
CREATE MATERIALIZED VIEW IF NOT EXISTS events.stream_events_hourly
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(hour)
ORDER BY (dsp, tier, country, hour)
AS
SELECT
    toStartOfHour(occurred_at) AS hour,
    dsp,
    tier,
    proxy_country AS country,
    countIf(outcome = 'counted')   AS counted,
    countIf(outcome = 'partial')   AS partial,
    countIf(outcome = 'skipped')   AS skipped,
    countIf(outcome = 'failed')    AS failed,
    sum(duration_seconds)          AS total_seconds
FROM events.stream_events
GROUP BY hour, dsp, tier, country;
