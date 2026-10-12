"""实现身份认证与令牌安全适配。"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from argon2 import PasswordHasher as Argon2Hasher
from argon2.exceptions import InvalidHashError, VerificationError
import jwt

from safemeal.modules.identity.contracts import AccessTokenClaims


# 类说明（业务或基础设施实现类）：Argon2PasswordHasher
# 作用：实现Argon2 密码哈希实现，封装该组件的业务处理与依赖协作。
class Argon2PasswordHasher:
    # 方法说明：__init__
    # 作用：初始化Argon2 密码哈希实现，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self) -> None:
        # 实例属性说明：_hasher
        # 作用：Argon2 密码哈希计算与验证实现。
        self._hasher = Argon2Hasher()

    # 方法说明：hash
    # 作用：为明文密码生成安全哈希。
    # 入参：
    #   password（str）：用户提供的明文密码，仅用于校验或生成哈希。
    # 出参：str；可持久化的密码哈希文本。
    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    # 方法说明：verify
    # 作用：校验明文密码与已存密码哈希是否匹配。
    # 入参：
    #   password_hash（str）：已经持久化的密码哈希。
    #   password（str）：用户提供的明文密码，仅用于校验或生成哈希。
    # 出参：bool；明文密码与保存的哈希是否匹配。
    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (VerificationError, InvalidHashError):
            return False

    # 方法说明：needs_rehash
    # 作用：判断密码哈希参数是否需要升级。
    # 入参：
    #   password_hash（str）：已经持久化的密码哈希。
    # 出参：bool；密码哈希是否需要升级参数。
    def needs_rehash(self, password_hash: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(password_hash)
        except InvalidHashError:
            return True


# 类说明（业务或基础设施实现类）：JwtTokenIssuer
# 作用：实现JWT 访问令牌签发与校验实现，封装该组件的业务处理与依赖协作。
class JwtTokenIssuer:
    # 方法说明：__init__
    # 作用：初始化JWT 访问令牌签发与校验实现，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   secret（str）：令牌签名密钥。
    #   issuer（str）：访问令牌预期签发者。
    #   audience（str）：访问令牌预期受众。
    #   access_token_minutes（int）：访问令牌有效时长，单位分钟。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(
        self,
        *,
        secret: str,
        issuer: str,
        audience: str,
        access_token_minutes: int,
    ) -> None:
        # 实例属性说明：_secret
        # 作用：令牌签名密钥。
        self._secret = secret
        # 实例属性说明：_issuer
        # 作用：访问令牌预期签发者。
        self._issuer = issuer
        # 实例属性说明：_audience
        # 作用：访问令牌预期受众。
        self._audience = audience
        # 实例属性说明：_access_token_minutes
        # 作用：访问令牌有效时长，单位分钟。
        self._access_token_minutes = access_token_minutes

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
    ) -> tuple[str, datetime]:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=self._access_token_minutes)
        token = jwt.encode(
            {
                "sub": subject,
                "tid": tenant_id,
                "roles": list(roles),
                "ver": token_version,
                "typ": "access",
                "jti": uuid4().hex,
                "iat": now,
                "nbf": now,
                "exp": expires_at,
                "iss": self._issuer,
                "aud": self._audience,
            },
            self._secret,
            algorithm="HS256",
        )
        return token, expires_at

    # 方法说明：decode_access_token
    # 作用：校验访问令牌签名和声明，并解析令牌负载。
    # 入参：
    #   token（str）：令牌或本次租约的处理凭证。
    # 出参：AccessTokenClaims；访问令牌声明。
    def decode_access_token(self, token: str) -> AccessTokenClaims:
        payload = jwt.decode(
            token,
            self._secret,
            algorithms=["HS256"],
            issuer=self._issuer,
            audience=self._audience,
            options={"require": ["sub", "tid", "ver", "typ", "exp", "iat"]},
        )
        if payload.get("typ") != "access":
            raise jwt.InvalidTokenError("unexpected token type")
        roles = payload.get("roles")
        return AccessTokenClaims(
            subject=str(payload["sub"]),
            tenant_id=str(payload["tid"]),
            roles=tuple(str(item) for item in roles) if isinstance(roles, list) else (),
            token_version=int(payload["ver"]),
            expires_at=datetime.fromtimestamp(float(payload["exp"]), timezone.utc),
        )
