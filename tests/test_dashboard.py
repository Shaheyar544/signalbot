from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app.dashboard import create_dashboard_app
from app.config.settings import CSDSettings, SwingSettings, load_settings
from app.events.models import Candle
from app.monitoring.health import HealthStatus
from app.monitoring.runtime import RuntimeHealthSnapshotStore
from app.storage.database import Database
from app.storage.repositories import CandleRepository


def _closed_candle(symbol: str = "ETHUSDT") -> Candle:
    opened = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return Candle(symbol, "15m", opened, opened.replace(minute=14, second=59),
                  Decimal("100"), Decimal("102"), Decimal("99"), Decimal("101"), Decimal("10"), True)


def test_dashboard_home_page_is_available(tmp_path: Path):
    app = create_dashboard_app(tmp_path / "engine.db", ("ETHUSDT",))

    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert "Multi-Pair CSD Signal Engine" in response.text
    assert "Monitoring only" in response.text
    assert "WebSocket" in response.text
    assert "Notification delivery" in response.text
    assert "Refresh interval: 1 minute" in response.text
    assert "setInterval(load,60000)" in response.text
    assert "Analyze latest closed candle" in response.text
    assert 'api("/api/analysis/check", {method:"POST"' in response.text


def test_signal_detail_empty_state_explains_that_no_signal_has_been_persisted(tmp_path: Path):
    response = TestClient(create_dashboard_app(tmp_path / "engine.db", ("ETHUSDT",))).get("/")

    assert response.status_code == 200
    assert "No persisted signals yet" in response.text
    assert "only displays signals actually persisted by the signal engine" in response.text
    assert "Requested signal is unavailable" in response.text
    assert "Stale data" in response.text


def test_signal_detail_api_returns_not_found_for_an_invalid_signal_id(tmp_path: Path):
    client = TestClient(create_dashboard_app(tmp_path / "engine.db", ("ETHUSDT",)))

    response = client.get("/api/signals/not-a-persisted-signal")

    assert response.status_code == 404
    assert response.json()["detail"] == "Signal not found"


def test_signal_detail_uses_latest_persisted_signal_or_explicit_query_selection(tmp_path: Path):
    response = TestClient(create_dashboard_app(tmp_path / "engine.db", ("ETHUSDT",))).get("/")

    assert "state.selectedSignal||state.signals[0]" in response.text
    assert "URLSearchParams(location.search).get('signal_id')" in response.text
    assert "Loading persisted signal" in response.text
    assert "Signal data unavailable" in response.text


def test_dashboard_includes_read_only_lightweight_chart_controls(tmp_path: Path):
    response = TestClient(create_dashboard_app(tmp_path / "engine.db", ("ETHUSDT",))).get("/")

    assert "lightweight-charts@5.2.1" in response.text
    assert "CandlestickSeries" in response.text
    assert "HistogramSeries" in response.text
    assert "TradingView" in response.text
    assert "chartSymbolIsEnabled" in response.text
    assert "is not enabled by the backend" in response.text
    for symbol in ("ETHUSDT", "BTCUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"):
        assert symbol in response.text
    for timeframe in ("15m", "1h", "4h"):
        assert timeframe in response.text


def test_status_endpoint_reports_database_and_enabled_symbols(tmp_path: Path):
    app = create_dashboard_app(tmp_path / "engine.db", ("ETHUSDT", "BTCUSDT"))

    response = TestClient(app).get("/api/status")

    assert response.status_code == 200
    assert response.json()["database_connected"] is True
    assert response.json()["enabled_symbols"] == ["ETHUSDT", "BTCUSDT"]


def test_manual_analysis_endpoint_reports_no_closed_candles_without_persisting_a_signal(tmp_path: Path):
    database_path = tmp_path / "engine.db"
    client = TestClient(create_dashboard_app(
        database_path,
        ("ETHUSDT",),
        strategy_settings=load_settings("tests/fixtures/settings.yaml"),
    ))

    response = client.post("/api/analysis/check", json={"symbol": "ETHUSDT"})

    assert response.status_code == 200
    assert response.json() == {
        "symbol": "ETHUSDT", "timeframe": "15m", "status": "NO_CLOSED_CANDLES",
        "read_only": True, "analyzed_candle_time": None, "classification": None,
        "confidence": None, "direction": None, "evidence": None, "reference_plan": None,
    }
    assert client.get("/api/signals").json() == {"signals": []}


