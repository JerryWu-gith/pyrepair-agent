from config_merge import merge_config


def test_inherited_containers_are_isolated_in_both_directions():
    defaults = {"routes": [{"tags": ["stable"]}], "cache": {"sizes": [4]}}
    result = merge_config(defaults, {})
    result["routes"][0]["tags"].append("new")
    result["cache"]["sizes"].append(8)
    assert defaults == {"routes": [{"tags": ["stable"]}], "cache": {"sizes": [4]}}
    defaults["routes"].append({"tags": []})
    assert result["routes"] == [{"tags": ["stable", "new"]}]


def test_override_containers_are_isolated_in_both_directions():
    overrides = {
        "plugins": [{"options": ["fast"]}], "new": {"values": [3]},
        "nested": {"added": [7]},
    }
    result = merge_config({"plugins": ["old"], "nested": {"kept": 1}}, overrides)
    result["plugins"][0]["options"].append("safe")
    result["new"]["values"].append(5)
    result["nested"]["added"].append(9)
    assert overrides == {
        "plugins": [{"options": ["fast"]}], "new": {"values": [3]},
        "nested": {"added": [7]},
    }
    overrides["plugins"].append("external")
    assert result["plugins"] == [{"options": ["fast", "safe"]}]
    overrides["nested"]["added"].append(11)
    assert result["nested"] == {"kept": 1, "added": [7, 9]}


def test_falsey_overrides_replace_values_without_fallback():
    defaults = {"a": 7, "b": True, "c": "yes", "d": [1], "e": {"old": 1}}
    overrides = {"a": 0, "b": False, "c": "", "d": [], "e": None}
    assert merge_config(defaults, overrides) == {
        "a": 0, "b": False, "c": "", "d": [], "e": None
    }
    assert defaults == {"a": 7, "b": True, "c": "yes", "d": [1], "e": {"old": 1}}


def test_recursive_values_lists_and_type_replacement_are_preserved():
    result = merge_config(
        {"db": {"timeout": 10, "flags": {"read": True}}, "items": [1, 2], "mode": 9},
        {"db": {"flags": {"write": True}}, "items": [3], "mode": {"name": "safe"}},
    )
    assert result == {
        "db": {"timeout": 10, "flags": {"read": True, "write": True}},
        "items": [3], "mode": {"name": "safe"},
    }


def test_empty_dictionary_merges_and_empty_inputs_are_preserved():
    assert merge_config({"nested": {"retained": 1}}, {"nested": {}}) == {
        "nested": {"retained": 1}
    }
    assert merge_config({}, {}) == {}


def test_empty_dictionary_replaces_scalar_value():
    assert merge_config({"value": 4}, {"value": {}}) == {"value": {}}
