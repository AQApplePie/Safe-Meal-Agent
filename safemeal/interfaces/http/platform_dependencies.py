"""传统后端 HTTP 依赖；仅连接请求状态和业务服务。"""

from typing import Any
from fastapi import Depends, Request
from safemeal.config.platform import PlatformSettings
from safemeal.modules.identity.application import AuthService
from safemeal.modules.recipe.application.recipe_service import RecipeService
from safemeal.modules.interaction.application.history_service import HistoryService
from safemeal.modules.interaction.application.interaction_service import (
    InteractionService,
)
from safemeal.modules.interaction.application.ranking_service import RankingService


# 方法说明：get_container
# 作用：从 FastAPI 应用状态取得依赖容器。
# 入参：
#   request（Request）：HTTP 请求或应用层请求契约。
# 出参：Any；由调用约定决定的数据对象。
def get_container(request: Request) -> Any:

    return request.app.state.container


# 方法说明：get_auth_service
# 作用：提供注册、登录及令牌验证业务服务。
# 入参：
#   container（Any）：当前应用的依赖容器；由 FastAPI 依赖注入。
# 出参：AuthService；注册登录与令牌管理服务。
def get_auth_service(
    container: Any = Depends(get_container),
) -> AuthService:
    return container.get_auth_service()


# 方法说明：get_recipe_browse_service
# 作用：提供食谱查询、详情与推荐业务服务。
# 入参：
#   container（Any）：当前应用的依赖容器；由 FastAPI 依赖注入。
# 出参：RecipeService；食谱查询推荐与生成业务服务。
def get_recipe_browse_service(
    container: Any = Depends(get_container),
) -> RecipeService:
    return container.get_recipe_browse_service()


# 方法说明：get_interaction_service
# 作用：提供点赞、收藏及批量状态查询服务。
# 入参：
#   container（Any）：当前应用的依赖容器；由 FastAPI 依赖注入。
# 出参：InteractionService；点赞收藏业务服务。
def get_interaction_service(
    container: Any = Depends(get_container),
) -> InteractionService:
    return container.get_interaction_service()


# 方法说明：get_history_service
# 作用：提供浏览历史写入及分页查询服务。
# 入参：
#   container（Any）：当前应用的依赖容器；由 FastAPI 依赖注入。
# 出参：HistoryService；浏览历史业务服务。
def get_history_service(container: Any = Depends(get_container)) -> HistoryService:
    return container.get_history_service()


# 方法说明：get_ranking_service
# 作用：提供热门榜单读取与刷新服务。
# 入参：
#   container（Any）：当前应用的依赖容器；由 FastAPI 依赖注入。
# 出参：RankingService；热门榜单读取与重建服务。
def get_ranking_service(container: Any = Depends(get_container)) -> RankingService:
    return container.get_ranking_service()


# 方法说明：get_http_settings
# 作用：读取当前入口使用的 HTTP 配置。
# 入参：
#   request（Request）：HTTP 请求或应用层请求契约。
# 出参：PlatformSettings；传统平台独立运行配置。
def get_http_settings(request: Request) -> PlatformSettings:
    config = getattr(request.app.state, "settings", None)
    if config is not None:
        return config
    # 单独装配 router 的兼容路径；两个生产入口都显式注入配置。
    from safemeal.config.settings import settings

    return settings
