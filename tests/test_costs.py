from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.backtest.costs import CostModel
from app.config.settings import CostSettings
from app.structure.csd import CSDDirection


def _model(**overrides):
    return CostModel(CostSettings(**overrides))


def test_entry_cost_percent_uses_the_selected_maker_or_taker_fee_plus_slippage():
    assert _model().entry_cost_percent() == Decimal("0.07")
    assert _model(entry_order_type="maker").entry_cost_percent() == Decimal("0.04")


def test_stop_exit_cost_uses_wider_stop_slippage():
    model = _model()
    assert model.exit_cost_percent(is_stop=False) == Decimal("0.07")
    assert model.exit_cost_percent(is_stop=True) == Decimal("0.10")


def test_funding_is_zero_under_eight_hours_and_charged_for_each_crossed_boundary():
    model = _model()
    opened = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert model.funding_r(opened_at=opened, closed_at=opened + timedelta(hours=7, minutes=59), risk_unit_percent=Decimal("1")) == Decimal("0")
    assert model.funding_r(opened_at=opened, closed_at=opened + timedelta(hours=24), risk_unit_percent=Decimal("1")) == Decimal("0.03")


def test_breakdown_total_equals_all_cost_components_without_double_counting():
    opened = datetime(2026, 1, 1, tzinfo=timezone.utc)
    breakdown = _model().breakdown(
        direction=CSDDirection.BULLISH,
        entry=Decimal("100"), stop_loss=Decimal("99"), exit_price=Decimal("102"),
        is_stop_exit=False, opened_at=opened, closed_at=opened + timedelta(hours=8),
    )
    assert breakdown.total_r == (
        breakdown.entry_fee_r + breakdown.exit_fee_r + breakdown.entry_slippage_r
        + breakdown.exit_slippage_r + breakdown.funding_r
    )
    assert breakdown.entry_fee_r == Decimal("0.05")
    assert breakdown.entry_slippage_r == Decimal("0.02")
