"""Explicit operator CLI: aggregate status or requeue one SQL dead letter."""

import argparse
import json
import os
from uuid import UUID

from safemeal.config.platform import PlatformSettings
from safemeal.infrastructure.persistence.database import (
    configure_database,
    dispose_engine,
)
from safemeal.infrastructure.persistence.behavior_outbox import SqlBehaviorOutbox


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "requeue"))
    parser.add_argument("event_id", nargs="?")
    args = parser.parse_args()
    if args.action == "requeue":
        try:
            if str(UUID(args.event_id)) != args.event_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            parser.error("requeue requires one canonical event UUID")
    elif args.event_id is not None:
        parser.error("status does not accept an event UUID")
    try:
        config = PlatformSettings(_env_file=os.environ.get("SAFEMEAL_ENV_FILE"))  # type: ignore[call-arg]
        configure_database(
            config.DATABASE_URL,
            debug=False,
            connect_timeout=config.DB_CONNECT_TIMEOUT,
            lock_wait_timeout=config.DB_LOCK_WAIT_TIMEOUT_SECONDS,
        )
        sql = SqlBehaviorOutbox()
        if args.action == "status":
            print(json.dumps(sql.metrics_snapshot()))
            return 0
        requeued = sql.requeue(args.event_id)
        print(json.dumps({"requeued": requeued}))
        return 0 if requeued else 2
    except Exception:
        # No credentials, identities or raw database exception messages.
        print(json.dumps({"error": "operation_failed"}))
        return 3
    finally:
        dispose_engine()


if __name__ == "__main__":
    raise SystemExit(main())
