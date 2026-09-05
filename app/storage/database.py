from __future__ import annotations

import sqlite3
from pathlib import Path


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.connection: sqlite3.Connection | None = None

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS candles (
                id INTEGER PRIMARY KEY,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                open_time TEXT NOT NULL,
                close_time TEXT NOT NULL,
                open TEXT NOT NULL,
                high TEXT NOT NULL,
                low TEXT NOT NULL,
                close TEXT NOT NULL,
                volume TEXT NOT NULL,
                is_closed INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, timeframe, open_time)
            )"""
        )
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_candles_lookup ON candles(symbol, timeframe, open_time)")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY,
                signal_id TEXT NOT NULL UNIQUE,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                direction TEXT NOT NULL,
                classification TEXT NOT NULL,
                confidence INTEGER NOT NULL,
                entry_low TEXT NOT NULL,
                entry_high TEXT NOT NULL,
                reference_entry TEXT NOT NULL,
                stop_loss TEXT NOT NULL,
                take_profit_1 TEXT NOT NULL,
                take_profit_2 TEXT NOT NULL,
                take_profit_3 TEXT NOT NULL,
                take_profit_4 TEXT,
                created_at TEXT NOT NULL
            )"""
        )
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_signals_lookup ON signals(symbol, timeframe, created_at)")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY,
                signal_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                success INTEGER NOT NULL,
                attempts INTEGER NOT NULL,
                error TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_notifications_signal ON notifications(signal_id, created_at)")
        self.connection.execute("CREATE TABLE IF NOT EXISTS backtest_runs (run_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, timeframe TEXT NOT NULL, status TEXT NOT NULL, warnings TEXT NOT NULL, created_at TEXT NOT NULL)")
        self.connection.execute("CREATE TABLE IF NOT EXISTS backtest_trades (trade_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, signal_time TEXT NOT NULL, direction TEXT NOT NULL, entry_price TEXT, stop_loss TEXT, take_profit_1 TEXT, take_profit_2 TEXT, take_profit_3 TEXT, setup_valid INTEGER NOT NULL, confluence_score INTEGER NOT NULL, exit_time TEXT, exit_reason TEXT, gross_r TEXT, costs_r TEXT, net_r TEXT, resolution_method TEXT, ambiguous_intrabar INTEGER NOT NULL, FOREIGN KEY(run_id) REFERENCES backtest_runs(run_id))")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_backtest_trades_run ON backtest_trades(run_id, signal_time)")
        self.connection.commit()

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None
