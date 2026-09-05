from dataclasses import replace
from decimal import Decimal

from app.backtest.exits import ExitPolicyEngine, TradeState, gross_r
from app.config.settings import ExitLeg, ExitPolicySettings
from app.structure.csd import CSDDirection


def _engine(*, time_stop_bars=10, breakeven_offset_r=Decimal("0.1")):
    return ExitPolicyEngine(ExitPolicySettings(
        legs=(ExitLeg(Decimal("1"), Decimal("50")), ExitLeg(Decimal("2"), Decimal("25")), ExitLeg(Decimal("3"), Decimal("25"))),
        move_stop_to_breakeven_after_leg=1,
        breakeven_offset_r=breakeven_offset_r,
        time_stop_bars=time_stop_bars,
    ))


def _trade():
    return _engine().open_trade(direction=CSDDirection.BULLISH, entry_low=Decimal("100"), entry_high=Decimal("100"), reference_entry=Decimal("100"), stop_loss=Decimal("99"))


def _candle(make_candle, offset, low, high, close):
    return replace(make_candle(offset=offset), open=Decimal(str(close)), low=Decimal(str(low)), high=Decimal(str(high)), close=Decimal(str(close)))


def test_entry_is_not_processed_on_the_signal_candle(make_candle):
    engine = _engine()
    trade = _trade()
    signal_candle = _candle(make_candle, 0, 97, 102, 100)

    # The runner deliberately does not call advance on this candle.
    assert trade.state is TradeState.AWAITING_ENTRY
    engine.advance(trade, _candle(make_candle, 1, 102, 103, 102.5))
    assert trade.state is TradeState.AWAITING_ENTRY


def test_scaled_legs_fill_on_separate_candles(make_candle):
    engine = _engine(); trade = _trade()
    for offset, high in enumerate((Decimal("101"), Decimal("102"), Decimal("103")), start=1):
        engine.advance(trade, _candle(make_candle, offset, 100 if offset == 1 else 100.2, high, high))
    assert trade.state is TradeState.CLOSED
    assert [leg.filled_at_candle_index for leg in trade.legs] == [1, 2, 3]
    assert trade.remaining_size_percent == Decimal("0")
    assert gross_r(trade) == Decimal("1.75")


def test_breakeven_stop_replaces_original_stop_after_first_leg(make_candle):
    engine = _engine(); trade = _trade()
    engine.advance(trade, _candle(make_candle, 1, 100, 101, 101))
    assert trade.current_stop == Decimal("100.1")
    engine.advance(trade, _candle(make_candle, 2, 100.2, 100.5, 100.3))
    assert trade.state is TradeState.OPEN


def test_same_candle_stop_and_target_is_pessimistically_resolved_as_stop(make_candle):
    engine = _engine(); trade = _trade()
    engine.advance(trade, _candle(make_candle, 1, 99, 101, 100))
    assert trade.state is TradeState.CLOSED
    assert trade.exit_reason == "SL"
    assert trade.ambiguous_intrabar_events == 1
    assert gross_r(trade) == Decimal("-1")


def test_time_stop_uses_the_actual_close_price_for_gross_r(make_candle):
    engine = _engine(time_stop_bars=2); trade = _trade()
    engine.advance(trade, _candle(make_candle, 1, 100, 100.5, 100.25))
    engine.advance(trade, _candle(make_candle, 2, 100, 100.5, 100.5))
    assert trade.exit_reason == "TIME_STOP"
    assert gross_r(trade) == Decimal("0.5")


def test_end_of_data_uses_the_actual_close_price_for_gross_r(make_candle):
    engine = _engine(); trade = _trade()
    last = _candle(make_candle, 1, 99.5, 100.5, 99.5)
    engine.advance(trade, last)
    engine.close_at_end_of_data(trade, last)
    assert trade.exit_reason == "END_OF_DATA"
    assert gross_r(trade) == Decimal("-0.5")


def test_unfilled_entry_expires_without_becoming_a_trade(make_candle):
    engine = _engine(time_stop_bars=2); trade = _trade()
    for offset in (1, 2, 3):
        engine.advance(trade, _candle(make_candle, offset, 102, 103, 102.5))
    assert trade.state is TradeState.EXPIRED_UNFILLED
