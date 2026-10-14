"""从已有浏览和当前点赞收藏事实计算绝对分数。"""

from datetime import datetime, timezone
from sqlalchemy import func, select, union
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from safemeal.infrastructure.persistence.database import get_engine
from safemeal.infrastructure.persistence.history_repository import history
from safemeal.infrastructure.persistence.reaction_repository import reactions
from safemeal.infrastructure.persistence.recipe_repository import recipes
from safemeal.modules.interaction.contracts.ranking import RankedRecipe, RankingMode
from safemeal.shared.exceptions import DatabaseOperationError, DatabaseUnavailableError


# 类说明（SQL 类）：SqlAlchemyRankingRepository
# 作用：实现行为事实榜单 SQL 聚合仓储的查询、写入或运行状态持久化。
class SqlAlchemyRankingRepository:
    # 方法说明：__init__
    # 作用：初始化行为事实榜单 SQL 聚合仓储，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   engine（Engine | None）：SQLAlchemy 数据库引擎；默认值为 None。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, engine: Engine | None = None) -> None:
        # 实例属性说明：_engine
        # 作用：SQLAlchemy 数据库引擎。
        self._engine = engine

    # 方法说明：tenants
    # 作用：按游标分页读取存在行为事实的租户。
    # 入参：
    #   after（str | None）：分页游标或查询下界。
    #   limit（int）：本次查询或处理的最大条目数。
    # 出参：tuple[str, ...]；按游标排序取得的租户标识元组。
    def tenants(self, after: str | None, limit: int) -> tuple[str, ...]:
        candidates = union(
            select(history.c.tenant_id), select(reactions.c.tenant_id)
        ).subquery()
        query = (
            select(candidates.c.tenant_id).order_by(candidates.c.tenant_id).limit(limit)
        )
        if after is not None:
            query = query.where(candidates.c.tenant_id > after)
        try:
            with (self._engine or get_engine()).connect() as connection:
                return tuple(connection.execute(query).scalars())
        except OperationalError as exc:
            raise DatabaseUnavailableError() from exc
        except SQLAlchemyError as exc:
            raise DatabaseOperationError() from exc

    # 方法说明：aggregate
    # 作用：按租户与榜单模式聚合行为事实，返回按分数排序的菜谱。
    # 入参：
    #   tenant_id（str）：可信租户标识，用于业务数据隔离。
    #   mode（RankingMode）：当前榜单或运行模式。
    #   start（datetime）：查询时间窗口的起始时刻。
    #   end（datetime）：时间查询窗口的结束时刻。
    #   limit（int）：本次查询或处理的最大条目数。
    # 出参：tuple[RankedRecipe, ...]；SQL 聚合得到的排名食谱组成的元组。
    def aggregate(
        self,
        tenant_id: str,
        mode: RankingMode,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> tuple[RankedRecipe, ...]:
        facts = history if mode == "today" else reactions
        score = func.count().label("score")
        # Aggregate narrow fact rows first: one catalog lookup per scored recipe,
        # rather than one lookup per reaction/view. Keep filtering inside the group.
        scores = select(facts.c.recipe_id, score).where(facts.c.tenant_id == tenant_id)
        if mode == "today":
            scores = scores.where(
                history.c.last_viewed_at
                >= start.astimezone(timezone.utc).replace(tzinfo=None),
                history.c.last_viewed_at
                < end.astimezone(timezone.utc).replace(tzinfo=None),
            )
        grouped = scores.group_by(facts.c.recipe_id).subquery()
        query = (
            select(recipes.c.id, recipes.c.name, grouped.c.score)
            .join(grouped, grouped.c.recipe_id == recipes.c.id)
            .order_by(grouped.c.score.desc(), recipes.c.id.desc())
            .limit(limit)
        )
        try:
            with (self._engine or get_engine()).connect() as connection:
                return tuple(
                    RankedRecipe(
                        recipe_id=row.id, recipe_name=row.name, score=row.score
                    )
                    for row in connection.execute(query)
                )
        except OperationalError as exc:
            raise DatabaseUnavailableError() from exc
        except SQLAlchemyError as exc:
            raise DatabaseOperationError() from exc
