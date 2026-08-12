class RecordFormatError(ValueError):
    pass


def parse_record_id(value: str) -> int:
    return int(value)
