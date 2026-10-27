"""Behaviour of askfootage.settings: validated, read-only settings that keep the key secret.

No test touches the real .env in the project root. Each one hands load_settings() its
own temporary env file or env_file=None, and an autouse fixture first removes the five
AskFootage variables from the process environment.
"""

import traceback
from collections.abc import Callable
from decimal import Decimal
from inspect import signature
from pathlib import Path

import pytest
from pydantic import ValidationError

from askfootage.settings import (
    DEFAULT_ENV_FILE,
    ConfigurationError,
    MissingApiKeyError,
    Settings,
    load_settings,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_NAMES = (
    "META_API_KEY",
    "META_API_BASE_URL",
    "MAX_RUN_COST_USD",
    "DATA_DIR",
    "ASKFOOTAGE_DEMO",
)
# Obviously fake and low-entropy, so no secret scanner mistakes these for real keys.
FAKE_KEY = "not-a-real-key"
REJECTED_KEY = "not a-real-key"  # the space is what gets it rejected


@pytest.fixture(autouse=True)
def _no_askfootage_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def _write_env_file(directory: Path, *lines: str, name: str = "test.env") -> Path:
    env_file = directory / name
    env_file.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return env_file


def _configuration_error(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> str:
    monkeypatch.setenv(name, value)
    with pytest.raises(ConfigurationError) as excinfo:
        load_settings(env_file=None)
    return str(excinfo.value)


# --- Where values come from ---------------------------------------------------------------


def test_loads_all_five_values_from_an_env_file(tmp_path: Path) -> None:
    data_dir = tmp_path / "footage"
    env_file = _write_env_file(
        tmp_path,
        f"META_API_KEY={FAKE_KEY}",
        "META_API_BASE_URL=https://api.example.test/v2",
        "MAX_RUN_COST_USD=12.50",
        f"DATA_DIR='{data_dir}'",
        "ASKFOOTAGE_DEMO=1",
    )

    settings = load_settings(env_file)

    assert settings.require_api_key() == FAKE_KEY
    assert settings.api_base_url == "https://api.example.test/v2"
    assert settings.max_run_cost_usd == Decimal("12.50")
    assert settings.data_dir == data_dir
    assert settings.demo_mode is True


def test_defaults_apply_when_nothing_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # the default data dir must not follow the working directory

    settings = load_settings(env_file=None)

    assert settings.api_key is None
    assert settings.api_base_url == "https://api.meta.ai/v1"
    assert settings.max_run_cost_usd == Decimal("25")
    assert settings.data_dir == PROJECT_ROOT / "data"
    assert settings.demo_mode is False


def test_a_real_environment_variable_beats_the_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = _write_env_file(tmp_path, "MAX_RUN_COST_USD=10")
    monkeypatch.setenv("MAX_RUN_COST_USD", "3")
    assert load_settings(env_file).max_run_cost_usd == Decimal("3")


def test_unknown_variables_in_the_env_file_are_ignored(tmp_path: Path) -> None:
    env_file = _write_env_file(tmp_path, "SOME_OTHER_TOOL_SETTING=1", "ASKFOOTAGE_DEMO=1")
    assert load_settings(env_file).demo_mode is True


def test_a_missing_env_file_is_not_an_error(tmp_path: Path) -> None:
    assert load_settings(tmp_path / "absent.env") == load_settings(env_file=None)


def test_no_env_file_means_none_is_read_even_from_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_env_file(tmp_path, "ASKFOOTAGE_DEMO=1", name=".env")
    monkeypatch.chdir(tmp_path)
    assert load_settings(env_file=None).demo_mode is False


def test_an_env_file_saved_with_a_byte_order_mark_is_read(tmp_path: Path) -> None:
    # Windows PowerShell 5.1 and Notepad can both save UTF-8 with a BOM.
    env_file = tmp_path / "bom.env"
    env_file.write_text("ASKFOOTAGE_DEMO=1\n", encoding="utf-8-sig")
    assert load_settings(env_file).demo_mode is True


def test_load_settings_reads_the_project_env_file_by_default() -> None:
    # Checked through the signature, because calling it would read the real .env.
    assert signature(load_settings).parameters["env_file"].default == DEFAULT_ENV_FILE


def test_the_default_env_file_is_the_dotenv_in_the_project_root() -> None:
    assert DEFAULT_ENV_FILE.is_absolute()
    assert DEFAULT_ENV_FILE.name == ".env"
    assert DEFAULT_ENV_FILE == PROJECT_ROOT / ".env"


# --- Blank means "not set" -------------------------------------------------------------------


def test_a_blank_key_in_the_env_file_means_no_key(tmp_path: Path) -> None:
    env_file = _write_env_file(tmp_path, "META_API_KEY=")
    assert load_settings(env_file).api_key is None


@pytest.mark.parametrize("blank", [" ", "   ", "\t"], ids=["space", "spaces", "tab"])
def test_a_whitespace_only_key_means_no_key(monkeypatch: pytest.MonkeyPatch, blank: str) -> None:
    monkeypatch.setenv("META_API_KEY", blank)
    assert load_settings(env_file=None).api_key is None


def test_a_blank_base_url_falls_back_to_the_default(tmp_path: Path) -> None:
    env_file = _write_env_file(tmp_path, "META_API_BASE_URL=")
    assert load_settings(env_file).api_base_url == "https://api.meta.ai/v1"


def test_a_copied_env_example_with_every_value_blank_gives_the_defaults(tmp_path: Path) -> None:
    env_file = _write_env_file(tmp_path, *(f"{name}=" for name in ENV_NAMES))
    assert load_settings(env_file) == load_settings(env_file=None)


# --- The API key stays secret ----------------------------------------------------------------


def test_require_api_key_explains_the_fix_when_the_key_is_missing() -> None:
    settings = load_settings(env_file=None)

    with pytest.raises(MissingApiKeyError) as excinfo:
        settings.require_api_key()

    message = str(excinfo.value)
    assert "META_API_KEY" in message
    assert "project root" in message
    assert ".env.example" in message
    assert "ASKFOOTAGE_DEMO=1" in message


def test_a_missing_key_is_a_configuration_error() -> None:
    assert issubclass(MissingApiKeyError, ConfigurationError)


@pytest.mark.parametrize(
    "render",
    [repr, str, lambda settings: str(settings.redacted_summary()), Settings.model_dump_json],
    ids=["repr", "str", "redacted_summary", "model_dump_json"],
)
def test_the_key_never_appears_when_settings_are_printed(
    tmp_path: Path, render: Callable[[Settings], str]
) -> None:
    settings = load_settings(_write_env_file(tmp_path, f"META_API_KEY={FAKE_KEY}"))
    assert settings.require_api_key() == FAKE_KEY  # the key really was loaded
    assert FAKE_KEY not in render(settings)


def test_redacted_summary_lists_exactly_the_five_variables() -> None:
    assert sorted(load_settings(env_file=None).redacted_summary()) == sorted(ENV_NAMES)


@pytest.mark.parametrize(
    ("line", "shown"), [(f"META_API_KEY={FAKE_KEY}", "set"), ("META_API_KEY=", "not set")]
)
def test_redacted_summary_shows_only_whether_the_key_is_set(
    tmp_path: Path, line: str, shown: str
) -> None:
    summary = load_settings(_write_env_file(tmp_path, line)).redacted_summary()
    assert summary["META_API_KEY"] == shown


@pytest.mark.parametrize(("flag", "shown"), [("1", "on"), ("0", "off")])
def test_redacted_summary_shows_demo_mode_as_on_or_off(
    tmp_path: Path, flag: str, shown: str
) -> None:
    env_file = _write_env_file(tmp_path, f"ASKFOOTAGE_DEMO={flag}")
    assert load_settings(env_file).redacted_summary()["ASKFOOTAGE_DEMO"] == shown


@pytest.mark.parametrize(
    "unsafe_key",
    [
        pytest.param("not a-real-key", id="space"),
        pytest.param(f" {FAKE_KEY}", id="leading-space"),
        pytest.param(f"{FAKE_KEY} ", id="trailing-space"),
        pytest.param("not\ta-real-key", id="tab"),
        pytest.param("not\na-real-key", id="newline"),
        pytest.param("not a-real-key", id="non-breaking-space"),
        pytest.param(f"'{FAKE_KEY}'", id="single-quotes"),
        pytest.param(f'"{FAKE_KEY}"', id="double-quotes"),
    ],
)
def test_an_unsafe_key_is_rejected_with_the_fix(
    monkeypatch: pytest.MonkeyPatch, unsafe_key: str
) -> None:
    message = _configuration_error(monkeypatch, "META_API_KEY", unsafe_key)
    assert any(
        line.startswith("META_API_KEY: ") and "META_API_KEY=value" in line
        for line in message.splitlines()
    )


def test_the_error_for_a_rejected_key_does_not_contain_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("META_API_KEY", REJECTED_KEY)
    with pytest.raises(ConfigurationError) as excinfo:
        load_settings(env_file=None)

    full_report = "".join(traceback.format_exception(excinfo.value))
    for text in (str(excinfo.value), repr(excinfo.value), full_report):
        assert "a-real-key" not in text


def test_the_error_for_a_rejected_key_does_not_chain_the_original_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # pydantic's ValidationError keeps the raw input in .errors(); it must not ride along.
    monkeypatch.setenv("META_API_KEY", REJECTED_KEY)
    with pytest.raises(ConfigurationError) as excinfo:
        load_settings(env_file=None)

    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__ is True
    assert excinfo.value.__context__ is None


# --- Error messages ---------------------------------------------------------------------------


def test_the_error_lists_every_broken_variable_on_its_own_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("META_API_BASE_URL", "http://api.example.test")
    lines = _configuration_error(monkeypatch, "MAX_RUN_COST_USD", "0").splitlines()
    assert any(line.startswith("META_API_BASE_URL: ") for line in lines)
    assert any(line.startswith("MAX_RUN_COST_USD: ") for line in lines)


@pytest.mark.parametrize(
    ("name", "bad_value"),
    [
        ("META_API_BASE_URL", "http://leaky-host.example.test"),
        ("MAX_RUN_COST_USD", "leaky-cost"),
        ("ASKFOOTAGE_DEMO", "leaky-flag"),
    ],
)
def test_the_error_never_echoes_a_rejected_value(
    monkeypatch: pytest.MonkeyPatch, name: str, bad_value: str
) -> None:
    message = _configuration_error(monkeypatch, name, bad_value)
    assert f"{name}: " in message
    assert "leaky" not in message


# --- Base URL ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("http://api.meta.ai/v1", id="http"),
        pytest.param("ftp://api.meta.ai/v1", id="ftp"),
        pytest.param("api.meta.ai/v1", id="bare-host"),
        pytest.param("https:", id="scheme-only"),
        pytest.param("https://", id="empty-after-trim"),
        pytest.param("  https:// ", id="spaces-around-nothing"),
        pytest.param("https:///v1", id="no-host"),
    ],
)
def test_a_base_url_without_https_and_a_host_is_rejected(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    message = _configuration_error(monkeypatch, "META_API_BASE_URL", url)
    assert "META_API_BASE_URL: " in message
    assert "https://" in message


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.test/v2/",
        "  https://api.example.test/v2  ",
        " https://api.example.test/v2/ ",
    ],
)
def test_the_base_url_loses_surrounding_spaces_and_a_trailing_slash(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("META_API_BASE_URL", url)
    assert load_settings(env_file=None).api_base_url == "https://api.example.test/v2"


# --- Cost limit -------------------------------------------------------------------------------


@pytest.mark.parametrize("limit", ["0", "-1", "abc", "nan", "inf"])
def test_an_unusable_cost_limit_is_rejected(monkeypatch: pytest.MonkeyPatch, limit: str) -> None:
    assert "MAX_RUN_COST_USD: " in _configuration_error(monkeypatch, "MAX_RUN_COST_USD", limit)


def test_the_cost_limit_is_an_exact_decimal_not_a_float(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_RUN_COST_USD", "0.1")
    limit = load_settings(env_file=None).max_run_cost_usd
    assert type(limit) is Decimal
    assert limit == Decimal("0.1")  # a detour through float would give 0.1000000000000000055...


# --- Data directory ---------------------------------------------------------------------------


def test_a_relative_data_dir_is_anchored_to_the_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATA_DIR", "footage/run1")
    assert load_settings(env_file=None).data_dir == PROJECT_ROOT / "footage" / "run1"


def test_an_absolute_data_dir_is_used_as_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert load_settings(env_file=None).data_dir == tmp_path


# --- Demo flag --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spelling", "expected"),
    [
        ("1", True),
        ("0", False),
        ("true", True),
        ("false", False),
        ("TRUE", True),
        ("False", False),
        ("yes", True),
        ("no", False),
        ("YES", True),
        ("No", False),
        ("on", True),
        ("off", False),
        ("On", True),
        ("OFF", False),
    ],
)
def test_the_demo_flag_accepts_common_spellings_in_any_case(
    monkeypatch: pytest.MonkeyPatch, spelling: str, expected: bool
) -> None:
    monkeypatch.setenv("ASKFOOTAGE_DEMO", spelling)
    assert load_settings(env_file=None).demo_mode is expected


@pytest.mark.parametrize("spelling", ["maybe", "2"])
def test_an_unrecognised_demo_flag_is_rejected(
    monkeypatch: pytest.MonkeyPatch, spelling: str
) -> None:
    assert "ASKFOOTAGE_DEMO: " in _configuration_error(monkeypatch, "ASKFOOTAGE_DEMO", spelling)


# --- Read-only ------------------------------------------------------------------------------


def test_settings_cannot_be_changed_after_loading() -> None:
    settings = load_settings(env_file=None)
    with pytest.raises(ValidationError, match="frozen"):
        settings.demo_mode = True
