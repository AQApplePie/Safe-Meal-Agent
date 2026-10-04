"""环境变量、模型和外部服务配置。"""

import json
from typing import List, Literal, Optional
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DASHSCOPE_COMPATIBLE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DASHSCOPE_RERANK_BASE_URL = "https://dashscope.aliyuncs.com/api/v1/services"


def _configured_pricing_models(raw: str) -> set[str]:
    """Validate pricing JSON used by Agent execution budgets."""

    payload = json.loads(raw or "{}")
    if not isinstance(payload, dict):
        raise ValueError("MODEL_PRICING_JSON must be an object")
    models: set[str] = set()
    for model, item in payload.items():
        if not isinstance(item, dict):
            raise ValueError(f"pricing for {model!r} must be an object")
        input_price = float(item.get("input_cost_per_million", 0))
        output_price = float(item.get("output_cost_per_million", 0))
        cached_price = float(item.get("cached_input_cost_per_million", input_price))
        if min(input_price, output_price, cached_price) < 0:
            raise ValueError("model prices cannot be negative")
        models.add(str(model))
    return models


class Settings(BaseSettings):
    """Application configuration loaded from ``.env`` and environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Application and HTTP API
    APP_ENV: Literal["development", "test", "production"] = "development"
    APP_NAME: str = "SafeMeal Agent"
    APP_VERSION: str = "0.1.2"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    HOST: str = "0.0.0.0"
    PORT: int = Field(default=8000, ge=1, le=65535)
    UPLOAD_DIR: str = "uploads"
    FILE_UPLOAD_MAX_MB: int = Field(default=2, ge=1)
    HTTP_MAX_BODY_MB: int = Field(default=12, ge=1, le=100)
    HTTP_RATE_LIMIT_PER_MINUTE: int = Field(default=120, ge=1, le=10_000)
    REDIS_RATE_LIMIT_URL: Optional[str] = None
    LLM_MAX_OUTPUT_TOKENS: int = Field(default=2_048, ge=64, le=32_768)
    MODEL_PRICING_JSON: str = "{}"
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"
    AUTH_JWT_SECRET: str = "development-only-change-me"
    AUTH_JWT_ISSUER: str = "safemeal"
    AUTH_JWT_AUDIENCE: str = "safemeal-api"
    AUTH_ACCESS_TOKEN_MINUTES: int = Field(default=15, ge=1, le=1_440)
    AUTH_REFRESH_TOKEN_DAYS: int = Field(default=30, ge=1, le=365)

    # Optional integrations
    ENABLE_LLM: bool = True
    ENABLE_EMBEDDINGS: bool = True
    ENABLE_MILVUS: bool = True
    ENABLE_NEO4J: bool = True
    ENABLE_EXTERNAL_RECIPE_SEARCH: bool = True
    EXTERNAL_RECIPE_ENDPOINT: str = "https://zh.wikibooks.org/w/api.php"
    EXTERNAL_RECIPE_TIMEOUT: float = Field(default=8.0, gt=0, le=30)
    REQUEST_UNDERSTANDING_BACKEND: Literal["rules", "local_model"] = "rules"
    REQUEST_UNDERSTANDING_MODEL_PATH: Optional[str] = None
    REQUEST_UNDERSTANDING_ENDPOINT: Optional[str] = None
    REQUEST_UNDERSTANDING_CATALOG_PATH: str = "training/nlu/recipe_catalog.json"
    REQUEST_UNDERSTANDING_TIMEOUT: float = Field(default=15.0, gt=0, le=120)
    REQUEST_UNDERSTANDING_CONFIDENCE_THRESHOLD: float = Field(
        default=0.7, ge=0, le=1
    )
    INTEGRATION_PROBE_TIMEOUT: float = Field(default=10.0, gt=0, le=60)

    # Alibaba Cloud DashScope through its OpenAI-compatible API.
    # OPENAI_* aliases are accepted for compatibility with OpenAI SDK-based tooling.
    LLM_MODEL: str = Field(
        default="qwen3-max",
        validation_alias=AliasChoices("LLM_MODEL", "OPENAI_MODEL"),
    )
    LLM_API_KEY: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "LLM_API_KEY", "DASHSCOPE_API_KEY", "OPENAI_API_KEY"
        ),
    )
    LLM_BASE_URL: str = Field(
        default=DASHSCOPE_COMPATIBLE_BASE_URL,
        validation_alias=AliasChoices(
            "LLM_BASE_URL", "OPENAI_API_BASE", "OPENAI_BASE_URL"
        ),
    )
    LLM_REQUEST_TIMEOUT: float = Field(default=90.0, gt=0, le=600)
    LLM_MAX_RETRIES: int = Field(default=2, ge=0, le=10)
    LLM_STRUCTURED_REPAIR_RETRIES: int = Field(default=1, ge=0, le=3)

    # DashScope text embeddings. The API key and base URL inherit the LLM
    # settings when omitted, so one Alibaba Cloud key is normally sufficient.
    EMBEDDING_MODEL: str = "text-embedding-v4"
    EMBEDDING_API_KEY: Optional[str] = None
    EMBEDDING_BASE_URL: Optional[str] = None
    EMBEDDING_DIMENSION: int = Field(default=1024, gt=0)

    # DashScope reranker uses a native endpoint rather than the compatible API.
    RERANK_ENABLED: bool = True
    RERANK_PROVIDER: Literal["custom", "jina", "voyage"] = "custom"
    RERANK_BASE_URL: str = DASHSCOPE_RERANK_BASE_URL
    RERANK_ENDPOINT: str = "/rerank/text-rerank/text-rerank"
    RERANK_MODEL: str = "qwen3-rerank"
    RERANK_API_KEY: Optional[str] = None
    RERANK_MAX_CANDIDATES: int = Field(default=20, ge=1, le=100)
    RERANK_TOP_N: int = Field(default=6, ge=1, le=100)
    RERANK_TIMEOUT: float = Field(default=30.0, gt=0, le=300)

    # MySQL
    DATABASE_URL: str = Field(min_length=1)
    DB_CONNECT_TIMEOUT: int = Field(default=10, ge=1, le=120)

    # Milvus
    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = Field(default=19530, ge=1, le=65535)
    MILVUS_COLLECTION: str = "recipes_current"
    MILVUS_INDEX_TYPE: str = "IVF_FLAT"
    MILVUS_METRIC_TYPE: str = "IP"
    MILVUS_LOAD_TIMEOUT: float = Field(default=30.0, gt=0, le=300)

    # Neo4j recipe knowledge graph
    NEO4J_URI: str = "bolt://localhost:17687"
    NEO4J_USER: Optional[str] = None
    NEO4J_PASSWORD: Optional[str] = None
    NEO4J_DATABASE: str = "neo4j"
    NEO4J_MAX_CONNECTION_LIFETIME: Optional[int] = Field(default=None, gt=0)
    NEO4J_CONNECTION_TIMEOUT: float = Field(default=10.0, gt=0, le=120)
    NEO4J_RECIPE_JSON_PATH: str = "data/recipe.json"
    NEO4J_INGREDIENT_JSON_PATH: Optional[str] = "data/neo4j/excipients.json"

    # Agent runtime
    MAX_ITERATIONS: int = Field(default=4, ge=1, le=6)
    AGENT_TIMEOUT: int = Field(default=300, gt=0, le=1800)
    AGENT_TOOL_TIMEOUT: float = Field(default=60.0, gt=0, le=300)
    AGENT_HISTORY_MESSAGES: int = Field(default=12, ge=0, le=100)
    AGENT_HISTORY_SCAN_MESSAGES: int = Field(default=40, ge=4, le=100)
    AGENT_CONTEXT_TOKEN_BUDGET: int = Field(default=6_000, ge=512, le=100_000)
    AGENT_RESPONSE_TOKEN_RESERVE: int = Field(default=1_200, ge=128, le=20_000)
    AGENT_MEMORY_RETRIEVAL_LIMIT: int = Field(default=20, ge=1, le=100)
    AGENT_MAX_TOOL_CALLS: int = Field(default=12, ge=1, le=100)
    AGENT_MAX_MODEL_TOKENS: int = Field(default=20_000, ge=1_000, le=1_000_000)
    AGENT_MAX_COST: float = Field(default=0.0, ge=0, le=1_000_000)
    AGENT_MAX_CONCURRENCY: int = Field(default=8, ge=1, le=100)
    STREAM_FIRST_PACKET_TIMEOUT: float = Field(default=8.0, gt=0, le=120)
    STREAM_CHUNK_CHARS: int = Field(default=64, ge=1, le=1000)

    AGENT_CHECKPOINT_PATH: str = "data/runtime/agent_checkpoints.sqlite3"
    AGENT_CHECKPOINT_DATABASE_URL: Optional[str] = None
    AGENT_REQUIRE_HUMAN_APPROVAL: bool = True

    # Knowledge retrieval
    KB_TOP_K: int = Field(default=5, ge=1, le=100)
    KB_SIMILARITY_THRESHOLD: float = Field(default=0.2, ge=-1, le=1)
    KB_CHUNK_SIZE: int = Field(default=512, ge=64)
    KB_CHUNK_OVERLAP: int = Field(default=80, ge=0)
    KB_CHUNK_STRATEGY: Literal["auto", "recursive", "semantic"] = "auto"
    KB_SEMANTIC_BREAKPOINT_THRESHOLD: float = Field(default=0.55, ge=-1, le=1)
    KB_SEMANTIC_MAX_SEGMENTS: int = Field(default=256, ge=2, le=4096)
    KB_DOCUMENT_CHUNK_STRATEGIES_JSON: str = (
        '{"pypdf":"semantic","markdown":"recursive","text":"recursive"}'
    )
    KB_MAX_CHUNKS_PER_DOCUMENT: int = Field(default=2, ge=1, le=20)
    KB_DOCUMENT_RECALL_MULTIPLIER: int = Field(default=4, ge=1, le=20)
    KB_HYBRID_ENABLED: bool = True
    KB_BM25_PATH: str = "data/runtime/knowledge_bm25.sqlite3"
    KB_RRF_RANK_CONSTANT: int = Field(default=60, ge=1, le=1_000)
    OCR_ENABLED: bool = True
    OCR_LANGUAGES: str = "chi_sim+eng"
    OCR_MIN_EXTRACTED_CHARS: int = Field(default=32, ge=0, le=10_000)

    # Background ingestion
    INGESTION_QUEUE_URL: Optional[str] = None
    INGESTION_QUEUE_NAME: str = "safemeal:ingestion"
    INGESTION_JOB_TTL_SECONDS: int = Field(default=86_400, ge=60)

    # OIDC and tenant isolation
    ENABLE_OIDC: bool = False
    OIDC_ISSUER: Optional[str] = None
    OIDC_AUDIENCE: Optional[str] = None
    OIDC_JWKS_URL: Optional[str] = None
    OIDC_ALGORITHMS: str = "RS256"
    OIDC_TENANT_CLAIM: str = "tenant_id"
    DEFAULT_TENANT_ID: str = "default"

    @model_validator(mode="after")
    def inherit_dashscope_credentials(self) -> "Settings":
        """Reuse the main DashScope credentials unless a service overrides them."""
        self.LLM_API_KEY = (self.LLM_API_KEY or "").strip() or None
        self.LLM_BASE_URL = (self.LLM_BASE_URL or "").strip().rstrip("/")
        if not self.LLM_BASE_URL:
            self.LLM_BASE_URL = DASHSCOPE_COMPATIBLE_BASE_URL

        if not self.EMBEDDING_API_KEY:
            self.EMBEDDING_API_KEY = self.LLM_API_KEY
        else:
            self.EMBEDDING_API_KEY = self.EMBEDDING_API_KEY.strip() or self.LLM_API_KEY
        if not self.EMBEDDING_BASE_URL:
            self.EMBEDDING_BASE_URL = self.LLM_BASE_URL
        else:
            self.EMBEDDING_BASE_URL = self.EMBEDDING_BASE_URL.strip().rstrip("/")
        if not self.RERANK_API_KEY:
            self.RERANK_API_KEY = self.LLM_API_KEY
        else:
            self.RERANK_API_KEY = self.RERANK_API_KEY.strip() or self.LLM_API_KEY
        self.RERANK_BASE_URL = self.RERANK_BASE_URL.strip().rstrip("/")

        if self.KB_CHUNK_OVERLAP >= self.KB_CHUNK_SIZE:
            raise ValueError("KB_CHUNK_OVERLAP must be smaller than KB_CHUNK_SIZE")
        if self.AGENT_RESPONSE_TOKEN_RESERVE >= self.AGENT_CONTEXT_TOKEN_BUDGET:
            raise ValueError(
                "AGENT_RESPONSE_TOKEN_RESERVE must be smaller than AGENT_CONTEXT_TOKEN_BUDGET"
            )
        priced_models = _configured_pricing_models(self.MODEL_PRICING_JSON)
        if self.AGENT_MAX_COST > 0 and not (
            self.LLM_MODEL in priced_models or "*" in priced_models
        ):
            raise ValueError(
                "AGENT_MAX_COST requires pricing for LLM_MODEL or a '*' fallback"
            )

        if not self.KB_DOCUMENT_CHUNK_STRATEGIES_JSON.strip():
            self.KB_DOCUMENT_CHUNK_STRATEGIES_JSON = Settings.model_fields[
                "KB_DOCUMENT_CHUNK_STRATEGIES_JSON"
            ].default
        try:
            document_strategies = json.loads(self.KB_DOCUMENT_CHUNK_STRATEGIES_JSON)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "KB_DOCUMENT_CHUNK_STRATEGIES_JSON must be valid JSON"
            ) from exc
        if not isinstance(document_strategies, dict) or not all(
            isinstance(key, str) and value in {"auto", "recursive", "semantic"}
            for key, value in document_strategies.items()
        ):
            raise ValueError(
                "KB_DOCUMENT_CHUNK_STRATEGIES_JSON must map document types to chunk strategies"
            )

        if self.APP_ENV == "production":
            production_issues = self.configuration_issues
            if self.DEBUG:
                production_issues.append("DEBUG must be false in production")
            if not self.DATABASE_URL.lower().startswith("mysql+pymysql://"):
                production_issues.append(
                    "production DATABASE_URL must use mysql+pymysql"
                )
            unsafe_origins = {
                origin
                for origin in self.cors_origins_list
                if origin == "*" or "localhost" in origin or "127.0.0.1" in origin
            }
            if unsafe_origins:
                production_issues.append(
                    "production CORS_ORIGINS must not contain wildcard or loopback origins"
                )
            if (
                not self.ENABLE_OIDC
                and (
                    self.AUTH_JWT_SECRET == "development-only-change-me"
                    or len(self.AUTH_JWT_SECRET) < 32
                )
            ):
                production_issues.append(
                    "production AUTH_JWT_SECRET must be changed and contain at least 32 characters"
                )
            if self.ENABLE_OIDC and not (self.OIDC_ISSUER and self.OIDC_AUDIENCE):
                production_issues.append("production OIDC requires issuer and audience")
            if not self.AGENT_CHECKPOINT_DATABASE_URL:
                production_issues.append(
                    "production requires a shared AGENT_CHECKPOINT_DATABASE_URL"
                )
            if production_issues:
                raise ValueError(
                    "invalid production configuration: " + "; ".join(production_issues)
                )
        return self

    @property
    def OPENAI_API_KEY(self) -> Optional[str]:
        """Compatibility alias used by OpenAI-compatible clients."""
        return self.LLM_API_KEY

    @property
    def OPENAI_API_BASE(self) -> str:
        """Compatibility alias used by OpenAI-compatible clients."""
        return self.LLM_BASE_URL

    @property
    def OPENAI_MODEL(self) -> str:
        """Compatibility alias used by OpenAI-compatible clients."""
        return self.LLM_MODEL

    @property
    def cors_origins_list(self) -> List[str]:
        return [
            origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()
        ]

    @property
    def configuration_issues(self) -> List[str]:
        """Return startup-readiness issues without performing network probes."""

        issues: List[str] = []
        if self.ENABLE_LLM and not self.LLM_API_KEY:
            issues.append("ENABLE_LLM=true but LLM_API_KEY is missing")
        if self.ENABLE_EMBEDDINGS and not self.EMBEDDING_API_KEY:
            issues.append("ENABLE_EMBEDDINGS=true but EMBEDDING_API_KEY is missing")
        if self.ENABLE_MILVUS and not self.ENABLE_EMBEDDINGS:
            issues.append("Milvus search requires embeddings to be enabled")
        if self.ENABLE_NEO4J:
            if not self.NEO4J_URI.strip():
                issues.append("ENABLE_NEO4J=true but NEO4J_URI is missing")
            if bool(self.NEO4J_USER) != bool(self.NEO4J_PASSWORD):
                issues.append(
                    "NEO4J_USER and NEO4J_PASSWORD must be configured together"
                )
            if self.APP_ENV == "production" and not (
                self.NEO4J_USER and self.NEO4J_PASSWORD
            ):
                issues.append("production Neo4j requires username and password")
        for name, value in (
            ("LLM_BASE_URL", self.LLM_BASE_URL),
            ("EMBEDDING_BASE_URL", self.EMBEDDING_BASE_URL),
            ("RERANK_BASE_URL", self.RERANK_BASE_URL),
        ):
            if value and urlsplit(value).scheme not in {"http", "https"}:
                issues.append(f"{name} must be an HTTP URL")
        return issues


# DATABASE_URL is intentionally required from Settings sources rather than a
# constructor literal; the static Pydantic signature cannot express env loading.
settings = Settings()  # type: ignore[call-arg]
