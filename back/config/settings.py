"""环境变量、模型和外部服务配置。"""

import json
from typing import List, Literal, Optional
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DASHSCOPE_COMPATIBLE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DASHSCOPE_RERANK_BASE_URL = "https://dashscope.aliyuncs.com/api/v1/services"


def _configured_pricing_models(raw: str) -> set[str]:
    """Validate pricing JSON without importing the application observability layer."""

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
    TOOL_RATE_LIMIT_PER_MINUTE: int = Field(default=600, ge=1, le=100_000)
    MODEL_RATE_LIMIT_PER_MINUTE: int = Field(default=120, ge=1, le=100_000)
    LLM_MAX_OUTPUT_TOKENS: int = Field(default=2_048, ge=64, le=32_768)
    MODEL_COST_CURRENCY: str = Field(default="CNY", min_length=3, max_length=8)
    MODEL_PRICING_JSON: str = "{}"
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"
    AUTH_MODE: Literal["disabled", "trusted_gateway"] = "disabled"
    AUTH_GATEWAY_SECRET: Optional[str] = None

    # Optional integrations
    ENABLE_LLM: bool = True
    ENABLE_EMBEDDINGS: bool = True
    ENABLE_MILVUS: bool = True
    ENABLE_NEO4J: bool = True
    ENABLE_LIGHTRAG: bool = True
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
    LLM_FALLBACKS_JSON: str = "[]"
    DEEPSEEK_API_KEY: Optional[str] = None
    LLM_REQUEST_TIMEOUT: float = Field(default=90.0, gt=0, le=600)
    LLM_MAX_RETRIES: int = Field(default=2, ge=0, le=10)
    LLM_STRUCTURED_REPAIR_RETRIES: int = Field(default=1, ge=0, le=3)
    LLM_CIRCUIT_FAILURE_THRESHOLD: int = Field(default=3, ge=1, le=100)
    LLM_CIRCUIT_RECOVERY_SECONDS: float = Field(default=30.0, gt=0, le=3600)

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
    DB_POOL_SIZE: int = Field(default=5, ge=1, le=100)
    DB_MAX_OVERFLOW: int = Field(default=10, ge=0, le=200)
    DB_POOL_TIMEOUT: float = Field(default=30.0, gt=0, le=300)
    DB_POOL_RECYCLE: int = Field(default=1800, ge=60, le=86400)
    DB_CONNECT_TIMEOUT: int = Field(default=10, ge=1, le=120)

    # Milvus
    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = Field(default=19530, ge=1, le=65535)
    MILVUS_COLLECTION: str = "recipes_current"
    MILVUS_LEGACY_COLLECTION: str = "recipes"
    MILVUS_COLLECTION_TARGET: str = "recipes_v2"
    MILVUS_INDEX_TYPE: str = "IVF_FLAT"
    MILVUS_METRIC_TYPE: str = "IP"
    MILVUS_LOAD_TIMEOUT: float = Field(default=30.0, gt=0, le=300)

    # Neo4j recipe knowledge graph
    NEO4J_URI: str = "bolt://localhost:17687"
    NEO4J_USER: Optional[str] = None
    NEO4J_PASSWORD: Optional[str] = None
    NEO4J_DATABASE: str = "neo4j"
    NEO4J_DEFAULT_GRAPH_QUERY: str = "MATCH (a)-[r]-(b) RETURN a, r, b LIMIT 100"
    NEO4J_GRAPH_CACHE_PATH: str = "data/neo4j/graph.json"
    NEO4J_MAX_CONNECTION_LIFETIME: Optional[int] = Field(default=None, gt=0)
    NEO4J_CONNECTION_TIMEOUT: float = Field(default=10.0, gt=0, le=120)
    NEO4J_RECIPE_JSON_PATH: str = "data/recipe.json"
    NEO4J_INGREDIENT_JSON_PATH: Optional[str] = "data/neo4j/excipients.json"

    # LightRAG cross-document graph retrieval
    LIGHTRAG_WORKING_DIR: str = "./data/lightrag"
    LIGHTRAG_RETRIEVAL_MODE: Literal[
        "naive", "local", "global", "hybrid", "mix", "bypass"
    ] = "hybrid"
    LIGHTRAG_TOP_K: int = Field(default=10, ge=1, le=100)
    LIGHTRAG_MAX_TOKEN_SIZE: int = Field(default=4096, ge=256)
    LIGHTRAG_OPERATION_TIMEOUT: float = Field(default=120.0, gt=0, le=600)

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
    AGENT_DISTRIBUTED_MAX_CONCURRENCY: int = Field(default=16, ge=1, le=10_000)
    AGENT_QUEUE_WAIT_TIMEOUT: float = Field(default=15.0, gt=0, le=300)
    AGENT_QUEUE_LEASE_SECONDS: float = Field(default=330.0, gt=1, le=3600)
    STREAM_FIRST_PACKET_TIMEOUT: float = Field(default=8.0, gt=0, le=120)
    STREAM_CHUNK_CHARS: int = Field(default=64, ge=1, le=1000)

    # Online product feedback
    ENABLE_ONLINE_FAILURE_CAPTURE: bool = True
    ONLINE_FAILURE_QUEUE_PATH: str = "data/runtime/online_failures.jsonl"
    ENABLE_AGENT_TRACE_PERSISTENCE: bool = True
    AGENT_TRACE_PATH: str = "data/runtime/agent_traces.jsonl"
    AGENT_TRACE_MAX_BYTES: int = Field(default=50_000_000, ge=1_000_000)
    AGENT_TRACE_BACKUP_COUNT: int = Field(default=5, ge=1, le=100)

    # Knowledge retrieval
    KB_TOP_K: int = Field(default=5, ge=1, le=100)
    KB_SIMILARITY_THRESHOLD: float = Field(default=0.2, ge=-1, le=1)
    KB_CHUNK_SIZE: int = Field(default=512, ge=64)
    KB_CHUNK_OVERLAP: int = Field(default=80, ge=0)
    KB_CHUNK_STRATEGY: Literal["auto", "recursive", "semantic"] = "auto"
    KB_SEMANTIC_BREAKPOINT_THRESHOLD: float = Field(default=0.55, ge=-1, le=1)
    KB_SEMANTIC_MAX_SEGMENTS: int = Field(default=256, ge=2, le=4096)
    KB_DOCUMENT_CHUNK_STRATEGIES_JSON: str = (
        '{"pypdf":"semantic","python-docx":"semantic",'
        '"python-pptx":"semantic","apache-tika":"semantic",'
        '"html":"recursive","text":"recursive","json":"recursive",'
        '"csv":"recursive","openpyxl":"recursive"}'
    )
    KB_RERANK_SCORE_THRESHOLD: float = Field(default=0.8, ge=0, le=1)
    TIKA_ENABLED: bool = False
    TIKA_URL: str = "http://localhost:9998"
    TIKA_TIMEOUT: float = Field(default=120.0, gt=0, le=600)
    TIKA_MAX_EXTRACTED_CHARS: int = Field(default=2_000_000, ge=1000)
    SOURCE_LOCAL_ROOT: str = "uploads"
    SOURCE_HTTP_ALLOWED_HOSTS: str = ""
    SOURCE_S3_BUCKET: Optional[str] = None
    SOURCE_S3_PREFIX: str = ""
    SOURCE_S3_ENDPOINT_URL: Optional[str] = None
    FEISHU_ACCESS_TOKEN: Optional[str] = None
    SOURCE_SYNC_STATE_PATH: str = "data/sync/source_states.json"
    SOURCE_SYNC_JOBS_JSON: str = "[]"
    SOURCE_DELETE_MISSING: bool = True

    @model_validator(mode="after")
    def inherit_dashscope_credentials(self) -> "Settings":
        """Reuse the main DashScope credentials unless a service overrides them."""
        self.LLM_API_KEY = (self.LLM_API_KEY or "").strip() or None
        self.DEEPSEEK_API_KEY = (self.DEEPSEEK_API_KEY or "").strip() or None
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
        if self.AGENT_QUEUE_LEASE_SECONDS <= self.AGENT_TIMEOUT:
            raise ValueError(
                "AGENT_QUEUE_LEASE_SECONDS must exceed AGENT_TIMEOUT so a live run "
                "cannot lose its distributed lease"
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

        try:
            sync_jobs = json.loads(self.SOURCE_SYNC_JOBS_JSON)
        except json.JSONDecodeError as exc:
            raise ValueError("SOURCE_SYNC_JOBS_JSON must be valid JSON") from exc
        if not isinstance(sync_jobs, list) or not all(
            isinstance(item, dict)
            and isinstance(item.get("source_uri"), str)
            and isinstance(item.get("interval_seconds"), (int, float))
            and item["interval_seconds"] > 0
            for item in sync_jobs
        ):
            raise ValueError(
                "SOURCE_SYNC_JOBS_JSON must contain source_uri and positive interval_seconds"
            )

        try:
            fallbacks = json.loads(self.LLM_FALLBACKS_JSON)
        except json.JSONDecodeError as exc:
            raise ValueError("LLM_FALLBACKS_JSON must be valid JSON") from exc
        if not isinstance(fallbacks, list) or not all(
            isinstance(item, dict)
            and (
                item.get("extra_body") is None
                or isinstance(item.get("extra_body"), dict)
            )
            for item in fallbacks
        ):
            raise ValueError(
                "LLM_FALLBACKS_JSON must be an array of objects with object extra_body"
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
            if self.AUTH_MODE != "trusted_gateway":
                production_issues.append("production AUTH_MODE must be trusted_gateway")
            if not self.AUTH_GATEWAY_SECRET:
                production_issues.append(
                    "production AUTH_GATEWAY_SECRET must contain at least 32 characters"
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
    def source_http_allowed_hosts(self) -> set[str]:
        return {
            item.strip().casefold()
            for item in self.SOURCE_HTTP_ALLOWED_HOSTS.split(",")
            if item.strip()
        }

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
        if self.ENABLE_LIGHTRAG and not (self.ENABLE_LLM and self.ENABLE_EMBEDDINGS):
            issues.append("LightRAG requires both LLM and embeddings")
        if (
            self.AUTH_MODE == "trusted_gateway"
            and len(self.AUTH_GATEWAY_SECRET or "") < 32
        ):
            issues.append("AUTH_GATEWAY_SECRET must contain at least 32 characters")
        for name, value in (
            ("LLM_BASE_URL", self.LLM_BASE_URL),
            ("EMBEDDING_BASE_URL", self.EMBEDDING_BASE_URL),
            ("RERANK_BASE_URL", self.RERANK_BASE_URL),
            ("TIKA_URL", self.TIKA_URL if self.TIKA_ENABLED else None),
        ):
            if value and urlsplit(value).scheme not in {"http", "https"}:
                issues.append(f"{name} must be an HTTP URL")
        return issues


# DATABASE_URL is intentionally required from Settings sources rather than a
# constructor literal; the static Pydantic signature cannot express env loading.
settings = Settings()  # type: ignore[call-arg]
