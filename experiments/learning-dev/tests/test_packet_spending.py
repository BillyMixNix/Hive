from datetime import datetime, timezone
import pytest
from analysis.packet_spending import SpendingGuard, MODEL


def test_current_guard_and_expiration(tmp_path):
    guard = SpendingGuard(tmp_path/'ledger', now=datetime(2026, 9, 9, tzinfo=timezone.utc))
    guard.reserve()
    guard.settle(MODEL, 100, 10, 'default')
    assert guard.snapshot()['measured_usage_upper_nano_usd'] == 68000
    guard._clock = lambda: datetime(2026, 9, 10, tzinfo=timezone.utc)
    with pytest.raises(RuntimeError, match='expired'):
        guard.reserve()
    guard.close()


def test_budget_and_unresolved_request_stop(tmp_path):
    guard = SpendingGuard(tmp_path/'ledger', now=datetime(2026, 9, 9, tzinfo=timezone.utc))
    guard.reserve()
    with pytest.raises(RuntimeError, match='unresolved'):
        guard.reserve()
    guard.fail()
    assert guard.snapshot()['total_upper_nano_usd'] == 532372800
    guard.close()
    guard = SpendingGuard(tmp_path/'near-limit', now=datetime(2026, 9, 9, tzinfo=timezone.utc), prior_upper_nano_usd=4_500_000_000)
    with pytest.raises(RuntimeError, match='budget'):
        guard.reserve()
    assert guard.snapshot()['requests_reserved'] == 0
    guard.close()
