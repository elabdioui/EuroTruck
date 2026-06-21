CREATE TABLE IF NOT EXISTS signal_lifecycle (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    setup           TEXT    NOT NULL,
    direction       TEXT    NOT NULL,
    pattern         TEXT    NOT NULL,
    killzone        TEXT,
    killzone_match  INTEGER NOT NULL,

    entry           REAL    NOT NULL,
    entry_fill      REAL    NOT NULL,
    spread_pips     REAL    NOT NULL DEFAULT 0,
    sl              REAL    NOT NULL,
    tp1             REAL    NOT NULL,
    tp_final        REAL    NOT NULL,
    risk_pips       REAL    NOT NULL,
    planned_rr      REAL    NOT NULL,

    status          TEXT    NOT NULL,
    mfe_pips        REAL    NOT NULL DEFAULT 0,
    mae_pips        REAL    NOT NULL DEFAULT 0,
    realized_r      REAL,
    realized_r_net  REAL,

    opened_at       TEXT    NOT NULL,
    partial_at      TEXT,
    closed_at       TEXT,
    last_tick_at    TEXT    NOT NULL,

    extra_json      TEXT
);

CREATE INDEX IF NOT EXISTS idx_lifecycle_status   ON signal_lifecycle(status);
CREATE INDEX IF NOT EXISTS idx_lifecycle_setup    ON signal_lifecycle(setup);
CREATE INDEX IF NOT EXISTS idx_lifecycle_opened   ON signal_lifecycle(opened_at);
