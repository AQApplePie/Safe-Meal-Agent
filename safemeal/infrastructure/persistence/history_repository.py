"""高频浏览只更新唯一事实行；使用索引游标读取最近记录。"""

from datetime import timezone
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    literal,
    String,
    Table,
    and_,
    case,
    func,
    or_,
    select,
)
from sqlalchemy.dialects.mysql import DATETIME, insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.sql.dml import Insert
from safemeal.infrastructure.persistence.behavior_outbox import SqlBehaviorOutbox
from safemeal.infrastructure.persistence.database import Base, get_engine
from safemeal.infrastructure.persistence.transaction_retry import run_transaction
from safemeal.infrastructure.persistence.recipe_repository import recipes
from safemeal.modules.interaction.contracts.history import HistoryEntry, HistoryPosition
from safemeal.modules.interaction.contracts.models import InteractionActor
from safemeal.shared.exceptions import (
    DatabaseOperationError,
    DatabaseUnavailableError,
    FeatureUnavailableError,
    ResourceNotFoundError,
)

history = Table(
    "recipe_view_history",
    Base.metadata,
    Column(
        "tenant_id",
        String(100, collation="utf8mb4_0900_bin").with_variant(String(100), "sqlite"),
        primary_key=True,
    ),
    Column(
        "subject",
        String(255, collation="utf8mb4_0900_bin").with_variant(String(255), "sqlite"),
        primary_key=True,
    ),
    Column(
        "recipe_id",
        Integer,
        ForeignKey(recipes.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "last_viewed_at",
        DateTime().with_variant(DATETIME(fsp=6), "mysql"),
        nullable=False,
    ),
    Index(
        "ix_recipe_history_recent",
        "tenant_id",
        "subject",
        "last_viewed_at",
        "recipe_id",
    ),
    Index("ix_recipe_history_recipe", "recipe_id"),
    Index("ix_recipe_history_ranking_day", "tenant_id", "last_viewed_at", "recipe_id"),
)


# 类说明（SQL 类）：SqlAlchemyHistoryRepository
# 作用：实现浏览历史 SQL 仓储的查询、写入或运行状态持久化。
class SqlAlchemyHistoryRepository:
    # 方法说明：__init__
    # 作用：初始化浏览历史 SQL 仓储，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   engine（Engine | None）：SQLAlchemy 数据库引擎；默认值为 None。
    #   outbox（SqlBehaviorOutbox | None）：同事务行为事件持久化组件；默认值为 None。
    #   transaction_attempts（int）：完整数据库事务最多尝试次数；默认值为 3。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(
        self,
        engine: Engine | None = None,
        *,
        outbox: SqlBehaviorOutbox | None = None,
        transaction_attempts: int = 3,
    ) -> None:
        # 实例属性说明：_engine
        # 作用：SQLAlchemy 数据库引擎。
        self._engine = engine
        # 实例属性说明：_outbox
        # 作用：同事务行为事件持久化组件。
        self._outbox = outbox
        if not 1 <= transaction_attempts <= 5:
            raise ValueError("Transaction attempts must be between 1 and 5")
        # 实例属性说明：_transaction_attempts
        # 作用：完整数据库事务最多尝试次数。
        self._transaction_attempts = transaction_attempts

    # 方法说明：record
    # 作用：向浏览历史 SQL 仓储记录本次操作的结果和状态。
    # 入参：
    #   recipe_id（int）：目标食谱的整数标识。
    #   actor（InteractionActor）：包含租户与用户标识的行为操作主体。
    # 出参：HistoryEntry；浏览历史条目。
    def record(self, recipe_id: int, actor: InteractionActor) -> HistoryEntry:
        engine = self._engine or get_engine()

        # 方法说明：operation
        # 作用：执行当前外层用例委托的数据库事务操作。
        # 入参：
        #   connection（Connection）：当前 SQL 事务使用的连接。
        # 出参：HistoryEntry；浏览历史条目。
        def operation(connection: Connection) -> HistoryEntry:
            name = connection.execute(
                select(recipes.c.name).where(recipes.c.id == recipe_id)
            ).scalar_one_or_none()
            if name is None:
                raise ResourceNotFoundError("Recipe not found")
            scope = and_(
                history.c.tenant_id == actor.tenant_id,
                history.c.subject == actor.subject,
                history.c.recipe_id == recipe_id,
            )
            statement: Insert
            if connection.dialect.name == "mysql":
                insert = mysql_insert(history).values(
                    tenant_id=actor.tenant_id,
                    subject=actor.subject,
                    recipe_id=recipe_id,
                    last_viewed_at=func.utc_timestamp(6),
                )
                statement = insert.on_duplicate_key_update(
                    last_viewed_at=func.greatest(
                        history.c.last_viewed_at, insert.inserted.last_viewed_at
                    )
                )
            elif connection.dialect.name == "sqlite":
                insert_sqlite = sqlite_insert(history).values(
                    tenant_id=actor.tenant_id,
                    subject=actor.subject,
                    recipe_id=recipe_id,
                    # SQLite strftime emits milliseconds. Normalize to the six
                    # digits used by DateTime binds so keyset equality is exact.
                    last_viewed_at=(
                        func.strftime("%Y-%m-%d %H:%M:%f", "now", type_=String)
                        + literal("000")
                    ),
                )
                statement = insert_sqlite.on_conflict_do_update(
                    index_elements=["tenant_id", "subject", "recipe_id"],
                    set_={
                        "last_viewed_at": case(
                            (
                                insert_sqlite.excluded.last_viewed_at
                                > history.c.last_viewed_at,
                                insert_sqlite.excluded.last_viewed_at,
                            ),
                            else_=history.c.last_viewed_at,
                        )
                    },
                )
            else:
                raise FeatureUnavailableError(
                    "History storage supports MySQL and SQLite"
                )
            connection.execute(statement)
            timestamp_query = select(history.c.last_viewed_at).where(scope)
            if connection.dialect.name == "mysql":
                # The recipe SELECT may have opened an old RR snapshot. A
                # duplicate-key no-op does not make the new row visible to a
                # consistent read; use a current read while holding its lock.
                timestamp_query = timestamp_query.with_for_update()
            timestamp = connection.execute(timestamp_query).scalar_one()
            if self._outbox is not None:
                self._outbox.append(connection, actor, recipe_id, "view")
            return HistoryEntry(
                recipe_id=recipe_id,
                recipe_name=name,
                last_viewed_at=timestamp.replace(tzinfo=timezone.utc),
            )

        try:
            return run_transaction(
                engine, operation, max_attempts=self._transaction_attempts
            )
        except OperationalError as exc:
            raise DatabaseUnavailableError() from exc
        except SQLAlchemyError as exc:
            raise DatabaseOperationError() from exc

    # 方法说明：list_recent
    # 作用：读取当前用户最近浏览的食谱及时间。
    # 入参：
    #   actor（InteractionActor）：包含租户与用户标识的行为操作主体。
    #   limit（int）：本次查询或处理的最大条目数。
    #   before（HistoryPosition | None）：查询的上界或检查点游标。
    # 出参：tuple[HistoryEntry, ...]；浏览历史条目组成的元组。
    def list_recent(
        self, actor: InteractionActor, limit: int, before: HistoryPosition | None
    ) -> tuple[HistoryEntry, ...]:
        engine = self._engine or get_engine()
        query = (
            select(history.c.recipe_id, recipes.c.name, history.c.last_viewed_at)
            .join(recipes, recipes.c.id == history.c.recipe_id)
            .where(
                history.c.tenant_id == actor.tenant_id,
                history.c.subject == actor.subject,
            )
        )
        if before is not None:
            timestamp = before.last_viewed_at.astimezone(timezone.utc).replace(
                tzinfo=None
            )
            query = query.where(
                or_(
                    history.c.last_viewed_at < timestamp,
                    and_(
                        history.c.last_viewed_at == timestamp,
                        history.c.recipe_id < before.recipe_id,
                    ),
                )
            )
        query = query.order_by(
            history.c.last_viewed_at.desc(), history.c.recipe_id.desc()
        ).limit(limit)
        try:
            with engine.connect() as connection:
                return tuple(
                    HistoryEntry(
                        recipe_id=row.recipe_id,
                        recipe_name=row.name,
                        last_viewed_at=row.last_viewed_at.replace(tzinfo=timezone.utc),
                    )
                    for row in connection.execute(query)
                )
        except OperationalError as exc:
            raise DatabaseUnavailableError() from exc
        except SQLAlchemyError as exc:
            raise DatabaseOperationError() from exc
