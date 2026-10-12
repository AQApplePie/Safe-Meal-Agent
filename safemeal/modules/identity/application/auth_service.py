"""处理注册、登录、令牌轮换与身份认证。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import secrets
from uuid import uuid4

from safemeal.modules.identity.contracts import (
    AccessTokenClaims,
    AuthTokens,
    LoginRequest,
    RegisterRequest,
    UserCreate,
    UserRead,
)
from safemeal.shared.exceptions import (
    AccountDisabledError,
    AuthenticationError,
    EmailAlreadyRegisteredError,
    InvalidAccessTokenError,
    InvalidRefreshTokenError,
)
from safemeal.modules.identity.ports.auth_repository import (
    AuthUnitOfWorkFactory,
    UserRecord,
)
from safemeal.modules.identity.ports.security import PasswordHasher, TokenIssuer


# 类说明（业务或基础设施实现类）：AuthService
# 作用：实现注册登录与令牌管理服务，封装该组件的业务处理与依赖协作。
class AuthService:
    # 方法说明：__init__
    # 作用：初始化注册登录与令牌管理服务，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   uow_factory（AuthUnitOfWorkFactory）：创建事务工作单元的工厂。
    #   password_hasher（PasswordHasher）：密码哈希与校验组件。
    #   token_issuer（TokenIssuer）：访问令牌签发与验证组件。
    #   refresh_token_days（int）：刷新令牌有效时长，单位天。
    #   default_tenant_id（str）：未显式指定时使用的租户标识。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(
        self,
        *,
        uow_factory: AuthUnitOfWorkFactory,
        password_hasher: PasswordHasher,
        token_issuer: TokenIssuer,
        refresh_token_days: int,
        default_tenant_id: str,
    ) -> None:
        # 实例属性说明：_uow_factory
        # 作用：创建事务工作单元的工厂。
        self._uow_factory = uow_factory
        # 实例属性说明：_password_hasher
        # 作用：密码哈希与校验组件。
        self._password_hasher = password_hasher
        # 实例属性说明：_token_issuer
        # 作用：访问令牌签发与验证组件。
        self._token_issuer = token_issuer
        # 实例属性说明：_refresh_token_days
        # 作用：刷新令牌有效时长，单位天。
        self._refresh_token_days = refresh_token_days
        # 实例属性说明：_default_tenant_id
        # 作用：未显式指定时使用的租户标识。
        self._default_tenant_id = default_tenant_id
        # 实例属性说明：_dummy_password_hash
        # 作用：不存在用户时用于执行密码校验的占位哈希，减少登录时序差异。
        self._dummy_password_hash = password_hasher.hash(secrets.token_urlsafe(32))

    # 方法说明：register
    # 作用：创建租户内用户并签发首次登录令牌。
    # 入参：
    #   request（RegisterRequest）：用户注册请求。
    # 出参：AuthTokens；访问与刷新令牌响应。
    def register(self, request: RegisterRequest) -> AuthTokens:
        with self._uow_factory() as uow:
            if uow.auth.get_user_by_email(self._default_tenant_id, request.email):
                raise EmailAlreadyRegisteredError()
            user = uow.auth.create_user(
                UserCreate(
                    id=str(uuid4()),
                    tenant_id=self._default_tenant_id,
                    email=request.email,
                    password_hash=self._password_hasher.hash(request.password),
                    display_name=request.display_name,
                )
            )
            tokens = self._issue_tokens(uow, user)
            uow.commit()
            return tokens

    # 方法说明：login
    # 作用：校验租户、账号与密码并签发登录令牌。
    # 入参：
    #   request（LoginRequest）：用户登录请求。
    # 出参：AuthTokens；访问与刷新令牌响应。
    def login(self, request: LoginRequest) -> AuthTokens:
        with self._uow_factory() as uow:
            user = uow.auth.get_user_by_email(self._default_tenant_id, request.email)
            password_hash = (
                user.password_hash if user is not None else self._dummy_password_hash
            )
            password_matches = self._password_hasher.verify(
                password_hash, request.password
            )
            if user is None or not password_matches:
                raise AuthenticationError()
            self._require_active(user)
            if self._password_hasher.needs_rehash(user.password_hash):
                uow.auth.update_password_hash(
                    user.id, self._password_hasher.hash(request.password)
                )
            tokens = self._issue_tokens(uow, user)
            uow.commit()
            return tokens

    # 方法说明：refresh
    # 作用：校验并轮换刷新令牌，重新签发访问令牌。
    # 入参：
    #   raw_token（str）：客户端提交的原始令牌。
    # 出参：AuthTokens；访问与刷新令牌响应。
    def refresh(self, raw_token: str) -> AuthTokens:
        token_hash = self._refresh_hash(raw_token)
        now = datetime.now(timezone.utc)
        with self._uow_factory() as uow:
            stored = uow.auth.get_refresh_token(token_hash)
            if stored is None:
                raise InvalidRefreshTokenError()
            user = uow.auth.get_user(stored.user_id)
            if user is None:
                raise InvalidRefreshTokenError()
            if stored.revoked_at is not None:
                if stored.replaced_by_hash is not None:
                    uow.auth.revoke_all_refresh_tokens(user.id, revoked_at=now)
                    uow.auth.increment_token_version(user.id)
                    uow.commit()
                raise InvalidRefreshTokenError()
            if self._as_utc(stored.expires_at) <= now:
                uow.auth.revoke_refresh_token(stored.id, revoked_at=now)
                uow.commit()
                raise InvalidRefreshTokenError()
            self._require_active(user)
            raw_next, next_hash = self._new_refresh_token()
            uow.auth.rotate_refresh_token(
                stored.id, replaced_by_hash=next_hash, revoked_at=now
            )
            tokens = self._issue_tokens(
                uow, user, raw_refresh_token=raw_next, refresh_hash=next_hash
            )
            uow.commit()
            return tokens

    # 方法说明：logout
    # 作用：撤销当前刷新令牌或用户已有登录凭据。
    # 入参：
    #   raw_token（str）：客户端提交的原始令牌。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def logout(self, raw_token: str) -> None:
        token_hash = self._refresh_hash(raw_token)
        with self._uow_factory() as uow:
            stored = uow.auth.get_refresh_token(token_hash)
            if stored is not None and stored.revoked_at is None:
                uow.auth.revoke_refresh_token(
                    stored.id, revoked_at=datetime.now(timezone.utc)
                )
                uow.commit()

    # 方法说明：authenticate_access_token
    # 作用：校验访问令牌和用户状态，建立当前可信身份。
    # 入参：
    #   raw_token（str）：客户端提交的原始令牌。
    # 出参：UserRead；用户公开读取视图。
    def authenticate_access_token(self, raw_token: str) -> UserRead:
        try:
            claims: AccessTokenClaims = self._token_issuer.decode_access_token(
                raw_token
            )
        except Exception as exc:
            raise InvalidAccessTokenError() from exc
        with self._uow_factory() as uow:
            user = uow.auth.get_user(claims.subject)
            if user is None or user.tenant_id != claims.tenant_id:
                raise InvalidAccessTokenError()
            self._require_active(user)
            if user.token_version != claims.token_version:
                raise InvalidAccessTokenError()
            return self._read_user(user)

    # 方法说明：get_user
    # 作用：按标识读取用户信息。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：UserRead；用户公开读取视图。
    def get_user(self, user_id: str) -> UserRead:
        with self._uow_factory() as uow:
            user = uow.auth.get_user(user_id)
            if user is None:
                raise InvalidAccessTokenError()
            self._require_active(user)
            return self._read_user(user)

    # 方法说明：_issue_tokens
    # 作用：签发访问令牌与刷新令牌，并持久化刷新令牌记录。
    # 入参：
    #   uow（由调用契约决定）：当前事务工作单元。
    #   user（UserRecord）：当前用户的仓储记录。
    #   raw_refresh_token（str | None）：客户端提交的原始令牌；默认值为 None。
    #   refresh_hash（str | None）：刷新令牌的哈希值；默认值为 None。
    # 出参：AuthTokens；访问与刷新令牌响应。
    def _issue_tokens(
        self,
        uow,
        user: UserRecord,
        *,
        raw_refresh_token: str | None = None,
        refresh_hash: str | None = None,
    ) -> AuthTokens:
        access_token, access_expires_at = self._token_issuer.issue_access_token(
            subject=user.id,
            tenant_id=user.tenant_id,
            roles=tuple(user.roles),
            token_version=user.token_version,
        )
        if raw_refresh_token is None or refresh_hash is None:
            raw_refresh_token, refresh_hash = self._new_refresh_token()
        uow.auth.create_refresh_token(
            token_id=str(uuid4()),
            user_id=user.id,
            token_hash=refresh_hash,
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=self._refresh_token_days),
        )
        expires_in = max(
            1,
            int((access_expires_at - datetime.now(timezone.utc)).total_seconds()),
        )
        return AuthTokens(
            access_token=access_token,
            refresh_token=raw_refresh_token,
            expires_in=expires_in,
            user=self._read_user(user),
        )

    # 方法说明：_read_user
    # 作用：按用户标识读取用户记录并转换为仓储记录。
    # 入参：
    #   user（UserRecord）：当前用户的仓储记录。
    # 出参：UserRead；用户公开读取视图。
    @staticmethod
    def _read_user(user: UserRecord) -> UserRead:
        return UserRead.model_validate(user)

    # 方法说明：_require_active
    # 作用：校验账户处于允许登录和访问的活动状态。
    # 入参：
    #   user（UserRecord）：当前用户的仓储记录。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    @staticmethod
    def _require_active(user: UserRecord) -> None:
        if user.status != "active":
            raise AccountDisabledError()

    # 方法说明：_new_refresh_token
    # 作用：生成随机刷新令牌及对应的持久化哈希。
    # 入参：
    #   无显式入参。
    # 出参：tuple[str, str]；文本字符串、文本字符串组成的元组。
    @staticmethod
    def _new_refresh_token() -> tuple[str, str]:
        raw = secrets.token_urlsafe(48)
        return raw, AuthService._refresh_hash(raw)

    # 方法说明：_refresh_hash
    # 作用：计算刷新令牌哈希，避免在数据库中保存明文令牌。
    # 入参：
    #   raw_token（str）：客户端提交的原始令牌。
    # 出参：str；刷新令牌的单向哈希文本。
    @staticmethod
    def _refresh_hash(raw_token: str) -> str:
        return sha256(raw_token.encode("utf-8")).hexdigest()

    # 方法说明：_as_utc
    # 作用：将日期时间归一化为 UTC，统一时间比较与存储语义。
    # 入参：
    #   value（datetime）：当前待转换或校验的值。
    # 出参：datetime；日期时间。
    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
