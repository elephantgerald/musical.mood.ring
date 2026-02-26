import pytest
from poller import Poller, _INTERVAL_MS, _BACKOFF_BASE_MS, _PERSISTENT_MS

T0 = 0   # reference "now"


# ── Initial state ──────────────────────────────────────────────────────────

def test_fires_immediately_on_start():
    assert Poller().should_poll(T0)


def test_no_persistent_failure_initially():
    assert not Poller().is_persistent_failure(T0)


# ── on_success ─────────────────────────────────────────────────────────────

def test_success_schedules_next_poll():
    p = Poller()
    p.on_success(T0)
    assert not p.should_poll(T0 + _INTERVAL_MS - 1)
    assert     p.should_poll(T0 + _INTERVAL_MS)


def test_success_clears_error_state():
    p = Poller()
    p.on_error(T0)
    p.on_success(T0 + 1000)
    assert not p.is_persistent_failure(T0 + _PERSISTENT_MS + 1000)


def test_success_resets_back_off():
    p = Poller()
    p.on_error(T0)
    p.on_error(T0 + 1000)
    p.on_success(T0 + 2000)
    # After success the next error should restart back-off at step 0
    p.on_error(T0 + 3000)
    assert p.should_poll(T0 + 3000 + _BACKOFF_BASE_MS)
    assert not p.should_poll(T0 + 3000 + _BACKOFF_BASE_MS - 1)


# ── on_rate_limit ──────────────────────────────────────────────────────────

def test_rate_limit_waits_retry_after():
    p = Poller()
    retry_after = 90_000   # 90 seconds
    p.on_rate_limit(T0, retry_after)
    assert not p.should_poll(T0 + retry_after - 1)
    assert     p.should_poll(T0 + retry_after)


def test_rate_limit_does_not_affect_error_count():
    p = Poller()
    p.on_rate_limit(T0, 30_000)
    assert not p.is_persistent_failure(T0 + _PERSISTENT_MS + 1)


# ── on_error / back-off ────────────────────────────────────────────────────

def test_first_error_backs_off_1_min():
    p = Poller()
    p.on_error(T0)
    assert not p.should_poll(T0 + _BACKOFF_BASE_MS - 1)
    assert     p.should_poll(T0 + _BACKOFF_BASE_MS)


def test_second_error_backs_off_2_min():
    p = Poller()
    p.on_error(T0)
    p.on_error(T0 + _BACKOFF_BASE_MS)
    assert not p.should_poll(T0 + _BACKOFF_BASE_MS + 2 * _BACKOFF_BASE_MS - 1)
    assert     p.should_poll(T0 + _BACKOFF_BASE_MS + 2 * _BACKOFF_BASE_MS)


def test_third_error_backs_off_4_min():
    # Errors at t=0, 60k, 120k. Third back-off = 4 min → next poll = 120k + 240k = 360k.
    p = Poller()
    t = T0
    for _ in range(3):
        p.on_error(t)
        t += 60_000
    next_poll = 120_000 + 4 * _BACKOFF_BASE_MS   # = 360_000
    assert not p.should_poll(next_poll - 1)
    assert     p.should_poll(next_poll)


def test_back_off_caps_at_4_min():
    p = Poller()
    t = T0
    for _ in range(10):   # many errors
        p.on_error(t)
        t += 60_000
    # Back-off should cap — next interval should be exactly 4 min
    assert p.should_poll(t + 4 * _BACKOFF_BASE_MS)


# ── is_persistent_failure ──────────────────────────────────────────────────

def test_persistent_failure_after_15_min_of_errors():
    p = Poller()
    p.on_error(T0)
    assert not p.is_persistent_failure(T0 + _PERSISTENT_MS - 1)
    assert     p.is_persistent_failure(T0 + _PERSISTENT_MS)


def test_persistent_failure_after_last_success_window():
    # Success at T0, error at T0+1000. Persistent window is measured from last success.
    p = Poller()
    p.on_success(T0)
    p.on_error(T0 + 1000)
    assert not p.is_persistent_failure(T0 + _PERSISTENT_MS - 1)
    assert     p.is_persistent_failure(T0 + _PERSISTENT_MS)


def test_not_persistent_when_no_errors():
    p = Poller()
    p.on_success(T0)
    assert not p.is_persistent_failure(T0 + _PERSISTENT_MS + 9999)
