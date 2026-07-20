"""Functional API router groups for v1."""

from .admin import admin_api_router
from .internal import internal_api_router
from .public import public_api_router

__all__ = ["admin_api_router", "internal_api_router", "public_api_router"]
