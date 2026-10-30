"""core-worker compose sağlık kontrolü: Postgres'e bağlanıp job tablosunu okuyabiliyor mu."""

import sys

from tp_core import db


def main() -> int:
    try:
        db.ping("SELECT 1 FROM job LIMIT 1")
    except Exception as exc:
        print(f"unhealthy: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
