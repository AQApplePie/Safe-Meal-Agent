from typing import Protocol
from safemeal.modules.knowledge.contracts.ingestion import IngestionJob


# 类说明（接口类）：IngestionQueue
# 作用：定义文档摄取队列接口的能力契约，供应用层与具体实现解耦。
class IngestionQueue(Protocol):
    # 方法说明：enqueue
    # 作用：将摄取任务写入队列，供后台工作者读取。
    # 入参：
    #   job（IngestionJob）：文档摄取任务。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    async def enqueue(self, job: IngestionJob) -> None: ...
    # 方法说明：dequeue
    # 作用：从摄取队列取得待处理文档任务。
    # 入参：
    #   timeout_seconds（int）：操作超时上限，单位秒；默认值为 5。
    # 出参：IngestionJob | None；异步文档摄取任务或None（未取得结果）。
    async def dequeue(self, timeout_seconds: int = 5) -> IngestionJob | None: ...
    # 方法说明：update
    # 作用：通过文档摄取队列接口更新指定业务对象的可修改字段。
    # 入参：
    #   job（IngestionJob）：文档摄取任务。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    async def update(self, job: IngestionJob) -> None: ...
    # 方法说明：get
    # 作用：通过文档摄取队列接口读取指定标识对应的业务对象。
    # 入参：
    #   job_id（str）：文档摄取任务标识。
    # 出参：IngestionJob | None；异步文档摄取任务或None（未取得结果）。
    async def get(self, job_id: str) -> IngestionJob | None: ...
