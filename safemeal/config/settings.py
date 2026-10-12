"""环境变量、模型和外部服务配置。"""

import json
import math
from typing import List, Literal, Optional
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import SettingsConfigDict
from safemeal.config.platform import PlatformSettings


DASHSCOPE_COMPATIBLE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DASHSCOPE_RERANK_BASE_URL = "https://dashscope.aliyuncs.com/api/v1/services"


# 方法说明：_configured_pricing_models
# 作用：解析已配置的模型价格表，供模型调用成本计算使用。
# 入参：
#   raw（str）：尚未完成归一化的外部原始数据。
# 出参：set[str]；文本字符串的集合。
def _configured_pricing_models(raw: str) -> set[str]:

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
        if any(
            not math.isfinite(value) or value < 0
            for value in (input_price, output_price, cached_price)
        ):
            raise ValueError("model prices cannot be negative")
        models.add(str(model))
    return models


# 类说明（业务或基础设施实现类）：Settings
# 作用：实现完整 Agent 应用配置，封装该组件的业务处理与依赖协作。
class Settings(PlatformSettings):
    # 字段说明：APP_NAME
    # 作用：应用名称，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'SafeMeal Agent'。
    APP_NAME: str = "SafeMeal Agent"

    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：读取环境变量文件='.env'；环境文件编码='utf-8'；环境变量名是否区分大小写=True；额外字段策略（forbid 禁止，ignore 忽略）='ignore'。
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # 字段说明：UPLOAD_DIR
    # 作用：上传目录，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'uploads'。
    UPLOAD_DIR: str = "uploads"
    # 字段说明：FILE_UPLOAD_MAX_MB
    # 作用：文件上传最大兆字节上限，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=2；最小值（含）=1。
    FILE_UPLOAD_MAX_MB: int = Field(default=2, ge=1)

    # 字段说明：LLM_MAX_OUTPUT_TOKENS
    # 作用：语言模型最大输出令牌数，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=2048；最小值（含）=64；最大值（含）=32768。
    LLM_MAX_OUTPUT_TOKENS: int = Field(default=2_048, ge=64, le=32_768)
    # 字段说明：MODEL_PRICING_JSON
    # 作用：模型价格表 JSON；按模型名映射 input_cost_per_million、output_cost_per_million、cached_input_cost_per_million，分别为每百万输入、输出和缓存输入令牌单价。
    # 类型：str。
    # 初始值：'{}'。
    MODEL_PRICING_JSON: str = "{}"

    # 字段说明：ENABLE_LLM
    # 作用：启用语言模型，供该组件初始化及运行控制使用。
    # 类型：bool。
    # 初始值：True。
    ENABLE_LLM: bool = True
    # 字段说明：ENABLE_EMBEDDINGS
    # 作用：启用EMBEDDINGS，供该组件初始化及运行控制使用。
    # 类型：bool。
    # 初始值：True。
    ENABLE_EMBEDDINGS: bool = True
    # 字段说明：ENABLE_MILVUS
    # 作用：启用Milvus，供该组件初始化及运行控制使用。
    # 类型：bool。
    # 初始值：True。
    ENABLE_MILVUS: bool = True
    # 字段说明：ENABLE_NEO4J
    # 作用：启用Neo4j，供该组件初始化及运行控制使用。
    # 类型：bool。
    # 初始值：True。
    ENABLE_NEO4J: bool = True
    # 字段说明：ENABLE_EXTERNAL_RECIPE_SEARCH
    # 作用：启用外部菜谱SEARCH，供该组件初始化及运行控制使用。
    # 类型：bool。
    # 初始值：True。
    ENABLE_EXTERNAL_RECIPE_SEARCH: bool = True
    # 字段说明：EXTERNAL_RECIPE_ENDPOINT
    # 作用：外部菜谱请求端点，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'https://zh.wikibooks.org/w/api.php'。
    EXTERNAL_RECIPE_ENDPOINT: str = "https://zh.wikibooks.org/w/api.php"
    # 字段说明：EXTERNAL_RECIPE_TIMEOUT
    # 作用：外部菜谱超时秒数，供该组件初始化及运行控制使用。
    # 类型：float。
    # 配置：默认值=8.0；下限（不含）=0；最大值（含）=30。
    EXTERNAL_RECIPE_TIMEOUT: float = Field(default=8.0, gt=0, le=30)
    # 字段说明：REQUEST_UNDERSTANDING_BACKEND
    # 作用：请求语义理解后端类型，供该组件初始化及运行控制使用。
    # 类型：Literal['rules', 'local_model']。
    # 初始值：'rules'。
    # 取值说明：
    #   rules：规则理解后端。
    #   local_model：本地模型理解后端。
    REQUEST_UNDERSTANDING_BACKEND: Literal["rules", "local_model"] = "rules"
    # 字段说明：REQUEST_UNDERSTANDING_MODEL_PATH
    # 作用：请求语义理解模型存储路径，供该组件初始化及运行控制使用。
    # 类型：Optional[str]。
    # 初始值：None。
    REQUEST_UNDERSTANDING_MODEL_PATH: Optional[str] = None
    # 字段说明：REQUEST_UNDERSTANDING_ENDPOINT
    # 作用：请求语义理解请求端点，供该组件初始化及运行控制使用。
    # 类型：Optional[str]。
    # 初始值：None。
    REQUEST_UNDERSTANDING_ENDPOINT: Optional[str] = None
    # 字段说明：REQUEST_UNDERSTANDING_CATALOG_PATH
    # 作用：请求语义理解目录存储路径，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'training/nlu/recipe_catalog.json'。
    REQUEST_UNDERSTANDING_CATALOG_PATH: str = "training/nlu/recipe_catalog.json"
    # 字段说明：REQUEST_UNDERSTANDING_TIMEOUT
    # 作用：请求语义理解超时秒数，供该组件初始化及运行控制使用。
    # 类型：float。
    # 配置：默认值=15.0；下限（不含）=0；最大值（含）=120。
    REQUEST_UNDERSTANDING_TIMEOUT: float = Field(default=15.0, gt=0, le=120)
    # 字段说明：REQUEST_UNDERSTANDING_CONFIDENCE_THRESHOLD
    # 作用：请求语义理解置信度阈值，供该组件初始化及运行控制使用。
    # 类型：float。
    # 配置：默认值=0.7；最小值（含）=0；最大值（含）=1。
    REQUEST_UNDERSTANDING_CONFIDENCE_THRESHOLD: float = Field(default=0.7, ge=0, le=1)
    # 字段说明：INTEGRATION_PROBE_TIMEOUT
    # 作用：集成服务探测超时秒数，供该组件初始化及运行控制使用。
    # 类型：float。
    # 配置：默认值=10.0；下限（不含）=0；最大值（含）=60。
    INTEGRATION_PROBE_TIMEOUT: float = Field(default=10.0, gt=0, le=60)

    # 字段说明：LLM_MODEL
    # 作用：语言模型模型，供该组件初始化及运行控制使用。
    # 类型：str。
    # 配置：默认值='qwen3-max'。
    LLM_MODEL: str = Field(
        default="qwen3-max",
        validation_alias=AliasChoices("LLM_MODEL", "OPENAI_MODEL"),
    )
    # 字段说明：LLM_API_KEY
    # 作用：语言模型接口凭据，供该组件初始化及运行控制使用。
    # 类型：Optional[str]。
    # 配置：默认值=None。
    LLM_API_KEY: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "LLM_API_KEY", "DASHSCOPE_API_KEY", "OPENAI_API_KEY"
        ),
    )
    # 字段说明：LLM_BASE_URL
    # 作用：语言模型基础连接地址，供该组件初始化及运行控制使用。
    # 类型：str。
    # 配置：默认值=DASHSCOPE_COMPATIBLE_BASE_URL。
    LLM_BASE_URL: str = Field(
        default=DASHSCOPE_COMPATIBLE_BASE_URL,
        validation_alias=AliasChoices(
            "LLM_BASE_URL", "OPENAI_API_BASE", "OPENAI_BASE_URL"
        ),
    )
    # 字段说明：LLM_REQUEST_TIMEOUT
    # 作用：语言模型请求超时秒数，供该组件初始化及运行控制使用。
    # 类型：float。
    # 配置：默认值=90.0；下限（不含）=0；最大值（含）=600。
    LLM_REQUEST_TIMEOUT: float = Field(default=90.0, gt=0, le=600)
    # 字段说明：LLM_MAX_RETRIES
    # 作用：语言模型最大重试次数，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=2；最小值（含）=0；最大值（含）=10。
    LLM_MAX_RETRIES: int = Field(default=2, ge=0, le=10)
    # 字段说明：LLM_STRUCTURED_REPAIR_RETRIES
    # 作用：语言模型结构化输出修复重试次数，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=1；最小值（含）=0；最大值（含）=3。
    LLM_STRUCTURED_REPAIR_RETRIES: int = Field(default=1, ge=0, le=3)

    # 字段说明：EMBEDDING_MODEL
    # 作用：向量嵌入模型，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'text-embedding-v4'。
    EMBEDDING_MODEL: str = "text-embedding-v4"
    # 字段说明：EMBEDDING_API_KEY
    # 作用：向量嵌入接口凭据，供该组件初始化及运行控制使用。
    # 类型：Optional[str]。
    # 初始值：None。
    EMBEDDING_API_KEY: Optional[str] = None
    # 字段说明：EMBEDDING_BASE_URL
    # 作用：向量嵌入基础连接地址，供该组件初始化及运行控制使用。
    # 类型：Optional[str]。
    # 初始值：None。
    EMBEDDING_BASE_URL: Optional[str] = None
    # 字段说明：EMBEDDING_DIMENSION
    # 作用：向量嵌入维度，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=1024；下限（不含）=0。
    EMBEDDING_DIMENSION: int = Field(default=1024, gt=0)

    # 字段说明：RERANK_ENABLED
    # 作用：重排启用开关，供该组件初始化及运行控制使用。
    # 类型：bool。
    # 初始值：True。
    RERANK_ENABLED: bool = True
    # 字段说明：RERANK_PROVIDER
    # 作用：重排服务商，供该组件初始化及运行控制使用。
    # 类型：Literal['custom', 'jina', 'voyage']。
    # 初始值：'custom'。
    # 取值说明：
    #   custom：使用自定义配置。
    #   jina：使用 Jina 重排服务。
    #   voyage：使用 Voyage 重排服务。
    RERANK_PROVIDER: Literal["custom", "jina", "voyage"] = "custom"
    # 字段说明：RERANK_BASE_URL
    # 作用：重排基础连接地址，供该组件初始化及运行控制使用。
    # 类型：str。
    RERANK_BASE_URL: str = DASHSCOPE_RERANK_BASE_URL
    # 字段说明：RERANK_ENDPOINT
    # 作用：重排请求端点，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'/rerank/text-rerank/text-rerank'。
    RERANK_ENDPOINT: str = "/rerank/text-rerank/text-rerank"
    # 字段说明：RERANK_MODEL
    # 作用：重排模型，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'qwen3-rerank'。
    RERANK_MODEL: str = "qwen3-rerank"
    # 字段说明：RERANK_API_KEY
    # 作用：重排接口凭据，供该组件初始化及运行控制使用。
    # 类型：Optional[str]。
    # 初始值：None。
    RERANK_API_KEY: Optional[str] = None
    # 字段说明：RERANK_MAX_CANDIDATES
    # 作用：重排最大候选数，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=20；最小值（含）=1；最大值（含）=100。
    RERANK_MAX_CANDIDATES: int = Field(default=20, ge=1, le=100)
    # 字段说明：RERANK_TOP_N
    # 作用：重排返回前N 条，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=6；最小值（含）=1；最大值（含）=100。
    RERANK_TOP_N: int = Field(default=6, ge=1, le=100)
    # 字段说明：RERANK_TIMEOUT
    # 作用：重排超时秒数，供该组件初始化及运行控制使用。
    # 类型：float。
    # 配置：默认值=30.0；下限（不含）=0；最大值（含）=300。
    RERANK_TIMEOUT: float = Field(default=30.0, gt=0, le=300)

    # 字段说明：MILVUS_HOST
    # 作用：Milvus监听地址，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'localhost'。
    MILVUS_HOST: str = "localhost"
    # 字段说明：MILVUS_PORT
    # 作用：Milvus端口，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=19530；最小值（含）=1；最大值（含）=65535。
    MILVUS_PORT: int = Field(default=19530, ge=1, le=65535)
    # 字段说明：MILVUS_COLLECTION
    # 作用：Milvus集合名，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'recipes_current'。
    MILVUS_COLLECTION: str = "recipes_current"
    # 字段说明：MILVUS_INDEX_TYPE
    # 作用：Milvus索引类型，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'IVF_FLAT'。
    MILVUS_INDEX_TYPE: str = "IVF_FLAT"
    # 字段说明：MILVUS_METRIC_TYPE
    # 作用：Milvus距离度量类型，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'IP'。
    MILVUS_METRIC_TYPE: str = "IP"
    # 字段说明：MILVUS_LOAD_TIMEOUT
    # 作用：Milvus加载超时秒数，供该组件初始化及运行控制使用。
    # 类型：float。
    # 配置：默认值=30.0；下限（不含）=0；最大值（含）=300。
    MILVUS_LOAD_TIMEOUT: float = Field(default=30.0, gt=0, le=300)

    # 字段说明：NEO4J_URI
    # 作用：Neo4j连接地址，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'bolt://localhost:17687'。
    NEO4J_URI: str = "bolt://localhost:17687"
    # 字段说明：NEO4J_USER
    # 作用：Neo4j用户名，供该组件初始化及运行控制使用。
    # 类型：Optional[str]。
    # 初始值：None。
    NEO4J_USER: Optional[str] = None
    # 字段说明：NEO4J_PASSWORD
    # 作用：Neo4j密码，供该组件初始化及运行控制使用。
    # 类型：Optional[str]。
    # 初始值：None。
    NEO4J_PASSWORD: Optional[str] = None
    # 字段说明：NEO4J_DATABASE
    # 作用：Neo4j数据库，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'neo4j'。
    NEO4J_DATABASE: str = "neo4j"
    # 字段说明：NEO4J_MAX_CONNECTION_LIFETIME
    # 作用：Neo4j最大连接存活秒数，供该组件初始化及运行控制使用。
    # 类型：Optional[int]。
    # 配置：默认值=None；下限（不含）=0。
    NEO4J_MAX_CONNECTION_LIFETIME: Optional[int] = Field(default=None, gt=0)
    # 字段说明：NEO4J_CONNECTION_TIMEOUT
    # 作用：Neo4j连接超时秒数，供该组件初始化及运行控制使用。
    # 类型：float。
    # 配置：默认值=10.0；下限（不含）=0；最大值（含）=120。
    NEO4J_CONNECTION_TIMEOUT: float = Field(default=10.0, gt=0, le=120)
    # 字段说明：NEO4J_RECIPE_JSON_PATH
    # 作用：Neo4j菜谱JSON 配置存储路径，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'data/recipe.json'。
    NEO4J_RECIPE_JSON_PATH: str = "data/recipe.json"
    # 字段说明：NEO4J_INGREDIENT_JSON_PATH
    # 作用：Neo4j食材JSON 配置存储路径，供该组件初始化及运行控制使用。
    # 类型：Optional[str]。
    # 初始值：'data/neo4j/excipients.json'。
    NEO4J_INGREDIENT_JSON_PATH: Optional[str] = "data/neo4j/excipients.json"

    # 字段说明：MAX_ITERATIONS
    # 作用：最大ITERATIONS，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=4；最小值（含）=1；最大值（含）=6。
    MAX_ITERATIONS: int = Field(default=4, ge=1, le=6)
    # 字段说明：AGENT_TIMEOUT
    # 作用：Agent 执行超时秒数，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=300；下限（不含）=0；最大值（含）=1800。
    AGENT_TIMEOUT: int = Field(default=300, gt=0, le=1800)
    # 字段说明：AGENT_TOOL_TIMEOUT
    # 作用：Agent 执行工具超时秒数，供该组件初始化及运行控制使用。
    # 类型：float。
    # 配置：默认值=60.0；下限（不含）=0；最大值（含）=300。
    AGENT_TOOL_TIMEOUT: float = Field(default=60.0, gt=0, le=300)
    # 字段说明：AGENT_HISTORY_SCAN_MESSAGES
    # 作用：Agent 执行历史扫描消息数，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=40；最小值（含）=4；最大值（含）=100。
    AGENT_HISTORY_SCAN_MESSAGES: int = Field(default=40, ge=4, le=100)
    # 字段说明：AGENT_CONTEXT_TOKEN_BUDGET
    # 作用：Agent 执行上下文令牌预算，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=6000；最小值（含）=512；最大值（含）=100000。
    AGENT_CONTEXT_TOKEN_BUDGET: int = Field(default=6_000, ge=512, le=100_000)
    # 字段说明：AGENT_RESPONSE_TOKEN_RESERVE
    # 作用：Agent 执行回复令牌预留，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=1200；最小值（含）=128；最大值（含）=20000。
    AGENT_RESPONSE_TOKEN_RESERVE: int = Field(default=1_200, ge=128, le=20_000)
    # 字段说明：AGENT_MEMORY_RETRIEVAL_LIMIT
    # 作用：Agent 执行记忆检索上限，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=20；最小值（含）=1；最大值（含）=100。
    AGENT_MEMORY_RETRIEVAL_LIMIT: int = Field(default=20, ge=1, le=100)
    # 字段说明：AGENT_MAX_TOOL_CALLS
    # 作用：Agent 执行最大工具调用次数，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=12；最小值（含）=1；最大值（含）=100。
    AGENT_MAX_TOOL_CALLS: int = Field(default=12, ge=1, le=100)
    # 字段说明：AGENT_MAX_MODEL_TOKENS
    # 作用：Agent 执行最大模型令牌数，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=20000；最小值（含）=1000；最大值（含）=1000000。
    AGENT_MAX_MODEL_TOKENS: int = Field(default=20_000, ge=1_000, le=1_000_000)
    # 字段说明：AGENT_MAX_COST
    # 作用：Agent 执行最大费用预算，供该组件初始化及运行控制使用。
    # 类型：float。
    # 配置：默认值=0.0；最小值（含）=0；最大值（含）=1000000。
    AGENT_MAX_COST: float = Field(default=0.0, ge=0, le=1_000_000)
    # 字段说明：AGENT_MAX_CONCURRENCY
    # 作用：Agent 执行最大并发数，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=8；最小值（含）=1；最大值（含）=100。
    AGENT_MAX_CONCURRENCY: int = Field(default=8, ge=1, le=100)
    # 字段说明：STREAM_FIRST_PACKET_TIMEOUT
    # 作用：流式响应首次数据包超时秒数，供该组件初始化及运行控制使用。
    # 类型：float。
    # 配置：默认值=8.0；下限（不含）=0；最大值（含）=120。
    STREAM_FIRST_PACKET_TIMEOUT: float = Field(default=8.0, gt=0, le=120)
    # 字段说明：STREAM_CHUNK_CHARS
    # 作用：流式响应切片字符数，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=64；最小值（含）=1；最大值（含）=1000。
    STREAM_CHUNK_CHARS: int = Field(default=64, ge=1, le=1000)

    # 字段说明：AGENT_CHECKPOINT_PATH
    # 作用：Agent 执行图检查点存储路径，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'data/runtime/agent_checkpoints.sqlite3'。
    AGENT_CHECKPOINT_PATH: str = "data/runtime/agent_checkpoints.sqlite3"
    # 字段说明：AGENT_CHECKPOINT_DATABASE_URL
    # 作用：Agent 执行图检查点数据库连接地址，供该组件初始化及运行控制使用。
    # 类型：Optional[str]。
    # 初始值：None。
    AGENT_CHECKPOINT_DATABASE_URL: Optional[str] = None
    # 字段说明：AGENT_REQUIRE_HUMAN_APPROVAL
    # 作用：Agent 执行要求人工审批，供该组件初始化及运行控制使用。
    # 类型：bool。
    # 初始值：True。
    AGENT_REQUIRE_HUMAN_APPROVAL: bool = True

    # 字段说明：KB_TOP_K
    # 作用：知识检索返回前K 条，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=5；最小值（含）=1；最大值（含）=100。
    KB_TOP_K: int = Field(default=5, ge=1, le=100)
    # 字段说明：KB_SIMILARITY_THRESHOLD
    # 作用：知识检索相似度阈值，供该组件初始化及运行控制使用。
    # 类型：float。
    # 配置：默认值=0.2；最小值（含）=-1；最大值（含）=1。
    KB_SIMILARITY_THRESHOLD: float = Field(default=0.2, ge=-1, le=1)
    # 字段说明：KB_CHUNK_SIZE
    # 作用：知识检索切片大小，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=512；最小值（含）=64。
    KB_CHUNK_SIZE: int = Field(default=512, ge=64)
    # 字段说明：KB_CHUNK_OVERLAP
    # 作用：知识检索切片重叠长度，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=80；最小值（含）=0。
    KB_CHUNK_OVERLAP: int = Field(default=80, ge=0)
    # 字段说明：KB_CHUNK_STRATEGY
    # 作用：知识检索切片策略，供该组件初始化及运行控制使用。
    # 类型：Literal['auto', 'recursive', 'semantic']。
    # 初始值：'auto'。
    # 取值说明：
    #   auto：自动选择的模式。
    #   recursive：递归切分。
    #   semantic：语义匹配或切分。
    KB_CHUNK_STRATEGY: Literal["auto", "recursive", "semantic"] = "auto"
    # 字段说明：KB_SEMANTIC_BREAKPOINT_THRESHOLD
    # 作用：知识检索语义切分断点阈值，供该组件初始化及运行控制使用。
    # 类型：float。
    # 配置：默认值=0.55；最小值（含）=-1；最大值（含）=1。
    KB_SEMANTIC_BREAKPOINT_THRESHOLD: float = Field(default=0.55, ge=-1, le=1)
    # 字段说明：KB_SEMANTIC_MAX_SEGMENTS
    # 作用：知识检索语义切分最大片段数，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=256；最小值（含）=2；最大值（含）=4096。
    KB_SEMANTIC_MAX_SEGMENTS: int = Field(default=256, ge=2, le=4096)
    # 字段说明：KB_DOCUMENT_CHUNK_STRATEGIES_JSON
    # 作用：知识检索文档切片策略映射JSON 配置，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'{"pypdf":"semantic","markdown":"recursive","text":"recursive"}'。
    KB_DOCUMENT_CHUNK_STRATEGIES_JSON: str = (
        '{"pypdf":"semantic","markdown":"recursive","text":"recursive"}'
    )
    # 字段说明：KB_MAX_CHUNKS_PER_DOCUMENT
    # 作用：知识检索最大切片数每文档，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=2；最小值（含）=1；最大值（含）=20。
    KB_MAX_CHUNKS_PER_DOCUMENT: int = Field(default=2, ge=1, le=20)
    # 字段说明：KB_DOCUMENT_RECALL_MULTIPLIER
    # 作用：知识检索文档召回倍数，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=4；最小值（含）=1；最大值（含）=20。
    KB_DOCUMENT_RECALL_MULTIPLIER: int = Field(default=4, ge=1, le=20)
    # 字段说明：KB_HYBRID_ENABLED
    # 作用：知识检索混合检索启用开关，供该组件初始化及运行控制使用。
    # 类型：bool。
    # 初始值：True。
    KB_HYBRID_ENABLED: bool = True
    # 字段说明：KB_BM25_PATH
    # 作用：知识检索BM25 词法索引存储路径，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'data/runtime/knowledge_bm25.sqlite3'。
    KB_BM25_PATH: str = "data/runtime/knowledge_bm25.sqlite3"
    # 字段说明：KB_RRF_RANK_CONSTANT
    # 作用：知识检索RRF 融合排序常量，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=60；最小值（含）=1；最大值（含）=1000。
    KB_RRF_RANK_CONSTANT: int = Field(default=60, ge=1, le=1_000)
    # 字段说明：OCR_ENABLED
    # 作用：OCR 识别启用开关，供该组件初始化及运行控制使用。
    # 类型：bool。
    # 初始值：True。
    OCR_ENABLED: bool = True
    # 字段说明：OCR_LANGUAGES
    # 作用：OCR 识别语言列表，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'chi_sim+eng'。
    OCR_LANGUAGES: str = "chi_sim+eng"
    # 字段说明：OCR_MIN_EXTRACTED_CHARS
    # 作用：OCR 识别最小已提取字符数，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=32；最小值（含）=0；最大值（含）=10000。
    OCR_MIN_EXTRACTED_CHARS: int = Field(default=32, ge=0, le=10_000)

    # 字段说明：INGESTION_QUEUE_URL
    # 作用：文档入库队列连接地址，供该组件初始化及运行控制使用。
    # 类型：Optional[str]。
    # 初始值：None。
    INGESTION_QUEUE_URL: Optional[str] = None
    # 字段说明：INGESTION_QUEUE_NAME
    # 作用：文档入库队列名称，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'safemeal:ingestion'。
    INGESTION_QUEUE_NAME: str = "safemeal:ingestion"
    # 字段说明：INGESTION_JOB_TTL_SECONDS
    # 作用：文档入库JOB有效期秒数，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=86400；最小值（含）=60。
    INGESTION_JOB_TTL_SECONDS: int = Field(default=86_400, ge=60)

    # 方法说明：inherit_dashscope_credentials
    # 作用：在供应商主机匹配时复用凭据，避免将密钥发送给其他主机。
    # 入参：
    #   无显式入参。
    # 出参：'Settings'；完整 Agent 应用配置。
    @model_validator(mode="after")
    def inherit_dashscope_credentials(self) -> "Settings":
        self.LLM_API_KEY = (self.LLM_API_KEY or "").strip() or None
        self.LLM_BASE_URL = (self.LLM_BASE_URL or "").strip().rstrip("/")
        if not self.LLM_BASE_URL:
            self.LLM_BASE_URL = DASHSCOPE_COMPATIBLE_BASE_URL

        # Provider credentials must never silently cross host boundaries.
        self.EMBEDDING_BASE_URL = (self.EMBEDDING_BASE_URL or "").strip().rstrip(
            "/"
        ) or DASHSCOPE_COMPATIBLE_BASE_URL
        self.RERANK_BASE_URL = self.RERANK_BASE_URL.strip().rstrip("/")
        self.EMBEDDING_API_KEY = (self.EMBEDDING_API_KEY or "").strip() or None
        self.RERANK_API_KEY = (self.RERANK_API_KEY or "").strip() or None
        llm_host = urlsplit(self.LLM_BASE_URL).hostname
        if (
            not self.EMBEDDING_API_KEY
            and urlsplit(self.EMBEDDING_BASE_URL).hostname == llm_host
        ):
            self.EMBEDDING_API_KEY = self.LLM_API_KEY
        if (
            not self.RERANK_API_KEY
            and urlsplit(self.RERANK_BASE_URL).hostname == llm_host
        ):
            self.RERANK_API_KEY = self.LLM_API_KEY

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
            if not self.AGENT_CHECKPOINT_DATABASE_URL:
                production_issues.append(
                    "production requires a shared AGENT_CHECKPOINT_DATABASE_URL"
                )
            if production_issues:
                raise ValueError(
                    "invalid production configuration: " + "; ".join(production_issues)
                )
        return self

    # 方法说明：OPENAI_API_KEY
    # 作用：提供兼容旧配置名称的语言模型 API 凭据。
    # 入参：
    #   无显式入参。
    # 出参：Optional[str]；文本字符串或 None。
    @property
    def OPENAI_API_KEY(self) -> Optional[str]:
        return self.LLM_API_KEY

    # 方法说明：OPENAI_API_BASE
    # 作用：提供兼容旧配置名称的语言模型服务地址。
    # 入参：
    #   无显式入参。
    # 出参：str；文本字符串。
    @property
    def OPENAI_API_BASE(self) -> str:
        return self.LLM_BASE_URL

    # 方法说明：OPENAI_MODEL
    # 作用：提供兼容旧配置名称的语言模型名称。
    # 入参：
    #   无显式入参。
    # 出参：str；文本字符串。
    @property
    def OPENAI_MODEL(self) -> str:
        return self.LLM_MODEL

    # 方法说明：configuration_issues
    # 作用：汇总配置缺失、占位值或不安全组合，供启动校验使用。
    # 入参：
    #   无显式入参。
    # 出参：List[str]；当前配置中需要处理的问题说明列表。
    @property
    def configuration_issues(self) -> List[str]:

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


settings = Settings()  # type: ignore[call-arg]
