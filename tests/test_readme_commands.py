from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]


def test_readme_documents_real_commands() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    assert "pip install -e ." in readme
    assert "pyrepair fix" in readme
    assert "python -m pytest" in readme
    assert "安全边界" in readme
    assert "benchmark" in readme.lower()
