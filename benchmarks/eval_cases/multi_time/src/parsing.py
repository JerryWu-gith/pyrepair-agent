from datetime import datetime, timezone


def parse_timestamp(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
