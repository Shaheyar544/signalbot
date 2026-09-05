import pytest

from app.data.candles import CandleStore
from app.replay import HistoricalReplay


class RecordingStrategy:
    def __init__(self):
        self.received = []

    async def on_candle_closed(self, event):
        self.received.append(event.candle)


class CausalRecordingStrategy:
    def __init__(self, store):
        self.store, self.visible_counts = store, []

    async def on_candle_closed(self, event):
        visible = self.store.get_recent_as_of(event.symbol, event.timeframe, 500, event.candle.open_time)
        self.visible_counts.append((event.candle.open_time, len(visible), max(item.open_time for item in visible)))


@pytest.mark.asyncio
async def test_replay_delivers_only_closed_candles_in_chronological_order(make_candle):
    store = CandleStore()
    strategy = RecordingStrategy()
    newest = make_candle(offset=2)
    forming = make_candle(offset=1, closed=False)
    oldest = make_candle(offset=0)

    result = await HistoricalReplay(store, strategy).run([newest, forming, oldest])

    assert result.processed_candles == 2
    assert strategy.received == [oldest, newest]
    assert store.get_recent("ETHUSDT", "15m", 2) == [oldest, newest]


@pytest.mark.asyncio
async def test_replay_never_exposes_future_candles_to_a_decision(make_candle):
    store = CandleStore(); strategy = CausalRecordingStrategy(store)
    candles = [make_candle(offset=index) for index in range(5)]

    await HistoricalReplay(store, strategy).run(candles)

    assert strategy.visible_counts == [(candle.open_time, index + 1, candle.open_time) for index, candle in enumerate(candles)]
