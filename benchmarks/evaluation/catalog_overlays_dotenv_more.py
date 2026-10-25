"""Static catalog overlays; embedded tests execute only in the Docker runner.

Materialization paths are pyrepair_public_tests/test_repro.py and
hidden_tests/test_contract.py. Origins refer to the pinned source snapshots.
"""

DOTENV_MORE_OVERLAYS = {
    "os_dotenv_bom_640": {
        "task": (
            "# Parse UTF-8 BOM-prefixed dotenv input\n\n"
            "A single Unicode BOM at the very beginning of a text stream must not "
            "become part of the first dotenv key. This applies to ordinary, quoted "
            "and export-prefixed bindings, including multiline input. Binding "
            "original text and line numbers should describe the input after this "
            "initial marker. Preserve BOM characters inside keys and values, and "
            "preserve existing parsing of comments and input without a BOM.\n"
        ),
        "public": r"""from io import StringIO
from dotenv.parser import parse_stream


def test_initial_bom_is_not_part_of_key():
    try:
        bindings = list(parse_stream(StringIO("\ufeffA=one\nB=two\n")))
        actual = [(b.key, b.value, b.original.string, b.original.line, b.error) for b in bindings]
    except Exception as exc:
        actual = (type(exc).__name__, str(exc))
    assert actual == [("A", "one", "A=one\n", 1, False), ("B", "two", "B=two\n", 2, False)]


def test_plain_bindings_and_comments():
    bindings = list(parse_stream(StringIO("# note\nA='one two'\n")))
    assert [(b.key, b.value, b.error) for b in bindings] == [(None, None, False), ("A", "one two", False)]
""",
        "hidden": r"""from io import StringIO
from dotenv.parser import parse_stream


def test_bom_before_export_and_quoted_key():
    actual = []
    for text in ("\ufeffexport A=one\n", "\ufeff'A'=one\n"):
        try:
            actual.append([(b.key, b.value, b.error) for b in parse_stream(StringIO(text))])
        except Exception as exc:
            actual.append((type(exc).__name__, str(exc)))
    assert actual == [[("A", "one", False)], [("A", "one", False)]]


def test_noninitial_bom_is_data():
    bindings = list(parse_stream(StringIO("A=left\ufeffright\nB\ufeff=two\n")))
    assert [(b.key, b.value, b.error) for b in bindings] == [("A", "left\ufeffright", False), ("B\ufeff", "two", False)]
""",
        "f2p_public": ["test_initial_bom_is_not_part_of_key"],
        "f2p_hidden": ["test_bom_before_export_and_quoted_key"],
        "p2p_public": ["test_plain_bindings_and_comments"],
        "p2p_hidden": ["test_noninitial_bom_is_data"],
        "public_origin": "Adapted pinned python-dotenv PR #640 tests/test_parser.py BOM bindings, with local plain-input regression.",
        "hidden_origin": "Project-authored grammar-prefix and noninitial-BOM boundaries derived from pinned parser.py and PR #640 contract.",
        "mutant_origin": "Artificial incomplete repair: remove an initial BOM only before a plain word key, overlooking quoted and export-prefixed bindings.",
        "mutant": {
            "keep_paths": ["src/dotenv/parser.py"],
            "replacements": [
                {
                    "path": "src/dotenv/parser.py",
                    "old": 'stream.read().removeprefix("\\ufeff")',
                    "new": 're.sub(r"^\\ufeff(?=\\w+=)", "", stream.read())',
                }
            ],
        },
    },
    "os_dotenv_backslash_680": {
        "task": (
            "# Preserve backslashes through dotenv writes and reads\n\n"
            "Values written using set_key with always or auto quoting must round-trip "
            "through dotenv_values/get_key, including repeated and trailing backslashes "
            "and combinations of backslashes and apostrophes. A quoted value ending "
            "with an escaped backslash must not absorb following bindings; this also "
            "applies when parsing double-quoted input. Preserve unrelated bindings, "
            "ordinary quote escaping, multiline values and quote_mode='never'.\n"
        ),
        "public": r"""from dotenv import dotenv_values, set_key


def test_repeated_backslashes_round_trip(tmp_path):
    path = tmp_path / "config.txt"
    path.write_text("A=old\nTAIL=sentinel\n", encoding="utf-8")
    value = r"\\server\share"
    try:
        status = set_key(path, "A", value)
        actual = dict(dotenv_values(path, interpolate=False))
    except Exception as exc:
        status, actual = None, (type(exc).__name__, str(exc))
    assert status == (True, "A", value)
    assert actual == {"A": value, "TAIL": "sentinel"}


def test_plain_and_never_quoted_values(tmp_path):
    path = tmp_path / "config.txt"
    set_key(path, "A", "ordinary")
    set_key(path, "B", "two words", quote_mode="never")
    assert dict(dotenv_values(path, interpolate=False)) == {"A": "ordinary", "B": "two words"}
""",
        "hidden": r"""from io import StringIO
from dotenv import dotenv_values, get_key, set_key


def test_trailing_backslash_and_apostrophe_round_trip(tmp_path):
    actual = []
    values = ["folder" + "\\", "a\\'b", "line\none\\", "\\\\"]
    for mode in ("always", "auto"):
        for index, value in enumerate(values):
            path = tmp_path / (mode + str(index) + ".txt")
            path.write_text("A=old\nTAIL=sentinel\n", encoding="utf-8")
            try:
                set_key(path, "A", value, quote_mode=mode)
                actual.append((get_key(path, "A"), get_key(path, "TAIL")))
            except Exception as exc:
                actual.append((type(exc).__name__, str(exc)))
    assert actual == [(v, "sentinel") for mode in ("always", "auto") for v in values]


def test_double_quote_backslash_does_not_swallow_next_line():
    text = 'A="tail' + '\\' * 2 + '"\nB="next"\n'
    try:
        actual = dict(dotenv_values(stream=StringIO(text), interpolate=False))
    except Exception as exc:
        actual = (type(exc).__name__, str(exc))
    assert actual == {"A": "tail\\", "B": "next"}


def test_existing_quote_and_multiline_parsing():
    text = "A='it\\'s'\nB=\"line\none\"\nC='literal\\n'\n"
    assert dict(dotenv_values(stream=StringIO(text), interpolate=False)) == {"A": "it's", "B": "line\none", "C": "literal\\n"}
""",
        "f2p_public": ["test_repeated_backslashes_round_trip"],
        "f2p_hidden": [
            "test_trailing_backslash_and_apostrophe_round_trip",
            "test_double_quote_backslash_does_not_swallow_next_line",
        ],
        "p2p_public": ["test_plain_and_never_quoted_values"],
        "p2p_hidden": ["test_existing_quote_and_multiline_parsing"],
        "public_origin": "Adapted pinned PR #680 tests/test_main.py test_set_key_round_trips, using a preserved following binding.",
        "hidden_origin": "Adapted PR #680 trailing-backslash single/double-quote parser cases and local auto-quote/multiline boundaries.",
        "mutant_origin": "Artificial incomplete repair: retain writer escaping in main.py but restore buggy quoted-value parser.",
        "mutant": {"keep_paths": ["src/dotenv/main.py"], "replacements": []},
    },
    "os_dotenv_override_698": {
        "task": (
            "# Respect dotenv run override policy during expansion\n\n"
            "dotenv run --no-override must resolve interpolated values using existing "
            "environment values in preference to earlier file bindings. Existing empty "
            "strings are values, not absent variables, including in an otherwise empty "
            "environment. Derived values and chained references must consistently "
            "reflect that policy. Default/--override execution must continue to prefer "
            "file values. Preserve command arguments, inherited environment values and "
            "the omission of bare keys from the command environment.\n"
        ),
        "public": r"""from types import SimpleNamespace
from click.testing import CliRunner
import dotenv.cli as dotenv_cli


def _run(tmp_path, monkeypatch, text, env, options):
    path = tmp_path / "config.txt"
    path.write_text(text, encoding="utf-8")
    calls = []
    def capture(file, args, env):
        calls.append((file, list(args), dict(env)))
    monkeypatch.setattr(dotenv_cli.os, "environ", dict(env))
    monkeypatch.setattr(dotenv_cli.os, "execvpe", capture)
    monkeypatch.setattr(dotenv_cli, "sys", SimpleNamespace(platform="linux"))
    result = CliRunner().invoke(dotenv_cli.cli, ["--file", str(path), "run", *options, "example-command", "--flag"])
    return result, calls


def test_no_override_expansion_uses_environment(tmp_path, monkeypatch):
    result, calls = _run(tmp_path, monkeypatch, "BASE=file\nDERIVED=${BASE}/tail\n", {"BASE": "parent"}, ["--no-override"])
    assert result.exit_code == 0, repr(result.exception)
    assert calls == [("example-command", ["example-command", "--flag"], {"BASE": "parent", "DERIVED": "parent/tail"})]


def test_override_still_prefers_file(tmp_path, monkeypatch):
    result, calls = _run(tmp_path, monkeypatch, "BASE=file\nDERIVED=${BASE}/tail\nBARE\n", {"BASE": "parent", "KEEP": "yes"}, ["--override"])
    assert result.exit_code == 0, repr(result.exception)
    assert calls == [("example-command", ["example-command", "--flag"], {"BASE": "file", "DERIVED": "file/tail", "KEEP": "yes"})]
""",
        "hidden": r"""from types import SimpleNamespace
from click.testing import CliRunner
import dotenv.cli as dotenv_cli


def _run(tmp_path, monkeypatch, text, env, options):
    path = tmp_path / "config.txt"
    path.write_text(text, encoding="utf-8")
    calls = []
    def capture(file, args, env):
        calls.append((file, list(args), dict(env)))
    monkeypatch.setattr(dotenv_cli.os, "environ", dict(env))
    monkeypatch.setattr(dotenv_cli.os, "execvpe", capture)
    monkeypatch.setattr(dotenv_cli, "sys", SimpleNamespace(platform="linux"))
    result = CliRunner().invoke(dotenv_cli.cli, ["--file", str(path), "run", *options, "example-command", "arg"])
    return result, calls


def test_empty_existing_value_controls_chained_expansion(tmp_path, monkeypatch):
    result, calls = _run(tmp_path, monkeypatch, "BASE=file\nDERIVED=${BASE}/tail\nCHAIN=${DERIVED}/end\n", {"BASE": ""}, ["--no-override"])
    assert result.exit_code == 0, repr(result.exception)
    assert calls == [("example-command", ["example-command", "arg"], {"BASE": "", "DERIVED": "/tail", "CHAIN": "/tail/end"})]


def test_existing_derived_variable_wins_during_chain(tmp_path, monkeypatch):
    result, calls = _run(tmp_path, monkeypatch, "BASE=file\nDERIVED=${BASE}/tail\nCHAIN=${DERIVED}/end\n", {"BASE": "host", "DERIVED": "existing"}, ["--no-override"])
    assert result.exit_code == 0, repr(result.exception)
    assert calls[0][2] == {"BASE": "host", "DERIVED": "existing", "CHAIN": "existing/end"}


def test_default_override_and_missing_environment(tmp_path, monkeypatch):
    result, calls = _run(tmp_path, monkeypatch, "BASE=file\nDERIVED=${BASE}/tail\nBARE\n", {}, [])
    assert result.exit_code == 0, repr(result.exception)
    assert calls[0][2] == {"BASE": "file", "DERIVED": "file/tail"}
""",
        "f2p_public": ["test_no_override_expansion_uses_environment"],
        "f2p_hidden": [
            "test_empty_existing_value_controls_chained_expansion",
            "test_existing_derived_variable_wins_during_chain",
        ],
        "p2p_public": ["test_override_still_prefers_file"],
        "p2p_hidden": ["test_default_override_and_missing_environment"],
        "public_origin": "Adapted pinned PR #698 test_run_interpolation_respects_override; actual CLI/run_command with only execvpe intercepted.",
        "hidden_origin": "PR #698 empty-environment-value case extended to chained references; local inherited-variable/default-policy regressions.",
        "mutant_origin": "Artificial incomplete repair: regard an environment whose values are all empty as absent during interpolation.",
        "mutant": {
            "keep_paths": ["src/dotenv/cli.py"],
            "replacements": [
                {
                    "path": "src/dotenv/cli.py",
                    "old": 'DotEnv(file, override=override, encoding="utf-8")',
                    "new": 'DotEnv(file, override=(override or not any(os.environ.values())), encoding="utf-8")',
                }
            ],
        },
    },
    "os_dotenv_empty_get_700": {
        "task": (
            "# Distinguish empty values from missing dotenv keys\n\n"
            "The dotenv get CLI must exit successfully and print one newline for "
            "a key whose parsed value is an empty string, whether unquoted, quoted "
            "or produced by interpolation. Missing keys and bare keys without an "
            "equals sign still fail with exit status 1 and no value output. Preserve "
            "nonempty-value output and the existing file-opening error behavior.\n"
        ),
        "public": r"""from click.testing import CliRunner
from dotenv.cli import cli


def test_get_empty_assignment_succeeds(tmp_path):
    path = tmp_path / "config.txt"
    path.write_text("A=\n", encoding="utf-8")
    result = CliRunner().invoke(cli, ["--file", str(path), "get", "A"])
    assert (result.exit_code, result.output) == (0, "\n")


def test_get_nonempty_assignment(tmp_path):
    path = tmp_path / "config.txt"
    path.write_text("A=value\n", encoding="utf-8")
    result = CliRunner().invoke(cli, ["--file", str(path), "get", "A"])
    assert (result.exit_code, result.output) == (0, "value\n")
""",
        "hidden": r"""from click.testing import CliRunner
from dotenv.cli import cli


def test_get_quoted_and_expanded_empty_values(tmp_path, monkeypatch):
    monkeypatch.delenv("PYREPAIR_EMPTY_VALUE", raising=False)
    path = tmp_path / "config.txt"
    path.write_text("S=''\nD=\"\"\nE=${PYREPAIR_EMPTY_VALUE:-}\n", encoding="utf-8")
    actual = []
    for key in ("S", "D", "E"):
        result = CliRunner().invoke(cli, ["--file", str(path), "get", key])
        actual.append((result.exit_code, result.output))
    assert actual == [(0, "\n"), (0, "\n"), (0, "\n")]


def test_bare_and_missing_keys_still_fail(tmp_path):
    path = tmp_path / "config.txt"
    path.write_text("BARE\nZERO=0\n", encoding="utf-8")
    actual = []
    for key in ("BARE", "MISSING", "ZERO"):
        result = CliRunner().invoke(cli, ["--file", str(path), "get", key])
        actual.append((result.exit_code, result.output))
    assert actual == [(1, ""), (1, ""), (0, "0\n")]


def test_missing_file_keeps_open_error(tmp_path):
    result = CliRunner().invoke(cli, ["--file", str(tmp_path / "absent.txt"), "get", "A"])
    assert result.exit_code == 2
    assert "Error opening env file" in result.output
""",
        "f2p_public": ["test_get_empty_assignment_succeeds"],
        "f2p_hidden": ["test_get_quoted_and_expanded_empty_values"],
        "p2p_public": ["test_get_nonempty_assignment"],
        "p2p_hidden": [
            "test_bare_and_missing_keys_still_fail",
            "test_missing_file_keeps_open_error",
        ],
        "public_origin": "Adapted pinned PR #700 test_get_empty_string_value and existing nonempty-value test using CliRunner.",
        "hidden_origin": "Project-authored quoted/interpolated empty-value boundaries plus pinned bare/missing/file-error regressions.",
        "mutant_origin": "Artificial incomplete repair: accept literal empty values but disable interpolation, leaving expanded empty values unresolved.",
        "mutant": {
            "keep_paths": ["src/dotenv/cli.py"],
            "replacements": [
                {
                    "path": "src/dotenv/cli.py",
                    "old": "values = dotenv_values(stream=stream)\n\n    # Empty strings are valid values;",
                    "new": "values = dotenv_values(stream=stream, interpolate=False)\n\n    # Empty strings are valid values;",
                }
            ],
        },
    },
    "os_dotenv_missing_command_606": {
        "task": (
            "# Report missing dotenv run commands cleanly\n\n"
            "When process launch reports FileNotFoundError, dotenv run must exit "
            "with status 1 and emit 'Command not found: <command>' to stderr, "
            "without leaking the launch exception. This contract applies both to "
            "POSIX exec and the Windows Popen path. Preserve command arguments and "
            "environment merging, Windows child exit codes, and existing no-command "
            "and missing-env-file diagnostics.\n"
        ),
        "public": r"""import io
import sys
from types import SimpleNamespace
from click.testing import CliRunner
import dotenv.cli as dotenv_cli


def test_posix_missing_command_is_clean_cli_failure(tmp_path, monkeypatch):
    path = tmp_path / "config.txt"
    path.write_text("EXTRA=value\n", encoding="utf-8")
    errors = io.StringIO()
    calls = []
    def missing(file, args, env):
        calls.append((file, list(args), env.get("EXTRA")))
        raise FileNotFoundError(file)
    monkeypatch.setattr(dotenv_cli.os, "execvpe", missing)
    monkeypatch.setattr(dotenv_cli, "sys", SimpleNamespace(platform="linux", stderr=errors, exit=sys.exit))
    result = CliRunner().invoke(dotenv_cli.cli, ["--file", str(path), "run", "missing-example", "arg"])
    assert (result.exit_code, type(result.exception).__name__, errors.getvalue()) == (1, "SystemExit", "Command not found: missing-example\n")
    assert calls == [("missing-example", ["missing-example", "arg"], "value")]


def test_no_command_diagnostic(tmp_path):
    path = tmp_path / "config.txt"
    path.write_text("", encoding="utf-8")
    result = CliRunner().invoke(dotenv_cli.cli, ["--file", str(path), "run"])
    assert (result.exit_code, result.output) == (1, "No command given.\n")
""",
        "hidden": r"""import io
import sys
from types import SimpleNamespace
from click.testing import CliRunner
import dotenv.cli as dotenv_cli


def test_windows_missing_command_is_clean_cli_failure(tmp_path, monkeypatch):
    path = tmp_path / "config.txt"
    path.write_text("EXTRA=value\n", encoding="utf-8")
    errors = io.StringIO()
    calls = []
    def missing(command, **kwargs):
        calls.append((list(command), kwargs["shell"], kwargs["env"].get("EXTRA")))
        raise FileNotFoundError(command[0])
    monkeypatch.setattr(dotenv_cli, "Popen", missing, raising=False)
    monkeypatch.setattr(dotenv_cli, "sys", SimpleNamespace(platform="win32", stderr=errors, exit=sys.exit))
    result = CliRunner().invoke(dotenv_cli.cli, ["--file", str(path), "run", "missing-other", "--flag"])
    assert (result.exit_code, type(result.exception).__name__, errors.getvalue()) == (1, "SystemExit", "Command not found: missing-other\n")
    assert calls == [(["missing-other", "--flag"], False, "value")]


def test_windows_child_status_and_inherited_environment(tmp_path, monkeypatch):
    path = tmp_path / "config.txt"
    path.write_text("EXTRA=value\n", encoding="utf-8")
    monkeypatch.setenv("PYREPAIR_INHERITED", "kept")
    calls = []
    class Child:
        returncode = 7
        def communicate(self):
            calls.append("communicate")
            return None, None
    def launch(command, **kwargs):
        calls.append((list(command), kwargs["shell"], kwargs["env"].get("EXTRA"), kwargs["env"].get("PYREPAIR_INHERITED")))
        return Child()
    monkeypatch.setattr(dotenv_cli, "Popen", launch, raising=False)
    monkeypatch.setattr(dotenv_cli, "sys", SimpleNamespace(platform="win32", stderr=io.StringIO(), exit=sys.exit))
    result = CliRunner().invoke(dotenv_cli.cli, ["--file", str(path), "run", "example", "arg"])
    assert result.exit_code == 7
    assert calls == [(["example", "arg"], False, "value", "kept"), "communicate"]


def test_missing_env_file_precedes_launch(tmp_path, monkeypatch):
    calls = []
    def boundary(*args, **kwargs):
        calls.append(True)
    monkeypatch.setattr(dotenv_cli.os, "execvpe", boundary)
    monkeypatch.setattr(dotenv_cli, "Popen", boundary, raising=False)
    result = CliRunner().invoke(dotenv_cli.cli, ["--file", str(tmp_path / "absent.txt"), "run", "missing"])
    assert result.exit_code == 2
    assert "Invalid value for '-f'" in result.output
    assert calls == []
""",
        "f2p_public": ["test_posix_missing_command_is_clean_cli_failure"],
        "f2p_hidden": ["test_windows_missing_command_is_clean_cli_failure"],
        "p2p_public": ["test_no_command_diagnostic"],
        "p2p_hidden": [
            "test_windows_child_status_and_inherited_environment",
            "test_missing_env_file_precedes_launch",
        ],
        "public_origin": "Adapted pinned PR #606 test_run_with_invalid_cmd; actual CLI with POSIX exec boundary raising FileNotFoundError.",
        "hidden_origin": "Project-authored Windows boundary parity and child-status regression, plus pinned missing-env-file precedence contract.",
        "mutant_origin": "Artificial incomplete repair: POSIX error handling works, but Windows catches the wrong launch-error subtype.",
        "mutant": {
            "keep_paths": ["src/dotenv/cli.py"],
            "replacements": [
                {
                    "path": "src/dotenv/cli.py",
                    "old": '        except FileNotFoundError:\n            print(f"Command not found: {command[0]}", file=sys.stderr)\n            sys.exit(1)\n\n        _, _ = p.communicate()',
                    "new": '        except NotADirectoryError:\n            print(f"Command not found: {command[0]}", file=sys.stderr)\n            sys.exit(1)\n\n        _, _ = p.communicate()',
                }
            ],
        },
    },
    "os_dotenv_empty_cache_638": {
        "task": (
            "# Cache empty dotenv results\n\n"
            "A DotEnv instance must parse its input only once after dict() computes "
            "a result, even when that result is empty. Subsequent dict()/get() calls "
            "must use the computed snapshot for both file-backed and stream-backed "
            "input, with interpolation enabled or disabled. Later source changes "
            "must not silently replace that cached snapshot. Preserve nonempty "
            "caching and the distinction between bare keys and empty strings.\n"
        ),
        "public": r"""from io import StringIO
from dotenv.main import DotEnv


def test_empty_stream_is_read_once():
    class CountingStream(StringIO):
        reads = 0
        def read(self, *args, **kwargs):
            self.reads += 1
            return super().read(*args, **kwargs)
    source = CountingStream("")
    env = DotEnv(None, stream=source)
    try:
        first, second, absent = env.dict(), env.dict(), env.get("MISSING")
        actual = (dict(first), dict(second), absent, source.reads)
    except Exception as exc:
        actual = (type(exc).__name__, str(exc))
    assert actual == ({}, {}, None, 1)


def test_nonempty_stream_is_cached():
    source = StringIO("A=one\nBARE\nEMPTY=\n")
    env = DotEnv(None, stream=source)
    assert dict(env.dict()) == {"A": "one", "BARE": None, "EMPTY": ""}
    assert dict(env.dict()) == {"A": "one", "BARE": None, "EMPTY": ""}
""",
        "hidden": r"""from io import StringIO
from dotenv.main import DotEnv


def test_empty_file_remains_cached_after_source_changes(tmp_path):
    actual = []
    for interpolate in (True, False):
        path = tmp_path / (str(interpolate) + ".txt")
        path.write_text("# only a comment\n", encoding="utf-8")
        env = DotEnv(path, interpolate=interpolate)
        try:
            first = dict(env.dict())
            path.write_text("A=changed\n", encoding="utf-8")
            actual.append((first, dict(env.dict()), env.get("A")))
        except Exception as exc:
            actual.append((type(exc).__name__, str(exc)))
    assert actual == [({}, {}, None), ({}, {}, None)]


def test_empty_noninterpolating_stream_is_read_once():
    class CountingStream(StringIO):
        reads = 0
        def read(self, *args, **kwargs):
            self.reads += 1
            return super().read(*args, **kwargs)
    source = CountingStream("# note\n")
    env = DotEnv(None, stream=source, interpolate=False)
    try:
        actual = (dict(env.dict()), dict(env.dict()), source.reads)
    except Exception as exc:
        actual = (type(exc).__name__, str(exc))
    assert actual == ({}, {}, 1)


def test_nonempty_file_snapshot_is_unchanged(tmp_path):
    path = tmp_path / "config.txt"
    path.write_text("A=old\nBARE\nEMPTY=\n", encoding="utf-8")
    env = DotEnv(path)
    assert dict(env.dict()) == {"A": "old", "BARE": None, "EMPTY": ""}
    path.write_text("A=new\n", encoding="utf-8")
    assert env.get("A") == "old"
    assert dict(env.dict()) == {"A": "old", "BARE": None, "EMPTY": ""}
""",
        "f2p_public": ["test_empty_stream_is_read_once"],
        "f2p_hidden": [
            "test_empty_file_remains_cached_after_source_changes",
            "test_empty_noninterpolating_stream_is_read_once",
        ],
        "p2p_public": ["test_nonempty_stream_is_cached"],
        "p2p_hidden": ["test_nonempty_file_snapshot_is_unchanged"],
        "public_origin": "Adapted pinned PR #638 test_empty_dotenv_dict_is_cached with a real read-counting stream rather than a parse mock.",
        "hidden_origin": "Project-authored file/stream, source-change and interpolate=False boundaries grounded in pinned DotEnv.dict/get behavior.",
        "mutant_origin": "Artificial incomplete repair: cache empty streams but still reparse empty file-backed results.",
        "mutant": {
            "keep_paths": ["src/dotenv/main.py"],
            "replacements": [
                {
                    "path": "src/dotenv/main.py",
                    "old": "        if self._dict is not None:\n            return self._dict",
                    "new": "        if self._dict is not None and (self._dict or self.stream is not None):\n            return self._dict",
                }
            ],
        },
    },
    "os_more_bucket_validator_1309": {
        "task": (
            "# Honor callable bucket validators regardless of truthiness\n\n"
            "bucket(..., validator=...) must use every supplied callable validator, "
            "even if its object is falsey through __bool__ or __len__, rather than "
            "treating it as an omitted validator. Rejected keys must yield no values, "
            "fail membership and be absent from key iteration. Accessing rejected "
            "keys must not consume the source; accepted keys and later iteration "
            "must retain order and data. Preserve None/default and ordinary callable "
            "validator behavior.\n"
        ),
        "public": r"""from more_itertools import bucket


def test_empty_callable_set_is_still_a_validator():
    class AllowedKeys(set):
        def __call__(self, key):
            return key in self
    grouped = bucket([10, 20, 11, 21], key=lambda x: x, validator=AllowedKeys())
    try:
        actual = (list(grouped[10]), 10 in grouped, set(grouped))
    except Exception as exc:
        actual = (type(exc).__name__, str(exc))
    assert actual == ([], False, set())


def test_default_validator_keeps_group_values():
    grouped = bucket([1, 2, 3, 4], key=lambda x: x % 2, validator=None)
    assert list(grouped[0]) == [2, 4]
    assert list(grouped[1]) == [1, 3]
""",
        "hidden": r"""from more_itertools import bucket


def test_false_bool_validator_rejects_without_consumption():
    class EvenKeys:
        def __bool__(self):
            return False
        def __call__(self, key):
            return key % 2 == 0
    consumed = []
    def source():
        for item in [1, 2, 3, 4, 6]:
            consumed.append(item)
            yield item
    grouped = bucket(source(), key=lambda x: x, validator=EvenKeys())
    try:
        rejected = (list(grouped[1]), 3 in grouped, list(consumed))
        keys = set(grouped)
        actual = (rejected, keys, list(grouped[2]), list(grouped[4]), list(grouped[6]))
    except Exception as exc:
        actual = (type(exc).__name__, str(exc))
    assert actual == (([], False, []), {2, 4, 6}, [2], [4], [6])


def test_zero_length_callable_preserves_accepted_bucket_order():
    class AcceptA:
        def __len__(self):
            return 0
        def __call__(self, key):
            return key == "a"
    grouped = bucket(["b1", "a1", "b2", "a2"], key=lambda x: x[0], validator=AcceptA())
    try:
        actual = (list(grouped["b"]), "b" in grouped, set(grouped), list(grouped["a"]))
    except Exception as exc:
        actual = (type(exc).__name__, str(exc))
    assert actual == ([], False, {"a"}, ["a1", "a2"])


def test_ordinary_callable_membership_does_not_drop_item():
    grouped = bucket([1, 2, 3, 4], key=lambda x: x % 2, validator=lambda key: key == 0)
    assert 0 in grouped
    assert 1 not in grouped
    assert list(grouped[0]) == [2, 4]
    assert set(grouped) == {0}
""",
        "f2p_public": ["test_empty_callable_set_is_still_a_validator"],
        "f2p_hidden": [
            "test_false_bool_validator_rejects_without_consumption",
            "test_zero_length_callable_preserves_accepted_bucket_order",
        ],
        "p2p_public": ["test_default_validator_keeps_group_values"],
        "p2p_hidden": ["test_ordinary_callable_membership_does_not_drop_item"],
        "public_origin": "Adapted pinned PR #1309 BucketTests.test_falsey_validator_is_honoured and default grouping regression.",
        "hidden_origin": "Project-authored non-set __bool__/__len__ callables, no-consumption and grouping-order boundaries from pinned bucket API.",
        "mutant_origin": "Artificial incomplete repair: special-case falsey set validators but still discard other falsey callables.",
        "mutant": {
            "keep_paths": ["more_itertools/more.py"],
            "replacements": [
                {
                    "path": "more_itertools/more.py",
                    "old": "self._validator = (lambda x: True) if validator is None else validator",
                    "new": "self._validator = validator if isinstance(validator, set) else (validator or (lambda x: True))",
                }
            ],
        },
    },
    "os_more_ichunked_sizes_1305": {
        "task": (
            "# Handle zero and negative ichunked sizes consistently\n\n"
            "ichunked(iterable, 0) must yield no chunks and must not consume any "
            "source elements, including nonempty and one-shot sources. Negative "
            "sizes must raise ValueError with 'n must be at least 0', including for "
            "empty sources, without consuming source elements. Preserve ordinary "
            "positive-size chunking, final short chunks, out-of-order consumption "
            "and lazy source access.\n"
        ),
        "public": r"""from more_itertools import ichunked


def test_zero_size_does_not_consume_nonempty_source():
    source = iter([1, 2, 3])
    try:
        chunks = [list(part) for part in ichunked(source, 0)]
        actual = (chunks, list(source))
    except Exception as exc:
        actual = (type(exc).__name__, str(exc))
    assert actual == ([], [1, 2, 3])


def test_positive_size_keeps_short_final_chunk():
    assert [list(part) for part in ichunked(range(5), 2)] == [[0, 1], [2, 3], [4]]
""",
        "hidden": r"""from more_itertools import ichunked


def test_negative_sizes_reject_empty_and_nonempty_without_consuming():
    actual = []
    for values in ([], [1, 2, 3]):
        for size in (-1, -7):
            source = iter(values)
            try:
                result = [list(part) for part in ichunked(source, size)]
                outcome = ("returned", result)
            except Exception as exc:
                outcome = (type(exc).__name__, str(exc))
            actual.append((outcome, list(source)))
    assert actual == [(("ValueError", "n must be at least 0"), values) for values in ([], [1, 2, 3]) for size in (-1, -7)]


def test_zero_size_never_advances_generator():
    consumed = []
    def source():
        consumed.append("advanced")
        yield 42
    try:
        actual = ([list(part) for part in ichunked(source(), 0)], consumed)
    except Exception as exc:
        actual = (type(exc).__name__, str(exc))
    assert actual == ([], [])


def test_out_of_order_chunks_and_lazy_start():
    consumed = []
    def source():
        for value in range(7):
            consumed.append(value)
            yield value
    chunks = ichunked(source(), 3)
    assert consumed == []
    first = next(chunks)
    assert consumed == [0]
    second = next(chunks)
    assert list(second) == [3, 4, 5]
    assert list(first) == [0, 1, 2]
    assert [list(part) for part in chunks] == [[6]]
""",
        "f2p_public": ["test_zero_size_does_not_consume_nonempty_source"],
        "f2p_hidden": [
            "test_negative_sizes_reject_empty_and_nonempty_without_consuming",
            "test_zero_size_never_advances_generator",
        ],
        "p2p_public": ["test_positive_size_keeps_short_final_chunk"],
        "p2p_hidden": ["test_out_of_order_chunks_and_lazy_start"],
        "public_origin": "Adapted pinned PR #1305 IChunkedTests.test_zero_nonempty and existing positive-size regression.",
        "hidden_origin": "Adapted PR #1305 negative-size diagnostic and local empty-source/no-consumption boundaries; pinned out-of-order/laziness regression.",
        "mutant_origin": "Artificial incomplete repair: retain zero-size handling but omit negative-size validation.",
        "mutant": {
            "keep_paths": ["more_itertools/more.py"],
            "replacements": [
                {
                    "path": "more_itertools/more.py",
                    "old": "    if n is not None and n < 0:\n        raise ValueError('n must be at least 0')\n    if n == 0:\n        return\n\n    iterator = iter(iterable)",
                    "new": "    if n == 0:\n        return\n\n    iterator = iter(iterable)",
                }
            ],
        },
    },
}
