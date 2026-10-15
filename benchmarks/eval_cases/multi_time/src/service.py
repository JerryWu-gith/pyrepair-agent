from parsing import parse_timestamp
from formatting import format_utc


def normalize(text):
    return format_utc(parse_timestamp(text))
