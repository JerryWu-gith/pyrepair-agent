import pytest
from more_itertools import seekable


def test_falsey_elements_are_not_dropped():
    for head in [0, False, None, ""]:
        stream = seekable([head, "tail", "end"], maxlen=0)
        assert stream.peek() == head
        assert bool(stream) is True
        assert list(stream) == [head, "tail", "end"]
        assert list(stream.elements()) == []


def test_interleaved_peek_bool_next():
    stream = seekable([1, 2, 3, 4], maxlen=0)
    assert stream.peek() == 1
    assert stream.peek() == 1
    assert bool(stream) is True
    assert next(stream) == 1
    assert stream.peek() == 2
    assert next(stream) == 2
    assert list(stream) == [3, 4]
    assert list(stream.elements()) == []
    assert bool(stream) is False


def test_empty_and_default_behavior():
    stream = seekable([], maxlen=0)
    marker = object()
    assert stream.peek(default=marker) is marker
    with pytest.raises(StopIteration):
        stream.peek()
    assert bool(stream) is False
    assert list(stream.elements()) == []


def test_nonzero_bounded_cache_regression():
    stream = seekable(["a", "b", "c"], maxlen=2)
    assert list(stream) == ["a", "b", "c"]
    assert list(stream.elements()) == ["b", "c"]
    stream.seek(0)
    assert list(stream) == ["b", "c"]
