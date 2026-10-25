"""Static, independently authored behavioral contracts for the eight Click cases."""

CLICK_OVERLAYS = {
    "os_click_flags_2930": {
        "task": r"""# Explicitly typed flags

An option declared with `is_flag=True` must work when its type is explicitly
provided. Without an explicit `flag_value`, a boolean flag selects the opposite
of its default when supplied, for both `bool` and `click.BOOL`. A string-typed
flag selects the string representation of that boolean selection. Omitting a
flag must continue to use its normal default. Preserve explicit flag values,
implicitly typed flags, and ordinary value-taking options, including defaults
whose truth value cannot be inspected.

Public checks: `pyrepair_public_tests/test_repro.py`.
Additional contract checks: `hidden_tests/test_contract.py`.
""",
        "public": r"""import click
from click.testing import CliRunner


def test_typed_boolean_flag_selects_true():
    @click.command()
    @click.option("--enabled", is_flag=True, type=bool)
    def cli(enabled):
        click.echo(repr(enabled))

    result = CliRunner().invoke(cli, ["--enabled"])
    assert (result.exit_code, result.output) == (0, "True\n")


def test_explicit_flag_value_and_absent_default():
    @click.command()
    @click.option("--mode", is_flag=True, type=str, flag_value="fast", default=True)
    def cli(mode):
        click.echo(mode)

    runner = CliRunner()
    assert runner.invoke(cli, []).output == "fast\n"
    assert runner.invoke(cli, ["--mode"]).output == "fast\n"


def test_value_option_does_not_inspect_default_truth():
    class Opaque:
        def __bool__(self):
            raise ValueError("truth is unavailable")

    marker = Opaque()
    observed = []
    try:
        option = click.Option(["--value"], type=click.UNPROCESSED, default=marker)
        cli = click.Command("cli", params=[option], callback=lambda value: observed.append(value))
        result = CliRunner().invoke(cli, [])
        outcome = result.exit_code
    except Exception as exc:
        outcome = type(exc).__name__
    assert outcome == 0
    assert observed == [marker]
""",
        "hidden": r"""import click
from click.testing import CliRunner


def test_true_default_boolean_flag_can_select_false():
    @click.command()
    @click.option("--online", is_flag=True, type=click.BOOL, default=True)
    def cli(online):
        click.echo(repr(online))

    runner = CliRunner()
    assert runner.invoke(cli, []).output == "True\n"
    result = runner.invoke(cli, ["--online"])
    assert (result.exit_code, result.output) == (0, "False\n")


def test_string_typed_flag_has_a_selected_value():
    @click.command()
    @click.option("--selected", is_flag=True, type=str)
    def cli(selected):
        click.echo(selected)

    result = CliRunner().invoke(cli, ["--selected"])
    assert (result.exit_code, result.output) == (0, "True\n")


def test_implicit_boolean_and_regular_integer_option():
    @click.command()
    @click.option("--verbose", is_flag=True)
    @click.option("--count", type=int, default=4)
    def cli(verbose, count):
        click.echo(f"{verbose}:{count}")

    result = CliRunner().invoke(cli, ["--verbose", "--count", "9"])
    assert (result.exit_code, result.output) == (0, "True:9\n")
""",
        "f2p_public": ["test_typed_boolean_flag_selects_true"],
        "f2p_hidden": [
            "test_true_default_boolean_flag_can_select_false",
            "test_string_typed_flag_has_a_selected_value",
        ],
        "p2p_public": [
            "test_explicit_flag_value_and_absent_default",
            "test_value_option_does_not_inspect_default_truth",
        ],
        "p2p_hidden": ["test_implicit_boolean_and_regular_integer_option"],
        "public_origin": "Independently authored CliRunner contracts, informed by upstream tests/test_options.py additions in pallets/click PR #2930; changed names and explicit non-flag identity regression.",
        "hidden_origin": "Independent true-default, singleton BOOL, string conversion, and ordinary-option checks derived from PR #2930's supported behavioral matrix.",
        "mutant_origin": "Artificial incomplete fix: initialize missing flag_value only for false-like defaults, leaving true-default flags unsupported.",
        "mutant": {
            "keep_paths": ["src/click/core.py"],
            "replacements": [
                {
                    "path": "src/click/core.py",
                    "old": "        if is_flag and flag_value is None:\n            flag_value = not self.default\n",
                    "new": "        if is_flag and flag_value is None and not self.default:\n            flag_value = not self.default\n",
                }
            ],
        },
    },
    "os_click_enum_default_3004": {
        "task": r"""# Enum defaults in option help

When a Choice option has an Enum member as its default and displays defaults,
help must show the member's name, consistently with the displayed choices.
This includes ordinary Enum, integer Enum, string-valued Enum, Flag, and IntFlag
members. Rendering help must not change the configured default or choice
conversion. Preserve non-Enum defaults and explicit custom `show_default` text.

Public checks: `pyrepair_public_tests/test_repro.py`.
Additional contract checks: `hidden_tests/test_contract.py`.
""",
        "public": r"""import enum
import click
from click.testing import CliRunner


def test_enum_member_default_help_uses_name():
    class Format(enum.Enum):
        BRIEF = "short-output"
        FULL = "long-output"

    @click.command()
    @click.option("--format", type=click.Choice(Format), default=Format.FULL, show_default=True)
    def cli(format):
        click.echo(format.name)

    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "[default: FULL]" in result.output
    assert cli.params[0].default is Format.FULL


def test_non_enum_default_and_choice_conversion():
    @click.command()
    @click.option("--size", type=click.Choice(["small", "large"]), default="large", show_default=True)
    def cli(size):
        click.echo(size)

    runner = CliRunner()
    assert "[default: large]" in runner.invoke(cli, ["--help"]).output
    result = runner.invoke(cli, ["--size", "small"])
    assert (result.exit_code, result.output) == (0, "small\n")
""",
        "hidden": r"""import enum
import click
from click.testing import CliRunner


def test_integer_enum_default_help_uses_member_name():
    class Level(enum.IntEnum):
        LOW = 11
        HIGH = 29

    option = click.Option(["--level"], type=click.Choice(Level), default=Level.HIGH, show_default=True)
    cli = click.Command("cli", params=[option])
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "[default: HIGH]" in result.output
    assert option.default is Level.HIGH


def test_flag_and_string_enum_defaults_use_names():
    class Access(enum.Flag):
        READ = 1
        WRITE = 2

    class Token(str, enum.Enum):
        PRIMARY = "primary-token"
        BACKUP = "backup-token"

    cli = click.Command("cli", params=[
        click.Option(["--access"], type=click.Choice(Access), default=Access.WRITE, show_default=True),
        click.Option(["--token"], type=click.Choice(Token), default=Token.BACKUP, show_default=True),
    ])
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "[default: WRITE]" in result.output
    assert "[default: BACKUP]" in result.output


def test_intflag_default_help_uses_member_name():
    class Capability(enum.IntFlag):
        FETCH = 1
        PUSH = 2

    option = click.Option(["--capability"], type=click.Choice(Capability), default=Capability.PUSH, show_default=True)
    cli = click.Command("cli", params=[option])
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "[default: PUSH]" in result.output


def test_enum_custom_default_label_and_conversion_are_preserved():
    class Permission(enum.IntFlag):
        VIEW = 1
        EDIT = 2

    observed = []
    option = click.Option(["--permission"], type=click.Choice(Permission), default=Permission.EDIT, show_default="site policy")
    cli = click.Command("cli", params=[option], callback=lambda permission: observed.append(permission))
    runner = CliRunner()
    assert "[default: (site policy)]" in runner.invoke(cli, ["--help"]).output
    result = runner.invoke(cli, ["--permission", "VIEW"])
    assert result.exit_code == 0
    assert observed == [Permission.VIEW]
""",
        "f2p_public": ["test_enum_member_default_help_uses_name"],
        "f2p_hidden": [
            "test_integer_enum_default_help_uses_member_name",
            "test_flag_and_string_enum_defaults_use_names",
            "test_intflag_default_help_uses_member_name",
        ],
        "p2p_public": ["test_non_enum_default_and_choice_conversion"],
        "p2p_hidden": ["test_enum_custom_default_label_and_conversion_are_preserved"],
        "public_origin": "Independent help and conversion checks informed by tests/test_options.py test_choice_default_rendering in pallets/click PR #3004.",
        "hidden_origin": "Independent Enum subtype and explicit display-label contracts, based on PR #3004's Enum/IntEnum/Flag/IntFlag coverage and production help behavior.",
        "mutant_origin": "Artificial incomplete fix: handles ordinary enum defaults but excludes int-backed Enum members.",
        "mutant": {
            "keep_paths": ["src/click/core.py"],
            "replacements": [
                {
                    "path": "src/click/core.py",
                    "old": "            elif isinstance(default_value, enum.Enum):\n                default_string = default_value.name\n",
                    "new": "            elif isinstance(default_value, enum.Enum) and not isinstance(default_value, int):\n                default_string = default_value.name\n",
                }
            ],
        },
    },
    "os_click_env_hint_2972": {
        "task": r"""# Environment-variable hints in errors

With `show_envvar=True`, an option error must not advertise an environment
variable when the option has no explicit envvar configured. This applies to
missing required options and invalid values of optional or required options,
including options with aliases. When an envvar is explicitly configured, retain
the existing hint; `show_envvar=False` must continue to omit it. Valid command
invocations must remain unaffected.

Public checks: `pyrepair_public_tests/test_repro.py`.
Additional contract checks: `hidden_tests/test_contract.py`.
""",
        "public": r"""import click
from click.testing import CliRunner


def test_required_option_without_envvar_has_no_phantom_hint():
    cli = click.Command("cli", params=[click.Option(["--account"], required=True, show_envvar=True)])
    result = CliRunner().invoke(cli, [])
    assert result.exit_code == 2
    assert "Error: Missing option '--account'." in result.output
    assert "env var:" not in result.output


def test_configured_required_envvar_hint_is_retained():
    cli = click.Command("cli", params=[click.Option(["--account"], required=True, show_envvar=True, envvar="PYREPAIR_ACCOUNT")])
    result = CliRunner().invoke(cli, [], env={"PYREPAIR_ACCOUNT": None})
    assert result.exit_code == 2
    assert "(env var: 'PYREPAIR_ACCOUNT')" in result.output


def test_valid_value_is_not_changed_by_hint_setting():
    @click.command()
    @click.option("--amount", type=int, show_envvar=True)
    def cli(amount):
        click.echo(amount + 1)

    result = CliRunner().invoke(cli, ["--amount", "6"])
    assert (result.exit_code, result.output) == (0, "7\n")
""",
        "hidden": r"""import click
from click.testing import CliRunner


def test_optional_conversion_error_has_no_unconfigured_envvar():
    cli = click.Command("cli", params=[click.Option(["-q", "--quantity"], type=int, show_envvar=True)])
    result = CliRunner().invoke(cli, ["-q", "many"])
    assert result.exit_code == 2
    assert "Invalid value" in result.output
    assert "env var:" not in result.output


def test_required_aliased_conversion_error_has_no_unconfigured_envvar():
    cli = click.Command("cli", params=[click.Option(["-p", "--port"], required=True, type=int, show_envvar=True)])
    result = CliRunner().invoke(cli, ["--port", "bad"])
    assert result.exit_code == 2
    assert "Invalid value" in result.output
    assert "env var:" not in result.output


def test_configured_optional_hint_and_disabled_hint():
    runner = CliRunner()
    shown = click.Command("cli", params=[click.Option(["--width"], type=int, envvar="PYREPAIR_WIDTH", show_envvar=True)])
    result = runner.invoke(shown, ["--width", "wide"], env={"PYREPAIR_WIDTH": None})
    assert result.exit_code == 2
    assert "(env var: 'PYREPAIR_WIDTH')" in result.output
    hidden = click.Command("cli", params=[click.Option(["--width"], type=int, envvar="PYREPAIR_WIDTH", show_envvar=False)])
    result = runner.invoke(hidden, ["--width", "wide"], env={"PYREPAIR_WIDTH": None})
    assert result.exit_code == 2
    assert "env var:" not in result.output
""",
        "f2p_public": ["test_required_option_without_envvar_has_no_phantom_hint"],
        "f2p_hidden": [
            "test_optional_conversion_error_has_no_unconfigured_envvar",
            "test_required_aliased_conversion_error_has_no_unconfigured_envvar",
        ],
        "p2p_public": [
            "test_configured_required_envvar_hint_is_retained",
            "test_valid_value_is_not_changed_by_hint_setting",
        ],
        "p2p_hidden": ["test_configured_optional_hint_and_disabled_hint"],
        "public_origin": "Independent CLI error contracts adapted from tests/test_options.py test_missing_envvar addition in pallets/click PR #2972.",
        "hidden_origin": "Independent invalid-value, alias, and configured/disabled hint checks extending the public no-unconfigured-envvar contract.",
        "mutant_origin": "Artificial incomplete fix: suppresses phantom hints only for required options, retaining the optional invalid-value defect.",
        "mutant": {
            "keep_paths": ["src/click/core.py"],
            "replacements": [
                {
                    "path": "src/click/core.py",
                    "old": "        if self.show_envvar and self.envvar is not None:\n            result += f\" (env var: '{self.envvar}')\"\n",
                    "new": "        if self.show_envvar and (self.envvar is not None or not self.required):\n            result += f\" (env var: '{self.envvar}')\"\n",
                }
            ],
        },
    },
    "os_click_resource_exit_3058": {
        "task": r"""# Context resources receive exception information

Resources registered with `Context.with_resource` must receive the exception
type, object, and traceback when a Click context exits exceptionally. Normal
context-manager suppression must work, including a resource suppressing an
exception before earlier resources are exited. Resources unwind in reverse
registration order. Non-suppressed exceptions must propagate unchanged.
Normal close callbacks, explicit close, nested scopes, and reuse of a context
must retain their cleanup behavior without duplicate cleanup.

Public checks: `pyrepair_public_tests/test_repro.py`.
Additional contract checks: `hidden_tests/test_contract.py`.
""",
        "public": r"""import click


def test_resource_receives_exception_identity_and_traceback():
    observed = []
    problem = ValueError("resource failure")

    class Resource:
        def __enter__(self):
            return "handle"

        def __exit__(self, kind, value, traceback):
            observed.append((kind, value, traceback is not None))
            return False

    ctx = click.Context(click.Command("cli"))
    caught = None
    try:
        with ctx:
            assert ctx.with_resource(Resource()) == "handle"
            raise problem
    except Exception as exc:
        caught = exc
    assert caught is problem
    assert observed == [(ValueError, problem, True)]


def test_normal_resources_callbacks_and_explicit_close():
    events = []

    class Resource:
        def __enter__(self):
            events.append("enter")
            return self

        def __exit__(self, kind, value, traceback):
            events.append((kind, value, traceback))

    ctx = click.Context(click.Command("cli"))
    ctx.with_resource(Resource())
    ctx.call_on_close(lambda: events.append("callback"))
    ctx.close()
    ctx.close()
    assert events == ["enter", "callback", (None, None, None)]
""",
        "hidden": r"""import click


def test_nested_resources_can_suppress_before_earlier_exit():
    events = []
    problem = RuntimeError("transaction cancelled")

    class Resource:
        def __init__(self, name, suppress):
            self.name = name
            self.suppress = suppress

        def __enter__(self):
            return self

        def __exit__(self, kind, value, traceback):
            events.append((self.name, kind, value, traceback is not None))
            return self.suppress

    ctx = click.Context(click.Command("cli"))
    caught = None
    try:
        with ctx.scope():
            ctx.with_resource(Resource("outer", False))
            with ctx.scope():
                ctx.with_resource(Resource("inner", True))
                raise problem
    except Exception as exc:
        caught = exc
    assert caught is None
    assert events == [("inner", RuntimeError, problem, True), ("outer", None, None, False)]


def test_suppressing_resource_allows_context_reuse():
    events = []

    class Resource:
        def __enter__(self):
            return self

        def __exit__(self, kind, value, traceback):
            events.append(kind)
            return True

    ctx = click.Context(click.Command("cli"))
    caught = None
    try:
        with ctx:
            ctx.with_resource(Resource())
            raise LookupError("first scope")
    except Exception as exc:
        caught = exc
    with ctx:
        ctx.with_resource(Resource())
    assert caught is None
    assert events == [LookupError, None]


def test_nested_normal_scope_defers_cleanup_until_outer_exit():
    events = []
    ctx = click.Context(click.Command("cli"))
    with ctx:
        ctx.call_on_close(lambda: events.append("closed"))
        with ctx.scope():
            assert click.get_current_context() is ctx
        assert events == []
    assert events == ["closed"]
    with ctx:
        ctx.call_on_close(lambda: events.append("reused"))
    assert events == ["closed", "reused"]
""",
        "f2p_public": ["test_resource_receives_exception_identity_and_traceback"],
        "f2p_hidden": [
            "test_nested_resources_can_suppress_before_earlier_exit",
            "test_suppressing_resource_allows_context_reuse",
        ],
        "p2p_public": ["test_normal_resources_callbacks_and_explicit_close"],
        "p2p_hidden": ["test_nested_normal_scope_defers_cleanup_until_outer_exit"],
        "public_origin": "Independent context-manager observer tests informed by tests/test_context.py additions in pallets/click PR #3058; verifies exact exception identity without leaking exceptions out of test assertions.",
        "hidden_origin": "Independent suppression, nested-scope reverse unwind, traceback presence, and context reuse cases based on PR #3058's exception-resource contract.",
        "mutant_origin": "Artificial incomplete fix: forwards exception details but discards Context.__exit__ suppression result.",
        "mutant": {
            "keep_paths": ["src/click/core.py"],
            "replacements": [
                {
                    "path": "src/click/core.py",
                    "old": "        pop_context()\n\n        return exit_result\n",
                    "new": "        pop_context()\n\n        return None\n",
                }
            ],
        },
    },
    "os_click_eof_2940": {
        "task": r"""# CliRunner stdin exhaustion

Commands run by CliRunner must be able to consume text stdin using normal
iteration: exhaustion terminates the iterator rather than aborting the command.
This applies to empty input, multiple lines, and a final line without a newline;
`next(stream, sentinel)` must also work normally. Preserve Click's visible and
hidden prompt behavior: exhausted prompt input is an abort, while supplied
prompt input is returned normally. No real terminal or subprocess is needed.

Public checks: `pyrepair_public_tests/test_repro.py`.
Additional contract checks: `hidden_tests/test_contract.py`.
""",
        "public": r"""import sys
import click
from click.testing import CliRunner


def test_stdin_iteration_finishes_without_aborting():
    @click.command()
    def cli():
        lines = [line.rstrip("\r\n") for line in sys.stdin]
        click.echo("|".join(lines))

    result = CliRunner().invoke(cli, input="north\nsouth\n")
    assert (result.exit_code, result.output) == (0, "north|south\n")
    assert result.exception is None


def test_visible_prompt_still_returns_input_and_aborts_at_eof():
    @click.command()
    def cli():
        click.echo("received=" + click.prompt("Label"))

    runner = CliRunner()
    result = runner.invoke(cli, input="oak\n")
    assert result.exit_code == 0
    assert "received=oak\n" in result.output
    exhausted = runner.invoke(cli, input="")
    assert exhausted.exit_code == 1
    assert "Aborted!" in exhausted.output
""",
        "hidden": r"""import sys
import click
from click.testing import CliRunner


def test_empty_stdin_is_an_empty_iterator():
    @click.command()
    def cli():
        click.echo(len(list(sys.stdin)))

    result = CliRunner().invoke(cli, input="")
    assert (result.exit_code, result.output) == (0, "0\n")
    assert result.exception is None


def test_unterminated_line_then_next_default():
    @click.command()
    def cli():
        first = next(sys.stdin, "EMPTY")
        second = next(sys.stdin, "DONE")
        click.echo(repr((first, second)))

    result = CliRunner().invoke(cli, input="last-line")
    assert (result.exit_code, result.output) == (0, "('last-line', 'DONE')\n")


def test_hidden_prompt_eof_is_abort_not_stop_iteration():
    @click.command()
    def cli():
        click.echo("secret=" + click.prompt("Secret", hide_input=True))

    runner = CliRunner()
    result = runner.invoke(cli, input="hidden-value\n")
    assert result.exit_code == 0
    assert "secret=hidden-value\n" in result.output
    exhausted = runner.invoke(cli, input="")
    assert exhausted.exit_code == 1
    assert "Aborted!" in exhausted.output
    assert isinstance(exhausted.exception, SystemExit)
""",
        "f2p_public": ["test_stdin_iteration_finishes_without_aborting"],
        "f2p_hidden": [
            "test_empty_stdin_is_an_empty_iterator",
            "test_unterminated_line_then_next_default",
        ],
        "p2p_public": ["test_visible_prompt_still_returns_input_and_aborts_at_eof"],
        "p2p_hidden": ["test_hidden_prompt_eof_is_abort_not_stop_iteration"],
        "public_origin": "Independent CliRunner stdin iteration reproducer informed by tests/test_chain.py pipeline expectation update in pallets/click PR #2940; visible-prompt regression follows inspected testing.py and termui.py behavior.",
        "hidden_origin": "Independent empty-input, unterminated-line, next-default, and hidden-prompt contracts based on standard text stream and Click prompt behavior.",
        "mutant_origin": "Artificial incomplete fix: line iteration terminates normally but drops a final line without a newline.",
        "mutant": {
            "keep_paths": ["src/click/testing.py"],
            "replacements": [
                {
                    "path": "src/click/testing.py",
                    "old": "    @property\n    def mode(self) -> str:\n        return self._mode\n",
                    "new": '    @property\n    def mode(self) -> str:\n        return self._mode\n\n    def __next__(self) -> str:\n        line = super().__next__()\n        if not line.endswith(("\\r", "\\n")):\n            raise StopIteration\n        return line\n',
                }
            ],
        },
    },
    "os_click_zsh_colon_2846": {
        "task": r"""# Zsh completion values containing colons

Preserve the existing three-line Zsh completion protocol (type, value, help).
For a completion with real help text, each colon in its value must be escaped
so the deployed Zsh completion script can distinguish the value from its
description. Help text itself must remain unchanged. Values without help,
with empty help, or with the protocol's `_` help sentinel must remain literal,
including their colons. Preserve completion types and unrelated shell formats.

Public checks: `pyrepair_public_tests/test_repro.py`.
Additional contract checks: `hidden_tests/test_contract.py`.
""",
        "public": r"""import click
from click.shell_completion import CompletionItem, ZshComplete


def test_described_zsh_completion_escapes_colon_in_value():
    shell = ZshComplete(click.Command("tool"), {}, "tool", "_TOOL_COMPLETE")
    output = shell.format_completion(CompletionItem("cache:clear", help="clear: cache"))
    assert output == "plain\ncache\\:clear\nclear: cache"


def test_undescribed_zsh_completion_remains_literal():
    shell = ZshComplete(click.Command("tool"), {}, "tool", "_TOOL_COMPLETE")
    assert shell.format_completion(CompletionItem("cache:list")) == "plain\ncache:list\n_"
    assert shell.format_completion(CompletionItem("status", help="show status")) == "plain\nstatus\nshow status"
""",
        "hidden": r"""import click
from click.shell_completion import BashComplete, CompletionItem, FishComplete, ZshComplete


def test_all_colons_in_described_completion_are_escaped():
    shell = ZshComplete(click.Command("tool"), {}, "tool", "_TOOL_COMPLETE")
    item = CompletionItem(":region:host:", type="file", help="choose: remote path")
    assert shell.format_completion(item) == "file\n\\:region\\:host\\:\nchoose: remote path"


def test_help_sentinel_and_empty_help_do_not_escape_values():
    shell = ZshComplete(click.Command("tool"), {}, "tool", "_TOOL_COMPLETE")
    assert shell.format_completion(CompletionItem("left:right", help="_")) == "plain\nleft:right\n_"
    assert shell.format_completion(CompletionItem("one:two:three", help="")) == "plain\none:two:three\n_"


def test_other_shell_formats_are_unchanged():
    item = CompletionItem("pool:node", help="node: description")
    bash = BashComplete(click.Command("tool"), {}, "tool", "_TOOL_COMPLETE")
    fish = FishComplete(click.Command("tool"), {}, "tool", "_TOOL_COMPLETE")
    assert bash.format_completion(item) == "plain,pool:node"
    assert fish.format_completion(item) == "plain,pool:node\tnode: description"
""",
        "f2p_public": ["test_described_zsh_completion_escapes_colon_in_value"],
        "f2p_hidden": ["test_all_colons_in_described_completion_are_escaped"],
        "p2p_public": ["test_undescribed_zsh_completion_remains_literal"],
        "p2p_hidden": [
            "test_help_sentinel_and_empty_help_do_not_escape_values",
            "test_other_shell_formats_are_unchanged",
        ],
        "public_origin": "Independent formatter-level tests informed by tests/test_shell_completion.py test_zsh_full_complete_with_colons in pallets/click PR #2846; no Zsh process required.",
        "hidden_origin": "Independent multi-colon, leading/trailing colon, help sentinel, completion type, and other-shell regression contracts from inspected shell_completion.py protocol.",
        "mutant_origin": "Artificial incomplete fix: escapes only the first colon in described completion values.",
        "mutant": {
            "keep_paths": ["src/click/shell_completion.py"],
            "replacements": [
                {
                    "path": "src/click/shell_completion.py",
                    "old": '        value = item.value.replace(":", r"\\:") if help_ != "_" else item.value\n',
                    "new": '        value = item.value.replace(":", r"\\:", 1) if help_ != "_" else item.value\n',
                }
            ],
        },
    },
    "os_click_progress_final_3769": {
        "task": r"""# Progress bars settle on actual completed work

When a progress-bar context exits, its position and final rendered position
must reflect all completed updates, even if `update_min_steps` does not divide
the total or exceeds all completed work. Both iteration and manual updates
must work. Exiting after partial work must preserve the actual completed count,
not fabricate completion of the declared total. Already applied updates must
not be counted twice. Preserve ordinary divisible-threshold iteration behavior.
Checks use an in-memory stream reporting terminal capability, not a real TTY.

Public checks: `pyrepair_public_tests/test_repro.py`.
Additional contract checks: `hidden_tests/test_contract.py`.
""",
        "public": r"""import io
import click


class TerminalBuffer(io.StringIO):
    def isatty(self):
        return True


def test_iteration_renders_and_records_final_remainder():
    output = TerminalBuffer()
    with click.progressbar(range(17), show_pos=True, update_min_steps=6, file=output) as bar:
        values = list(bar)
    assert values == list(range(17))
    assert bar.pos == 17
    assert bar.finished
    assert "17/17" in output.getvalue()


def test_divisible_iteration_keeps_exact_position():
    output = TerminalBuffer()
    with click.progressbar(range(12), show_pos=True, update_min_steps=3, file=output) as bar:
        for _ in bar:
            pass
    assert bar.pos == 12
    assert bar.finished
    assert "12/12" in output.getvalue()
""",
        "hidden": r"""import io
import click


class TerminalBuffer(io.StringIO):
    def isatty(self):
        return True


def test_manual_updates_below_threshold_still_finish():
    output = TerminalBuffer()
    with click.progressbar(length=9, show_pos=True, update_min_steps=20, file=output) as bar:
        bar.update(4)
        bar.update(5)
    assert bar.pos == 9
    assert bar.finished
    assert "9/9" in output.getvalue()


def test_partial_manual_work_does_not_fabricate_completion():
    output = TerminalBuffer()
    with click.progressbar(length=23, show_pos=True, update_min_steps=8, file=output) as bar:
        bar.update(2)
        bar.update(3)
    assert bar.pos == 5
    assert not bar.finished
    assert "5/23" in output.getvalue()


def test_repeated_finish_render_does_not_double_count():
    output = TerminalBuffer()
    with click.progressbar(length=16, show_pos=True, update_min_steps=4, file=output) as bar:
        bar.update(8)
        bar.update(8)
    bar.render_finish()
    assert bar.pos == 16
    assert bar.finished
""",
        "f2p_public": ["test_iteration_renders_and_records_final_remainder"],
        "f2p_hidden": [
            "test_manual_updates_below_threshold_still_finish",
            "test_partial_manual_work_does_not_fabricate_completion",
        ],
        "p2p_public": ["test_divisible_iteration_keeps_exact_position"],
        "p2p_hidden": ["test_repeated_finish_render_does_not_double_count"],
        "public_origin": "Independent in-memory progress stream and iteration cases informed by tests/test_termui.py test_progressbar_lands_on_final_position in pallets/click PR #3769.",
        "hidden_origin": "Independent manual-update, over-total threshold, partial-work and no-double-counting contracts; no timing sleeps, actual terminal, or subprocess.",
        "mutant_origin": "Artificial incomplete fix: flushes a remainder only if a previous threshold update already advanced position.",
        "mutant": {
            "keep_paths": ["src/click/_termui_impl.py"],
            "replacements": [
                {
                    "path": "src/click/_termui_impl.py",
                    "old": "        if self._completed_intervals:\n            self.make_step(self._completed_intervals)\n",
                    "new": "        if self._completed_intervals and self.pos:\n            self.make_step(self._completed_intervals)\n",
                }
            ],
        },
    },
    "os_click_callable_flag_3225": {
        "task": r"""# Callable flag values used as defaults

A callable `flag_value` selected by `default=True` is a value, not a default
factory: omitting the flag must select that callable itself without calling it,
just as supplying the flag does. Support classes and ordinary functions, with
`UNPROCESSED` preserving object identity and normal string conversion otherwise.
Help rendering must not instantiate a callable flag value. Preserve explicit
callable defaults as factories, including `call=False` default inspection.
Context default-map overrides, including callable and None entries, must keep
their precedence; an explicit CLI flag still wins over the default map.

Public checks: `pyrepair_public_tests/test_repro.py`.
Additional contract checks: `hidden_tests/test_contract.py`.
""",
        "public": r"""import click
from click.testing import CliRunner


def test_default_true_preserves_class_flag_value_identity():
    calls = []

    class Strategy:
        def __init__(self):
            calls.append("constructed")

    observed = []
    @click.command()
    @click.option("--strategy", flag_value=Strategy, default=True, type=click.UNPROCESSED)
    def cli(strategy):
        observed.append(strategy)

    result = CliRunner().invoke(cli, [])
    assert result.exit_code == 0
    assert observed == [Strategy]
    assert calls == []


def test_supplied_class_flag_and_noncallable_default_are_unchanged():
    class Strategy:
        pass

    observed = []
    @click.command()
    @click.option("--strategy", flag_value=Strategy, default=True, type=click.UNPROCESSED)
    @click.option("--style", flag_value="compact", default=True)
    def cli(strategy, style):
        observed.append((strategy, style))

    result = CliRunner().invoke(cli, ["--strategy"])
    assert result.exit_code == 0
    assert observed == [(Strategy, "compact")]
""",
        "hidden": r"""import click
from click.testing import CliRunner


def test_function_flag_value_is_not_called_as_default():
    calls = []
    def strategy():
        calls.append("called")
        return "factory-result"

    observed = []
    @click.command()
    @click.option("--strategy", flag_value=strategy, default=True, type=click.UNPROCESSED)
    def cli(strategy):
        observed.append(strategy)

    result = CliRunner().invoke(cli, [])
    assert result.exit_code == 0
    assert observed == [strategy]
    assert calls == []


def test_class_help_and_string_default_do_not_construct_instances():
    calls = []
    class Codec:
        def __init__(self):
            calls.append("constructed")

    observed = []
    @click.command()
    @click.option("--codec", flag_value=Codec, default=True, show_default=True)
    def cli(codec):
        observed.append(codec)

    runner = CliRunner()
    help_result = runner.invoke(cli, ["--help"])
    result = runner.invoke(cli, [])
    assert help_result.exit_code == 0
    assert "Codec" in help_result.output
    assert "object at" not in help_result.output
    assert result.exit_code == 0
    assert observed == [str(Codec)]
    assert calls == []


def test_default_map_and_cli_precedence_remain_intact():
    class Marker:
        pass

    observed = []
    calls = []
    def factory():
        calls.append("map")
        return "mapped"

    @click.command()
    @click.option("--marker", flag_value=Marker, default=True, type=click.UNPROCESSED)
    def cli(marker):
        observed.append(marker)

    runner = CliRunner()
    first = runner.invoke(cli, [], default_map={"marker": factory})
    second = runner.invoke(cli, [], default_map={"marker": None})
    third = runner.invoke(cli, ["--marker"], default_map={"marker": "overridden"})
    assert [first.exit_code, second.exit_code, third.exit_code] == [0, 0, 0]
    assert observed == ["mapped", None, Marker]
    assert calls == ["map"]


def test_explicit_callable_default_and_call_false_inspection():
    calls = []
    def factory():
        calls.append("factory")
        return "built"

    class Marker:
        pass

    option = click.Option(["--marker"], flag_value=Marker, default=factory, type=click.UNPROCESSED)
    cli = click.Command("cli", params=[option])
    ctx = click.Context(cli)
    untouched = option.get_default(ctx, call=False)
    assert untouched is factory
    assert calls == []
    assert option.get_default(ctx) == "built"
    assert calls == ["factory"]
""",
        "f2p_public": ["test_default_true_preserves_class_flag_value_identity"],
        "f2p_hidden": [
            "test_function_flag_value_is_not_called_as_default",
            "test_class_help_and_string_default_do_not_construct_instances",
        ],
        "p2p_public": ["test_supplied_class_flag_and_noncallable_default_are_unchanged"],
        "p2p_hidden": [
            "test_default_map_and_cli_precedence_remain_intact",
            "test_explicit_callable_default_and_call_false_inspection",
        ],
        "public_origin": "Independent object-identity and invocation-count checks informed by tests/test_options.py callable flag-value additions in pallets/click PR #3225.",
        "hidden_origin": "Independent ordinary-function, string conversion, help no-construction, default-map precedence and explicit callable-factory contracts informed by PR #3225 tests/test_defaults.py and tests/test_options.py.",
        "mutant_origin": "Artificial incomplete fix: preserves classes but still invokes ordinary function flag values during default resolution.",
        "mutant": {
            "keep_paths": ["src/click/core.py"],
            "replacements": [
                {
                    "path": "src/click/core.py",
                    "old": "        if value is True and self.is_flag:\n            value = self.flag_value\n",
                    "new": "        if value is True and self.is_flag:\n            value = self.flag_value() if call and inspect.isfunction(self.flag_value) else self.flag_value\n",
                }
            ],
        },
    },
}
