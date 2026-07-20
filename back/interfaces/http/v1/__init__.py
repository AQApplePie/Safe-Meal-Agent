"""API v1 router aggregation.

Route import errors are programming/startup errors and must stop the process
instead of silently removing API capabilities.
"""

from fastapi import APIRouter

from .routers import admin_api_router, internal_api_router, public_api_router

api_router = APIRouter()
api_router.include_router(public_api_router)
api_router.include_router(admin_api_router)
api_router.include_router(internal_api_router)

__all__ = [
    "admin_api_router",
    "api_router",
    "internal_api_router",
    "public_api_router",
]
