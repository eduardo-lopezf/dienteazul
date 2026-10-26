"""Application configuration via environment variables."""

from typing import Final

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class InsecureSecretError(RuntimeError):
    """A production deployment carries a secret that cannot protect anything.

    Raised at settings construction, so the process refuses to start
    (ADR 0029, invariant 6). This is the one security invariant that
    blocks rather than warns: ADR 0027 and ADR 0028 report, because
    taking a working clinic offline over a commercial rule is the worse
    trade. A forgeable signing key is not that trade — every JWT the
    deployment would ever issue is mintable by anyone who reads the
    example ``.env``.
    """


# The levels ``LOG_LEVEL`` accepts, in the order a reader expects.
_LOG_LEVELS: Final = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

# Minimum for HS256: the key is the whole security of every token.
# ``openssl rand -hex 32`` yields 64 characters, comfortably over.
_MIN_SECRET_LENGTH: Final = 32

# Substrings that mark a value as a placeholder someone forgot to
# replace rather than a secret. Matched case-insensitively. Kept
# unambiguous on purpose: a marker that could plausibly occur inside a
# real random secret would reject good deployments, which is how a
# check like this gets disabled.
_PLACEHOLDER_MARKERS: Final = (
    "your_secret",
    "your-secret",
    "secret_key_here",
    "changeme",
    "change_me",
    "change-me",
    "placeholder",
    "insecure",
    "dental_dev",
    "dienteazul_dev",
)

# A hex-32 secret draws from 16 symbols, so "distinct characters" is a
# blunt instrument. It is set low deliberately: this catches "aaaa…"
# and "12341234…", not weak-but-plausible keys, which length and the
# placeholder list cover.
_MIN_DISTINCT_CHARS: Final = 8


