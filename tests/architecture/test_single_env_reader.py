"""Single-reader rule: only askfootage/settings.py reads the environment or a .env file.

Every other module is handed a Settings object instead. That keeps configuration to one
validated entry point, and leaves the API key one place to leak from instead of many.
"""

import ast
from pathlib import Path

import pytest

PACKAGE_DIR = Path(__file__).resolve().parents[2] / "askfootage"
SETTINGS_FILE = PACKAGE_DIR / "settings.py"
SOURCE_FILES = sorted(path for path in PACKAGE_DIR.rglob("*.py") if path != SETTINGS_FILE)

# Libraries whose whole job is reading .env files or the environment.
_ENV_READING_MODULES = {"dotenv", "pydantic_settings"}
# Names in `os` that read or change the process environment.
_ENV_NAMES_IN_OS = {"environ", "environb", "getenv", "getenvb", "putenv", "unsetenv"}


def _names_bound_to_os(tree: ast.Module) -> set[str]:
    """Local names for the os module: `import os`, `import os as o` and `import os.path`."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "os" or (alias.name.startswith("os.") and alias.asname is None):
                    names.add(alias.asname or "os")
    return names


def _env_access(source_file: Path) -> list[str]:
    """Each place the file reads or changes the environment, as 'line N: what', in line order."""
    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    os_names = _names_bound_to_os(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in _ENV_READING_MODULES:
                    found.append((node.lineno, f"import {alias.name}"))
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module.split(".")[0] in _ENV_READING_MODULES:
                found.append((node.lineno, f"from {node.module} import ..."))
            elif node.module == "os":
                for alias in node.names:
                    if alias.name in _ENV_NAMES_IN_OS or alias.name == "*":
                        found.append((node.lineno, f"from os import {alias.name}"))
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in os_names
            and node.attr in _ENV_NAMES_IN_OS
        ):
            found.append((node.lineno, f"{node.value.id}.{node.attr}"))
    return [f"line {line}: {what}" for line, what in sorted(found)]


@pytest.mark.parametrize(
    "source_file", SOURCE_FILES, ids=lambda path: path.relative_to(PACKAGE_DIR).as_posix()
)
def test_only_settings_reads_the_environment(source_file: Path) -> None:
    assert _env_access(source_file) == []


def test_the_scan_covers_the_whole_package_except_settings() -> None:
    assert SETTINGS_FILE.is_file()
    assert SETTINGS_FILE not in SOURCE_FILES
    assert PACKAGE_DIR / "adapters" / "meta" / "client.py" in SOURCE_FILES


def test_the_check_itself_catches_every_kind_of_environment_access(tmp_path: Path) -> None:
    offender = tmp_path / "offender.py"
    offender.write_text(
        "import os\n"
        "import os as system\n"
        "from os import getenv\n"
        "from os import environ as env\n"
        "from os import *\n"
        "import dotenv\n"
        "from pydantic_settings import BaseSettings\n"
        "value = os.getenv('X')\n"
        "os.environ['X'] = '1'\n"
        "system.putenv('X', '1')\n",
        encoding="utf-8",
    )
    assert _env_access(offender) == [
        "line 3: from os import getenv",
        "line 4: from os import environ",
        "line 5: from os import *",
        "line 6: import dotenv",
        "line 7: from pydantic_settings import ...",
        "line 8: os.getenv",
        "line 9: os.environ",
        "line 10: system.putenv",
    ]


def test_the_check_itself_passes_a_clean_file(tmp_path: Path) -> None:
    clean = tmp_path / "clean.py"
    clean.write_text(
        "import os\n"
        "import os.path as osp\n"
        "from os import path\n"
        "from askfootage.settings import load_settings\n"
        "here = os.path.join('a', 'b')\n"
        "there = osp.join('a', 'b')\n"
        "def demo(settings): return settings.environ\n",
        encoding="utf-8",
    )
    assert _env_access(clean) == []
