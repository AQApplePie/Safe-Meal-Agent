"""实现持久化基础设施适配。"""

from __future__ import annotations
import asyncio
from inspect import signature
from langgraph.checkpoint.base import BaseCheckpointSaver


# 类说明（业务或基础设施实现类）：ThreadedCheckpointSaver
# 作用：实现同步检查点存储的异步线程包装器，封装该组件的业务处理与依赖协作。
class ThreadedCheckpointSaver(BaseCheckpointSaver):
    # 方法说明：__init__
    # 作用：初始化同步检查点存储的异步线程包装器，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   delegate（BaseCheckpointSaver）：被当前适配器包装的底层组件。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, delegate: BaseCheckpointSaver):
        super().__init__(serde=delegate.serde)
        # 实例属性说明：delegate
        # 作用：被当前适配器包装的底层组件。
        self.delegate = delegate
        # 实例属性说明：_supports_task_path
        # 作用：依赖是否支持按任务路径执行的能力标记。
        self._supports_task_path = (
            "task_path" in signature(delegate.put_writes).parameters
        )

    # 方法说明：config_specs
    # 作用：声明检查点适配器需要的配置字段规范。
    # 入参：
    #   无显式入参。
    # 出参：按实现返回；底层检查点适配器声明的配置字段规范。
    @property
    def config_specs(self):
        return self.delegate.config_specs

    # 方法说明：get_tuple
    # 作用：读取检查点、元数据与待处理写入，用于恢复图执行。
    # 入参：
    #   config（由调用契约决定）：图调用或检查点配置。
    # 出参：CheckpointTuple 或 None；读取到的检查点、元数据和待处理写入。
    def get_tuple(self, config):
        return self.delegate.get_tuple(config)

    # 方法说明：list
    # 作用：通过同步检查点存储的异步线程包装器按过滤和分页条件列出记录。
    # 入参：
    #   config（由调用契约决定）：图调用或检查点配置。
    #   filter（由调用契约决定）：当前检索使用的过滤条件或表达式；默认值为 None。
    #   before（由调用契约决定）：查询的上界或检查点游标；默认值为 None。
    #   limit（由调用契约决定）：本次查询或处理的最大条目数；默认值为 None。
    # 出参：Iterator[CheckpointTuple]；按过滤条件读取的检查点迭代器。
    def list(self, config, *, filter=None, before=None, limit=None):
        return self.delegate.list(config, filter=filter, before=before, limit=limit)

    # 方法说明：put
    # 作用：保存检查点及通道版本，返回新的检查点配置。
    # 入参：
    #   config（由调用契约决定）：图调用或检查点配置。
    #   checkpoint（由调用契约决定）：待保存的图检查点状态。
    #   metadata（由调用契约决定）：文档、消息或证据的来源与辅助元数据。
    #   new_versions（由调用契约决定）：本次检查点保存后的通道版本映射。
    # 出参：RunnableConfig；本次保存后对应的检查点配置。
    def put(self, config, checkpoint, metadata, new_versions):
        return self.delegate.put(config, checkpoint, metadata, new_versions)

    # 方法说明：put_writes
    # 作用：保存图任务的待处理通道写入，供恢复执行使用。
    # 入参：
    #   config（由调用契约决定）：图调用或检查点配置。
    #   writes（由调用契约决定）：待保存的检查点通道写入集合。
    #   task_id（由调用契约决定）：图执行任务标识。
    #   task_path（由调用契约决定）：本次读取或写入的路径；默认值为 ''。
    # 出参：None；无返回值，通道写入保存到底层检查点存储。
    def put_writes(self, config, writes, task_id, task_path=""):
        if self._supports_task_path:
            writer = getattr(self.delegate, "put_writes")
            return writer(config, writes, task_id, task_path=task_path)
        return self.delegate.put_writes(config, writes, task_id)

    # 方法说明：get_next_version
    # 作用：为检查点通道计算下一版本标识。
    # 入参：
    #   current（由调用契约决定）：当前待处理状态或条目。
    #   channel（由调用契约决定）：检查点通道名称。
    # 出参：按实现返回；当前通道的下一检查点版本标识。
    def get_next_version(self, current, channel):
        return self.delegate.get_next_version(current, channel)

    # 方法说明：aget_tuple
    # 作用：读取检查点、元数据与待处理写入，用于恢复图执行。
    # 入参：
    #   config（由调用契约决定）：图调用或检查点配置。
    # 出参：CheckpointTuple 或 None；异步取得的检查点、元数据和待处理写入。
    async def aget_tuple(self, config):
        return await asyncio.to_thread(self.get_tuple, config)

    # 方法说明：alist
    # 作用：通过同步检查点存储的异步线程包装器异步迭代查询记录。
    # 入参：
    #   config（由调用契约决定）：图调用或检查点配置。
    #   filter（由调用契约决定）：当前检索使用的过滤条件或表达式；默认值为 None。
    #   before（由调用契约决定）：查询的上界或检查点游标；默认值为 None。
    #   limit（由调用契约决定）：本次查询或处理的最大条目数；默认值为 None。
    # 出参：AsyncIterator[CheckpointTuple]；按过滤条件读取的检查点异步迭代器。
    async def alist(self, config, *, filter=None, before=None, limit=None):
        rows = await asyncio.to_thread(
            lambda: list(self.list(config, filter=filter, before=before, limit=limit))
        )
        for row in rows:
            yield row

    # 方法说明：aput
    # 作用：保存检查点及通道版本，返回新的检查点配置。
    # 入参：
    #   config（由调用契约决定）：图调用或检查点配置。
    #   checkpoint（由调用契约决定）：待保存的图检查点状态。
    #   metadata（由调用契约决定）：文档、消息或证据的来源与辅助元数据。
    #   new_versions（由调用契约决定）：本次检查点保存后的通道版本映射。
    # 出参：RunnableConfig；异步保存后对应的检查点配置。
    async def aput(self, config, checkpoint, metadata, new_versions):
        return await asyncio.to_thread(
            self.put, config, checkpoint, metadata, new_versions
        )

    # 方法说明：aput_writes
    # 作用：保存图任务的待处理通道写入，供恢复执行使用。
    # 入参：
    #   config（由调用契约决定）：图调用或检查点配置。
    #   writes（由调用契约决定）：待保存的检查点通道写入集合。
    #   task_id（由调用契约决定）：图执行任务标识。
    #   task_path（由调用契约决定）：本次读取或写入的路径；默认值为 ''。
    # 出参：None；无返回值，结果通过状态更新或外部操作体现。
    async def aput_writes(self, config, writes, task_id, task_path=""):
        await asyncio.to_thread(self.put_writes, config, writes, task_id, task_path)
