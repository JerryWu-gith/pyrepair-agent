from datetime import date
from time import strptime


def parse_display_date(value: str) -> date:
    parsed = strptime(value, "%m-%d-%Y")
    return date(parsed.tm_year, parsed.tm_mon, parsed.tm_mday)
