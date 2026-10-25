from boltons.dictutils import OMD
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
