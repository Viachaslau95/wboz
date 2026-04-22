import datetime

from bot.db import _select_due_tracks, is_track_due


def test_due_tracks_query_selects_required_columns() -> None:
    query = _select_due_tracks()
    selected_keys = set(query.selected_columns.keys())
    assert "last_checked_at" in selected_keys
    assert "initial_price" in selected_keys
    assert "last_drop5_notified_at" in selected_keys
    assert "last_approach_notified_at" in selected_keys


def test_is_track_due_happy_path_when_old_check_time() -> None:
    now = datetime.datetime(2026, 4, 22, 13, 0, 0, tzinfo=datetime.UTC)
    last_checked_at = now - datetime.timedelta(minutes=31)
    assert is_track_due(last_checked_at, interval_minutes=30, now=now) is True


def test_is_track_due_boundary_exact_interval() -> None:
    now = datetime.datetime(2026, 4, 22, 13, 0, 0, tzinfo=datetime.UTC)
    last_checked_at = now - datetime.timedelta(minutes=30)
    assert is_track_due(last_checked_at, interval_minutes=30, now=now) is True


def test_is_track_due_failure_path_when_not_yet_due() -> None:
    now = datetime.datetime(2026, 4, 22, 13, 0, 0, tzinfo=datetime.UTC)
    last_checked_at = now - datetime.timedelta(minutes=29)
    assert is_track_due(last_checked_at, interval_minutes=30, now=now) is False
