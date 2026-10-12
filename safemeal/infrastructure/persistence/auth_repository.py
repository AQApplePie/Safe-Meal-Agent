"""实现持久化基础设施适配。"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from types import TracebackType
from typing import cast

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from safemeal.modules.identity.contracts import UserCreate
from safemeal.shared.exceptions import EmailAlreadyRegisteredError
from safemeal.modules.identity.ports.auth_repository import AuthUnitOfWork
from safemeal.infrastructure.persistence.database import session_scope
from safemeal.infrastructure.persistence.db.models import RefreshToken, User


# 类说明（SQL 类）：SqlAlchemyAuthRepository
# 作用：实现用户与刷新令牌 SQL 仓储的查询、写入或运行状态持久化。
class SqlAlchemyAuthRepository:
    # 方法说明：__init__
    # 作用：初始化用户与刷新令牌 SQL 仓储，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   session（Session）：当前 SQL 会话或聊天会话对象。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, session: Session) -> None:
        # 实例属性说明：_session
        # 作用：当前 SQL 会话或聊天会话对象。
        self._session = session

    # 方法说明：create_user
    # 作用：创建带租户、密码哈希和角色的用户记录。
    # 入参：
    #   data（UserCreate）：用户创建契约。
    # 出参：User；用户账户数据库模型。
    def create_user(self, data: UserCreate) -> User:
        entity = User(**data.model_dump(), status="active", roles=[], token_version=0)
        self._session.add(entity)
        try:
            self._session.flush()
        except IntegrityError as exc:
            raise EmailAlreadyRegisteredError() from exc
        return entity

    # 方法说明：get_user
    # 作用：按标识读取用户信息。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：User | None；用户账户数据库模型或None（未取得结果）。
    def get_user(self, user_id: str) -> User | None:
        return self._session.get(User, user_id)

    # 方法说明：get_user_by_email
    # 作用：按租户和规范化邮箱读取用户记录。
    # 入参：
    #   tenant_id（str）：可信租户标识，用于业务数据隔离。
    #   email（str）：用户邮箱。
    # 出参：User | None；用户账户数据库模型或None（未取得结果）。
    def get_user_by_email(self, tenant_id: str, email: str) -> User | None:
        return (
            self._session.query(User)
            .filter(User.tenant_id == tenant_id, User.email == email)
            .one_or_none()
        )

    # 方法说明：update_password_hash
    # 作用：保存升级后的密码哈希。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   password_hash（str）：已经持久化的密码哈希。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def update_password_hash(self, user_id: str, password_hash: str) -> None:
        self._session.query(User).filter(User.id == user_id).update(
            {User.password_hash: password_hash}, synchronize_session=False
        )
        self._session.flush()

    # 方法说明：increment_token_version
    # 作用：增加用户令牌版本，使之前签发的访问令牌失效。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def increment_token_version(self, user_id: str) -> None:
        self._session.query(User).filter(User.id == user_id).update(
            {User.token_version: User.token_version + 1}, synchronize_session=False
        )
        self._session.flush()

    # 方法说明：create_refresh_token
    # 作用：保存刷新令牌哈希及其有效期和撤销状态。
    # 入参：
    #   token_id（str）：访问令牌或刷新令牌的唯一标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   token_hash（str）：令牌的持久化哈希。
    #   expires_at（datetime）：令牌或租约的到期时间。
    # 出参：RefreshToken；刷新令牌数据库模型。
    def create_refresh_token(
        self,
        *,
        token_id: str,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
    ) -> RefreshToken:
        entity = RefreshToken(
            id=token_id,
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self._session.add(entity)
        self._session.flush()
        return entity

    # 方法说明：get_refresh_token
    # 作用：按令牌哈希读取刷新令牌记录。
    # 入参：
    #   token_hash（str）：令牌的持久化哈希。
    # 出参：RefreshToken | None；刷新令牌数据库模型或None（未取得结果）。
    def get_refresh_token(self, token_hash: str) -> RefreshToken | None:
        return (
            self._session.query(RefreshToken)
            .filter(RefreshToken.token_hash == token_hash)
            .with_for_update()
            .one_or_none()
        )

    # 方法说明：rotate_refresh_token
    # 作用：在事务内撤销旧刷新令牌并保存新令牌记录。
    # 入参：
    #   token_id（str）：访问令牌或刷新令牌的唯一标识。
    #   replaced_by_hash（str）：轮换后新刷新令牌的哈希。
    #   revoked_at（datetime）：刷新令牌撤销时间。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def rotate_refresh_token(
        self,
        token_id: str,
        *,
        replaced_by_hash: str,
        revoked_at: datetime,
    ) -> None:
        self._session.query(RefreshToken).filter(RefreshToken.id == token_id).update(
            {
                RefreshToken.revoked_at: revoked_at,
                RefreshToken.replaced_by_hash: replaced_by_hash,
            },
            synchronize_session=False,
        )
        self._session.flush()

    # 方法说明：revoke_refresh_token
    # 作用：按令牌哈希撤销单个刷新令牌。
    # 入参：
    #   token_id（str）：访问令牌或刷新令牌的唯一标识。
    #   revoked_at（datetime）：刷新令牌撤销时间。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def revoke_refresh_token(self, token_id: str, *, revoked_at: datetime) -> None:
        self._session.query(RefreshToken).filter(
            RefreshToken.id == token_id, RefreshToken.revoked_at.is_(None)
        ).update({RefreshToken.revoked_at: revoked_at}, synchronize_session=False)
        self._session.flush()

    # 方法说明：revoke_all_refresh_tokens
    # 作用：撤销用户已有刷新令牌，停止后续刷新。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   revoked_at（datetime）：刷新令牌撤销时间。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def revoke_all_refresh_tokens(self, user_id: str, *, revoked_at: datetime) -> None:
        (
            self._session.query(RefreshToken)
            .filter(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .update({RefreshToken.revoked_at: revoked_at}, synchronize_session=False)
        )
        self._session.flush()


# 类说明（SQL 类）：SqlAlchemyAuthUnitOfWork
# 作用：管理身份 SQL 事务工作单元的会话、提交与回滚边界。
class SqlAlchemyAuthUnitOfWork:
    # 方法说明：__init__
    # 作用：初始化身份 SQL 事务工作单元，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   session_factory（Callable[[], Session] | None）：创建 SQLAlchemy 会话的工厂；默认值为
    # None。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, *, session_factory: Callable[[], Session] | None = None) -> None:
        # 实例属性说明：_session_factory
        # 作用：创建 SQLAlchemy 会话的工厂。
        self._session_factory = session_factory
        # 实例属性说明：_scope
        # 作用：当前请求或查询的可信范围。
        # 类型：AbstractContextManager[Session] | None。
        # 初始值：None。
        self._scope: AbstractContextManager[Session] | None = None
        # 实例属性说明：_session
        # 作用：当前 SQL 会话或聊天会话对象。
        # 类型：Session | None。
        # 初始值：None。
        self._session: Session | None = None
        # 实例属性说明：_auth
        # 作用：当前 SQL 工作单元中的身份仓储，随事务会话创建。
        # 类型：SqlAlchemyAuthRepository | None。
        # 初始值：None。
        self._auth: SqlAlchemyAuthRepository | None = None

    # 方法说明：auth
    # 作用：取得当前工作单元绑定的身份数据仓储。
    # 入参：
    #   无显式入参。
    # 出参：SqlAlchemyAuthRepository；当前事务内的身份仓储。
    @property
    def auth(self) -> SqlAlchemyAuthRepository:
        if self._auth is None:
            raise RuntimeError("auth Unit of Work is not active")
        return self._auth

    # 方法说明：__enter__
    # 作用：进入工作单元并创建事务资源，供 with 块内的仓储操作共享。
    # 入参：
    #   无显式入参。
    # 出参：'SqlAlchemyAuthUnitOfWork'；身份 SQL 事务工作单元。
    def __enter__(self) -> "SqlAlchemyAuthUnitOfWork":
        scope = session_scope(commit=False, session_factory=self._session_factory)
        self._session = scope.__enter__()
        self._scope = scope
        self._auth = SqlAlchemyAuthRepository(self._session)
        return self

    # 方法说明：commit
    # 作用：提交当前工作单元的数据库事务。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("auth Unit of Work is not active")
        self._session.commit()

    # 方法说明：rollback
    # 作用：回滚当前工作单元的数据库事务。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def rollback(self) -> None:
        if self._session is not None:
            self._session.rollback()

    # 方法说明：__exit__
    # 作用：退出工作单元；异常时回滚事务，并关闭会话释放连接。
    # 入参：
    #   exc_type（type[BaseException] | None）：退出上下文时的异常类型。
    #   exc_value（BaseException | None）：当前捕获或退出上下文时传入的异常对象。
    #   traceback（TracebackType | None）：退出上下文时传入的异常堆栈。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._scope is None:
            raise RuntimeError("auth Unit of Work is not active")
        try:
            self._scope.__exit__(exc_type, exc_value, traceback)
        finally:
            self._scope = None
            self._session = None
            self._auth = None


# 方法说明：sqlalchemy_auth_unit_of_work
# 作用：创建身份模块 SQL 事务工作单元上下文。
# 入参：
#   无显式入参。
# 出参：AuthUnitOfWork；事务工作单元上下文；进入 with 块时取得对应事务和仓储能力。
def sqlalchemy_auth_unit_of_work() -> AuthUnitOfWork:
    return cast(AuthUnitOfWork, SqlAlchemyAuthUnitOfWork())


__all__ = [
    "SqlAlchemyAuthRepository",
    "SqlAlchemyAuthUnitOfWork",
    "sqlalchemy_auth_unit_of_work",
]
