from pathlib import Path

from pyrepair.repository_index import ImportInfo, build_repository_index


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def test_index_extracts_functions_methods_and_imports(tmp_path):
    write(
        tmp_path / "src/service.py",
        """
from helpers.money import cents


class Cart:
    def total(self, value):
        return cents(value)


def checkout(cart):
    return cart.total(10)
""",
    )

    index = build_repository_index(tmp_path)

    module = index.module_for_path("src/service.py")
    assert module is not None
    assert module.module == "src.service"
    assert [(item.name, item.kind) for item in module.symbols] == [
        ("Cart", "class"),
        ("Cart.total", "method"),
        ("checkout", "function"),
    ]
    assert module.imports == (ImportInfo("helpers.money", ("cents",)),)


def test_index_skips_excluded_and_keeps_parse_error(tmp_path):
    write(tmp_path / ".venv/ignored.py", "VALUE = 1")
    write(tmp_path / ".pyrepair/ignored.py", "VALUE = 2")
    write(tmp_path / "broken.py", "def broken(:")

    index = build_repository_index(tmp_path)

    assert [item.path for item in index.modules] == ["broken.py"]
    assert index.modules[0].parse_error == "SyntaxError"


def test_symbol_lookup_finds_qualified_methods_in_stable_order(tmp_path):
    write(tmp_path / "src/zoo.py", "def total():\n    return 1")
    write(
        tmp_path / "src/cart.py",
        """
class Cart:
    def total(self):
        return 2
""",
    )

    index = build_repository_index(tmp_path)

    assert [(item.path, item.name) for item in index.symbols_named("total")] == [
        ("src/cart.py", "Cart.total"),
        ("src/zoo.py", "total"),
    ]


def test_import_neighbors_include_forward_and_reverse_dependencies(tmp_path):
    write(tmp_path / "src/helpers.py", "def cents(value):\n    return value * 100")
    write(
        tmp_path / "src/service.py",
        """
from src.helpers import cents


def total(value):
    return cents(value)
""",
    )
    write(tmp_path / "src/entry.py", "import src.service")

    index = build_repository_index(tmp_path)

    neighbors = index.import_neighbors("src/service.py")
    assert [item.path for item in neighbors] == ["src/entry.py", "src/helpers.py"]


def test_index_extracts_async_functions_and_methods(tmp_path):
    write(
        tmp_path / "src/client.py",
        """
async def fetch():
    return "ok"


class Client:
    async def send(self):
        return await fetch()
""",
    )

    module = build_repository_index(tmp_path).module_for_path("src/client.py")

    assert module is not None
    assert [(item.name, item.kind) for item in module.symbols] == [
        ("fetch", "function"),
        ("Client", "class"),
        ("Client.send", "method"),
    ]


def test_import_neighbors_resolve_relative_imports_and_submodules(tmp_path):
    write(tmp_path / "pkg/__init__.py", "from . import helper")
    write(tmp_path / "pkg/helper.py", "VALUE = 1")
    write(tmp_path / "pkg/service.py", "from .helper import VALUE")
    write(tmp_path / "pkg/entry.py", "from . import service")
    write(tmp_path / "consumer.py", "from pkg import helper")

    index = build_repository_index(tmp_path)

    assert [item.path for item in index.import_neighbors("pkg/service.py")] == [
        "pkg/entry.py",
        "pkg/helper.py",
    ]
    assert "consumer.py" in {
        item.path for item in index.import_neighbors("pkg/helper.py")
    }
