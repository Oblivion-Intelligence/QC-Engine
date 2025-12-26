from datetime import datetime, timedelta, timezone

from qcengine.domain.time_windows import Window


def test_window_contains_half_open_interval() -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)
    window = Window(start, end)

    assert window.contains(start)
    assert window.contains(start + timedelta(minutes=5))
    assert not window.contains(start - timedelta(seconds=1))
    assert not window.contains(end)


def test_window_split_creates_consecutive_windows() -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(minutes=5)
    window = Window(start, end)

    chunks = window.split(timedelta(minutes=2))

    assert len(chunks) == 3
    assert chunks[0].start_utc == start
    assert chunks[-1].end_utc == end
    assert all(chunks[i].end_utc == chunks[i + 1].start_utc for i in range(len(chunks) - 1))
    assert all(chunk.contains(chunk.start_utc) for chunk in chunks)
