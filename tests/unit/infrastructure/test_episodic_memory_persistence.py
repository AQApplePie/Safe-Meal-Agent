from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from safemeal.application.use_cases.memory.user_memory_service import UserMemoryService
from safemeal.infrastructure.persistence.database import Base
from safemeal.infrastructure.persistence.user_memory_repository import (
    SqlAlchemyUserMemoryUnitOfWork,
)


def test_episode_is_persisted_and_updated_by_session() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def uow() -> SqlAlchemyUserMemoryUnitOfWork:
        return SqlAlchemyUserMemoryUnitOfWork(session_factory=sessions)

    writer = UserMemoryService(uow)
    first = writer.remember_episode(
        user_id="u1", session_id="s1", summary="用户想做清淡晚餐", message_count=8
    )
    second = writer.remember_episode(
        user_id="u1",
        session_id="s1",
        summary="用户想做清淡且少盐的晚餐",
        message_count=12,
    )

    episodes = UserMemoryService(uow).load_episodic_memories(user_id="u1")

    assert first.id == second.id
    assert len(episodes) == 1
    assert episodes[0]["session_id"] == "s1"
    assert episodes[0]["summary"] == "用户想做清淡且少盐的晚餐"
    assert episodes[0]["message_count"] == 12
