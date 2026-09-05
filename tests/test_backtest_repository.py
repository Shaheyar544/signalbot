from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from app.backtests import BacktestRun, BacktestStatus, TradeAudit
from app.storage.database import Database
from app.storage.repositories import BacktestRepository

def test_persists_incomplete_run_and_full_trade_audit():
    database=Database(Path(":memory:")); database.open(); repo=BacktestRepository(database)
    run=BacktestRun("run-1","ETHUSDT","15m",BacktestStatus.INCOMPLETE_EXIT_MODEL,("missing exit model",),datetime.now(timezone.utc)); repo.save_run(run)
    repo.save_trade(TradeAudit("trade-1","run-1",run.created_at,"BULLISH",Decimal("100"),Decimal("95"),Decimal("105"),Decimal("110"),Decimal("115"),Decimal("7.5"),"STRONG_SIGNAL",None,None,None,None,None,"SAME_CANDLE",True))
    assert database.connection.execute("SELECT status,warnings FROM backtest_runs").fetchone()[0] == "INCOMPLETE_EXIT_MODEL"
    assert database.connection.execute("SELECT resolution_method,ambiguous_intrabar FROM backtest_trades").fetchone() == ("SAME_CANDLE", 1)
