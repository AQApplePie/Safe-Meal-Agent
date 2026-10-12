from safemeal.modules.knowledge.contracts.ingestion import IngestionJob


# 类说明（业务或基础设施实现类）：RedisIngestionQueue
# 作用：实现Redis 文档摄取队列实现，封装该组件的业务处理与依赖协作。
class RedisIngestionQueue:
    # 方法说明：__init__
    # 作用：初始化Redis 文档摄取队列实现，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   redis_url（str）：Redis 连接地址。
    #   queue_name（str）：Redis 摄取队列名称。
    #   ttl_seconds（int）：缓存或记录的有效时长，单位秒。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, redis_url: str, *, queue_name: str, ttl_seconds: int) -> None:
        from redis.asyncio import Redis

        # 实例属性说明：_redis
        # 作用：Redis 客户端。
        self._redis = Redis.from_url(redis_url, decode_responses=True)
        # 实例属性说明：_queue_name
        # 作用：Redis 摄取队列名称。
        self._queue_name = queue_name
        # 实例属性说明：_ttl
        # 作用：缓存或记录的有效时长，单位秒。
        self._ttl = ttl_seconds

    # 方法说明：_key
    # 作用：根据摄取任务标识生成 Redis 状态存储键。
    # 入参：
    #   job_id（str）：文档摄取任务标识。
    # 出参：str；指定摄取任务的 Redis 状态键。
    def _key(self, job_id: str) -> str:
        return f"{self._queue_name}:job:{job_id}"

    # 方法说明：enqueue
    # 作用：将摄取任务写入队列，供后台工作者读取。
    # 入参：
    #   job（IngestionJob）：文档摄取任务。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    async def enqueue(self, job: IngestionJob) -> None:
        payload = job.model_dump_json()
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.setex(self._key(job.job_id), self._ttl, payload)
            pipe.lpush(self._queue_name, job.job_id)
            await pipe.execute()

    # 方法说明：dequeue
    # 作用：从摄取队列取得待处理文档任务。
    # 入参：
    #   timeout_seconds（int）：操作超时上限，单位秒；默认值为 5。
    # 出参：IngestionJob | None；异步文档摄取任务或None（未取得结果）。
    async def dequeue(self, timeout_seconds: int = 5) -> IngestionJob | None:
        result = await self._redis.brpop(self._queue_name, timeout=timeout_seconds)
        if not result:
            return None
        return await self.get(result[1])

    # 方法说明：update
    # 作用：通过Redis 文档摄取队列实现更新指定业务对象的可修改字段。
    # 入参：
    #   job（IngestionJob）：文档摄取任务。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    async def update(self, job: IngestionJob) -> None:
        await self._redis.setex(self._key(job.job_id), self._ttl, job.model_dump_json())

    # 方法说明：get
    # 作用：通过Redis 文档摄取队列实现读取指定标识对应的业务对象。
    # 入参：
    #   job_id（str）：文档摄取任务标识。
    # 出参：IngestionJob | None；异步文档摄取任务或None（未取得结果）。
    async def get(self, job_id: str) -> IngestionJob | None:
        raw = await self._redis.get(self._key(job_id))
        return IngestionJob.model_validate_json(raw) if raw else None

    # 方法说明：close
    # 作用：关闭当前组件拥有的客户端或连接，释放外部资源。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    async def close(self) -> None:
        await self._redis.aclose()
