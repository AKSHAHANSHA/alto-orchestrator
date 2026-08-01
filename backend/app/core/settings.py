"""Typed application configuration.

Every value is validated at startup. Configuration that lies about its type —
an `int` field holding a string because it came from `os.environ.get` — fails
in production at the worst possible moment, so nothing here is untyped.

Business rules deliberately do *not* live here. Confidence weights, slot
requirements and department mappings are in `domain/policies/*.yaml`, because
they are versioned business decisions rather than deployment configuration.
Only the routing *thresholds* appear here, so an operator can tighten
automation without a policy release.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, PostgresDsn, RedisDsn, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class ProviderName(StrEnum):
    MOCK = "mock"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Runtime ───────────────────────────────────────────────────────
    app_env: Literal["local", "staging", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # ── Postgres ──────────────────────────────────────────────────────
    postgres_user: str = "alto"
    postgres_password: str = "alto"
    postgres_db: str = "alto"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # ── Redis ─────────────────────────────────────────────────────────
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_ttl_seconds: int = 3600

    # ── Qdrant ────────────────────────────────────────────────────────
    # `qdrant_host` is either a bare host (local Docker, combined with the
    # port below) or a full `https://...cloud.qdrant.io` URL (Qdrant Cloud,
    # port already implied by the scheme).
    qdrant_host: str = "localhost"
    qdrant_http_port: int = 6333
    qdrant_api_key: str = ""

    # ── LLM providers ─────────────────────────────────────────────────
    llm_provider: ProviderName = ProviderName.MOCK

    openai_api_key: str = ""
    openai_fast_model: str = "gpt-5-mini"
    openai_premium_model: str = "gpt-4o"

    anthropic_api_key: str = ""
    anthropic_fast_model: str = "claude-haiku-4-5-20251001"
    anthropic_premium_model: str = "claude-opus-5"

    llm_daily_budget_usd: float = 5.00

    # ── Retrieval ─────────────────────────────────────────────────────
    dense_embedding_model: str = (
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    dense_embedding_dim: int = 384
    sparse_embedding_model: str = "Qdrant/bm25"
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"

    retrieval_prefetch_limit: int = Field(default=100, gt=0)
    retrieval_fusion_top_k: int = Field(default=20, gt=0)
    retrieval_rerank_top_k: int = Field(default=5, gt=0)
    retrieval_rrf_k: int = Field(default=2, gt=0)

    # ── Decision thresholds ───────────────────────────────────────────
    confidence_auto_threshold: float = Field(default=90.0, ge=0, le=100)
    confidence_premium_threshold: float = Field(default=75.0, ge=0, le=100)

    # Master kill-switch. Defaults to False so a fresh deployment cannot send
    # anything to a customer until someone deliberately turns it on.
    allow_auto_send: bool = False

    # ── Security ──────────────────────────────────────────────────────
    # Browser origins permitted to call the API. Configurable rather than
    # hardcoded, because the dev server port is not fixed and a wrong entry
    # fails as an opaque "failed to fetch" in the browser rather than as a
    # readable server error.
    cors_origins: str = "http://localhost:3000,http://localhost:3010"

    jwt_secret: str = "change-me-before-any-non-local-use"
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 720

    # ── Paths ─────────────────────────────────────────────────────────
    @computed_field  # type: ignore[prop-decorator]
    @property
    def data_dir(self) -> Path:
        return REPO_ROOT / "data"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def finance_docs_dir(self) -> Path:
        return self.data_dir / "knowledge" / "finance"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def policy_docs_dir(self) -> Path:
        return self.data_dir / "knowledge" / "policies"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def catalog_path(self) -> Path:
        return self.data_dir / "catalog" / "vehicles.csv"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def golden_set_path(self) -> Path:
        return self.data_dir / "eval" / "golden_set.jsonl"

    # ── Derived connection strings ────────────────────────────────────
    @computed_field  # type: ignore[prop-decorator]
    @property
    def postgres_dsn(self) -> str:
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=self.postgres_user,
                password=self.postgres_password,
                host=self.postgres_host,
                port=self.postgres_port,
                path=self.postgres_db,
            )
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def psycopg_dsn(self) -> str:
        """Synchronous DSN.

        LangGraph's Postgres checkpointer speaks psycopg rather than asyncpg,
        so the two coexist against the same database.
        """
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_dsn(self) -> str:
        return str(RedisDsn.build(scheme="redis", host=self.redis_host, port=self.redis_port))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def qdrant_url(self) -> str:
        if self.qdrant_host.startswith("http://") or self.qdrant_host.startswith("https://"):
            return self.qdrant_host
        return f"http://{self.qdrant_host}:{self.qdrant_http_port}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def allowed_origins(self) -> list[str]:
        """CORS origins, plus their 127.0.0.1 equivalents.

        Browsers treat `localhost` and `127.0.0.1` as distinct origins, and
        being strict about that distinction only ever produces confusing
        failures during local development.
        """
        origins: list[str] = []
        for entry in self.cors_origins.split(","):
            origin = entry.strip()
            if not origin:
                continue
            origins.append(origin)
            if "localhost" in origin:
                origins.append(origin.replace("localhost", "127.0.0.1"))
        return sorted(set(origins))

    # ── Cross-field validation ────────────────────────────────────────
    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.confidence_premium_threshold >= self.confidence_auto_threshold:
            raise ValueError(
                "confidence_premium_threshold must sit below confidence_auto_threshold; "
                f"got premium={self.confidence_premium_threshold} "
                f"auto={self.confidence_auto_threshold}"
            )

        # A provider selected without its key fails at the first customer
        # message. Better to refuse to boot.
        if self.llm_provider is ProviderName.OPENAI and not self.openai_api_key:
            raise ValueError("llm_provider=openai requires OPENAI_API_KEY to be set.")
        if self.llm_provider is ProviderName.ANTHROPIC and not self.anthropic_api_key:
            raise ValueError("llm_provider=anthropic requires ANTHROPIC_API_KEY to be set.")

        if self.retrieval_rerank_top_k > self.retrieval_fusion_top_k:
            raise ValueError(
                "retrieval_rerank_top_k cannot exceed retrieval_fusion_top_k — the "
                "reranker can only reorder what fusion returned."
            )
        if self.retrieval_fusion_top_k > self.retrieval_prefetch_limit:
            raise ValueError(
                "retrieval_fusion_top_k cannot exceed retrieval_prefetch_limit — "
                "fusion cannot return more candidates than were prefetched."
            )

        if self.is_production:
            if self.jwt_secret.startswith("change-me"):
                raise ValueError("JWT_SECRET must be set to a real secret in production.")
            if self.llm_provider is ProviderName.MOCK:
                raise ValueError("The mock LLM provider must not be used in production.")

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings, resolved once.

    Cached so that configuration cannot change mid-run — a threshold that
    shifted between two nodes of the same graph execution would make the
    resulting trace unreproducible.
    """
    return Settings()