def test_manual_analysis_reuses_strategy_for_a_retest_watch_without_persisting(tmp_path: Path, make_candle):
    prices = ((1, 1), (3, 1), (1, 1), (2, 1), (1, 1), (3, 3))
    candles = [replace(make_candle(offset=index), open=Decimal("1"), high=Decimal(str(high)),
                       low=Decimal("1"), close=Decimal(str(close)))
               for index, (high, close) in enumerate(prices)]
    candles.append(replace(make_candle(offset=6, close="2.1"), open=Decimal("2"), high=Decimal("3"), low=Decimal("1.9")))
    database_path = tmp_path / "engine.db"
    database = Database(database_path); database.open()
    CandleRepository(database).upsert_many(candles)
    database.close()
    settings = replace(load_settings("tests/fixtures/settings.yaml"), swing=SwingSettings(1, 1), csd=CSDSettings(Decimal("0.5")))
    client = TestClient(create_dashboard_app(database_path, ("ETHUSDT",), strategy_settings=settings))

    response = client.post("/api/analysis/check", json={"symbol": "ETHUSDT"})

    assert response.status_code == 200
    assert response.json()["status"] == "WATCH"
    assert response.json()["classification"] == "WATCH"
    assert response.json()["direction"] == "BULLISH"
    assert response.json()["evidence"]["retest"]["status"] == "RETEST_DETECTED"
    assert response.json()["reference_plan"] is None
    assert client.get("/api/signals").json() == {"signals": []}


def test_status_endpoint_includes_the_engine_runtime_snapshot(tmp_path: Path):
    database_path = tmp_path / "engine.db"
    snapshot_path = tmp_path / "runtime-health.json"
    health = HealthStatus(running=True, websocket_connected=True, database_connected=True, enabled_symbols=1)
    health.record_closed_candle(_closed_candle())
    RuntimeHealthSnapshotStore(snapshot_path).write(health)
    app = create_dashboard_app(database_path, ("ETHUSDT",), snapshot_path)

    response = TestClient(app).get("/api/status")

    assert response.status_code == 200
    assert response.json()["runtime"] == {
        "running": True, "websocket_connected": True, "database_connected": True, "enabled_symbol_count": 1,
        "last_message_time": None,
        "first_message_time": None,
        "active_subscriptions": [],
        "subscription_acknowledged": False,
        "messages_by_stream": [],
        "reconnect_attempts": 0,
        "last_reconnect_error": None,
        "last_closed_candles": [{"symbol": "ETHUSDT", "timeframe": "15m", "close_time": "2026-01-01T00:14:59+00:00"}],
    }


def test_candles_endpoint_returns_filtered_serialized_candles(tmp_path: Path):
    database_path = tmp_path / "engine.db"
    database = Database(database_path); database.open()
    CandleRepository(database).upsert(_closed_candle())
    database.close()
    app = create_dashboard_app(database_path, ("ETHUSDT",))

    response = TestClient(app).get("/api/candles?symbol=ETHUSDT&timeframe=15m&limit=10")

    assert response.status_code == 200
    assert response.json()["candles"] == [{
        "symbol": "ETHUSDT", "timeframe": "15m", "open_time": "2026-01-01T00:00:00+00:00",
        "close_time": "2026-01-01T00:14:59+00:00", "open": "100", "high": "102", "low": "99",
        "close": "101", "volume": "10", "is_closed": True,
    }]


def test_candles_endpoint_rejects_symbols_that_are_not_enabled(tmp_path: Path):
    app = create_dashboard_app(tmp_path / "engine.db", ("ETHUSDT",))

    response = TestClient(app).get("/api/candles?symbol=BTCUSDT&timeframe=15m")

    assert response.status_code == 404


