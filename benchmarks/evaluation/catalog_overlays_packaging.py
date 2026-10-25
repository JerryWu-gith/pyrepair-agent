"""Static behavioral overlays for the twelve packaging catalogue repairs."""

PACKAGING_OVERLAYS = {
    "os_packaging_hash_1232": {
        "task": """# Requirement keys in collections

Equivalent `packaging.requirements.Requirement` objects must behave as the same
key in dictionaries and sets, including when equivalent version constraints have
different trailing-zero spellings. This applies to equality and ordered version
constraints, normalized project names, and requirements carrying extras and
markers. Preserve ordinary parsing, string representation, and distinctions
between genuinely different requirements.
""",
        "public": """from packaging.requirements import Requirement


def test_equivalent_release_requirements_are_one_key():
    first = Requirement("sample==2.0.0")
    second = Requirement("sample==2.0.0.0")
    assert first == second
    assert hash(first) == hash(second)
    assert len({first, second}) == 1
    assert {first: "present"}.get(second) == "present"


def test_distinct_requirements_keep_distinct_meaning():
    lower = Requirement("Sample>=2")
    upper = Requirement("Sample<2")
    assert lower != upper
    assert str(lower) == "Sample>=2"
    assert "2.1" in lower.specifier
    assert "1.9" not in lower.specifier
""",
        "hidden": """from packaging.requirements import Requirement


def test_equivalent_constraints_with_extras_and_marker_are_one_key():
    left = Requirement('Widget_Name[fast]>=4.0; python_version >= "3.9"')
    right = Requirement('widget-name[fast]>=4.0.0; python_version >= "3.9"')
    assert left == right
    assert hash(left) == hash(right)
    assert {left: 17}.get(right) == 17


def test_url_and_extra_distinctions_are_preserved():
    plain = Requirement("sample @ https://example.invalid/a.whl")
    other = Requirement("sample @ https://example.invalid/b.whl")
    assert plain != other
    assert Requirement("sample[a]") != Requirement("sample[b]")
    assert plain.url == "https://example.invalid/a.whl"
""",
        "f2p_public": ["test_equivalent_release_requirements_are_one_key"],
        "f2p_hidden": ["test_equivalent_constraints_with_extras_and_marker_are_one_key"],
        "p2p_public": ["test_distinct_requirements_keep_distinct_meaning"],
        "p2p_hidden": ["test_url_and_extra_distinctions_are_preserved"],
        "public_origin": "Adapted from upstream d8e08df tests/test_requirements.py EQUIVALENT_DEPENDENCIES; independent project/version values and collection assertions.",
        "hidden_origin": "Independent boundary combining the upstream ordered-constraint and extras/marker contracts, plus stable URL/extra distinctions.",
        "mutant_origin": "Incomplete canonical hashing handles plain requirements but retains textual specifiers whenever extras are present.",
        "mutant": {
            "keep_paths": ["src/packaging/requirements.py"],
            "replacements": [
                {
                    "path": "src/packaging/requirements.py",
                    "old": "                self.specifier,\n",
                    "new": "                str(self.specifier) if self.extras else self.specifier,\n",
                }
            ],
        },
    },
    "os_packaging_quotes_1213": {
        "task": """# Marker literal serialization

Serialize marker string values without changing their literal contents or turning
their contents into marker syntax. Values containing either one quote character
must remain valid literals; marker and requirement string round-trips must retain
their meaning. `packaging._parser.Value.serialize()` must raise `ValueError` for
a value containing both quote characters, which this marker grammar cannot
represent. Preserve ordinary quote normalization and marker evaluation.
""",
        "public": """from packaging._parser import Value
from packaging.markers import Marker


def test_double_quote_inside_value_has_valid_serialization():
    value = 'east"west'
    try:
        serialized = Value(value).serialize()
        marker = Marker("os_name == " + serialized)
        outcome = (serialized, marker.evaluate({"os_name": value}))
    except Exception as exc:
        outcome = (type(exc).__name__, False)
    assert outcome == (chr(39) + value + chr(39), True)


def test_plain_and_single_quote_values_remain_supported():
    assert Value("plain").serialize() == '"plain"'
    assert Value("can't").serialize() == chr(34) + "can't" + chr(34)
    assert str(Marker("python_version >= '3.9'")) == 'python_version >= "3.9"'
""",
        "hidden": """from packaging._parser import Value
from packaging.requirements import Requirement


def test_unrepresentable_both_quote_value_is_rejected():
    outcome = None
    try:
        Value("one" + chr(34) + "two" + chr(39) + "three").serialize()
    except Exception as exc:
        outcome = type(exc).__name__
    assert outcome == "ValueError"


def test_requirement_literal_contents_do_not_become_logic():
    literal = 'a" == os_name or python_version >= "0" or "z'
    source = "widget; '" + literal + "' == os_name"
    try:
        before = Requirement(source)
        after = Requirement(str(before))
        env = {"os_name": "unrelated", "python_version": "3.12"}
        outcome = (before.marker.evaluate(env), after.marker.evaluate(env))
    except Exception as exc:
        outcome = type(exc).__name__
    assert outcome == (False, False)


def test_regular_requirement_marker_is_stable():
    req = Requirement('widget[fast]>=2; os_name == "posix"')
    assert req.extras == {"fast"}
    assert req.marker.evaluate({"os_name": "posix"}) is True
    assert req.marker.evaluate({"os_name": "nt"}) is False
""",
        "f2p_public": ["test_double_quote_inside_value_has_valid_serialization"],
        "f2p_hidden": [
            "test_unrepresentable_both_quote_value_is_rejected",
            "test_requirement_literal_contents_do_not_become_logic",
        ],
        "p2p_public": ["test_plain_and_single_quote_values_remain_supported"],
        "p2p_hidden": ["test_regular_requirement_marker_is_stable"],
        "public_origin": "Adapted from upstream 5b583e3 tests/test_markers.py Value serialization tests, with independent literal and semantic assertion.",
        "hidden_origin": "Upstream both-quote rejection and requirement round-trip behavior from tests/test_requirements.py, with independent literals and explicit environment.",
        "mutant_origin": "Incomplete serializer chooses delimiters for representable values but falls back to an invalid double-quoted string for values containing both delimiters.",
        "mutant": {
            "keep_paths": ["src/packaging/_parser.py"],
            "replacements": [
                {
                    "path": "src/packaging/_parser.py",
                    "old": '        raise ValueError(\n            "Cannot serialize marker value containing both quote characters"\n        )',
                    "new": "        return chr(34) + value + chr(34)",
                }
            ],
        },
    },
    "os_packaging_empty_tags_1234": {
        "task": """# Empty compatibility tag components

`packaging.tags.parse_tag` must reject empty interpreter, ABI, and platform
fields, including empty members anywhere inside dot-compressed fields, using an
`InvalidTag` exception that is a `ValueError`. This requirement applies with and
without order validation. Wheel filenames with these invalid tags must instead
raise `packaging.utils.InvalidWheelFilename`. Preserve expansion of valid tags,
wheel metadata, and the existing optional ordering validation.
""",
        "public": """from packaging import tags


def test_empty_abi_is_invalid_tag():
    outcome = None
    try:
        tags.parse_tag("py3--any")
    except Exception as exc:
        outcome = (type(exc).__name__, isinstance(exc, ValueError))
    assert outcome == ("InvalidTag", True)


def test_valid_compressed_interpreters_expand():
    parsed = tags.parse_tag("py2.py3-none-any")
    assert parsed == frozenset({tags.Tag("py2", "none", "any"), tags.Tag("py3", "none", "any")})
""",
        "hidden": """from packaging import tags
from packaging.utils import parse_wheel_filename


def test_compressed_empty_members_are_invalid_in_all_fields():
    outcomes = []
    for tag in (".py3-none-any", "py3-abi3..none-any", "py3-none-any."):
        try:
            tags.parse_tag(tag)
            outcomes.append(None)
        except Exception as exc:
            outcomes.append(type(exc).__name__)
    assert outcomes == ["InvalidTag", "InvalidTag", "InvalidTag"]


def test_wheel_empty_tag_error_uses_wheel_api_exception():
    outcome = None
    try:
        parse_wheel_filename("widget-2.0-py3.-none-any.whl")
    except Exception as exc:
        outcome = type(exc).__name__
    assert outcome == "InvalidWheelFilename"


def test_order_validation_does_not_replace_empty_validation():
    outcome = None
    try:
        tags.parse_tag("py3-none-.any", validate_order=True)
    except Exception as exc:
        outcome = type(exc).__name__
    assert outcome == "InvalidTag"


def test_valid_wheel_and_order_validation_remain_supported():
    name, version, build, parsed = parse_wheel_filename("widget-2.0-py3-none-any.whl")
    assert name == "widget" and str(version) == "2.0" and build == ()
    assert parsed == tags.parse_tag("py3-none-any", validate_order=True)
    outcome = None
    try:
        tags.parse_tag("py3.py2-none-any", validate_order=True)
    except Exception as exc:
        outcome = type(exc).__name__
    assert outcome == "UnsortedTagsError"
""",
        "f2p_public": ["test_empty_abi_is_invalid_tag"],
        "f2p_hidden": [
            "test_compressed_empty_members_are_invalid_in_all_fields",
            "test_wheel_empty_tag_error_uses_wheel_api_exception",
            "test_order_validation_does_not_replace_empty_validation",
        ],
        "p2p_public": ["test_valid_compressed_interpreters_expand"],
        "p2p_hidden": ["test_valid_wheel_and_order_validation_remain_supported"],
        "public_origin": "Upstream c5b253b tests/test_tags.py empty-ABI contract, plus preexisting valid compressed tag behavior.",
        "hidden_origin": "Independent leading/interior/trailing compressed empties across fields and wheel API translation, based on upstream tests/test_tags.py and tests/test_utils.py.",
        "mutant_origin": "Incomplete validation rejects only wholly empty fields and overlooks empty members of compressed fields; wheel translation is retained.",
        "mutant": {
            "keep_paths": ["src/packaging/tags.py", "src/packaging/utils.py"],
            "replacements": [
                {
                    "path": "src/packaging/tags.py",
                    "old": '        if "" in component.split("."):',
                    "new": "        if not component:",
                }
            ],
        },
    },
    "os_packaging_tag_fields_1238": {
        "task": """# Compatibility tag field-count errors

The `parse_tag` API must report a tag with too few or too many hyphen-separated
fields as `packaging.tags.InvalidTag`, rather than leaking an unrelated unpacking
exception. The diagnostic must explain the requirement for exactly three
components. Preserve valid compressed expansion, empty-member checks, ordering
checks, and the tag-count limit behavior.
""",
        "public": """from packaging.tags import parse_tag


def test_missing_platform_reports_invalid_tag():
    outcome = None
    try:
        parse_tag("py3-none")
    except Exception as exc:
        outcome = (type(exc).__name__, "exactly three components" in str(exc))
    assert outcome == ("InvalidTag", True)


def test_valid_three_fields_are_unchanged():
    parsed = parse_tag("py2.py3-none-any", limit=2)
    assert {str(tag) for tag in parsed} == {"py2-none-any", "py3-none-any"}
""",
        "hidden": """from packaging.tags import parse_tag


def test_extra_field_reports_invalid_tag():
    outcome = None
    try:
        parse_tag("cp312-abi3-any-extra", validate_order=True)
    except Exception as exc:
        outcome = (type(exc).__name__, "exactly three components" in str(exc))
    assert outcome == ("InvalidTag", True)


def test_single_field_reports_invalid_tag():
    outcome = None
    try:
        parse_tag("py3")
    except Exception as exc:
        outcome = type(exc).__name__
    assert outcome == "InvalidTag"


def test_existing_tag_validation_contracts_are_unchanged():
    outcomes = []
    for tag, kwargs in (("py3--any", {}), ("py3.py2-none-any", {"validate_order": True}), ("py2.py3-none-any", {"limit": 1})):
        try:
            parse_tag(tag, **kwargs)
            outcomes.append(None)
        except Exception as exc:
            outcomes.append(type(exc).__name__)
    assert outcomes == ["InvalidTag", "UnsortedTagsError", "TooManyTagsError"]
""",
        "f2p_public": ["test_missing_platform_reports_invalid_tag"],
        "f2p_hidden": [
            "test_extra_field_reports_invalid_tag",
            "test_single_field_reports_invalid_tag",
        ],
        "p2p_public": ["test_valid_three_fields_are_unchanged"],
        "p2p_hidden": ["test_existing_tag_validation_contracts_are_unchanged"],
        "public_origin": "Adapted from upstream f0620a9 tests/test_tags.py invalid component count case with two fields.",
        "hidden_origin": "Independent extra/single-field cases and regression checks for adjacent parse_tag validation APIs.",
        "mutant_origin": "Incomplete exception adaptation translates underfilled tags but leaves overfilled tags as bare ValueError.",
        "mutant": {
            "keep_paths": ["src/packaging/tags.py"],
            "replacements": [
                {
                    "path": "src/packaging/tags.py",
                    "old": '    except ValueError as exc:\n        raise InvalidTag(f"Tag {tag!r} must have exactly three components") from exc',
                    "new": '    except ValueError as exc:\n        if len(component_parts) > 3:\n            raise\n        raise InvalidTag(f"Tag {tag!r} must have exactly three components") from exc',
                }
            ],
        },
    },
    "os_packaging_file_scheme_1240": {
        "task": """# Directory direct URLs with file schemes

`packaging.direct_url.DirectUrl.from_dict` must accept directory URLs with a
`file` scheme regardless of scheme letter case and whether the path follows one
or three slashes. Retain the input URL in the resulting object and when serializing
with `strip_user_password=False` (default credential stripping may normalize URLs).
Directory information must still reject non-file or merely file-prefixed schemes;
archive URLs and ordinary lowercase file directory URLs must continue to work.
""",
        "public": """from packaging.direct_url import DirectUrl


def test_uppercase_file_directory_url_is_accepted():
    source = {"url": "FILE:///opt/widgets", "dir_info": {"editable": True}}
    try:
        parsed = DirectUrl.from_dict(source)
        outcome = (parsed.url, parsed.to_dict(strip_user_password=False))
    except Exception as exc:
        outcome = type(exc).__name__
    assert outcome == (source["url"], source)


def test_lowercase_file_directory_is_unchanged():
    parsed = DirectUrl.from_dict({"url": "file:///opt/widget", "dir_info": {}})
    assert parsed.url == "file:///opt/widget"
    assert parsed.dir_info is not None
""",
        "hidden": """from packaging.direct_url import DirectUrl


def test_single_slash_mixed_case_file_directory_is_accepted():
    source = {"url": "FiLe:/srv/project", "dir_info": {}}
    try:
        parsed = DirectUrl.from_dict(source)
        outcome = (parsed.url, parsed.to_dict(strip_user_password=False))
    except Exception as exc:
        outcome = type(exc).__name__
    assert outcome == (source["url"], source)


def test_other_schemes_stay_invalid_for_directories():
    outcomes = []
    for url in ("https://example.invalid/project", "file+https:///srv/project", "filex:///srv/project"):
        try:
            DirectUrl.from_dict({"url": url, "dir_info": {}})
            outcomes.append(None)
        except Exception as exc:
            outcomes.append(type(exc).__name__)
    assert outcomes == ["DirectUrlValidationError"] * 3


def test_https_archive_url_remains_valid():
    source = {"url": "https://example.invalid/widget.zip", "archive_info": {}}
    parsed = DirectUrl.from_dict(source)
    assert parsed.archive_info is not None
    assert parsed.to_dict() == source
""",
        "f2p_public": ["test_uppercase_file_directory_url_is_accepted"],
        "f2p_hidden": ["test_single_slash_mixed_case_file_directory_is_accepted"],
        "p2p_public": ["test_lowercase_file_directory_is_unchanged"],
        "p2p_hidden": [
            "test_other_schemes_stay_invalid_for_directories",
            "test_https_archive_url_remains_valid",
        ],
        "public_origin": "Adapted from upstream e80f70f tests/test_direct_url.py case-insensitive file scheme cases with independent paths.",
        "hidden_origin": "Upstream single-slash acceptance generalized to mixed case; independent non-file-scheme and archive regression boundaries.",
        "mutant_origin": "Incomplete validation accepts case variants but still requires the literal double-slash delimiter.",
        "mutant": {
            "keep_paths": ["src/packaging/direct_url.py"],
            "replacements": [
                {
                    "path": "src/packaging/direct_url.py",
                    "old": 'and urllib.parse.urlsplit(direct_url.url).scheme != "file"',
                    "new": 'and not direct_url.url.lower().startswith("file://")',
                }
            ],
        },
    },
    "os_packaging_bool_int_1244": {
        "task": """# Pylock integer and boolean types

`packaging.pylock.Pylock.from_dict` must distinguish TOML booleans from integers:
both `True` and `False` are invalid for integer-valued fields such as wheel and
sdist sizes. Reject them with `PylockValidationError` identifying the field's
context and expected/actual types. Preserve real integer sizes, omitted optional
sizes, and legitimate boolean fields such as directory editability.
""",
        "public": """from packaging.pylock import Pylock


def _wheel_data(size):
    wheel = {"name": "widget-2.0-py3-none-any.whl", "path": "./widget.whl", "hashes": {"sha256": "a" * 64}, "size": size}
    return {"lock-version": "1.0", "created-by": "contract", "packages": [{"name": "widget", "wheels": [wheel]}]}


def test_true_is_not_a_wheel_size():
    outcome = None
    try:
        Pylock.from_dict(_wheel_data(True))
    except Exception as exc:
        outcome = (type(exc).__name__, str(exc))
    assert outcome == ("PylockValidationError", "Unexpected type bool (expected int) in 'packages[0].wheels[0].size'")


def test_integer_wheel_size_is_preserved():
    result = Pylock.from_dict(_wheel_data(1024)).to_dict()
    assert result["packages"][0]["wheels"][0]["size"] == 1024
    assert type(result["packages"][0]["wheels"][0]["size"]) is int
""",
        "hidden": """from packaging.pylock import Pylock


def test_false_is_not_an_sdist_size():
    data = {"lock-version": "1.0", "created-by": "contract", "packages": [{"name": "widget", "sdist": {"name": "widget-2.0.tar.gz", "path": "./widget.tar.gz", "hashes": {"sha256": "b" * 64}, "size": False}}]}
    outcome = None
    try:
        Pylock.from_dict(data)
    except Exception as exc:
        outcome = (type(exc).__name__, str(exc))
    assert outcome == ("PylockValidationError", "Unexpected type bool (expected int) in 'packages[0].sdist.size'")


def test_optional_size_and_real_boolean_field_remain_supported():
    data = {"lock-version": "1.0", "created-by": "contract", "packages": [{"name": "widget", "directory": {"path": "./widget", "editable": False}}]}
    result = Pylock.from_dict(data).to_dict()
    assert result["packages"][0]["directory"]["editable"] is False
    archive = {"lock-version": "1.0", "created-by": "contract", "packages": [{"name": "widget", "wheels": [{"name": "widget-2.0-py3-none-any.whl", "path": "./widget.whl", "hashes": {"sha256": "c" * 64}}]}]}
    assert "size" not in Pylock.from_dict(archive).to_dict()["packages"][0]["wheels"][0]
""",
        "f2p_public": ["test_true_is_not_a_wheel_size"],
        "f2p_hidden": ["test_false_is_not_an_sdist_size"],
        "p2p_public": ["test_integer_wheel_size_is_preserved"],
        "p2p_hidden": ["test_optional_size_and_real_boolean_field_remain_supported"],
        "public_origin": "Adapted from upstream 9a11fba tests/test_pylock.py bool wheel-size rejection and context diagnostic, with independent package data.",
        "hidden_origin": "Independent False and sdist boundary exercises the same documented integer contract; optional-size and editable-boolean regressions.",
        "mutant_origin": "Incomplete boolean exclusion rejects only True, allowing False to masquerade as integer zero.",
        "mutant": {
            "keep_paths": ["src/packaging/pylock.py"],
            "replacements": [
                {
                    "path": "src/packaging/pylock.py",
                    "old": "expected_type is int and isinstance(value, bool)",
                    "new": "expected_type is int and value is True",
                }
            ],
        },
    },
    "os_packaging_nested_extra_1246": {
        "task": """# Extra names in nested markers

Marker serialization must normalize literal extra names consistently at every
parenthesis depth, whether `extra` appears on the left or right of a comparison.
Use the same canonical spelling as ordinary top-level extra comparisons, without
changing grouping or evaluation. Comparisons between two marker variables must
remain variable comparisons rather than becoming quoted string comparisons.
Preserve unrelated variables and ordinary top-level marker behavior.
""",
        "public": """from packaging.markers import Marker


def test_nested_literal_extras_are_canonicalized():
    marker = Marker('(extra == "Fast_Mode" or extra == "SLOW.Mode") and python_version >= "3"')
    assert str(marker) == '(extra == "fast-mode" or extra == "slow-mode") and python_version >= "3"'
    assert marker.evaluate({"extra": "fast-mode", "python_version": "3.12"}) is True


def test_top_level_extra_normalization_is_unchanged():
    marker = Marker('extra == "Fast_Mode"')
    assert str(marker) == 'extra == "fast-mode"'
    assert marker.evaluate({"extra": "FAST.mode"}) is True
""",
        "hidden": """from packaging.markers import Marker


def test_reversed_literal_extras_are_normalized_deeply():
    marker = Marker('(("Fast_Mode" == extra or "Other.Mode" == extra)) and os_name == "posix"')
    rendered = str(marker)
    assert '"fast-mode" == extra' in rendered
    assert '"other-mode" == extra' in rendered
    assert "Fast_Mode" not in rendered and "Other.Mode" not in rendered
    assert marker.evaluate({"extra": "fast-mode", "os_name": "posix"}) is True


def test_variable_operands_remain_variables():
    assert str(Marker("extra == os_name")) == "extra == os_name"
    assert str(Marker("os_name == extra")) == "os_name == extra"


def test_non_extra_literal_case_and_logic_are_preserved():
    marker = Marker('(os_name == "UPPER_Case" or os_name == "nt") and python_version >= "3"')
    assert '"UPPER_Case"' in str(marker)
    assert marker.evaluate({"os_name": "UPPER_Case", "python_version": "3.12"}) is True
    assert marker.evaluate({"os_name": "posix", "python_version": "3.12"}) is False
""",
        "f2p_public": ["test_nested_literal_extras_are_canonicalized"],
        "f2p_hidden": [
            "test_reversed_literal_extras_are_normalized_deeply",
            "test_variable_operands_remain_variables",
        ],
        "p2p_public": ["test_top_level_extra_normalization_is_unchanged"],
        "p2p_hidden": ["test_non_extra_literal_case_and_logic_are_preserved"],
        "public_origin": "Adapted from upstream 0726512 tests/test_markers.py nested normalization, with independent extra names.",
        "hidden_origin": "Independent reversed/deep literal boundary plus upstream variable-vs-variable preservation; non-extra case regression.",
        "mutant_origin": "Incomplete recursive normalization handles literal extras on the right of extra but omits the reversed operand orientation.",
        "mutant": {
            "keep_paths": ["src/packaging/markers.py"],
            "replacements": [
                {
                    "path": "src/packaging/markers.py",
                    "old": '    elif isinstance(rhs, Variable) and rhs.value == "extra" and isinstance(lhs, Value):\n        normalized_extra = canonicalize_name(lhs.value)\n        lhs = Value(normalized_extra)\n',
                    "new": "",
                }
            ],
        },
    },
    "os_packaging_literal_errors_1249": {
        "task": """# Errors for malformed quoted marker values

Malformed quoted values in a marker must be reported as
`packaging.markers.InvalidMarker`, and malformed marker values within a
requirement as `packaging.requirements.InvalidRequirement`. This covers either
operand position and malformed escape sequences or unterminated Python-style
literal contents. Diagnostics must identify an invalid quoted string and retain
the source and a caret location. Preserve valid quoted values and other parser
error classifications.
""",
        "public": r"""from packaging.markers import Marker


def test_malformed_right_literal_is_invalid_marker():
    source = r'os_name == "\x"'
    outcome = None
    try:
        Marker(source)
    except Exception as exc:
        outcome = (type(exc).__name__, "Invalid quoted string" in str(exc), source in str(exc), "^" in str(exc))
    assert outcome == ("InvalidMarker", True, True, True)


def test_valid_marker_and_existing_syntax_error_are_unchanged():
    marker = Marker('os_name == "posix"')
    assert marker.evaluate({"os_name": "posix"}) is True
    assert marker.evaluate({"os_name": "nt"}) is False
    outcome = None
    try:
        Marker("os_name ==")
    except Exception as exc:
        outcome = type(exc).__name__
    assert outcome == "InvalidMarker"
""",
        "hidden": r"""from packaging.markers import Marker
from packaging.requirements import Requirement


def test_malformed_left_literal_is_invalid_marker():
    source = r'"\x" == os_name'
    outcome = None
    try:
        Marker(source)
    except Exception as exc:
        outcome = (type(exc).__name__, "Invalid quoted string" in str(exc), source in str(exc), "^" in str(exc))
    assert outcome == ("InvalidMarker", True, True, True)


def test_malformed_requirement_marker_is_invalid_requirement():
    source = 'widget; os_name == "C:' + chr(92) + '"'
    outcome = None
    try:
        Requirement(source)
    except Exception as exc:
        outcome = (type(exc).__name__, "Invalid quoted string" in str(exc), source in str(exc), "^" in str(exc))
    assert outcome == ("InvalidRequirement", True, True, True)


def test_valid_requirement_literal_remains_supported():
    req = Requirement('widget>=2; os_name == "posix"')
    assert req.name == "widget"
    assert str(req.specifier) == ">=2"
    assert req.marker.evaluate({"os_name": "posix"}) is True
""",
        "f2p_public": ["test_malformed_right_literal_is_invalid_marker"],
        "f2p_hidden": [
            "test_malformed_left_literal_is_invalid_marker",
            "test_malformed_requirement_marker_is_invalid_requirement",
        ],
        "p2p_public": ["test_valid_marker_and_existing_syntax_error_are_unchanged"],
        "p2p_hidden": ["test_valid_requirement_literal_remains_supported"],
        "public_origin": "Adapted from upstream 6115033 tests/test_markers.py malformed hexadecimal escape diagnostic.",
        "hidden_origin": "Independent left-operand boundary and upstream trailing-backslash requirement case from tests/test_requirements.py; source diagnostics checked without overfitting exact spacing.",
        "mutant_origin": "Incomplete error adaptation only wraps literals after the start of the expression, overlooking a malformed leftmost literal.",
        "mutant": {
            "keep_paths": ["src/packaging/_parser.py"],
            "replacements": [
                {
                    "path": "src/packaging/_parser.py",
                    "old": "        except (SyntaxError, ValueError) as exc:\n            raise ParserSyntaxError(",
                    "new": "        except (SyntaxError, ValueError) as exc:\n            if token.position == 0:\n                raise\n            raise ParserSyntaxError(",
                }
            ],
        },
    },
    "os_packaging_license_with_1266": {
        "task": """# SPDX exception attachment and license references

`packaging.licenses.canonicalize_license_expression` must reject invalid SPDX
exception attachments with `InvalidLicenseExpression`: `WITH` attaches one
exception to a license identifier, not to a parenthesized group or to an already
attached exception. A custom `LicenseRef-` must have a nonempty valid identifier;
an empty identifier is invalid. Preserve ordinary license normalization, valid
exception attachments, nonempty license references, and boolean grouping.
""",
        "public": """from packaging.licenses import canonicalize_license_expression


def test_exception_cannot_attach_to_parenthesized_license():
    outcome = None
    try:
        canonicalize_license_expression("(MIT) WITH Classpath-exception-2.0")
    except Exception as exc:
        outcome = type(exc).__name__
    assert outcome == "InvalidLicenseExpression"


def test_valid_license_and_exception_normalize():
    assert canonicalize_license_expression("mit with classpath-exception-2.0") == "MIT WITH Classpath-exception-2.0"
    assert canonicalize_license_expression("mit and apache-2.0") == "MIT AND Apache-2.0"
""",
        "hidden": """from packaging.licenses import canonicalize_license_expression


def test_empty_license_reference_is_rejected():
    outcome = None
    try:
        canonicalize_license_expression("LicenseRef-")
    except Exception as exc:
        outcome = type(exc).__name__
    assert outcome == "InvalidLicenseExpression"


def test_repeated_exception_and_group_attachment_are_rejected():
    outcomes = []
    for source in ("MIT WITH Classpath-exception-2.0 WITH GCC-exception-3.1", "(Apache-2.0 OR MIT) WITH Classpath-exception-2.0"):
        try:
            canonicalize_license_expression(source)
            outcomes.append(None)
        except Exception as exc:
            outcomes.append(type(exc).__name__)
    assert outcomes == ["InvalidLicenseExpression", "InvalidLicenseExpression"]


def test_nonempty_reference_and_grouping_remain_valid():
    assert canonicalize_license_expression("LicenseRef-Custom.42-Internal") == "LicenseRef-Custom.42-Internal"
    assert canonicalize_license_expression("mit or (apache-2.0 and bsd-2-clause)") == "MIT OR (Apache-2.0 AND BSD-2-Clause)"
""",
        "f2p_public": ["test_exception_cannot_attach_to_parenthesized_license"],
        "f2p_hidden": [
            "test_empty_license_reference_is_rejected",
            "test_repeated_exception_and_group_attachment_are_rejected",
        ],
        "p2p_public": ["test_valid_license_and_exception_normalize"],
        "p2p_hidden": ["test_nonempty_reference_and_grouping_remain_valid"],
        "public_origin": "Upstream 0cc1cc8 tests/test_licenses.py invalid grouped WITH form; stable SPDX normalization examples.",
        "hidden_origin": "Upstream empty LicenseRef and repeated WITH contracts, independent grouped ordering and valid reference identifier.",
        "mutant_origin": "Incomplete patch enforces WITH grammar but retains an identifier pattern that permits zero-length LicenseRef suffixes.",
        "mutant": {
            "keep_paths": ["src/packaging/licenses/__init__.py"],
            "replacements": [
                {
                    "path": "src/packaging/licenses/__init__.py",
                    "old": 'license_ref_allowed = re.compile("^[A-Za-z0-9.-]+$")',
                    "new": 'license_ref_allowed = re.compile("^[A-Za-z0-9.-]*$")',
                }
            ],
        },
    },
    "os_packaging_missing_env_1276": {
        "task": """# Missing marker environment names

When marker evaluation references a name absent from the selected evaluation
context, raise `packaging.markers.UndefinedEnvironmentName` with the missing key
as its exception argument. It must remain catchable as `KeyError` for backward
compatibility. Apply this consistently to variables on either side of the marker
operator and to context-specific names such as `extra`, `extras`, and dependency
groups. Preserve evaluation when names are supplied and the defaults of metadata
and lock-file contexts.
""",
        "public": """from packaging.markers import Marker


def test_missing_right_environment_name_uses_public_exception():
    outcome = None
    try:
        Marker('"docs" in extras').evaluate()
    except Exception as exc:
        outcome = (type(exc).__name__, exc.args, isinstance(exc, KeyError))
    assert outcome == ("UndefinedEnvironmentName", ("extras",), True)


def test_metadata_extra_default_is_unchanged():
    assert Marker('extra == ""').evaluate() is True
    assert Marker('extra == "docs"').evaluate() is False
""",
        "hidden": """from packaging.markers import Marker


def test_missing_left_environment_name_uses_public_exception():
    outcome = None
    try:
        Marker('extra == "docs"').evaluate(context="requirement")
    except Exception as exc:
        outcome = (type(exc).__name__, exc.args, isinstance(exc, KeyError))
    assert outcome == ("UndefinedEnvironmentName", ("extra",), True)


def test_missing_dependency_group_uses_public_exception():
    outcome = None
    try:
        Marker('"build" in dependency_groups').evaluate(context="requirement")
    except Exception as exc:
        outcome = (type(exc).__name__, exc.args, isinstance(exc, KeyError))
    assert outcome == ("UndefinedEnvironmentName", ("dependency_groups",), True)


def test_context_defaults_and_supplied_names_are_unchanged():
    marker = Marker('"docs" in extras')
    assert marker.evaluate(context="lock_file") is False
    assert marker.evaluate({"extras": {"docs"}}, context="requirement") is True
    assert Marker('extra == "docs"').evaluate({"extra": "docs"}, context="requirement") is True
""",
        "f2p_public": ["test_missing_right_environment_name_uses_public_exception"],
        "f2p_hidden": [
            "test_missing_left_environment_name_uses_public_exception",
            "test_missing_dependency_group_uses_public_exception",
        ],
        "p2p_public": ["test_metadata_extra_default_is_unchanged"],
        "p2p_hidden": ["test_context_defaults_and_supplied_names_are_unchanged"],
        "public_origin": "Adapted from upstream b19df94 tests/test_markers.py missing extras exception and KeyError compatibility.",
        "hidden_origin": "Independent opposite-operand and dependency-group/context boundaries derived from evaluate's documented environment contract.",
        "mutant_origin": "Incomplete lookup adaptation handles right-side environment variables but keeps the old bare lookup for left-side variables.",
        "mutant": {
            "keep_paths": ["src/packaging/markers.py"],
            "replacements": [
                {
                    "path": "src/packaging/markers.py",
                    "old": "                lhs_value = _lookup_environment(environment, environment_key)",
                    "new": "                lhs_value = environment[environment_key]",
                }
            ],
        },
    },
    "os_packaging_nested_group_1316": {
        "task": """# Marker round-trip grouping

`str(packaging.markers.Marker(...))` must preserve boolean meaning when parsed
again. Redundant nested parentheses must not lose the grouping needed by mixed
`and`/`or` expressions. This applies to groups on either side of another
expression and to arbitrary redundant nesting depth. Preserve simple marker
serialization, ordinary grouping, and evaluation across true and false branches;
redundant outermost parentheses need not be retained literally.
""",
        "public": """from packaging.markers import Marker


def test_double_nested_group_roundtrip_preserves_precedence():
    original = Marker('python_version < "3.10" and ((sys_platform == "linux" or sys_platform == "darwin"))')
    try:
        restored = Marker(str(original))
        env = {"python_version": "3.12", "sys_platform": "darwin"}
        outcome = (original.evaluate(env), restored.evaluate(env))
    except Exception as exc:
        outcome = type(exc).__name__
    assert outcome == (False, False)


def test_simple_marker_serialization_and_evaluation_are_unchanged():
    marker = Marker('os_name == "posix" and python_version >= "3.9"')
    assert str(marker) == 'os_name == "posix" and python_version >= "3.9"'
    assert marker.evaluate({"os_name": "posix", "python_version": "3.12"}) is True
    assert marker.evaluate({"os_name": "nt", "python_version": "3.12"}) is False
""",
        "hidden": """from packaging.markers import Marker


def test_deeper_group_roundtrip_preserves_precedence():
    original = Marker('python_version < "3.11" and (((sys_platform == "linux" or sys_platform == "darwin")))')
    try:
        restored = Marker(str(original))
        envs = ({"python_version": "3.12", "sys_platform": "darwin"}, {"python_version": "3.10", "sys_platform": "linux"}, {"python_version": "3.10", "sys_platform": "win32"})
        outcome = [(original.evaluate(env), restored.evaluate(env)) for env in envs]
    except Exception as exc:
        outcome = type(exc).__name__
    assert outcome == [(False, False), (True, True), (False, False)]


def test_left_nested_group_roundtrip_preserves_precedence():
    original = Marker('((os_name == "posix" or os_name == "nt")) and python_version < "3"')
    try:
        restored = Marker(str(original))
        env = {"os_name": "posix", "python_version": "3.12"}
        outcome = (original.evaluate(env), restored.evaluate(env))
    except Exception as exc:
        outcome = type(exc).__name__
    assert outcome == (False, False)


def test_ordinary_group_and_outer_parentheses_are_unchanged():
    source = '(os_name == "posix" or os_name == "nt") and python_version >= "3"'
    marker = Marker(source)
    assert str(marker) == source
    assert str(Marker('((os_name == "posix"))')) == 'os_name == "posix"'
    assert marker.evaluate({"os_name": "nt", "python_version": "3.12"}) is True
""",
        "f2p_public": ["test_double_nested_group_roundtrip_preserves_precedence"],
        "f2p_hidden": [
            "test_deeper_group_roundtrip_preserves_precedence",
            "test_left_nested_group_roundtrip_preserves_precedence",
        ],
        "p2p_public": ["test_simple_marker_serialization_and_evaluation_are_unchanged"],
        "p2p_hidden": ["test_ordinary_group_and_outer_parentheses_are_unchanged"],
        "public_origin": "Adapted from upstream 0a85b41 tests/test_markers.py nested group precedence regression with explicit semantic expectation.",
        "hidden_origin": "Independent deeper and left-side group boundaries, with true/false environments and stable ordinary/outer grouping.",
        "mutant_origin": "Incomplete context propagation handles one redundant wrapper but resets context when another singleton wrapper remains.",
        "mutant": {
            "keep_paths": ["src/packaging/markers.py"],
            "replacements": [
                {
                    "path": "src/packaging/markers.py",
                    "old": "        return _format_marker(marker[0], first=first)",
                    "new": "        return _format_marker(marker[0], first=first if len(marker[0]) > 1 else True)",
                }
            ],
        },
    },
    "os_packaging_invalid_spec_1332": {
        "task": """# Requirement validation error boundary

Malformed version-specifier lists passed to
`packaging.requirements.Requirement` must raise `InvalidRequirement`, preserving
the useful invalid-specifier diagnostic rather than exposing `InvalidSpecifier`.
This includes arbitrary-equality lists with one or multiple invalid comma-separated
members and requirements with extras or markers. Restoring such an invalid
requirement through `Requirement.__setstate__` must retain its existing `TypeError`
boundary. Preserve valid requirements, arbitrary equality values, specifier
membership, and valid serialized-state restoration.
""",
        "public": """from packaging.requirements import Requirement


def test_invalid_specifier_list_uses_requirement_exception():
    outcome = None
    try:
        Requirement("widget===alpha,beta")
    except Exception as exc:
        outcome = (type(exc).__name__, "Invalid specifier:" in str(exc), "beta" in str(exc))
    assert outcome == ("InvalidRequirement", True, True)


def test_valid_constraints_and_arbitrary_equality_remain_supported():
    regular = Requirement("widget>=2,<3")
    assert "2.5" in regular.specifier
    assert "3.1" not in regular.specifier
    assert str(Requirement("widget===buildlabel")) == "widget===buildlabel"
""",
        "hidden": """from packaging.requirements import Requirement


def test_longer_invalid_list_with_extras_uses_requirement_exception():
    outcome = None
    try:
        Requirement('widget[fast]===alpha,beta,gamma; os_name == "posix"')
    except Exception as exc:
        outcome = (type(exc).__name__, "Invalid specifier:" in str(exc))
    assert outcome == ("InvalidRequirement", True)


def test_invalid_serialized_requirement_stays_type_error():
    instance = Requirement.__new__(Requirement)
    outcome = None
    try:
        instance.__setstate__("widget===alpha,beta")
    except Exception as exc:
        outcome = (type(exc).__name__, "Cannot restore Requirement" in str(exc))
    assert outcome == ("TypeError", True)


def test_valid_serialized_requirement_restores_fields():
    instance = Requirement.__new__(Requirement)
    instance.__setstate__(('Widget[fast]>=2; os_name == "posix"', True))
    assert instance.name == "Widget"
    assert instance.extras == {"fast"}
    assert instance.specifier.prereleases is True
    assert instance.marker.evaluate({"os_name": "posix"}) is True
""",
        "f2p_public": ["test_invalid_specifier_list_uses_requirement_exception"],
        "f2p_hidden": [
            "test_longer_invalid_list_with_extras_uses_requirement_exception",
            "test_invalid_serialized_requirement_stays_type_error",
        ],
        "p2p_public": ["test_valid_constraints_and_arbitrary_equality_remain_supported"],
        "p2p_hidden": ["test_valid_serialized_requirement_restores_fields"],
        "public_origin": "Adapted from upstream fe18f13 tests/test_requirements.py malformed arbitrary-equality list; independent values.",
        "hidden_origin": "Independent longer-list/decorated-requirement boundary and upstream serialized-state rejection, plus valid state restoration.",
        "mutant_origin": "Incomplete exception adaptation handles a single comma but lets longer malformed lists escape as InvalidSpecifier.",
        "mutant": {
            "keep_paths": ["src/packaging/requirements.py"],
            "replacements": [
                {
                    "path": "src/packaging/requirements.py",
                    "old": "        except InvalidSpecifier as e:\n            raise InvalidRequirement(str(e)) from e",
                    "new": '        except InvalidSpecifier as e:\n            if parsed.specifier.count(",") > 1:\n                raise\n            raise InvalidRequirement(str(e)) from e',
                }
            ],
        },
    },
}
