"""定义应用层依赖的能力端口。"""

from collections.abc import Callable
from datetime import datetime
from types import TracebackType
from typing import Protocol, TypeAlias

from safemeal.modules.identity.contracts import UserCreate


# 类说明（接口类）：UserRecord
# 作用：定义用户仓储记录接口的能力契约，供应用层与具体实现解耦。
class UserRecord(Protocol):
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
    display_name: str | None
    # 字段说明：status
    # 作用：HTTP 状态码或业务状态。
    # 类型：str。
    status: str
    # 字段说明：roles
    # 作用：用户拥有的角色集合。
    # 类型：tuple[str, ...] | list[str]。
    roles: tuple[str, ...] | list[str]
    # 字段说明：token_version
    # 作用：用户当前令牌版本。
    # 类型：int。
    token_version: int
    # 字段说明：created_at
    # 作用：记录创建时间，用于排序和审计。
    # 类型：datetime。
    created_at: datetime
    # 字段说明：updated_at
    # 作用：记录最后更新时间。
    # 类型：datetime | None。
    updated_at: datetime | None


# 类说明（接口类）：RefreshTokenRecord
# 作用：定义刷新令牌仓储记录接口的能力契约，供应用层与具体实现解耦。
class RefreshTokenRecord(Protocol):
    # 字段说明：id
    # 作用：该业务记录的唯一标识，SQL 模型中通常对应主键。
    # 类型：str。
    id: str
    # 字段说明：user_id
    # 作用：经身份绑定后的持久化用户标识。
    # 类型：str。
    user_id: str
    # 字段说明：token_hash
    # 作用：令牌的持久化哈希。
    # 类型：str。
    token_hash: str
    # 字段说明：expires_at
    # 作用：令牌或租约的到期时间。
    # 类型：datetime。
    expires_at: datetime
    # 字段说明：revoked_at
    # 作用：刷新令牌撤销时间。
    # 类型：datetime | None。
    revoked_at: datetime | None
    # 字段说明：replaced_by_hash
    # 作用：轮换后新刷新令牌的哈希。
    # 类型：str | None。
    replaced_by_hash: str | None


# 类说明（接口类）：AuthRepository
# 作用：定义身份数据仓储接口的能力契约，供应用层与具体实现解耦。
class AuthRepository(Protocol):
    # 方法说明：create_user
    # 作用：创建带租户、密码哈希和角色的用户记录。
    # 入参：
    #   data（UserCreate）：用户创建契约。
    # 出参：UserRecord；用户仓储记录接口。
    def create_user(self, data: UserCreate) -> UserRecord: ...
    # 方法说明：get_user
    # 作用：按标识读取用户信息。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：UserRecord | None；用户仓储记录接口或None（未取得结果）。
    def get_user(self, user_id: str) -> UserRecord | None: ...
    # 方法说明：get_user_by_email
    # 作用：按租户和规范化邮箱读取用户记录。
    # 入参：
    #   tenant_id（str）：可信租户标识，用于业务数据隔离。
    #   email（str）：用户邮箱。
    # 出参：UserRecord | None；用户仓储记录接口或None（未取得结果）。
    def get_user_by_email(self, tenant_id: str, email: str) -> UserRecord | None: ...
    # 方法说明：update_password_hash
    # 作用：保存升级后的密码哈希。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   password_hash（str）：已经持久化的密码哈希。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def update_password_hash(self, user_id: str, password_hash: str) -> None: ...
    # 方法说明：increment_token_version
    # 作用：增加用户令牌版本，使之前签发的访问令牌失效。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def increment_token_version(self, user_id: str) -> None: ...
    # 方法说明：create_refresh_token
    # 作用：保存刷新令牌哈希及其有效期和撤销状态。
    # 入参：
    #   token_id（str）：访问令牌或刷新令牌的唯一标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   token_hash（str）：令牌的持久化哈希。
    #   expires_at（datetime）：令牌或租约的到期时间。
    # 出参：RefreshTokenRecord；刷新令牌仓储记录接口。
    def create_refresh_token(
        self,
        *,
        token_id: str,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
    ) -> RefreshTokenRecord: ...
    # 方法说明：get_refresh_token
    # 作用：按令牌哈希读取刷新令牌记录。
    # 入参：
    #   token_hash（str）：令牌的持久化哈希。
    # 出参：RefreshTokenRecord | None；刷新令牌仓储记录接口或None（未取得结果）。
    def get_refresh_token(self, token_hash: str) -> RefreshTokenRecord | None: ...
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
    ) -> None: ...
    # 方法说明：revoke_refresh_token
    # 作用：按令牌哈希撤销单个刷新令牌。
    # 入参：
    #   token_id（str）：访问令牌或刷新令牌的唯一标识。
    #   revoked_at（datetime）：刷新令牌撤销时间。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def revoke_refresh_token(self, token_id: str, *, revoked_at: datetime) -> None: ...
    # 方法说明：revoke_all_refresh_tokens
    # 作用：撤销用户已有刷新令牌，停止后续刷新。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   revoked_at（datetime）：刷新令牌撤销时间。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def revoke_all_refresh_tokens(
        self, user_id: str, *, revoked_at: datetime
    ) -> None: ...


# 类说明（接口类）：AuthUnitOfWork
# 作用：定义身份业务事务工作单元接口的能力契约，供应用层与具体实现解耦。
class AuthUnitOfWork(Protocol):
    # 方法说明：auth
    # 作用：取得当前工作单元绑定的身份数据仓储。
    # 入参：
    #   无显式入参。
    # 出参：AuthRepository；当前事务内的身份仓储。
    @property
    def auth(self) -> AuthRepository: ...
    # 方法说明：commit
    # 作用：提交当前工作单元的数据库事务。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def commit(self) -> None: ...
    # 方法说明：rollback
    # 作用：回滚当前工作单元的数据库事务。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def rollback(self) -> None: ...
    # 方法说明：__enter__
    # 作用：进入工作单元并创建事务资源，供 with 块内的仓储操作共享。
    # 入参：
    #   无显式入参。
    # 出参：'AuthUnitOfWork'；身份业务事务工作单元接口。
    def __enter__(self) -> "AuthUnitOfWork": ...
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
    ) -> None: ...


AuthUnitOfWorkFactory: TypeAlias = Callable[[], AuthUnitOfWork]