def test_chart_supported_symbols_and_timeframes_use_existing_candle_endpoint(tmp_path: Path):
    symbols = ("ETHUSDT", "BTCUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
    client = TestClient(create_dashboard_app(tmp_path / "engine.db", symbols))

    for symbol in symbols:
        for timeframe in ("15m", "1h", "4h"):
            assert client.get(f"/api/candles?symbol={symbol}&timeframe={timeframe}&limit=80").status_code == 200


def test_signals_endpoint_returns_persisted_analysis_records(tmp_path: Path):
    database_path = tmp_path / "engine.db"
    database = Database(database_path); database.open()
    assert database.connection is not None
    database.connection.execute(
        """INSERT INTO signals (signal_id,symbol,timeframe,direction,classification,confidence,entry_low,entry_high,reference_entry,stop_loss,take_profit_1,take_profit_2,take_profit_3,take_profit_4,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("ETHUSDT-15m-BULLISH-example", "ETHUSDT", "15m", "BULLISH", "STRONG_SIGNAL", 9,
         "100", "101", "100.5", "99", "102", "104", "106", None, "2026-01-01T00:15:00+00:00"),
    )
    database.connection.commit(); database.close()
    app = create_dashboard_app(database_path, ("ETHUSDT",))

    response = TestClient(app).get("/api/signals?symbol=ETHUSDT&limit=10")

    assert response.status_code == 200
    assert response.json()["signals"] == [{
        "signal_id": "ETHUSDT-15m-BULLISH-example", "symbol": "ETHUSDT", "timeframe": "15m",
        "direction": "BULLISH", "classification": "STRONG_SIGNAL", "confidence": "9",
        "entry_low": "100", "entry_high": "101", "reference_entry": "100.5", "stop_loss": "99",
        "take_profit_1": "102", "take_profit_2": "104", "take_profit_3": "106",
        "take_profit_4": None, "created_at": "2026-01-01T00:15:00+00:00",
    }]

    detail = TestClient(app).get("/api/signals/ETHUSDT-15m-BULLISH-example")
    assert detail.status_code == 200
    assert detail.json()["evidence"] is None
    assert detail.json()["reference_entry"] == "100.5"


def test_phase9_endpoint_serves_only_a_persisted_report(tmp_path: Path):
    report_path = tmp_path / "phase9_report.json"
    app = create_dashboard_app(tmp_path / "engine.db", ("ETHUSDT",), phase9_report_path=report_path)
    client = TestClient(app)
    assert client.get("/api/phase9").json() == {
        "available": False, "status": "REPORT_UNAVAILABLE", "report": None,
    }
    report_path.write_text('{"status":"INCOMPLETE_VALIDATION_ORCHESTRATION","walk_forward":{"oos_trade_count":0}}', encoding="utf-8")
    response = client.get("/api/phase9")
    assert response.status_code == 200
    assert response.json()["available"] is True
    assert response.json()["report"]["walk_forward"]["oos_trade_count"] == 0


def test_notifications_endpoint_returns_delivery_attempts_for_a_signal(tmp_path: Path):
    database_path = tmp_path / "engine.db"
    database = Database(database_path); database.open()
    assert database.connection is not None
    database.connection.execute(
        "INSERT INTO notifications (signal_id,provider,success,attempts,error) VALUES (?,?,?,?,?)",
        ("signal-1", "discord", 0, 3, "connection refused"),
    )
    database.connection.commit(); database.close()
    app = create_dashboard_app(database_path, ("ETHUSDT",))

    response = TestClient(app).get("/api/notifications?signal_id=signal-1")

    assert response.status_code == 200
    assert response.json()["notifications"] == [{
        "provider": "discord", "success": False, "attempts": 3, "error": "connection refused",
    }]


def test_backtests_endpoint_exposes_persisted_runs_and_details(tmp_path: Path):
    database_path = tmp_path / "engine.db"
    database = Database(database_path); database.open()
    database.connection.execute(
        "INSERT INTO backtest_runs VALUES (?,?,?,?,?,?)",
        ("run-1", "ETHUSDT", "15m", "DIAGNOSTIC", "[\"diagnostic\"]", "2026-01-01T00:00:00+00:00"),
    )
    database.connection.commit(); database.close()
    client = TestClient(create_dashboard_app(database_path, ("ETHUSDT",)))
    assert client.get("/api/backtests").json()["backtests"][0]["run_id"] == "run-1"
    detail = client.get("/api/backtests/run-1")
    assert detail.status_code == 200
    assert detail.json()["status"] == "DIAGNOSTIC"
