"""按入口装配路由；公共 API 不导入 Agent 路由。"""

from fastapi import APIRouter


# 方法说明：build_api_router
# 作用：创建并组装当前模块的 HTTP 路由对象。
# 入参：
#   include_agent（bool）：是否装配 Agent 相关能力；默认值为 True。
# 出参：APIRouter；HTTP 路由集合。
def build_api_router(*, include_agent: bool = True) -> APIRouter:
    from safemeal.interfaces.http.routers import (
        auth,
        behavior,
        history,
        interactions,
        rankings,
        recipes,
    )

    router = APIRouter()
    for module, tag in (
        (behavior, "Personal Behavior"),
        (rankings, "Rankings"),
        (history, "History"),
        (interactions, "Interactions"),
        (recipes, "Recipes"),
    ):
        router.include_router(module.router, prefix="/recipes", tags=[tag])
    router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
    if include_agent:
        from safemeal.interfaces.http.routers import chat, knowledge

        router.include_router(chat.router, prefix="/chat", tags=["Unified Chat"])
        router.include_router(
            knowledge.router, prefix="/knowledge", tags=["File Knowledge"]
        )
    return router


# 方法说明：__getattr__
# 作用：按需装配或加载公开导出符号，避免导入时初始化完整应用。
# 入参：
#   name（str）：当前对象或字段的名称。
# 出参：按实现返回；按名称装配的公开路由或按需加载的公开函数。
def __getattr__(name: str):
    if name == "api_router":
        return build_api_router()
    raise AttributeError(name)


__all__ = ["build_api_router", "api_router"]