def _reject_weak_secret(name: str, value: str) -> None:
    """Raise if ``value`` cannot serve as a production signing key."""
    hint = f"Generate one with: openssl rand -hex 32, then set {name}."

    if len(value) < _MIN_SECRET_LENGTH:
        raise InsecureSecretError(
            f"{name} is {len(value)} characters; production requires at least "
            f"{_MIN_SECRET_LENGTH}. {hint}"
        )

    lowered = value.lower()
    for marker in _PLACEHOLDER_MARKERS:
        if marker in lowered:
            raise InsecureSecretError(
                f"{name} still looks like the placeholder from .env.example "
                f"(contains {marker!r}). {hint}"
            )

    if len(set(value)) < _MIN_DISTINCT_CHARS:
        raise InsecureSecretError(
            f"{name} uses only {len(set(value))} distinct characters and is not "
            f"plausibly random. {hint}"
        )


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    DATABASE_URL: str
    # Connections each backend process may hold: ``DB_POOL_SIZE`` kept
    # open, ``DB_MAX_OVERFLOW`` more under load. Every process has its own
    # pool, so with several backends the sum of both across all of them
    # has to stay under PostgreSQL's ``max_connections`` (100 unless the
    # server says otherwise) with room left for migrations and ``psql``.
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # Security
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    AUTH_SESSION_MAX_FAMILY_DAYS: int = Field(default=30, gt=0)
    AUTH_SESSION_IDLE_TIMEOUT_MINUTES: int = Field(default=60, gt=0)
    ALGORITHM: str = "HS256"
    # Independent secret used to sign the public-budget verification
    # cookies (ADR 0006). Falls back to ``SECRET_KEY`` for local/dev
    # convenience, but production deploys must set it explicitly so a
    # leak of one key does not compromise the other.
    BUDGET_PUBLIC_SECRET_KEY: str = ""

    # Environment
    ENVIRONMENT: str = "development"
    ALLOWED_ORIGINS: str = ""

    # Tenant custody and regime (ADR 0023). These describe *this*
    # deployment; a SaaS control plane supplies them per tenant instead.
    #
    # Defaults to ``managed`` because that is what this product is: we
    # run the deployment and hold its keys. A self-hoster overrides it.
    #
    # **The controls each mode names are not implemented yet.**
    # ``managed`` promises break-glass operator access — bounded,
    # justified, disclosed — and there is no such mechanism; today an
    # operator's access is simply standing. ``byok`` is out of scope for
    # this stage entirely. The mode is an accurate statement of *who
    # holds what*, and not yet a statement about enforced controls.
    TENANT_CUSTODY_MODE: str = "managed"
    # Comma-separated ISO 3166-1 alpha-2 codes. Decides which government
    # documents count as identifiers for the PHI boundary (ADR 0025).
    # Both markets by default: verifactu files with the Spanish AEAT
    # while the default currency is MXN.
    TENANT_JURISDICTIONS: str = "MX,ES"
    # Where the data physically lives — a region id, or ``on-prem``.
    # Left empty it resolves to ``on-prem`` under ``self`` (true by
    # definition) and to ``unspecified`` otherwise, with a warning: a
    # hosted deployment that cannot say where the data lives has not
    # answered the question a clinic is asking, and saying ``on-prem``
    # for it would be a lie rather than a gap.
    TENANT_DATA_RESIDENCY: str = ""
    # Comma-separated destination ids this deployment has contracted for
    # (``openai``, ``kapso``, ``aeat``, ``smtp``). Default-deny, so an
    # empty value means every module that calls out is reported at boot.
    # It is a report, not a block — see ADR 0027 for why.
    TENANT_EGRESS_ALLOWED: str = ""

    # Shared with the control plane (ADR 0049 rule 4): it signs the
    # short-lived tokens that open ``/api/v1/ops``, where an operator reads
    # what each clinic consumes — sizes, counts and identifiers, never
    # content. Empty, which is the default, means those routes do not
    # exist. They do not exist under ``self`` custody either, whatever
    # this holds.
    CONTROL_PLANE_SECRET: str = ""

    # Logging
    #
    # How much is written. One of DEBUG, INFO, WARNING, ERROR, CRITICAL;
    # anything else refuses at boot rather than silently logging nothing,
    # which is the failure mode of a misspelled level.
    LOG_LEVEL: str = "INFO"
    # Where a copy of the log is kept. Empty — the default — means the
    # process only writes to stdout, which is what `docker-compose logs`
    # and the platform's collector read. Set it to a directory and the
    # same lines are also appended to ``<LOG_DIR>/dienteazul.log``; the
    # directory is created if it is missing.
    #
    # **One writer per file.** The rotating handler lives in the process,
    # so with several backends (ADR 0051) each rolls the file over on its
    # own and they overwrite each other's rollovers. With replicas, give
    # each one its own LOG_DIR, or leave this empty and let the platform
    # collect stdout.
    LOG_DIR: str = ""
    # Where the requests that ended in a server error are kept, one JSON
    # line each, for the control panel to read (ADR 0060). Unlike
    # ``LOG_DIR`` this always writes: it is the panel's only source, so
    # an empty value would mean an operator with nothing to look at.
    # ``/var/log`` is the standard place for a service's logs; the image
    # creates this directory and gives it to the app's user, and
    # docker-compose mounts it so it outlives the container.
    ERROR_LOG_DIR: str = "/var/log/dienteazul"
    # Retention is the rotation: at most this many bytes per file, and
    # this many rolled files kept beside the live one. It replaced the
    # thirty-day purge the database table did.
    ERROR_LOG_MAX_BYTES: int = 5 * 1024 * 1024
    ERROR_LOG_BACKUP_COUNT: int = 3

    # Rollover threshold for that file, in bytes. 10 MiB.
    LOG_MAX_BYTES: int = 10 * 1024 * 1024
    # How many rolled files to keep beside the live one, so the whole set
    # is bounded at roughly ``LOG_MAX_BYTES * (LOG_BACKUP_COUNT + 1)``.
    LOG_BACKUP_COUNT: int = 5

    # Rate limiting
    LOGIN_RATE_LIMIT: str = "5/minute"
    REGISTER_RATE_LIMIT: str = "3/hour"
    # Where the limiter keeps its counters. Empty keeps them in the
    # process, which is right for one backend. With several, each would
    # count for itself and "5 logins a minute" becomes 5 per backend: give
    # them one store, e.g. ``redis://redis:6379/0``. That needs the Redis
    # client in the image — the ``redis`` extra in pyproject.toml, which a
    # default build does not install. If the store stops answering, each
    # process falls back to counting in memory until it is back.
    RATE_LIMIT_STORAGE_URI: str = ""

    # Testing
    TESTING: bool = False

    # Whether this process runs the periodic jobs (``app/core/scheduler.py``).
    # The scheduler lives in the process, so every backend that has it on
    # runs every job: two of them send each reminder twice. With one
    # backend, leave it on. With several, exactly one has it on and the
    # rest set it to ``false`` — nothing checks that, and with it off
    # everywhere no job runs at all.
    SCHEDULER_ENABLED: bool = True

    # Module system
    DIENTEAZUL_DEV_MODULE_SCAN: bool = True  # Fallback filesystem scan for dev
    # Host-mounted path where `frontend/modules.json` lives. The backend
    # writes this file whenever a module with a Nuxt layer is
    # installed/uninstalled so the Nuxt host picks up `extends` on next
    # build. docker-compose mounts `./frontend` → `/host_frontend`.
    DIENTEAZUL_FRONTEND_ROOT: str = "/host_frontend"
    # Absolute path INSIDE the frontend container where
    # `backend/app/modules` is mounted (see docker-compose). The writer
    # uses this prefix when rendering layer paths in `modules.json` so
    # the frontend container can resolve them with `extends`. In
    # production (single container / bundled deploy) this can be set to
    # the same path the backend sees for modules, in which case no
    # translation happens.
    DIENTEAZUL_MODULE_LAYERS_MOUNT: str = "/module_layers"
    # The backend-container path at which module packages live. Stripped
    # from absolute layer paths before the MOUNT prefix is applied. Rare
    # to override; exists for non-standard container layouts.
    DIENTEAZUL_MODULE_PKG_ROOT: str = "/app/app/modules"

    # Storage configuration
    STORAGE_BACKEND: str = "local"
    STORAGE_LOCAL_PATH: str = "/app/storage"
    STORAGE_MAX_FILE_SIZE: int = 10 * 1024 * 1024  # 10MB
    STORAGE_ALLOWED_MIME_TYPES: str = "application/pdf,image/jpeg,image/png"

    @property
    def storage_allowed_mime_types_list(self) -> list[str]:
        """Parse allowed MIME types as list."""
        return [t.strip() for t in self.STORAGE_ALLOWED_MIME_TYPES.split(",")]

    # Email configuration
    EMAIL_ENABLED: bool = True
    EMAIL_PROVIDER: str = "console"  # console, smtp (sendgrid, mailgun in future)

    # SMTP configuration
    EMAIL_SMTP_HOST: str = "smtp.gmail.com"
    EMAIL_SMTP_PORT: int = 587
    EMAIL_SMTP_TLS: bool = True
    EMAIL_SMTP_USER: str = ""
    EMAIL_SMTP_PASSWORD: str = ""

    # Default sender
    EMAIL_FROM_ADDRESS: str = "noreply@dienteazul.com"
    EMAIL_FROM_NAME: str = "Diente Azul"

    # Copilot / agentic layer (app/core/llm/). OpenAI is the only live
    # provider in v1; per-clinic `copilot_settings` overrides provider +
    # model. (ANTHROPIC_API_KEY + its model default land with that
    # provider.)
    OPENAI_API_KEY: str = ""
    COPILOT_PROVIDER_DEFAULT: str = "openai"
    COPILOT_MODEL_CHAT_OPENAI: str = "gpt-5.4-mini"
    COPILOT_MAX_TOKENS: int = 4096
    COPILOT_REDACTION_DEFAULT: bool = True

    @property
    def allowed_origins_list(self) -> list[str]:
        """Parse ALLOWED_ORIGINS as comma-separated list."""
        if not self.ALLOWED_ORIGINS:
            return []
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",")]

    @field_validator("LOG_LEVEL")
    @classmethod
    def _known_log_level(cls, value: str) -> str:
        """A level nobody recognises is silence, so say so at boot.

        ``logging.getLevelName`` answers ``"Level WARN"`` for anything it
        does not know instead of raising, and the root logger ends up at
        a numeric level that drops everything — a deployment that looks
        configured and logs nothing.
        """
        level = value.strip().upper()
        if level not in _LOG_LEVELS:
            raise ValueError(
                f"LOG_LEVEL={value!r} is not a logging level. Use one of: {', '.join(_LOG_LEVELS)}."
            )
        return level

    @model_validator(mode="after")
    def _refuse_weak_production_secrets(self) -> "Settings":
        """Refuse to start a production deployment on unusable secrets.

        Only ``production`` is checked. Development and the test suite
        run on throwaway keys by design, and enforcing this there would
        buy nothing but friction (ADR 0029, invariant 6).

        ``BUDGET_PUBLIC_SECRET_KEY`` is checked *and* required to differ
        from ``SECRET_KEY``: its whole reason to exist is that a leak of
        the staff-JWT key must not also open every patient's budget
        (ADR 0006). Left empty it silently falls back and that
        separation quietly disappears — which is the failure this
        catches.
        """
        if self.ENVIRONMENT != "production":
            return self

        _reject_weak_secret("SECRET_KEY", self.SECRET_KEY)

        if not self.BUDGET_PUBLIC_SECRET_KEY:
            raise InsecureSecretError(
                "BUDGET_PUBLIC_SECRET_KEY is unset, so it falls back to SECRET_KEY "
                "and the public-budget cookies are signed with the staff-JWT key "
                "(ADR 0006 wanted them independent). Generate one with: "
                "openssl rand -hex 32."
            )

        _reject_weak_secret("BUDGET_PUBLIC_SECRET_KEY", self.BUDGET_PUBLIC_SECRET_KEY)

        if self.BUDGET_PUBLIC_SECRET_KEY == self.SECRET_KEY:
            raise InsecureSecretError(
                "BUDGET_PUBLIC_SECRET_KEY is identical to SECRET_KEY. Two names for "
                "one key is not two keys: a leak of either compromises both, and "
                "neither can be rotated alone."
            )

        return self

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
