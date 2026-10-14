"""数据库唯一键保证幂等；在事务内从事实行计算状态与计数。"""

from safemeal.modules.interaction.contracts.behavior import FavoriteEntry
from sqlalchemy.sql.dml import Insert

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    and_,
    case,
    func,
    select,
)
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from safemeal.infrastructure.persistence.behavior_outbox import SqlBehaviorOutbox
from safemeal.infrastructure.persistence.database import Base, get_engine
from safemeal.infrastructure.persistence.transaction_retry import run_transaction
from safemeal.infrastructure.persistence.recipe_repository import recipes
from safemeal.modules.interaction.contracts.models import (
    InteractionActor,
    ReactionKind,
    RecipeInteraction,
)
from safemeal.shared.exceptions import (
    DatabaseOperationError,
    DatabaseUnavailableError,
    FeatureUnavailableError,
    ResourceNotFoundError,
)

# Direct column reference resolves the canonical catalog across its existing metadata.
reactions = Table(
    "recipe_reactions",
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
    Column("kind", String(10), primary_key=True),
    Column("created_at", DateTime(), nullable=False, server_default=func.now()),
    CheckConstraint("kind IN ('like', 'favorite')", name="ck_recipe_reactions_kind"),
    Index("ix_recipe_reactions_counts", "tenant_id", "recipe_id", "kind"),
    Index("ix_recipe_reactions_recipe", "recipe_id"),
    Index(
        "ix_recipe_reactions_favorites",
        "tenant_id",
        "subject",
        "kind",
        "created_at",
        "recipe_id",
    ),
)


