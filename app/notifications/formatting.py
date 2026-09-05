from app.signals.models import SignalRecord


def format_signal(record: SignalRecord) -> str:
    tp4 = f"\nTP4 {record.take_profit_4}" if record.take_profit_4 is not None else ""
    return (
        f"{record.symbol} {record.direction} {record.classification}\n"
        f"Confidence: {record.confidence}/10 | Timeframe: {record.timeframe}\n"
        f"Entry: {record.entry_low} – {record.entry_high} (ref {record.reference_entry})\n"
        f"Stop: {record.stop_loss}\n"
        f"TP1 {record.take_profit_1} | TP2 {record.take_profit_2} | TP3 {record.take_profit_3}{tp4}\n"
        "Signal only — no trade executed."
    )
