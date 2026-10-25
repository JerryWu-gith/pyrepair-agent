from boltons.dictutils import OMD


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
