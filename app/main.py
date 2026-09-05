from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import json
import os
from app.backtest.gate import GoLiveGateSettings, evaluate_gate

from app.config.settings import load_settings
from app.data.binance_rest import BinanceRestClient
from app.data.binance_ws import BinanceWebSocketClient
from app.data.candles import CandleStore
from app.events.bus import EventBus
from app.monitoring.health import HealthStatus
from app.monitoring.runtime import RuntimeHealthSnapshotStore
from app.notifications.dispatcher import NotificationDispatcher
from app.notifications.factory import configured_providers
from app.signals.models import build_signal_id
from app.storage.database import Database
from app.storage.repositories import CandleRepository, NotificationRepository, SignalRepository
from app.strategy.csd_strategy import CSDStrategyEngine


async def validate_enabled_symbols(rest: BinanceRestClient, symbols: tuple[str, ...]) -> tuple[str, ...]:
    valid: list[str] = []
    for symbol in symbols:
        if await rest.validate_symbol(symbol):
            valid.append(symbol)
    return tuple(valid)


async def run(config_path: str, *, force_live: bool = False, acknowledge_risk: bool = False) -> None:
    settings = load_settings(config_path)
    if force_live and not acknowledge_risk:
        raise ValueError("--force-live requires --acknowledge-risk")
    observation_mode = True
    report_path = os.getenv("VALIDATION_REPORT_PATH", str(settings.database_path.with_name("validation_report.json")))
    try:
        with open(report_path, encoding="utf-8") as handle:
            validation_report = json.load(handle)
        gate = evaluate_gate(validation_report, GoLiveGateSettings(**(settings.go_live_gate or {})))
        observation_mode = not gate.passed
        if gate.failures:
            logging.warning("Go-live gate failed; observation mode: %s", "; ".join(gate.failures))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        logging.warning("No valid validation report; observation mode: %s", error)
    if force_live:
        observation_mode = False
        logging.warning("--force-live acknowledged; bypassing go-live gate")
    logging.info("Starting Multi-Pair CSD Signal Engine")
    database = Database(settings.database_path)
    database.open()
    health = HealthStatus(running=True, database_connected=True, enabled_symbols=len(settings.enabled_symbols))
    runtime_health = RuntimeHealthSnapshotStore(settings.database_path.with_suffix(".health.json"))

    def publish_health() -> None:
        runtime_health.write(health)

    publish_health()
    store = CandleStore(CandleRepository(database))
    bus = EventBus()
    signals = SignalRepository(database)
    notification_dispatcher = NotificationDispatcher(configured_providers(), NotificationRepository(database))

    async def persist_signal(analysis) -> None:
        assessment = strategy.latest_assessment.get((analysis.symbol, analysis.timeframe))
        if assessment is None:
            logging.error("Risk analysis has no matching assessment for %s %s", analysis.symbol, analysis.timeframe)
            return
        if signals.save(assessment, analysis):
            logging.info("Persisted signal analysis for %s %s", analysis.symbol, analysis.timeframe)
            record = signals.get(build_signal_id(assessment))
            if record is not None:
                if not observation_mode:
                    await notification_dispatcher.dispatch(record)
        else:
            logging.info("Duplicate signal analysis ignored for %s %s", analysis.symbol, analysis.timeframe)

    strategy = CSDStrategyEngine(
        store,
        settings.primary_timeframe,
        left_bars=settings.swing.left_bars,
        right_bars=settings.swing.right_bars,
        minimum_close_distance_percent=settings.csd.minimum_close_distance_percent,
        retest_zone_percent=settings.retest.zone_percent,
        maximum_bars_after_breakout=settings.retest.maximum_bars_after_breakout,
        volume_ratio_minimum=settings.confirmation.volume_ratio_minimum,
        rsi_bullish_minimum=settings.confirmation.rsi_bullish_minimum,
        rsi_bearish_maximum=settings.confirmation.rsi_bearish_maximum,
        stop_buffer_percent=settings.risk.stop_buffer_percent,
        scoring_settings=settings.scoring,
        on_risk_analysis=persist_signal,
    )
    bus.subscribe_candle_closed(strategy.on_candle_closed)
    rest = BinanceRestClient()
    websocket: BinanceWebSocketClient | None = None
    try:
        for symbol in settings.invalid_symbols:
            logging.error("Configured symbol %s has an invalid format; skipping", symbol)
        valid_symbols = await validate_enabled_symbols(rest, settings.enabled_symbols)
        invalid = set(settings.enabled_symbols) - set(valid_symbols)
        for symbol in sorted(invalid):
            logging.error("Configured symbol %s is not a supported USD-M Futures trading pair; skipping", symbol)
        logging.info("Enabled valid symbols: %s", ", ".join(valid_symbols) or "none")

        async def reconcile() -> None:
            for symbol in valid_symbols:
                for timeframe in settings.timeframes:
                    for candle in await rest.fetch_candles(symbol, timeframe, settings.historical_candle_limit):
                        store.add_candle(candle)
                        if candle.is_closed:
                            health.record_closed_candle(candle)
            publish_health()
            logging.info("REST reconciliation complete")

        await reconcile()
        websocket = BinanceWebSocketClient(valid_symbols, settings.timeframes, store, bus, health,
            settings.websocket.max_reconnect_delay_seconds, settings.websocket.receive_timeout_seconds)
        websocket.on_health_update = publish_health
        loop = asyncio.get_running_loop()
        shutdown = asyncio.Event()
        def request_shutdown() -> None:
            logging.info("Shutdown requested")
            shutdown.set()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, request_shutdown)
            except NotImplementedError:  # Windows event loop limitation
                pass
        runner = asyncio.create_task(websocket.run(reconcile))
        await shutdown.wait()
        await websocket.stop()
        await runner
    finally:
        if websocket is not None:
            await websocket.stop()
        await rest.close()
        health.running = False
        health.database_connected = False
        database.close()
        publish_health()
        logging.info("Multi-Pair CSD Signal Engine stopped cleanly")


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-Pair CSD Signal Engine (market data and signal analysis)")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--force-live", action="store_true")
    parser.add_argument("--acknowledge-risk", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(run(args.config, force_live=args.force_live, acknowledge_risk=args.acknowledge_risk))


if __name__ == "__main__":
    main()
