"""Explicit one-event monitoring check; never imports the application or polling."""
import argparse
from app import observability


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=("core", "bot"))
    args = parser.parse_args(argv)
    try:
        if not observability.initialize(args.service):
            print("SENTRY_NOT_CONFIGURED")
            return 1
        client = observability._client
        event_id = client.capture_event({"message": "synthetic_check", "level": "error",
                                         "tags": {"category": "synthetic_check"}})
        client.flush(timeout=10)
        client.close(timeout=1)
        if not event_id:
            print("SENTRY_EVENT_NOT_QUEUED")
            return 1
        # An ID is correlation only, not proof of delivery: verify it in Sentry.
        print("SENTRY_EVENT_QUEUED " + event_id)
        return 0
    except Exception:
        print("SENTRY_CHECK_FAILED")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
