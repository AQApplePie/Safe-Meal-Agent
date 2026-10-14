"""独立食谱后端与 Agent 共用的 HTTP、数据库和身份配置。"""

from typing import List, Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# 类说明（业务或基础设施实现类）：PlatformSettings
# 作用：实现传统平台独立运行配置，封装该组件的业务处理与依赖协作。
class PlatformSettings(BaseSettings):
    # 独立入口不读取 Agent 的 .env；可显式传入 _env_file。
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：环境变量名是否区分大小写=True；额外字段策略（forbid 禁止，ignore 忽略）='ignore'。
    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    # 字段说明：APP_ENV
    # 作用：应用运行环境，供该组件初始化及运行控制使用。
    # 类型：Literal['development', 'test', 'production']。
    # 初始值：'development'。
    # 取值说明：
    #   development：开发环境。
    #   test：测试环境。
    #   production：生产环境。
    APP_ENV: Literal["development", "test", "production"] = "development"

    # 字段说明：APP_NAME
    # 作用：应用名称，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'SafeMeal Recipe Platform'。
    APP_NAME: str = "SafeMeal Recipe Platform"

    # 字段说明：APP_VERSION
    # 作用：应用版本，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'0.1.2'。
    APP_VERSION: str = "0.1.2"

    # 字段说明：DEBUG
    # 作用：是否启用应用调试模式。
    # 类型：bool。
    # 初始值：False。
    DEBUG: bool = False

    # 字段说明：API_V1_PREFIX
    # 作用：接口第一版路径前缀，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'/api/v1'。
    API_V1_PREFIX: str = "/api/v1"

    # 字段说明：HOST
    # 作用：应用服务监听的网络地址。
    # 类型：str。
    # 初始值：'0.0.0.0'。
    HOST: str = "0.0.0.0"

    # 字段说明：PORT
    # 作用：应用服务监听端口，范围为 1 至 65535。
    # 类型：int。
    # 配置：默认值=8000；最小值（含）=1；最大值（含）=65535。
    PORT: int = Field(default=8000, ge=1, le=65535)

    # 字段说明：METRICS_ENABLED
    # 作用：监控指标启用开关，供该组件初始化及运行控制使用。
    # 类型：bool。
    # 初始值：False。
    METRICS_ENABLED: bool = False
    # 字段说明：METRICS_OUTBOX_SCRAPE_SECONDS
    # 作用：监控指标事务发件箱采集间隔秒数，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=5；最小值（含）=1；最大值（含）=60。
    METRICS_OUTBOX_SCRAPE_SECONDS: int = Field(default=5, ge=1, le=60)
    # 字段说明：METRICS_TOKEN
    # 作用：监控指标令牌，供该组件初始化及运行控制使用。
    # 类型：Optional[str]。
    # 配置：默认值=None；最小长度=32。
    METRICS_TOKEN: Optional[str] = Field(default=None, repr=False, min_length=32)

    # 方法说明：empty_metrics_token
    # 作用：检查指标访问令牌是否为空或仅含空白。
    # 入参：
    #   value（object）：当前待转换或校验的值。
    # 出参：object；由调用约定决定的数据对象。
    @field_validator("METRICS_TOKEN", mode="before")
    @classmethod
    def empty_metrics_token(cls, value: object) -> object:
        return None if value == "" else value

    # 字段说明：HTTP_MAX_BODY_MB
    # 作用：HTTP 请求最大请求体兆字节上限，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=12；最小值（含）=1；最大值（含）=100。
    HTTP_MAX_BODY_MB: int = Field(default=12, ge=1, le=100)

    # 字段说明：HTTP_RATE_LIMIT_PER_MINUTE
    # 作用：HTTP 请求速率上限每分钟，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=120；最小值（含）=1；最大值（含）=10000。
    HTTP_RATE_LIMIT_PER_MINUTE: int = Field(default=120, ge=1, le=10_000)

    # 字段说明：REDIS_RATE_LIMIT_URL
    # 作用：Redis速率上限连接地址，供该组件初始化及运行控制使用。
    # 类型：Optional[str]。
    # 初始值：None。
    REDIS_RATE_LIMIT_URL: Optional[str] = None

    # 字段说明：RECIPE_CACHE_URL
    # 作用：菜谱缓存连接地址，供该组件初始化及运行控制使用。
    # 类型：Optional[str]。
    # 初始值：None。
    RECIPE_CACHE_URL: Optional[str] = None

    # 字段说明：BEHAVIOR_EVENT_REDIS_URL
    # 作用：用户行为事件Redis连接地址，供该组件初始化及运行控制使用。
    # 类型：Optional[str]。
    # 初始值：None。
    BEHAVIOR_EVENT_REDIS_URL: Optional[str] = None

    # 字段说明：BEHAVIOR_EVENT_BATCH
    # 作用：用户行为事件批次大小，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=100；最小值（含）=1；最大值（含）=1000。
    BEHAVIOR_EVENT_BATCH: int = Field(default=100, ge=1, le=1000)

    # 字段说明：BEHAVIOR_EVENT_POLL_SECONDS
    # 作用：用户行为事件轮询秒数，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=1；最小值（含）=1；最大值（含）=60。
    BEHAVIOR_EVENT_POLL_SECONDS: int = Field(default=1, ge=1, le=60)

    # 字段说明：BEHAVIOR_EVENT_MAX_ATTEMPTS
    # 作用：用户行为事件最大尝试次数，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=5；最小值（含）=1；最大值（含）=20。
    BEHAVIOR_EVENT_MAX_ATTEMPTS: int = Field(default=5, ge=1, le=20)

    # 字段说明：RECIPE_RANKING_REDIS_URL
    # 作用：菜谱排行Redis连接地址，供该组件初始化及运行控制使用。
    # 类型：Optional[str]。
    # 初始值：None。
    RECIPE_RANKING_REDIS_URL: Optional[str] = None

    # 字段说明：RECIPE_RANKING_REFRESH_SECONDS
    # 作用：菜谱排行刷新秒数，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=30；最小值（含）=1；最大值（含）=3600。
    RECIPE_RANKING_REFRESH_SECONDS: int = Field(default=30, ge=1, le=3600)

    # 字段说明：RECIPE_RANKING_TTL_SECONDS
    # 作用：菜谱排行有效期秒数，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=300；最小值（含）=1；最大值（含）=86400。
    RECIPE_RANKING_TTL_SECONDS: int = Field(default=300, ge=1, le=86400)

    # 字段说明：RECIPE_RANKING_CAP
    # 作用：菜谱排行容量上限，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=1000；最小值（含）=1；最大值（含）=10000。
    RECIPE_RANKING_CAP: int = Field(default=1000, ge=1, le=10000)

    # 字段说明：RECIPE_RANKING_TENANT_BATCH
    # 作用：菜谱排行租户批次大小，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=50；最小值（含）=1；最大值（含）=1000。
    RECIPE_RANKING_TENANT_BATCH: int = Field(default=50, ge=1, le=1000)

    # 字段说明：RECIPE_RANKING_TIMEZONE
    # 作用：菜谱排行时区，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'Asia/Shanghai'。
    RECIPE_RANKING_TIMEZONE: str = "Asia/Shanghai"

    # 方法说明：valid_ranking_timezone
    # 作用：校验榜单日期使用的时区名称。
    # 入参：
    #   value（str）：当前待转换或校验的值。
    # 出参：str；文本字符串。
    @field_validator("RECIPE_RANKING_TIMEZONE")
    @classmethod
    def valid_ranking_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(
                "RECIPE_RANKING_TIMEZONE must be an IANA timezone"
            ) from exc
        return value

    # 字段说明：RECIPE_CACHE_TTL_SECONDS
    # 作用：菜谱缓存有效期秒数，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=60；最小值（含）=1；最大值（含）=3600。
    RECIPE_CACHE_TTL_SECONDS: int = Field(default=60, ge=1, le=3600)

    # 字段说明：CORS_ORIGINS
    # 作用：跨域允许来源列表，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'http://localhost:3000,http://localhost:5173'。
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    # 字段说明：AUTH_JWT_SECRET
    # 作用：身份认证JWT 令牌签名密钥，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'development-only-change-me'。
    AUTH_JWT_SECRET: str = "development-only-change-me"

    # 字段说明：AUTH_JWT_ISSUER
    # 作用：身份认证JWT 令牌签发方，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'safemeal'。
    AUTH_JWT_ISSUER: str = "safemeal"

    # 字段说明：AUTH_JWT_AUDIENCE
    # 作用：身份认证JWT 令牌接收方，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'safemeal-api'。
    AUTH_JWT_AUDIENCE: str = "safemeal-api"

    # 字段说明：AUTH_ACCESS_TOKEN_MINUTES
    # 作用：身份认证访问令牌有效分钟数，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=15；最小值（含）=1；最大值（含）=1440。
    AUTH_ACCESS_TOKEN_MINUTES: int = Field(default=15, ge=1, le=1_440)

    # 字段说明：AUTH_REFRESH_TOKEN_DAYS
    # 作用：身份认证刷新令牌有效天数，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=30；最小值（含）=1；最大值（含）=365。
    AUTH_REFRESH_TOKEN_DAYS: int = Field(default=30, ge=1, le=365)

    # 字段说明：DATABASE_URL
    # 作用：数据库连接地址，供该组件初始化及运行控制使用。
    # 类型：str。
    # 配置：最小长度=1。
    DATABASE_URL: str = Field(min_length=1)

    # 字段说明：DB_CONNECT_TIMEOUT
    # 作用：数据库连接超时秒数，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=10；最小值（含）=1；最大值（含）=120。
    DB_CONNECT_TIMEOUT: int = Field(default=10, ge=1, le=120)
    # 字段说明：DB_LOCK_WAIT_TIMEOUT_SECONDS
    # 作用：数据库锁等待超时秒数秒数，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=2；最小值（含）=1；最大值（含）=30。
    DB_LOCK_WAIT_TIMEOUT_SECONDS: int = Field(default=2, ge=1, le=30)
    # 字段说明：DB_TRANSACTION_MAX_ATTEMPTS
    # 作用：数据库事务最大尝试次数，供该组件初始化及运行控制使用。
    # 类型：int。
    # 配置：默认值=3；最小值（含）=1；最大值（含）=5。
    DB_TRANSACTION_MAX_ATTEMPTS: int = Field(default=3, ge=1, le=5)

    # 字段说明：ENABLE_OIDC
    # 作用：启用OIDC，供该组件初始化及运行控制使用。
    # 类型：bool。
    # 初始值：False。
    ENABLE_OIDC: bool = False

    # 字段说明：OIDC_ISSUER
    # 作用：OIDC签发方，供该组件初始化及运行控制使用。
    # 类型：Optional[str]。
    # 初始值：None。
    OIDC_ISSUER: Optional[str] = None

    # 字段说明：OIDC_AUDIENCE
    # 作用：OIDC接收方，供该组件初始化及运行控制使用。
    # 类型：Optional[str]。
    # 初始值：None。
    OIDC_AUDIENCE: Optional[str] = None

    # 字段说明：OIDC_JWKS_URL
    # 作用：OIDC公钥集连接地址，供该组件初始化及运行控制使用。
    # 类型：Optional[str]。
    # 初始值：None。
    OIDC_JWKS_URL: Optional[str] = None

    # 字段说明：OIDC_ALGORITHMS
    # 作用：OIDC算法列表，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'RS256'。
    OIDC_ALGORITHMS: str = "RS256"

    # 字段说明：OIDC_TENANT_CLAIM
    # 作用：OIDC租户声明名，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'tenant_id'。
    OIDC_TENANT_CLAIM: str = "tenant_id"

    # 字段说明：DEFAULT_TENANT_ID
    # 作用：默认租户标识，供该组件初始化及运行控制使用。
    # 类型：str。
    # 初始值：'default'。
    DEFAULT_TENANT_ID: str = "default"

    # 方法说明：cors_origins_list
    # 作用：解析跨域来源配置为可直接使用的来源列表。
    # 入参：
    #   无显式入参。
    # 出参：List[str]；已清理的跨域来源字符串列表。
    @property
    def cors_origins_list(self) -> List[str]:
        return [
            origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()
        ]

    # 方法说明：validate_platform
    # 作用：校验平台独立启动所需的数据库、Redis 和身份配置。
    # 入参：
    #   无显式入参。
    # 出参：'PlatformSettings'；传统平台独立运行配置。
    @model_validator(mode="after")
    def validate_platform(self) -> "PlatformSettings":
        if self.BEHAVIOR_EVENT_REDIS_URL and not self.RECIPE_RANKING_REDIS_URL:
            raise ValueError("Behavior events require RECIPE_RANKING_REDIS_URL")
        issues = []
        if self.APP_ENV == "production":
            if self.METRICS_ENABLED and not self.METRICS_TOKEN:
                issues.append("production metrics require METRICS_TOKEN")
            if self.DEBUG:
                issues.append("DEBUG must be false in production")
            if not self.DATABASE_URL.lower().startswith("mysql+pymysql://"):
                issues.append("production DATABASE_URL must use mysql+pymysql")
            if any(
                o == "*" or "localhost" in o or "127.0.0.1" in o
                for o in self.cors_origins_list
            ):
                issues.append(
                    "production CORS_ORIGINS must not contain wildcard or loopback origins"
                )
            if not self.ENABLE_OIDC and (
                self.AUTH_JWT_SECRET == "development-only-change-me"
                or len(self.AUTH_JWT_SECRET) < 32
            ):
                issues.append(
                    "production AUTH_JWT_SECRET must be changed and contain at least 32 characters"
                )
            if self.ENABLE_OIDC and not (self.OIDC_ISSUER and self.OIDC_AUDIENCE):
                issues.append("production OIDC requires issuer and audience")
        if issues:
            raise ValueError("invalid production configuration: " + "; ".join(issues))
        return self
