from pathlib import Path
from typing import Annotated

import typer

from .config import AppConfig, ConfigError, load_config
from .context_builder import ContextBuilder
from .coordinator import CoordinatorError, RepairCoordinator
from .deepseek import DeepSeekClient
from .feedback import FeedbackBuilder
from .models import RepairRequest
from .policy import PatchPolicyGate
from .pytest_parser import PytestParser
from .recorder import RecorderError, RunRecorder
from .repair_agent import RepairAgent
from .review_agent import ReviewAgent
from .testing import TestExecutor, TestRunner
from .tools import ToolRegistry
from .verifier import Verifier
from .workspace import WorkspaceError, WorkspaceManager

app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """PyRepair Agent command line interface."""


@app.command()
def fix(
    target: Annotated[str | None, typer.Argument()] = None,
    repo: Annotated[Path, typer.Option()] = Path("."),
    model: Annotated[str, typer.Option()] = "deepseek-v4-flash",
    max_attempts: Annotated[int, typer.Option(min=1, max=3)] = 3,
    dry_run: Annotated[bool, typer.Option()] = False,
    verbose: Annotated[bool, typer.Option()] = False,
) -> None:
    """Diagnose pytest failures and generate a safe candidate patch."""
    try:
        config = load_config(
            require_api_key=not dry_run,
            model_override=model,
        )
        coordinator = build_coordinator(config, model_enabled=not dry_run)
        result = coordinator.run(
            RepairRequest(
                repo=repo.resolve(),
                test_target=target,
                model=config.model,
                max_attempts=max_attempts,
                dry_run=dry_run,
                verbose=verbose,
            )
        )
    except ConfigError as exc:
        typer.echo(f"配置错误：{exc}")
        raise typer.Exit(code=2) from exc
    except (WorkspaceError, RecorderError, CoordinatorError) as exc:
        typer.echo(f"运行错误：{exc}")
        artifact_dir = getattr(exc, "artifact_dir", None)
        if artifact_dir is not None:
            typer.echo(f"产物目录：{artifact_dir}")
        if verbose:
            typer.echo(f"异常类型：{type(exc).__name__}")
        raise typer.Exit(code=2) from exc

    typer.echo(f"状态：{result.status}")
    typer.echo(f"尝试次数：{result.attempts}")
    typer.echo(f"产物目录：{result.artifact_dir}")
    if result.failure_reason:
        typer.echo(f"失败原因：{result.failure_reason}")
    if result.status == "failed":
        raise typer.Exit(code=1)


def build_coordinator(
    config: AppConfig,
    model_enabled: bool,
    *,
    runner: TestExecutor | None = None,
) -> RepairCoordinator:
    if runner is None:
        runner = TestRunner(timeout_seconds=config.pytest_timeout_seconds)
    policy = PatchPolicyGate()
    if model_enabled:
        client = DeepSeekClient(
            api_key=config.api_key,
            model=config.model,
            base_url=config.base_url,
            timeout=config.api_timeout_seconds,
        )

        def agent_factory(registry: ToolRegistry) -> RepairAgent:
            return RepairAgent(client, registry)

        def reviewer_factory() -> ReviewAgent:
            return ReviewAgent(client)

    else:

        def agent_factory(registry: ToolRegistry) -> RepairAgent:
            del registry
            raise RuntimeError("dry-run must not create RepairAgent")

        def reviewer_factory() -> ReviewAgent:
            raise RuntimeError("dry-run must not create ReviewAgent")

    return RepairCoordinator(
        workspaces=WorkspaceManager(),
        runner=runner,
        parser=PytestParser(),
        registry_factory=lambda session, node_id: ToolRegistry(session, runner, node_id),
        agent_factory=agent_factory,
        context_builder=ContextBuilder(),
        feedback_builder=FeedbackBuilder(),
        policy=policy,
        reviewer_factory=reviewer_factory,
        verifier=Verifier(runner, policy),
        recorder_factory=lambda repo: RunRecorder(
            repo,
            sensitive_values=(config.api_key,),
        ),
        progress=lambda stage: typer.echo(f"阶段：{stage}"),
    )
