import tomllib
from pathlib import Path


def test_runtime_dependencies_include_socks_proxy_support() -> None:
    pyproject_path = Path(__file__).parents[1] / "pyproject.toml"
    project = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))["project"]

    assert "httpx[socks]>=0.27,<1" in project["dependencies"]
