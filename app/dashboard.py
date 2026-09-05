"""Read-only local monitoring dashboard for the signal engine."""

from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
import uvicorn

from app.config.settings import SUPPORTED_TIMEFRAMES, load_settings, normalize_symbol
from app.monitoring.runtime import RuntimeHealthSnapshotStore
from app.storage.database import Database
from app.storage.repositories import BacktestRepository
from app.backtest.report import HistoricalPerformanceReport


def _open_connection(database_path: Path) -> sqlite3.Connection:
    database = Database(database_path)
    database.open()
    connection = database.connection
    if connection is None:  # pragma: no cover - defensive guard
        raise RuntimeError("Database could not be opened")
    return connection


def _dashboard_html() -> str:
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Multi-Pair CSD Signal Engine</title>
<style>
:root { color-scheme: dark; --bg:#0b1020; --card:#141b31; --line:#283353; --text:#eef3ff; --muted:#9ca9c9; --good:#4ade80; --accent:#7dd3fc; }
* { box-sizing:border-box } body { margin:0; background:var(--bg); color:var(--text); font-family:system-ui,sans-serif; }
main { max-width:1100px; margin:auto; padding:32px 20px; } h1 { margin:0; font-size:clamp(1.6rem,4vw,2.4rem) } p { color:var(--muted) }
.grid { display:grid; gap:16px; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); margin:28px 0; }.card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:18px; }.label { color:var(--muted); font-size:.85rem }.value { font-size:1.15rem; margin-top:7px }.ok { color:var(--good) }
table { width:100%; border-collapse:collapse; font-size:.9rem } th,td { text-align:left; border-bottom:1px solid var(--line); padding:10px 6px; white-space:nowrap } th { color:var(--muted) }.scroll { overflow:auto }
</style></head><body><main>
<header><h1>Multi-Pair CSD Signal Engine</h1><p>Monitoring only — market analysis; no trading controls.</p></header>
<section class="grid" aria-label="Engine status"><article class="card"><div class="label">Database</div><div id="database" class="value">Loading…</div></article><article class="card"><div class="label">WebSocket</div><div id="websocket" class="value">Loading…</div></article><article class="card"><div class="label">Last market message</div><div id="last-message" class="value">Loading…</div></article><article class="card"><div class="label">Enabled symbols</div><div id="symbols" class="value">Loading…</div></article><article class="card"><div class="label">Latest signals</div><div id="signal-count" class="value">Loading…</div></article></section>
<section class="card"><h2>Timeframe health</h2><div class="scroll"><table><thead><tr><th>Symbol</th><th>Timeframe</th><th>Last closed candle</th></tr></thead><tbody id="timeframe-health"><tr><td colspan="3">Waiting for engine snapshot…</td></tr></tbody></table></div></section>
<section class="card"><h2>Latest 15-minute candles</h2><div class="scroll"><table><thead><tr><th>Symbol</th><th>Open time</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Closed</th></tr></thead><tbody id="candles"><tr><td colspan="7">Loading…</td></tr></tbody></table></div></section>
<section class="card"><h2>Signals and reference plans</h2><div class="scroll"><table><thead><tr><th>Symbol</th><th>Direction</th><th>Classification</th><th>Confidence</th><th>Entry</th><th>Stop loss</th><th>TP1</th><th>Created</th></tr></thead><tbody id="signals"><tr><td colspan="8">Loading…</td></tr></tbody></table></div></section>
<section class="card"><h2>Notification delivery</h2><div id="notifications" class="value">No persisted signal selected.</div></section>
<script>
const esc = value => String(value).replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
async function refresh() { const status = await fetch('/api/status').then(r=>r.json()); const runtime = status.runtime || {}; const symbol = status.enabled_symbols[0]; const [signals, candles] = await Promise.all([fetch('/api/signals?limit=20').then(r=>r.json()), symbol ? fetch(`/api/candles?symbol=${encodeURIComponent(symbol)}&timeframe=15m&limit=12`).then(r=>r.json()) : Promise.resolve({candles:[]})]); document.querySelector('#database').innerHTML=status.database_connected ? '<span class="ok">Connected</span>' : 'Unavailable'; document.querySelector('#websocket').innerHTML=runtime.websocket_connected ? '<span class="ok">Connected</span>' : 'Disconnected'; document.querySelector('#last-message').textContent=runtime.last_message_time || 'No runtime snapshot yet'; document.querySelector('#symbols').textContent=status.enabled_symbols.join(', ') || 'None'; document.querySelector('#signal-count').textContent=signals.signals.length; const healthRows=(runtime.last_closed_candles || []).map(c=>`<tr><td>${esc(c.symbol)}</td><td>${esc(c.timeframe)}</td><td>${esc(c.close_time)}</td></tr>`).join(''); document.querySelector('#timeframe-health').innerHTML=healthRows || '<tr><td colspan="3">No closed candles recorded yet.</td></tr>'; const signalRows=signals.signals.map(s=>`<tr><td>${esc(s.symbol)}</td><td>${esc(s.direction)}</td><td>${esc(s.classification)}</td><td>${esc(s.confidence)}/10</td><td>${esc(s.reference_entry)}</td><td>${esc(s.stop_loss)}</td><td>${esc(s.take_profit_1)}</td><td>${esc(s.created_at)}</td></tr>`).join(''); document.querySelector('#signals').innerHTML=signalRows || '<tr><td colspan="8">No signals recorded yet.</td></tr>'; const candleRows=candles.candles.map(c=>`<tr><td>${esc(c.symbol)}</td><td>${esc(c.open_time)}</td><td>${esc(c.open)}</td><td>${esc(c.high)}</td><td>${esc(c.low)}</td><td>${esc(c.close)}</td><td>${c.is_closed ? 'Yes' : 'No'}</td></tr>`).join(''); document.querySelector('#candles').innerHTML=candleRows || '<tr><td colspan="7">No stored candles yet.</td></tr>'; const latest=signals.signals[0]; const notifications=latest ? await fetch(`/api/notifications?signal_id=${encodeURIComponent(latest.signal_id)}`).then(r=>r.json()) : {notifications:[]}; document.querySelector('#notifications').textContent=latest ? (notifications.notifications.map(n=>`${n.provider}: ${n.success ? 'delivered' : 'failed'} (${n.attempts} attempt${n.attempts === 1 ? '' : 's'})${n.error ? ` — ${n.error}` : ''}`).join(' | ') || 'No delivery attempts recorded.') : 'No persisted signal selected.'; }
refresh(); setInterval(refresh, 15000);
</script></main></body></html>"""


def create_dashboard_app(
    database_path: str | Path, enabled_symbols: tuple[str, ...], health_snapshot_path: str | Path | None = None,
) -> FastAPI:
    """Create the read-only dashboard application over the engine SQLite data."""
    path = Path(database_path)
    symbols = tuple(normalize_symbol(symbol) for symbol in enabled_symbols)
    health_store = RuntimeHealthSnapshotStore(health_snapshot_path or path.with_suffix(".health.json"))
    app = FastAPI(title="Multi-Pair CSD Signal Engine Dashboard", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return _dashboard_html()

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        connection = _open_connection(path)
        try:
            connection.execute("SELECT 1").fetchone()
        finally:
            connection.close()
        return {"database_connected": True, "enabled_symbols": list(symbols), "runtime": health_store.read()}

    @app.get("/api/candles")
    def candles(symbol: str, timeframe: str, limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
        try:
            canonical_symbol = normalize_symbol(symbol)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if canonical_symbol not in symbols:
            raise HTTPException(status_code=404, detail="Symbol is not enabled")
        canonical_timeframe = timeframe.strip().lower()
        if canonical_timeframe not in SUPPORTED_TIMEFRAMES:
            raise HTTPException(status_code=422, detail="Unsupported timeframe")
        connection = _open_connection(path)
        try:
            rows = connection.execute(
                "SELECT symbol,timeframe,open_time,close_time,open,high,low,close,volume,is_closed "
                "FROM candles WHERE symbol=? AND timeframe=? ORDER BY open_time DESC LIMIT ?",
                (canonical_symbol, canonical_timeframe, limit),
            ).fetchall()
        finally:
            connection.close()
        rows.reverse()
        fields = ("symbol", "timeframe", "open_time", "close_time", "open", "high", "low", "close", "volume", "is_closed")
        return {"candles": [dict(zip(fields, (*row[:-1], bool(row[-1]),))) for row in rows]}

    @app.get("/api/signals")
    def signals(symbol: str | None = None, limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
        if symbol is not None:
            try:
                canonical_symbol = normalize_symbol(symbol)
            except ValueError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
            if canonical_symbol not in symbols:
                raise HTTPException(status_code=404, detail="Symbol is not enabled")
        else:
            canonical_symbol = None
        connection = _open_connection(path)
        try:
            if canonical_symbol is None:
                rows = connection.execute("SELECT signal_id,symbol,timeframe,direction,classification,confidence,entry_low,entry_high,reference_entry,stop_loss,take_profit_1,take_profit_2,take_profit_3,take_profit_4,created_at FROM signals ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            else:
                rows = connection.execute("SELECT signal_id,symbol,timeframe,direction,classification,confidence,entry_low,entry_high,reference_entry,stop_loss,take_profit_1,take_profit_2,take_profit_3,take_profit_4,created_at FROM signals WHERE symbol=? ORDER BY created_at DESC LIMIT ?", (canonical_symbol, limit)).fetchall()
        finally:
            connection.close()
        fields = ("signal_id", "symbol", "timeframe", "direction", "classification", "confidence", "entry_low", "entry_high", "reference_entry", "stop_loss", "take_profit_1", "take_profit_2", "take_profit_3", "take_profit_4", "created_at")
        return {"signals": [dict(zip(fields, row)) for row in rows]}

    @app.get("/api/notifications")
    def notifications(signal_id: str = Query(min_length=1)) -> dict[str, Any]:
        connection = _open_connection(path)
        try:
            rows = connection.execute(
                "SELECT provider,success,attempts,error FROM notifications WHERE signal_id=? ORDER BY id",
                (signal_id,),
            ).fetchall()
        finally:
            connection.close()
        fields = ("provider", "success", "attempts", "error")
        return {"notifications": [dict(zip(fields, (row[0], bool(row[1]), row[2], row[3]))) for row in rows]}

    @app.get("/api/backtests")
    def backtests() -> dict[str, Any]:
        connection = _open_connection(path)
        try:
            rows = connection.execute("SELECT run_id,symbol,timeframe,status,warnings,created_at FROM backtest_runs ORDER BY created_at DESC").fetchall()
        finally:
            connection.close()
        fields = ("run_id", "symbol", "timeframe", "status", "warnings", "created_at")
        return {"backtests": [dict(zip(fields, (row[0], row[1], row[2], row[3], __import__('json').loads(row[4]), row[5]))) for row in rows]}

    @app.get("/api/backtests/{run_id}")
    def backtest_detail(run_id: str) -> dict[str, Any]:
        database = Database(path); database.open()
        try:
            repository = BacktestRepository(database)
            if repository.get_run(run_id) is None:
                raise HTTPException(status_code=404, detail="Backtest not found")
            report = HistoricalPerformanceReport(repository).run(run_id)
            trades = repository.list_trades(run_id)
            report["trades"] = [{"trade_id": trade.trade_id, "signal_time": trade.signal_time.isoformat(),
                                 "direction": trade.direction, "entry_price": str(trade.entry_price) if trade.entry_price is not None else None,
                                 "stop_loss": str(trade.stop_loss) if trade.stop_loss is not None else None,
                                 "take_profit_1": str(trade.take_profit_1) if trade.take_profit_1 is not None else None,
                                 "take_profit_2": str(trade.take_profit_2) if trade.take_profit_2 is not None else None,
                                 "take_profit_3": str(trade.take_profit_3) if trade.take_profit_3 is not None else None,
                                 "score_total": str(trade.score_total), "score_classification": trade.score_classification,
                                 "exit_time": trade.exit_time.isoformat() if trade.exit_time else None,
                                 "exit_reason": trade.exit_reason, "gross_r": str(trade.gross_r) if trade.gross_r is not None else None,
                                 "costs_r": str(trade.costs_r) if trade.costs_r is not None else None,
                                 "net_r": str(trade.net_r) if trade.net_r is not None else None,
                                 "resolution_method": trade.resolution_method, "ambiguous_intrabar": trade.ambiguous_intrabar,
                                 "bars_in_trade": trade.bars_in_trade, "mfe_r": str(trade.mfe_r) if trade.mfe_r is not None else None,
                                 "mae_r": str(trade.mae_r) if trade.mae_r is not None else None,
                                 "symbol": trade.symbol, "regime": trade.regime, "session": trade.session} for trade in trades]
            return report
        finally:
            database.close()

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Multi-Pair CSD Signal Engine dashboard")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()
    settings = load_settings(args.config)
    uvicorn.run(create_dashboard_app(settings.database_path, settings.enabled_symbols), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
