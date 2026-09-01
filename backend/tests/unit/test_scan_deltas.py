"""`compute_scan_deltas` in isolation (FR-021, research.md R-405)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.governance.scan_deltas import ResourceTimestamps, compute_scan_deltas

WINDOW_START = datetime(2026, 1, 1, tzinfo=UTC)
WINDOW_END = WINDOW_START + timedelta(minutes=5)
BEFORE_WINDOW = WINDOW_START - timedelta(days=1)
INSIDE_WINDOW = WINDOW_START + timedelta(minutes=2)
AFTER_WINDOW = WINDOW_END + timedelta(days=1)


def test_a_resource_first_seen_in_the_window_counts_as_added() -> None:
    resources = [
        ResourceTimestamps(first_seen_at=INSIDE_WINDOW, last_seen_at=INSIDE_WINDOW, deleted_at=None)
    ]
    deltas = compute_scan_deltas(resources, WINDOW_START, WINDOW_END)
    assert deltas.added == 1
    assert deltas.removed == 0
    assert deltas.changed == 0


def test_a_resource_deleted_in_the_window_counts_as_removed() -> None:
    """`sweep_deleted_resources` only marks `deleted_at` for a resource whose
    `last_seen_at` predates the scan -- not re-confirmed by it -- so a deleted
    resource's `last_seen_at` is realistically before the window, never inside
    it (`orchestrator.py`'s own `last_seen_at < scan_started_at` filter)."""
    resources = [
        ResourceTimestamps(
            first_seen_at=BEFORE_WINDOW, last_seen_at=BEFORE_WINDOW, deleted_at=INSIDE_WINDOW
        )
    ]
    deltas = compute_scan_deltas(resources, WINDOW_START, WINDOW_END)
    assert deltas.added == 0
    assert deltas.removed == 1
    assert deltas.changed == 0


def test_a_pre_existing_resource_touched_again_counts_as_changed_not_added() -> None:
    """The `first_seen_at < window_start` guard: an existing resource this scan
    re-confirmed, not one it just discovered."""
    resources = [
        ResourceTimestamps(first_seen_at=BEFORE_WINDOW, last_seen_at=INSIDE_WINDOW, deleted_at=None)
    ]
    deltas = compute_scan_deltas(resources, WINDOW_START, WINDOW_END)
    assert deltas.added == 0
    assert deltas.removed == 0
    assert deltas.changed == 1


def test_a_resource_untouched_by_this_scan_counts_as_none_of_the_three() -> None:
    resources = [
        ResourceTimestamps(first_seen_at=BEFORE_WINDOW, last_seen_at=BEFORE_WINDOW, deleted_at=None)
    ]
    deltas = compute_scan_deltas(resources, WINDOW_START, WINDOW_END)
    assert deltas == (0, 0, 0)


def test_a_resource_seen_after_the_window_is_not_counted_either() -> None:
    resources = [
        ResourceTimestamps(first_seen_at=AFTER_WINDOW, last_seen_at=AFTER_WINDOW, deleted_at=None)
    ]
    deltas = compute_scan_deltas(resources, WINDOW_START, WINDOW_END)
    assert deltas == (0, 0, 0)


def test_the_window_bounds_are_inclusive() -> None:
    resources = [
        ResourceTimestamps(first_seen_at=WINDOW_START, last_seen_at=WINDOW_START, deleted_at=None),
        ResourceTimestamps(first_seen_at=BEFORE_WINDOW, last_seen_at=WINDOW_END, deleted_at=None),
    ]
    deltas = compute_scan_deltas(resources, WINDOW_START, WINDOW_END)
    assert deltas.added == 1
    assert deltas.changed == 1


def test_a_mix_of_resources_is_counted_independently() -> None:
    resources = [
        ResourceTimestamps(
            first_seen_at=INSIDE_WINDOW, last_seen_at=INSIDE_WINDOW, deleted_at=None
        ),  # added
        ResourceTimestamps(
            first_seen_at=BEFORE_WINDOW, last_seen_at=INSIDE_WINDOW, deleted_at=None
        ),  # changed
        ResourceTimestamps(
            first_seen_at=BEFORE_WINDOW, last_seen_at=BEFORE_WINDOW, deleted_at=INSIDE_WINDOW
        ),  # removed
        ResourceTimestamps(
            first_seen_at=BEFORE_WINDOW, last_seen_at=BEFORE_WINDOW, deleted_at=None
        ),  # untouched
    ]
    deltas = compute_scan_deltas(resources, WINDOW_START, WINDOW_END)
    assert deltas.added == 1
    assert deltas.removed == 1
    assert deltas.changed == 1


def test_no_resources_is_well_defined_as_all_zero() -> None:
    assert compute_scan_deltas([], WINDOW_START, WINDOW_END) == (0, 0, 0)
