"""Application settings: the one place AskFootage reads its environment.

Values come from real environment variables first, then from the `.env` file in the
project root (copy `.env.example` to start one). No other module reads the environment:
code that needs a setting is handed a `Settings` object, and
tests/architecture/test_single_env_reader.py enforces that rule.

The Meta API key is held as a pydantic `SecretStr`, so printing, logging or serialising
the settings shows asterisks. Only `Settings.require_api_key()` returns the real value.
"""

from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_ENV_FILE = _PROJECT_ROOT / ".env"
"""The `.env` file in the project root, which load_settings() reads unless told otherwise."""

_UNSAFE_KEY_MESSAGE = (
    "contains a space, tab, newline or quote; write it as META_API_KEY=value "
    "with nothing around the value"
)
_MISSING_KEY_MESSAGE = (
    "META_API_KEY is not set. Add META_API_KEY=<your key> to the .env file in the "
    f"project root ({DEFAULT_ENV_FILE}; see .env.example), or set ASKFOOTAGE_DEMO=1 "
    "to replay saved responses instead of calling the Meta API."
)


class ConfigurationError(Exception):
    """A setting is invalid or missing; the message names each variable and the rule broken.

    The message never contains a rejected value, so it is safe to log or show.
    """


class MissingApiKeyError(ConfigurationError):
    """A live Meta API call needs META_API_KEY, and it is not set."""


class Settings(BaseSettings):
    """AskFootage's configuration, validated once at start-up and read-only afterwards.

    Get one from load_settings(), which turns validation failures into a
    ConfigurationError. Each field is filled from the environment variable named in its
    validation_alias.
    """

    model_config = SettingsConfigDict(
        env_ignore_empty=True,  # `META_API_KEY=` copied from .env.example means "not set"
        env_file_encoding="utf-8-sig",  # also reads files saved with a byte-order mark
        extra="ignore",  # a .env may hold variables meant for other tools
        frozen=True,
        hide_input_in_errors=True,  # pydantic's own messages must never show the key
    )

    api_key: SecretStr | None = Field(default=None, validation_alias="META_API_KEY")
    """Meta API key, or None when only demo mode will be used. Read it via require_api_key()."""

    api_base_url: str = Field(
        default="https://api.meta.ai/v1", validation_alias="META_API_BASE_URL"
    )
    """Base URL of the Meta API: https only, with no trailing slash."""

    max_run_cost_usd: Decimal = Field(
        default=Decimal("25"), gt=0, validation_alias="MAX_RUN_COST_USD"
    )
    """Most a single run may spend on API calls, in US dollars, as an exact Decimal."""

    data_dir: Path = Field(default=_PROJECT_ROOT / "data", validation_alias="DATA_DIR")
    """Where AskFootage keeps its working data; a relative path is under the project root."""

    demo_mode: bool = Field(default=False, validation_alias="ASKFOOTAGE_DEMO")
    """True to replay saved API responses instead of making live calls."""

    @field_validator("api_key", mode="before")
    @classmethod
    def _blank_or_safe_key(cls, value: object) -> object:
        # Rejected rather than trimmed: a key pasted with stray quotes or a line break
        # should be fixed where it was written, not silently altered here.
        if isinstance(value, str):
            if not value.strip():
                return None
            if any(char.isspace() or char in "'\"" for char in value):
                raise ValueError(_UNSAFE_KEY_MESSAGE)
        return value

    @field_validator("api_base_url")
    @classmethod
    def _https_without_trailing_slash(cls, value: str) -> str:
        url = value.strip().rstrip("/")
        if not url.startswith("https://") or not urlsplit(url).netloc:
            raise ValueError("must start with https:// followed by a host name")
        return url

    @field_validator("data_dir")
    @classmethod
    def _anchor_to_project_root(cls, value: Path) -> Path:
        return value if value.is_absolute() else _PROJECT_ROOT / value

    def require_api_key(self) -> str:
        """Return the real API key, for code about to make a live Meta API call.

        Raises MissingApiKeyError, saying how to fix it, when no key is configured.
        Keep the returned string out of logs, messages and exceptions.
        """
        if self.api_key is None:
            raise MissingApiKeyError(_MISSING_KEY_MESSAGE)
        return self.api_key.get_secret_value()

    def redacted_summary(self) -> dict[str, str]:
        """Every setting under its environment variable name, safe to print or log.

        The API key appears only as "set" or "not set", and demo mode as "on" or "off".
        """
        return {
            "META_API_KEY": "not set" if self.api_key is None else "set",
            "META_API_BASE_URL": self.api_base_url,
            "MAX_RUN_COST_USD": str(self.max_run_cost_usd),
            "DATA_DIR": str(self.data_dir),
            "ASKFOOTAGE_DEMO": "on" if self.demo_mode else "off",
        }


def load_settings(env_file: Path | None = DEFAULT_ENV_FILE) -> Settings:
    """Read and validate the settings; this is how the rest of AskFootage gets them.

    Real environment variables win over `env_file`. Pass env_file=None to read the
    environment alone; a file that does not exist is skipped, as every value has a
    default. Raises ConfigurationError with one "VARIABLE: rule broken" line per
    problem and none of the rejected values.
    """
    try:
        return Settings(_env_file=env_file)
    except ValidationError as error:
        problems = _describe(error)
    # Raised outside the except block, so the ValidationError (whose details still hold
    # the raw input) is not attached as __context__. `from None` keeps it unchained even
    # if this line is ever moved inside the block.
    raise ConfigurationError(problems) from None


def _describe(error: ValidationError) -> str:
    lines = [
        f"{'.'.join(map(str, problem['loc']))}: {problem['msg'].removeprefix('Value error, ')}"
        for problem in error.errors(include_input=False, include_context=False)
    ]
    return "Invalid settings in the environment or .env file:\n" + "\n".join(lines)
