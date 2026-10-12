"""定义应用层依赖的能力端口。"""

from datetime import datetime
from typing import Protocol

from safemeal.modules.identity.contracts import AccessTokenClaims


# 类说明（接口类）：PasswordHasher
# 作用：定义密码哈希接口的能力契约，供应用层与具体实现解耦。
class PasswordHasher(Protocol):
    # 方法说明：hash
    # 作用：为明文密码生成安全哈希。
    # 入参：
    #   password（str）：用户提供的明文密码，仅用于校验或生成哈希。
    # 出参：str；可持久化的密码哈希文本。
    def hash(self, password: str) -> str: ...
    # 方法说明：verify
    # 作用：校验明文密码与已存密码哈希是否匹配。
    # 入参：
    #   password_hash（str）：已经持久化的密码哈希。
    #   password（str）：用户提供的明文密码，仅用于校验或生成哈希。
    # 出参：bool；明文密码与保存的哈希是否匹配。
    def verify(self, password_hash: str, password: str) -> bool: ...
    # 方法说明：needs_rehash
    # 作用：判断密码哈希参数是否需要升级。
    # 入参：
    #   password_hash（str）：已经持久化的密码哈希。
    # 出参：bool；密码哈希是否需要升级参数。
    def needs_rehash(self, password_hash: str) -> bool: ...


# 类说明（接口类）：TokenIssuer
# 作用：定义令牌签发与校验接口的能力契约，供应用层与具体实现解耦。
class TokenIssuer(Protocol):
    # 方法说明：issue_access_token
    # 作用：签发含身份、角色、有效期和版本的访问令牌。
    # 入参：
    #   subject（str）：当前身份的用户主体标识。
    #   tenant_id（str）：可信租户标识，用于业务数据隔离。
    #   roles（tuple[str, ...]）：用户拥有的角色集合。
    #   token_version（int）：用户当前令牌版本。
    # 出参：tuple[str, datetime]；文本字符串、日期时间组成的元组。
    def issue_access_token(
        self,
        *,
        subject: str,
        tenant_id: str,
        roles: tuple[str, ...],
        token_version: int,
    ) -> tuple[str, datetime]: ...

    # 方法说明：decode_access_token
    # 作用：校验访问令牌签名和声明，并解析令牌负载。
    # 入参：
    #   token（str）：令牌或本次租约的处理凭证。
    # 出参：AccessTokenClaims；访问令牌声明。
    def decode_access_token(self, token: str) -> AccessTokenClaims: ...
