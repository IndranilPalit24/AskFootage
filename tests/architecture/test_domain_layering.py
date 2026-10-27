"""Layering rule: the domain depends on nothing but the standard library."""

import ast
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

DOMAIN_DIR = Path(__file__).resolve().parents[2] / "askfootage" / "domain"


def _imported_modules(source_file: Path) -> set[str]:
    tree = ast.parse(source_file.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.ImportFrom):
            modules.add(_resolve_relative_import(node.level, node.module))
    return modules


def _resolve_relative_import(level: int, module: str | None) -> str:
    """Absolute name of a relative import made from a file directly inside the domain.

    One leading dot is the domain package; two climb to its parent, askfootage.
    Python rejects climbing past the top-level package, so more dots never run.
    """
    package = "askfootage.domain" if level == 1 else "askfootage"
    return f"{package}.{module}" if module else package


def _forbidden_imports(source_file: Path) -> Iterator[str]:
    for module in sorted(_imported_modules(source_file)):
        if module.split(".")[0] in sys.stdlib_module_names:
            continue
        if module == "askfootage.domain" or module.startswith("askfootage.domain."):
            continue
        yield module


@pytest.mark.parametrize("source_file", sorted(DOMAIN_DIR.glob("*.py")), ids=lambda p: p.name)
def test_domain_module_imports_only_stdlib_and_domain(source_file: Path) -> None:
    assert list(_forbidden_imports(source_file)) == []


def test_the_check_itself_catches_a_forbidden_import(tmp_path: Path) -> None:
    offender = tmp_path / "offender.py"
    offender.write_text("import numpy\nfrom askfootage.adapters import meta\n", encoding="utf-8")
    assert list(_forbidden_imports(offender)) == ["askfootage.adapters", "numpy"]


def test_the_check_itself_catches_a_relative_import_out_of_the_domain(tmp_path: Path) -> None:
    offender = tmp_path / "offender.py"
    offender.write_text("from . import models\nfrom ..adapters import meta\n", encoding="utf-8")
    assert list(_forbidden_imports(offender)) == ["askfootage.adapters"]
