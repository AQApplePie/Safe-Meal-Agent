"""定义跨层传递的稳定数据契约。"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# 方法说明：normalize_email
# 作用：清理邮箱并统一邮箱查找所需的格式。
# 入参：
#   value（str）：当前待转换或校验的值。
# 出参：str；文本字符串。
def normalize_email(value: str) -> str:
    normalized = value.strip().casefold()
    if len(normalized) > 320 or not re.fullmatch(
        r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?",
        normalized,
    ):
        raise ValueError("invalid email address")
    return normalized


# 类说明（数据契约类）：RegisterRequest
# 作用：描述用户注册请求的结构、类型及可校验字段。
class RegisterRequest(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(extra="forbid")

    # 字段说明：email
    # 作用：用户邮箱。
    # 类型：str。
    # 配置：最小长度=3；最大长度=320。
    email: str = Field(min_length=3, max_length=320)
    # 字段说明：password
    # 作用：用户提供的明文密码，仅用于校验或生成哈希。
    # 类型：str。
    # 配置：最小长度=12；最大长度=128。
    password: str = Field(min_length=12, max_length=128)
    # 字段说明：display_name
    # 作用：供界面显示的名称，不作为身份认证依据。
    # 类型：str | None。
    # 配置：默认值=None；最小长度=1；最大长度=100。
    display_name: str | None = Field(default=None, min_length=1, max_length=100)

    # 方法说明：validate_email
    # 作用：校验邮箱格式与长度。
    # 入参：
    #   value（str）：当前待转换或校验的值。
    # 出参：str；文本字符串。
    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalize_email(value)

    # 方法说明：validate_password
    # 作用：校验密码长度与输入合法性。
    # 入参：
    #   value（str）：当前待转换或校验的值。
    # 出参：str；文本字符串。
    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
            raise ValueError("password must contain at least one letter and one digit")
        return value


# 类说明（数据契约类）：LoginRequest
# 作用：描述用户登录请求的结构、类型及可校验字段。
class LoginRequest(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(extra="forbid")

    # 字段说明：email
    # 作用：用户邮箱。
    # 类型：str。
    # 配置：最小长度=3；最大长度=320。
    email: str = Field(min_length=3, max_length=320)
    # 字段说明：password
    # 作用：用户提供的明文密码，仅用于校验或生成哈希。
    # 类型：str。
    # 配置：最小长度=1；最大长度=128。
    password: str = Field(min_length=1, max_length=128)

    # 方法说明：validate_email
    # 作用：校验邮箱格式与长度。
    # 入参：
    #   value（str）：当前待转换或校验的值。
    # 出参：str；文本字符串。
    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalize_email(value)


# 类说明（数据契约类）：RefreshRequest
# 作用：描述刷新登录令牌请求的结构、类型及可校验字段。
class RefreshRequest(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(extra="forbid")
    # 字段说明：refresh_token
    # 作用：续签访问令牌所用的刷新凭据或凭据集合。
    # 类型：str。
    # 配置：最小长度=32；最大长度=512。
    refresh_token: str = Field(min_length=32, max_length=512)


# 类说明（业务或基础设施实现类）：LogoutRequest
# 作用：实现用户登出请求，封装该组件的业务处理与依赖协作。
class LogoutRequest(RefreshRequest):
    pass


# 类说明（数据契约类）：UserCreate
# 作用：描述用户创建契约的结构、类型及可校验字段。
class UserCreate(BaseModel):
    # 字段说明：id
    # 作用：该业务记录的唯一标识，SQL 模型中通常对应主键。
    # 类型：str。
    id: str
    # 字段说明：tenant_id
    # 作用：可信租户标识，用于业务数据隔离。
    # 类型：str。
    tenant_id: str
    # 字段说明：email
    # 作用：用户邮箱。
    # 类型：str。
    email: str
    # 字段说明：password_hash
    # 作用：已经持久化的密码哈希。
    # 类型：str。
    password_hash: str
    # 字段说明：display_name
    # 作用：供界面显示的名称，不作为身份认证依据。
    # 类型：str | None。
    # 初始值：None。
    display_name: str | None = None


# 类说明（数据契约类）：UserRead
# 作用：描述用户公开读取视图的结构、类型及可校验字段。
class UserRead(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    model_config = ConfigDict(from_attributes=True)

    # 字段说明：id
    # 作用：该业务记录的唯一标识，SQL 模型中通常对应主键。
    # 类型：str。
    id: str
    # 字段说明：tenant_id
    # 作用：可信租户标识，用于业务数据隔离。
    # 类型：str。
    tenant_id: str
    # 字段说明：email
    # 作用：用户邮箱。
    # 类型：str。
    email: str
    # 字段说明：display_name
    # 作用：供界面显示的名称，不作为身份认证依据。
    # 类型：str | None。
    # 初始值：None。
    display_name: str | None = None
    # 字段说明：status
    # 作用：HTTP 状态码或业务状态。
    # 类型：Literal['active', 'disabled', 'locked']。
    # 取值说明：
    #   active：处于可用状态。
    #   disabled：已关闭。
    #   locked：已锁定，不能按普通路径使用。
    status: Literal["active", "disabled", "locked"]
    # 字段说明：roles
    # 作用：用户拥有的角色集合。
    # 类型：tuple[str, ...]。
    # 初始值：()。
    roles: tuple[str, ...] = ()
    # 字段说明：created_at
    # 作用：记录创建时间，用于排序和审计。
    # 类型：datetime。
    created_at: datetime
    # 字段说明：updated_at
    # 作用：记录最后更新时间。
    # 类型：datetime | None。
    # 初始值：None。
    updated_at: datetime | None = None


# 类说明（数据契约类）：AuthTokens
# 作用：描述访问与刷新令牌响应的结构、类型及可校验字段。
class AuthTokens(BaseModel):
    # 字段说明：access_token
    # 作用：登录成功后访问受保护接口所用的短期身份令牌。
    # 类型：str。
    access_token: str
    # 字段说明：refresh_token
    # 作用：续签访问令牌所用的刷新凭据或凭据集合。
    # 类型：str。
    refresh_token: str
    # 字段说明：token_type
    # 作用：访问令牌的认证方案，bearer 表示由持有者携带令牌认证。
    # 类型：Literal['bearer']。
    # 初始值：'bearer'。
    # 取值说明：
    #   bearer：以 Bearer 方式携带身份令牌。
    token_type: Literal["bearer"] = "bearer"
    # 字段说明：expires_in
    # 作用：访问令牌剩余有效时间，单位为秒。
    # 类型：int。
    expires_in: int
    # 字段说明：user
    # 作用：当前用户的仓储记录。
    # 类型：UserRead。
    user: UserRead


# 类说明（数据契约类）：CurrentIdentity
# 作用：描述当前用户身份响应的结构、类型及可校验字段。
class CurrentIdentity(BaseModel):
    # 字段说明：subject
    # 作用：当前身份的用户主体标识。
    # 类型：str。
    subject: str
    # 字段说明：tenant_id
    # 作用：可信租户标识，用于业务数据隔离。
    # 类型：str。
    tenant_id: str
    # 字段说明：roles
    # 作用：用户拥有的角色集合。
    # 类型：tuple[str, ...]。
    # 初始值：()。
    roles: tuple[str, ...] = ()
    # 字段说明：provider
    # 作用：当前选中的外部模型供应商。
    # 类型：Literal['local', 'oidc']。
    # 取值说明：
    #   local：使用本地实现或本地数据。
    #   oidc：使用 OIDC 外部身份认证。
    provider: Literal["local", "oidc"]
    # 字段说明：email
    # 作用：用户邮箱。
    # 类型：str | None。
    # 初始值：None。
    email: str | None = None
    # 字段说明：display_name
    # 作用：供界面显示的名称，不作为身份认证依据。
    # 类型：str | None。
    # 初始值：None。
    display_name: str | None = None
    # 字段说明：status
    # 作用：HTTP 状态码或业务状态。
    # 类型：Literal['active', 'disabled', 'locked'] | None。
    # 初始值：None。
    # 取值说明：
    #   active：处于可用状态。
    #   disabled：已关闭。
    #   locked：已锁定，不能按普通路径使用。
    status: Literal["active", "disabled", "locked"] | None = None


# 类说明（数据契约类）：AccessTokenClaims
# 作用：描述访问令牌声明的结构、类型及可校验字段。
class AccessTokenClaims(BaseModel):
    # 字段说明：subject
    # 作用：当前身份的用户主体标识。
    # 类型：str。
    subject: str
    # 字段说明：tenant_id
    # 作用：可信租户标识，用于业务数据隔离。
    # 类型：str。
    tenant_id: str
    # 字段说明：roles
    # 作用：用户拥有的角色集合。
    # 类型：tuple[str, ...]。
    # 初始值：()。
    roles: tuple[str, ...] = ()
    # 字段说明：token_version
    # 作用：用户当前令牌版本。
    # 类型：int。
    token_version: int
    # 字段说明：expires_at
    # 作用：令牌或租约的到期时间。
    # 类型：datetime。
    expires_at: datetime
