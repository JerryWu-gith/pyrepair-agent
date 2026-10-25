"""Public/hidden overlays for two reviewed dev tasks; data, not imported tests.

Only the Docker task runner may execute these strings after materialization.
They are kept separate from upstream snapshots and each origin is recorded.
"""

MORE_PUBLIC = """from more_itertools import seekable


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
"""

MORE_HIDDEN = """import pytest
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
"""

BOLTONS_PUBLIC = """from boltons.dictutils import OMD


def test_addlist_one_shot_iterator():
    values = OMD()
    values.addlist("a", iter([1, 2, 3]))
    assert values.getlist("a") == [1, 2, 3]
    assert values.get("a") == 3
    assert values.items(multi=True) == [("a", 1), ("a", 2), ("a", 3)]


def test_addlist_list_input_regression():
    values = OMD()
    values.addlist("a", [1, 2])
    assert values.getlist("a") == [1, 2]
    assert values.get("a") == 2
"""

BOLTONS_HIDDEN = """from boltons.dictutils import OMD
from boltons.urlutils import QueryParamDict


def test_query_iterator_consistency():
    query = QueryParamDict()
    query.addlist("tag", iter(["first", "second"]))
    assert query.getlist("tag") == ["first", "second"]
    assert query.get("tag") == "second"
    assert query.keys() == ["tag"]
    assert len(query) == 1
    assert query.items(multi=True) == [("tag", "first"), ("tag", "second")]
    assert query.to_text() == "tag=first&tag=second"


def test_empty_iterators_create_no_key():
    for cls in (OMD, QueryParamDict):
        values = cls()
        values.addlist("empty", (item for item in []))
        assert len(values) == 0
        assert values.keys() == []
        assert values.getlist("empty") == []
        assert values.get("empty") is None
        assert values.items(multi=True) == []


def test_generator_appends_to_existing_key():
    for cls in (OMD, QueryParamDict):
        values = cls([("a", "first"), ("b", "other")])
        values.addlist("a", (item for item in ["second", "third"]))
        assert values.getlist("a") == ["first", "second", "third"]
        assert values.get("a") == "third"
        assert values.keys() == ["a", "b"]
        assert len(values) == 2
        assert values.items(multi=True) == [
            ("a", "first"), ("b", "other"), ("a", "second"), ("a", "third"),
        ]


def test_list_inputs_keep_multivalue_behavior():
    for cls in (OMD, QueryParamDict):
        values = cls()
        values.addlist("a", ["one", "two"])
        values.addlist("b", [])
        assert values.keys() == ["a"]
        assert values.getlist("a") == ["one", "two"]
        assert values.get("a") == "two"
        assert len(values.items(multi=True)) == 2
"""

OVERLAYS = {
    "os_more_seekable_1269": {
        "task": (
            "# Non-consuming lookahead with zero history cache\n\n"
            "A seekable iterator configured with maxlen=0 must allow peek() and bool() "
            "without consuming the next item seen by iteration. Repeated lookahead and "
            "interleaving with next() must preserve element order and values, including "
            "falsey values. elements() must remain empty in this mode. Preserve the "
            "existing empty-iterator/default and nonzero/default-cache behavior.\n"
        ),
        "public": MORE_PUBLIC,
        "hidden": MORE_HIDDEN,
        "f2p_public": [
            "test_zero_cache_peek_preserves_sequence",
            "test_zero_cache_bool_preserves_sequence",
        ],
        "f2p_hidden": ["test_falsey_elements_are_not_dropped", "test_interleaved_peek_bool_next"],
        "p2p_public": ["test_default_cache_regression"],
        "p2p_hidden": ["test_empty_and_default_behavior", "test_nonzero_bounded_cache_regression"],
        "public_origin": "Adapted upstream issue #1268 / PR #1269 repro; local cache regression.",
        "hidden_origin": "Project-authored contract boundary tests; not supplied to models.",
        "mutant_origin": "Artificial mutant: restore lookahead only when the item is truthy.",
    },
    "os_boltons_addlist_458": {
        "task": (
            "# Consistent addlist behavior for one-shot iterables\n\n"
            "OrderedMultiDict/OMD and URL QueryParamDict addlist() must accept lists, "
            "iterators and generators consistently. Every input value must remain "
            "visible through getlist(), get(), keys(), items(multi=True), and length. "
            "Appending to an existing key must retain earlier values and insertion "
            "order; empty iterables must not create an empty key. QueryParamDict "
            "serialization must remain consistent with its stored query values.\n"
        ),
        "public": BOLTONS_PUBLIC,
        "hidden": BOLTONS_HIDDEN,
        "f2p_public": ["test_addlist_one_shot_iterator"],
        "f2p_hidden": [
            "test_query_iterator_consistency",
            "test_empty_iterators_create_no_key",
            "test_generator_appends_to_existing_key",
        ],
        "p2p_public": ["test_addlist_list_input_regression"],
        "p2p_hidden": ["test_list_inputs_keep_multivalue_behavior"],
        "public_origin": "Adapted upstream PR #458 regression with local list-input regression.",
        "hidden_origin": "Project-authored cross-module and boundary tests.",
        "mutant_origin": "Artificial mutant: fix dictutils but leave urlutils unchanged.",
    },
}