# 类说明（SQL 类）：SqlAlchemyReactionRepository
# 作用：实现点赞收藏 SQL 仓储的查询、写入或运行状态持久化。
class SqlAlchemyReactionRepository:
    # 方法说明：__init__
    # 作用：初始化点赞收藏 SQL 仓储，保存注入依赖并建立初始配置或运行状态。
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

    # 方法说明：_snapshot
    # 作用：组装点赞收藏 SQL 仓储的内部状态快照。
    # 入参：
    #   connection（Connection）：当前 SQL 事务使用的连接。
    #   recipe_id（int）：目标食谱的整数标识。
    #   actor（InteractionActor）：包含租户与用户标识的行为操作主体。
    # 出参：RecipeInteraction；用户食谱交互状态与计数。
    def _snapshot(
        self, connection: Connection, recipe_id: int, actor: InteractionActor
    ) -> RecipeInteraction:
        row = connection.execute(
            select(
                func.count(case((reactions.c.kind == "like", 1))).label("like_count"),
                func.count(case((reactions.c.kind == "favorite", 1))).label(
                    "favorite_count"
                ),
                func.count(
                    case(
                        (
                            and_(
                                reactions.c.kind == "like",
                                reactions.c.subject == actor.subject,
                            ),
                            1,
                        )
                    )
                ).label("liked"),
                func.count(
                    case(
                        (
                            and_(
                                reactions.c.kind == "favorite",
                                reactions.c.subject == actor.subject,
                            ),
                            1,
                        )
                    )
                ).label("favorited"),
            ).where(
                reactions.c.tenant_id == actor.tenant_id,
                reactions.c.recipe_id == recipe_id,
            )
        ).one()
        return RecipeInteraction(
            recipe_id=recipe_id,
            liked=bool(row.liked),
            favorited=bool(row.favorited),
            like_count=row.like_count,
            favorite_count=row.favorite_count,
        )

    # 方法说明：_execute
    # 作用：在可重试事务中读取或设置点赞收藏状态并保存 outbox。
    # 入参：
    #   recipe_id（int）：目标食谱的整数标识。
    #   actor（InteractionActor）：包含租户与用户标识的行为操作主体。
    #   kind（ReactionKind | None）：当前业务记录或操作的类型。
    #   enabled（bool）：目标行为或功能是否启用。
    # 出参：RecipeInteraction；用户食谱交互状态与计数。
    def _execute(
        self,
        recipe_id: int,
        actor: InteractionActor,
        kind: ReactionKind | None,
        enabled: bool,
    ) -> RecipeInteraction:
        engine = self._engine or get_engine()

        # 方法说明：operation
        # 作用：执行当前外层用例委托的数据库事务操作。
        # 入参：
        #   connection（Connection）：当前 SQL 事务使用的连接。
        # 出参：RecipeInteraction；用户食谱交互状态与计数。
        def operation(connection: Connection) -> RecipeInteraction:
            # Serialize mutations per recipe with a DB row lock, including missing
            # reaction rows. MySQL locking reads do not open a stale RR snapshot.
            query = select(recipes.c.id).where(recipes.c.id == recipe_id)
            if kind is not None:
                query = query.with_for_update()
            if connection.execute(query).scalar_one_or_none() is None:
                raise ResourceNotFoundError("Recipe not found")
            if kind is not None:
                values = dict(
                    tenant_id=actor.tenant_id,
                    subject=actor.subject,
                    recipe_id=recipe_id,
                    kind=kind,
                )
                if enabled:
                    statement: Insert
                    if connection.dialect.name == "mysql":
                        statement = mysql_insert(reactions).values(**values)
                        statement = statement.on_duplicate_key_update(
                            created_at=reactions.c.created_at
                        )
                    elif connection.dialect.name == "sqlite":
                        statement = (
                            sqlite_insert(reactions)
                            .values(**values)
                            .on_conflict_do_nothing(
                                index_elements=[
                                    "tenant_id",
                                    "subject",
                                    "recipe_id",
                                    "kind",
                                ]
                            )
                        )
                    else:
                        raise FeatureUnavailableError(
                            "Reaction storage supports MySQL and SQLite"
                        )
                    connection.execute(statement)
                else:
                    connection.execute(
                        reactions.delete().where(
                            *(
                                reactions.c[key] == value
                                for key, value in values.items()
                            )
                        )
                    )
            if kind is not None and self._outbox is not None:
                self._outbox.append(connection, actor, recipe_id, kind, enabled)
            return self._snapshot(connection, recipe_id, actor)

        try:
            return run_transaction(
                engine, operation, max_attempts=self._transaction_attempts
            )
        except OperationalError as exc:
            raise DatabaseUnavailableError() from exc
        except SQLAlchemyError as exc:
            raise DatabaseOperationError() from exc

    # 方法说明：read
    # 作用：通过点赞收藏 SQL 仓储读取目标记录或当前状态。
    # 入参：
    #   recipe_id（int）：目标食谱的整数标识。
    #   actor（InteractionActor）：包含租户与用户标识的行为操作主体。
    # 出参：RecipeInteraction；用户食谱交互状态与计数。
    def read(self, recipe_id: int, actor: InteractionActor) -> RecipeInteraction:
        return self._execute(recipe_id, actor, None, False)

    # 方法说明：set_state
    # 作用：在同一事务中设置目标点赞或收藏状态，并追加行为事件。
    # 入参：
    #   recipe_id（int）：目标食谱的整数标识。
    #   actor（InteractionActor）：包含租户与用户标识的行为操作主体。
    #   kind（ReactionKind）：当前业务记录或操作的类型。
    #   enabled（bool）：目标行为或功能是否启用。
    # 出参：RecipeInteraction；用户食谱交互状态与计数。
    def set_state(
        self, recipe_id: int, actor: InteractionActor, kind: ReactionKind, enabled: bool
    ) -> RecipeInteraction:
        return self._execute(recipe_id, actor, kind, enabled)

    # 方法说明：read_many
    # 作用：批量读取食谱交互状态，避免逐条查询。
    # 入参：
    #   recipe_ids（tuple[int, ...]）：待查询或校验的食谱标识集合。
    #   actor（InteractionActor）：包含租户与用户标识的行为操作主体。
    # 出参：tuple[RecipeInteraction, ...]；用户食谱交互状态与计数组成的元组。
    def read_many(
        self, recipe_ids: tuple[int, ...], actor: InteractionActor
    ) -> tuple[RecipeInteraction, ...]:
        if not recipe_ids:
            return ()
        like = reactions.c.kind == "like"
        favorite = reactions.c.kind == "favorite"
        own = reactions.c.subject == actor.subject
        counts = (
            select(
                reactions.c.recipe_id,
                func.count(case((like, 1))).label("like_count"),
                func.count(case((favorite, 1))).label("favorite_count"),
                func.count(case((and_(like, own), 1))).label("liked"),
                func.count(case((and_(favorite, own), 1))).label("favorited"),
            )
            .where(
                reactions.c.tenant_id == actor.tenant_id,
                reactions.c.recipe_id.in_(recipe_ids),
            )
            .group_by(reactions.c.recipe_id)
            .subquery()
        )
        query = (
            select(
                recipes.c.id,
                *(
                    func.coalesce(counts.c[field], 0).label(field)
                    for field in ("liked", "favorited", "like_count", "favorite_count")
                ),
            )
            .outerjoin(counts, counts.c.recipe_id == recipes.c.id)
            .where(recipes.c.id.in_(recipe_ids))
        )
        try:
            with (self._engine or get_engine()).connect() as connection:
                return tuple(
                    RecipeInteraction(
                        recipe_id=row.id,
                        liked=bool(row.liked),
                        favorited=bool(row.favorited),
                        like_count=row.like_count,
                        favorite_count=row.favorite_count,
                    )
                    for row in connection.execute(query)
                )
        except OperationalError as exc:
            raise DatabaseUnavailableError() from exc
        except SQLAlchemyError as exc:
            raise DatabaseOperationError() from exc

    # 方法说明：list_favorites
    # 作用：分页读取当前用户收藏的食谱。
    # 入参：
    #   actor（InteractionActor）：包含租户与用户标识的行为操作主体。
    #   offset（int）：本次分页跳过的记录数量。
    #   limit（int）：本次查询或处理的最大条目数。
    # 出参：tuple[FavoriteEntry, ...]；收藏食谱条目组成的元组。
    def list_favorites(
        self, actor: InteractionActor, offset: int, limit: int
    ) -> tuple[FavoriteEntry, ...]:
        query = (
            select(reactions.c.recipe_id, recipes.c.name, reactions.c.created_at)
            .join(recipes, recipes.c.id == reactions.c.recipe_id)
            .where(
                reactions.c.tenant_id == actor.tenant_id,
                reactions.c.subject == actor.subject,
                reactions.c.kind == "favorite",
            )
            .order_by(reactions.c.created_at.desc(), reactions.c.recipe_id.desc())
            .offset(offset)
            .limit(limit)
        )
        try:
            with (self._engine or get_engine()).connect() as connection:
                return tuple(
                    FavoriteEntry(
                        recipe_id=row.recipe_id,
                        recipe_name=row.name,
                        favorited_at=row.created_at,
                    )
                    for row in connection.execute(query)
                )
        except OperationalError as exc:
            raise DatabaseUnavailableError() from exc
        except SQLAlchemyError as exc:
            raise DatabaseOperationError() from exc
