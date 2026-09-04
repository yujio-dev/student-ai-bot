"""Opt-in operational events only; never pass exceptions or user content."""
import os
import re

CATEGORIES = {"synthetic_check", "core_unhandled", "outbox_retry_failed"}
ENVIRONMENTS = {"production", "staging", "development", "test"}
_client = None


def scrub(event, hint=None):
    category = event.get("tags", {}).get("category") if isinstance(event.get("tags"), dict) else None
    event_id = event.get("event_id", "")
    if not isinstance(category, str) or category not in CATEGORIES or not isinstance(event_id, str) or not re.fullmatch(r"[a-f0-9]{32}", event_id):
        return None
    # Reconstruct, rather than redact known secret names: unknown data is discarded.
    clean = {"event_id": event_id, "message": category, "level": "error", "tags": {"category": category}}
    environment = event.get("environment")
    service = event.get("server_name")
    if isinstance(environment, str) and environment in ENVIRONMENTS:
        clean["environment"] = environment
    if isinstance(service, str) and service in {"core", "bot"}:
        clean["tags"]["service"] = service
    return clean


def initialize(service):
    global _client
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return False
    if service not in {"core", "bot"}:
        raise ValueError("Invalid observability service")
    environment = os.getenv("SENTRY_ENVIRONMENT", os.getenv("APP_ENV", "development"))
    if environment not in ENVIRONMENTS:
        raise ValueError("Invalid observability environment")
    import sentry_sdk
    _client = sentry_sdk.Client(
        dsn=dsn, environment=environment, release=None, server_name=service,
        default_integrations=False, auto_enabling_integrations=False,
        send_default_pii=False, include_local_variables=False, include_source_context=False,
        attach_stacktrace=False, max_breadcrumbs=0, traces_sample_rate=0,
        profiles_sample_rate=0, auto_session_tracking=False, send_client_reports=False,
        before_send=scrub)
    return True


def report(category):
    if category not in CATEGORIES:
        raise ValueError("Unknown operational category")
    if _client is not None:
        try:
            _client.capture_event({"message": category, "level": "error", "tags": {"category": category}})
        except Exception:
            pass  # Observability cannot affect a payment or user request.
