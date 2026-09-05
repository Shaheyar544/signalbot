from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.events.models import Candle
from app.signals.models import SignalRecord
from app.notifications.base import DeliveryResult
from app.storage.database import Database
from app.backtests import BacktestRun, TradeAudit, BacktestStatus
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.strategy.csd_strategy import SetupAssessment
    from app.strategy.risk import RiskAnalysis


class CandleRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert(self, candle: Candle) -> None:
        connection = self.database.connection
        if connection is None:
            raise RuntimeError("Database is not open")
        connection.execute(
            """INSERT INTO candles (symbol,timeframe,open_time,close_time,open,high,low,close,volume,is_closed)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol,timeframe,open_time) DO UPDATE SET
              close_time=excluded.close_time, open=excluded.open, high=excluded.high,
              low=excluded.low, close=excluded.close, volume=excluded.volume, is_closed=excluded.is_closed""",
            (candle.symbol, candle.timeframe, candle.open_time.isoformat(), candle.close_time.isoformat(),
             str(candle.open), str(candle.high), str(candle.low), str(candle.close), str(candle.volume), int(candle.is_closed)),
        )
        connection.commit()


class SignalRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def save(self, assessment: SetupAssessment, risk: RiskAnalysis) -> bool:
        connection = self.database.connection
        if connection is None:
            raise RuntimeError("Database is not open")
        record = SignalRecord.from_analysis(assessment, risk)
        cursor = connection.execute(
            """INSERT INTO signals (signal_id,symbol,timeframe,direction,classification,confidence,entry_low,entry_high,reference_entry,stop_loss,take_profit_1,take_profit_2,take_profit_3,take_profit_4,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(signal_id) DO NOTHING""",
            (record.signal_id, record.symbol, record.timeframe, record.direction, record.classification,
             str(record.confidence), str(record.entry_low), str(record.entry_high), str(record.reference_entry),
             str(record.stop_loss), str(record.take_profit_1), str(record.take_profit_2), str(record.take_profit_3),
             str(record.take_profit_4) if record.take_profit_4 is not None else None, record.created_at.isoformat()),
        )
        connection.commit()
        return cursor.rowcount == 1

    def get(self, signal_id: str) -> SignalRecord | None:
        connection = self.database.connection
        if connection is None:
            raise RuntimeError("Database is not open")
        row = connection.execute("SELECT signal_id,symbol,timeframe,direction,classification,confidence,entry_low,entry_high,reference_entry,stop_loss,take_profit_1,take_profit_2,take_profit_3,take_profit_4,created_at FROM signals WHERE signal_id=?", (signal_id,)).fetchone()
        if row is None:
            return None
        from app.strategy.scoring import SignalClassification
        from app.structure.csd import CSDDirection
        return SignalRecord(row[0], row[1], row[2], CSDDirection(row[3]), SignalClassification(row[4]), Decimal(row[5]),
                            *(Decimal(value) for value in row[6:13]), Decimal(row[13]) if row[13] is not None else None,
                            datetime.fromisoformat(row[14]))


class NotificationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def save_attempt(self, signal_id: str, result: DeliveryResult) -> None:
        connection = self.database.connection
        if connection is None:
            raise RuntimeError("Database is not open")
        connection.execute("INSERT INTO notifications (signal_id,provider,success,attempts,error) VALUES (?,?,?,?,?)",
                           (signal_id, result.provider, int(result.success), result.attempts, result.error))
        connection.commit()

    def get_for_signal(self, signal_id: str) -> list[DeliveryResult]:
        connection = self.database.connection
        if connection is None:
            raise RuntimeError("Database is not open")
        rows = connection.execute("SELECT provider,success,error,attempts FROM notifications WHERE signal_id=? ORDER BY id", (signal_id,)).fetchall()
        return [DeliveryResult(row[0], bool(row[1]), row[2], row[3]) for row in rows]

class BacktestRepository:
    def __init__(self, database: Database) -> None: self.database = database
    def save_run(self, run: BacktestRun) -> None:
        connection = self.database.connection
        if connection is None: raise RuntimeError("Database is not open")
        connection.execute("INSERT INTO backtest_runs VALUES (?,?,?,?,?,?)", (run.run_id, run.symbol, run.timeframe, run.status, json.dumps(run.warnings), run.created_at.isoformat())); connection.commit()
    def save_trade(self, trade: TradeAudit) -> None:
        connection = self.database.connection
        if connection is None: raise RuntimeError("Database is not open")
        values = (trade.trade_id, trade.run_id, trade.signal_time.isoformat(), trade.direction, *(str(x) if x is not None else None for x in (trade.entry_price, trade.stop_loss, trade.take_profit_1, trade.take_profit_2, trade.take_profit_3)), str(trade.score_total), str(trade.score_classification), trade.exit_time.isoformat() if trade.exit_time else None, trade.exit_reason, *(str(x) if x is not None else None for x in (trade.gross_r, trade.costs_r, trade.net_r)), trade.resolution_method, int(trade.ambiguous_intrabar))
        connection.execute("""INSERT INTO backtest_trades
            (trade_id,run_id,signal_time,direction,entry_price,stop_loss,take_profit_1,take_profit_2,take_profit_3,
             score_total,score_classification,exit_time,exit_reason,gross_r,costs_r,net_r,resolution_method,ambiguous_intrabar)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", values)
        connection.commit()
