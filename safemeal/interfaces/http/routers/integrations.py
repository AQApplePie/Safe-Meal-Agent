"""Operational routers for optional external integrations."""

from fastapi import APIRouter, Query

from safemeal.infrastructure.operations.health import get_integration_status

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/status")
async def read_integration_status(
    probe: bool = Query(
        False,
        description="Perform real network connectivity probes. Disabled by default.",
    ),
):
    return await get_integration_status(probe=probe)


__all__ = ["router"]
