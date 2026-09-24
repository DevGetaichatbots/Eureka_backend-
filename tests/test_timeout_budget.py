"""
The reply pipeline has three nested timeouts. They must stay ordered.

    n8n -> OpenAI (per LLM call)   20s   configured on the n8n "OpenAI Chat Model" node
    backend -> n8n (per attempt)   45s   N8NClient.REQUEST_TIMEOUT_SECONDS
    reply watchdog                 90s   settings.WATCHDOG_TIMEOUT_SECONDS

Until 24 Sep 2026 all three were 60s. Because the inner one could consume the entire outer
budget, a single slow dispatch guaranteed a wrong apology: in conversation 253 the customer
sent "بيت" at 12:12:52, the watchdog fired at 12:13:56, and n8n's real answer arrived at
12:14:06 - ten seconds after the customer had been told the bot was broken.

These tests fail loudly if anyone flattens the ladder again.
"""

from app.config import settings
from app.services.n8n_client import N8NClient, n8n_client


# Slowest legitimate n8n run measured over 141 executions after the media fast path
# went live (median 8.8s, p95 21.4s, max 41.2s).
OBSERVED_MAX_N8N_SECONDS = 41.2


def test_dispatch_timeout_is_below_the_watchdog():
    """A hung attempt must not be able to use up the watchdog's whole budget."""
    assert N8NClient.REQUEST_TIMEOUT_SECONDS < settings.WATCHDOG_TIMEOUT_SECONDS, (
        f"dispatch timeout {N8NClient.REQUEST_TIMEOUT_SECONDS}s must be under the watchdog "
        f"{settings.WATCHDOG_TIMEOUT_SECONDS}s, or a slow n8n always produces a false apology"
    )


def test_a_retry_can_still_beat_the_watchdog():
    """
    The point of retrying is that the second attempt can still deliver in time. If the
    watchdog fires first the retry is pointless and the customer gets an apology anyway.
    """
    first_attempt = N8NClient.REQUEST_TIMEOUT_SECONDS
    backoff = n8n_client.backoff_delays[0]
    # A healthy n8n answers well inside its own p95; give the retry that much room.
    second_attempt_budget = 25.0

    worst_case_for_a_successful_retry = first_attempt + backoff + second_attempt_budget
    assert worst_case_for_a_successful_retry <= settings.WATCHDOG_TIMEOUT_SECONDS, (
        f"a retry needs {worst_case_for_a_successful_retry}s but the watchdog fires at "
        f"{settings.WATCHDOG_TIMEOUT_SECONDS}s - raise WATCHDOG_TIMEOUT_SECONDS or lower "
        f"REQUEST_TIMEOUT_SECONDS"
    )


def test_dispatch_timeout_does_not_cut_off_a_healthy_run():
    """
    Too SHORT is its own bug: abandoning an n8n run that was about to succeed makes the
    client retry, and the customer receives the answer twice.
    """
    assert N8NClient.REQUEST_TIMEOUT_SECONDS > OBSERVED_MAX_N8N_SECONDS, (
        f"dispatch timeout {N8NClient.REQUEST_TIMEOUT_SECONDS}s is below the slowest observed "
        f"n8n run ({OBSERVED_MAX_N8N_SECONDS}s); legitimate runs would be retried and the "
        f"customer would get duplicate replies"
    )


def test_the_client_actually_uses_the_configured_timeout():
    """Guard against the literal creeping back into the httpx call."""
    import inspect

    source = inspect.getsource(N8NClient.dispatch)
    assert "self.REQUEST_TIMEOUT_SECONDS" in source, (
        "dispatch() must build its httpx client from REQUEST_TIMEOUT_SECONDS, not a literal"
    )
    assert "timeout=60.0" not in source, "the old hardcoded 60s timeout is back"
