from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app.dashboard import create_dashboard_app
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
