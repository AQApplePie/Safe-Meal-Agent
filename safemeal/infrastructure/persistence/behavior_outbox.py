"""Transactional notifications; SQL owns retry, leases and durable deduplication."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import (
    case,
    func,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Table,
    Text,
    or_,
    select,
)
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.dialects.mysql import DATETIME

from safemeal.infrastructure.persistence.database import Base, get_engine
from safemeal.modules.interaction.contracts.models import InteractionActor

outbox = Table(
    "behavior_outbox",
    Base.metadata,
    Column("event_id", String(36), primary_key=True),
    Column("tenant_id", String(100), nullable=False),
    Column("subject", String(255), nullable=False),
    Column("recipe_id", Integer, nullable=False),
    Column("kind", String(10), nullable=False),
    Column("enabled", Integer, nullable=True),
    Column(
        "created_at", DateTime().with_variant(DATETIME(fsp=6), "mysql"), nullable=False
    ),
    Column(
        "available_at",
        DateTime().with_variant(DATETIME(fsp=6), "mysql"),
        nullable=False,
    ),
    Column(
        "retry_at", DateTime().with_variant(DATETIME(fsp=6), "mysql"), nullable=False
    ),
    Column("lease_token", String(36)),
    Column("lease_until", DateTime().with_variant(DATETIME(fsp=6), "mysql")),
    Column("attempts", Integer, nullable=False, default=0),
    Column("completed_at", DateTime().with_variant(DATETIME(fsp=6), "mysql")),
    Column("dead_at", DateTime().with_variant(DATETIME(fsp=6), "mysql")),
    Column("last_error", Text),
    Index("ix_behavior_outbox_delivery", "completed_at", "dead_at", "available_at"),
)


# 方法说明：utcnow
# 作用：取得带 UTC 时区的当前时间。
# 入参：
#   无显式入参。
# 出参：datetime；日期时间。
def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# 类说明（SQL 类）：SqlBehaviorOutbox
# 作用：实现事务行为事件 SQL 存储的查询、写入或运行状态持久化。
class SqlBehaviorOutbox:
    # 方法说明：__init__
    # 作用：初始化事务行为事件 SQL 存储，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   engine（Engine | None）：SQLAlchemy 数据库引擎；默认值为 None。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, engine: Engine | None = None) -> None:
        # 实例属性说明：_engine
        # 作用：SQLAlchemy 数据库引擎。
        self._engine = engine

    # 方法说明：engine
    # 作用：取得当前容器管理的 SQLAlchemy 引擎。
    # 入参：
    #   无显式入参。
    # 出参：Engine；SQLAlchemy 引擎。
    @property
    def engine(self) -> Engine:
        return self._engine or get_engine()

    # 方法说明：metrics_snapshot
    # 作用：通过聚合 SQL 查询读取 outbox 状态计数与等待时间指标。
    # 入参：
    #   无显式入参。
    # 出参：dict[str, float]；outbox 状态数量及等待时间等聚合指标。
    def metrics_snapshot(self) -> dict[str, float]:
        """One aggregate query, no tenant/subject/event identifiers in telemetry."""
        now = utcnow()
        pending = outbox.c.completed_at.is_(None) & outbox.c.dead_at.is_(None)
        with self.engine.connect() as connection:
            row = connection.execute(
                select(
                    func.sum(case((pending, 1), else_=0)).label("pending"),
                    func.sum(case((outbox.c.dead_at.is_not(None), 1), else_=0)).label(
                        "dead"
                    ),
                    func.sum(
                        case((outbox.c.completed_at.is_not(None), 1), else_=0)
                    ).label("completed"),
                    func.sum(
                        case((pending & (outbox.c.lease_until > now), 1), else_=0)
                    ).label("leased"),
                    func.min(case((pending, outbox.c.created_at))).label("oldest"),
                    func.sum(outbox.c.attempts).label("failed_attempts"),
                )
            ).one()
        return {
            "pending": float(row.pending or 0),
            "dead": float(row.dead or 0),
            "completed": float(row.completed or 0),
            "leased": float(row.leased or 0),
            "failed_attempts": float(row.failed_attempts or 0),
            "oldest_pending_age_seconds": max(0.0, (now - row.oldest).total_seconds())
            if row.oldest
            else 0.0,
        }

    # 方法说明：append
    # 作用：在当前数据库事务中追加行为 outbox 事件。
    # 入参：
    #   connection（Connection）：当前 SQL 事务使用的连接。
    #   actor（InteractionActor）：包含租户与用户标识的行为操作主体。
    #   recipe_id（int）：目标食谱的整数标识。
    #   kind（str）：当前业务记录或操作的类型。
    #   enabled（bool | None）：目标行为或功能是否启用；默认值为 None。
    # 出参：str；新建 outbox 事件的唯一标识。
    def append(
        self,
        connection: Connection,
        actor: InteractionActor,
        recipe_id: int,
        kind: str,
        enabled: bool | None = None,
    ) -> str:
        event_id = str(uuid4())
        now = utcnow()
        connection.execute(
            outbox.insert().values(
                event_id=event_id,
                tenant_id=actor.tenant_id,
                subject=actor.subject,
                recipe_id=recipe_id,
                kind=kind,
                enabled=None if enabled is None else int(enabled),
                created_at=now,
                available_at=now,
                retry_at=now,
                attempts=0,
            )
        )
        return event_id

    # 方法说明：due
    # 作用：分页查询已经到达重试或投递时间的待处理 outbox 事件。
    # 入参：
    #   limit（int）：本次查询或处理的最大条目数。
    # 出参：tuple[str, ...]；当前已到投递时间的事件标识元组。
    def due(self, limit: int) -> tuple[str, ...]:
        with self.engine.connect() as connection:
            return tuple(
                connection.execute(
                    select(outbox.c.event_id)
                    .where(
                        outbox.c.completed_at.is_(None),
                        outbox.c.dead_at.is_(None),
                        outbox.c.available_at <= utcnow(),
                        or_(
                            outbox.c.lease_until.is_(None),
                            outbox.c.lease_until <= utcnow(),
                        ),
                    )
                    .order_by(outbox.c.available_at, outbox.c.event_id)
                    .limit(limit)
                ).scalars()
            )

    # 方法说明：published
    # 作用：记录 outbox 已投递时间，安排未完成事件的再次通知。
    # 入参：
    #   event_id（str）：行为 outbox 事件的唯一标识。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def published(self, event_id: str) -> None:
        # Redis loss/crash before consumption is repaired by republishing SQL rows.
        with self.engine.begin() as connection:
            connection.execute(
                outbox.update()
                .where(
                    outbox.c.event_id == event_id,
                    outbox.c.completed_at.is_(None),
                    outbox.c.dead_at.is_(None),
                    outbox.c.available_at <= utcnow(),
                )
                .values(available_at=utcnow() + timedelta(seconds=30))
            )

    # 方法说明：claim
    # 作用：按事件状态和租约条件认领 outbox，生成本次处理令牌。
    # 入参：
    #   event_id（str）：行为 outbox 事件的唯一标识。
    # 出参：tuple[str, str] | None；租约令牌与租户标识组成的二元组；竞争失败或不可处理时为 None。
    def claim(self, event_id: str) -> tuple[str, str] | None:
        now, token = utcnow(), str(uuid4())
        with self.engine.begin() as connection:
            result = connection.execute(
                outbox.update()
                .where(
                    outbox.c.event_id == event_id,
                    outbox.c.completed_at.is_(None),
                    outbox.c.dead_at.is_(None),
                    outbox.c.retry_at <= now,
                    or_(outbox.c.lease_until.is_(None), outbox.c.lease_until <= now),
                )
                .values(lease_token=token, lease_until=now + timedelta(seconds=180))
            )
            if result.rowcount != 1:
                return None
            tenant = connection.execute(
                select(outbox.c.tenant_id).where(outbox.c.event_id == event_id)
            ).scalar_one()
            return token, tenant

    # 方法说明：finish
    # 作用：仅在租约令牌仍有效时完成事件，记录成功或退避失败状态。
    # 入参：
    #   event_id（str）：行为 outbox 事件的唯一标识。
    #   token（str）：令牌或本次租约的处理凭证。
    #   error（str | None）：当前操作的错误信息。
    #   max_attempts（int）：完整数据库事务最多尝试次数。
    # 出参：bool；本次令牌是否成功完成事件状态更新。
    def finish(
        self, event_id: str, token: str, error: str | None, max_attempts: int
    ) -> bool:
        now = utcnow()
        with self.engine.begin() as connection:
            row = connection.execute(
                select(outbox.c.attempts).where(
                    outbox.c.event_id == event_id,
                    outbox.c.lease_token == token,
                    outbox.c.lease_until > now,
                )
            ).first()
            if row is None:
                return False
            attempts = row.attempts + (error is not None)
            result = connection.execute(
                outbox.update()
                .where(
                    outbox.c.event_id == event_id,
                    outbox.c.lease_token == token,
                    outbox.c.lease_until > now,
                )
                .values(
                    lease_token=None,
                    lease_until=None,
                    attempts=attempts,
                    completed_at=now if error is None else None,
                    dead_at=now
                    if error is not None and attempts >= max_attempts
                    else None,
                    available_at=now
                    + timedelta(seconds=min(300, 2 ** min(attempts, 9))),
                    retry_at=now + timedelta(seconds=min(300, 2 ** min(attempts, 9))),
                    last_error=error,
                )
            )

            return result.rowcount == 1

    # 方法说明：requeue
    # 作用：将指定死信恢复为可重试事件，禁止重放已完成事件。
    # 入参：
    #   event_id（str）：行为 outbox 事件的唯一标识。
    # 出参：bool；指定死信是否成功恢复为待处理事件。
    def requeue(self, event_id: str) -> bool:
        """Explicit operator recovery; completed events cannot be replayed."""
        with self.engine.begin() as connection:
            result = connection.execute(
                outbox.update()
                .where(
                    outbox.c.event_id == event_id,
                    outbox.c.dead_at.is_not(None),
                    outbox.c.completed_at.is_(None),
                )
                .values(
                    dead_at=None,
                    attempts=0,
                    last_error=None,
                    available_at=utcnow(),
                    retry_at=utcnow(),
                    lease_token=None,
                    lease_until=None,
                )
            )
            return result.rowcount == 1
