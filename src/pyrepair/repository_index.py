from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .workspace import EXCLUDED_NAMES


# 创建数据结构骨架
@dataclass(frozen=True)
class SymbolInfo:  # 记录函数、类、方法的位置
    path: str
    name: str
    kind: Literal["function", "class", "method"]
    start_line: int
    end_line: int


@dataclass(frozen=True)  # 记录一条 import
class ImportInfo:
    module: str
    names: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModuleInfo:  # 记录一个 Python 文件的分析结果
    path: str
    module: str
    symbols :tuple[SymbolInfo, ...]
    imports :tuple[ImportInfo, ...]
    parse_error: str | None = None



@dataclass(frozen=True)
class RepositoryIndex:  # 保存整个仓库所有 Python 文件的索引
    root: Path
    modules: tuple[ModuleInfo, ...]

    def module_for_path(self, path: str | Path) -> ModuleInfo | None:  # 按文件路径查它的分析
        normalized = str(path).replace("\\","/")
        for module in self.modules:
            if module.path == normalized:
                return module
        return None

    def symbols_named(self, name: str) -> tuple[SymbolInfo, ...]:  # 按名字查符号定义
        result: list[SymbolInfo] = []

        for module in self.modules:
            for symbol in module.symbols:
                short_name = symbol.name.rsplit(".", 1)[-1]  # 把带点名字（calc.add）拆出短名（add）
                if symbol.name == name or short_name == name:
                    result.append(symbol)

        return tuple(
            sorted(
                result,
                key=lambda item: (item.path, item.start_line, item.name),
                )  # 返回排序后的结果（按 文件 → 起始行 → 名字），保证确定性
            )

    def import_neighbors(self, path: str | Path) -> tuple[ModuleInfo, ...]:  # 给定一个文件，找出所有和它"有 import 关系"的项目内文件——它 import 了谁、谁 import 了它
        current = self.module_for_path(path)
        if current is None:
            return ()

        modules_by_name = {
            module.module: module for module in self.modules  # 名字→模块 # module.module模块对象的 .module 属性
        }
        neighbor_paths: set[str] = set()  # 收集邻居（set 去重）

        # 正向关系：当前文件 import 了哪些项目文件
        for imported in current.imports:
            neighbor = modules_by_name.get(imported.module)
            if neighbor is not None:
                neighbor_paths.add(neighbor.path)

        # 反向关系：哪些项目文件 import 了当前文件
        for module in self.modules:
            if module.path == current.path:
                continue

            imported_names = {
                imported.module for imported in module.imports
            }
            if current.module in imported_names:
                neighbor_paths.add(module.path)

        return tuple(
            module for module in self.modules if module.path in neighbor_paths
        )

def _module_name(path:Path) -> str:  # 把文件路径转换成模块名
    without_suffix = path.with_suffix("")
    parts = list(without_suffix.parts)

    if parts and parts[-1] == "__init__":
        parts.pop()

    return ".".join(parts)


class _ModuleVisitor(ast.NodeVisitor):  # 使用 AST 提取类、方法、函数和 import
    def __init__(self, path: str) -> None:
        self.path = path
        self.symbols: list[SymbolInfo] = []
        self.imports: list[ImportInfo] = []
        self.class_stack: list[str] = []
        self.function_depth = 0

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qualified_name = ".".join([*self.class_stack, node.name])

        self.symbols.append(
            SymbolInfo(
                path=self.path,
                name=qualified_name,
                kind="class",
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
            )
        )

        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        # 不记录函数内部再次定义的局部函数
        if self.function_depth == 0:
            if self.class_stack:
                name = ".".join([*self.class_stack, node.name])
                kind: Literal["function","method"] = "method"
            else:
                name = node.name
                kind = "function"

            self.symbols.append(
                SymbolInfo(
                    path=self.path,
                    name=name,
                    kind=kind,
                    start_line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                )
            )
        self.function_depth += 1
        self.generic_visit(node)
        self.function_depth -= 1

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(
                ImportInfo(module=alias.name)
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = "." * node.level + (node.module or "")
        names = tuple(alias.name for alias in node.names)

        self.imports.append(
            ImportInfo(module=module, names=names)
        )


def _module_info(path: Path, tree: ast.AST) -> ModuleInfo:  # 把一个 AST 转成 ModuleInfo
    relative_path = path.as_posix()
    visitor = _ModuleVisitor(relative_path)
    visitor.visit(tree)

    symbols = tuple(
        sorted(
            visitor.symbols,
            key=lambda item: (
                item.start_line,
                item.name,
                item.kind,
            ),
        )
    )

    imports = tuple(
        sorted(
            visitor.imports,
            key=lambda item: (item.module, item.names),
        )
    )

    return ModuleInfo(
        path=relative_path,
        module=_module_name(path),
        symbols=symbols,
        imports=imports,
    )

def build_repository_index(root: Path) -> RepositoryIndex:  # 扫描整个仓库
    resolved_root = root.resolve()
    modules: list[ModuleInfo] = []

    paths = sorted(
        resolved_root.rglob("*.py"),
        key=lambda item: item.relative_to(resolved_root).as_posix(),
    )

    for path in paths:
        relative = path.relative_to(resolved_root)

        if not path.is_file():
            continue

        if any(part in EXCLUDED_NAMES for part in relative.parts):
            continue

        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(
                source,
                filename=relative.as_posix(),
            )
        except UnicodeDecodeError:
            continue
        except SyntaxError:
            modules.append(
                ModuleInfo(
                    path=relative.as_posix(),
                    module=_module_name(relative),
                    symbols=(),
                    imports=(),
                    parse_error="SyntaxError",
                )
            )
            continue

        modules.append(_module_info(relative, tree))

    return RepositoryIndex(
        root=resolved_root,
        modules=tuple(modules),
    )

    
