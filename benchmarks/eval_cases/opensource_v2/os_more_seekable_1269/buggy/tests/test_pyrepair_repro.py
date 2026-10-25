from more_itertools import seekable


def test_zero_cache_peek_preserves_sequence():
    stream = seekable([10, 20, 30], maxlen=0)
    assert stream.peek() == 10
    assert list(stream) == [10, 20, 30]


def test_zero_cache_bool_preserves_sequence():
    stream = seekable([10, 20, 30], maxlen=0)
    assert bool(stream) is True
    assert list(stream) == [10, 20, 30]


def test_default_cache_regression():
    stream = seekable([10, 20])
    assert next(stream) == 10
    stream.seek(0)
    assert list(stream) == [10, 20]
