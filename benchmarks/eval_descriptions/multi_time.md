# multi_time

normalize accepts valid ISO-8601 datetime strings that include a timezone offset (Z allowed). Preserve the instant, convert to UTC and return YYYY-MM-DDTHH:MM:SSZ, dropping fractional seconds. Naive inputs are outside the contract. Exposed parse_timestamp must return a UTC aware datetime representing that instant; format_utc accepts UTC aware datetimes.

Fix production code; preserve public APIs and visible tests.
