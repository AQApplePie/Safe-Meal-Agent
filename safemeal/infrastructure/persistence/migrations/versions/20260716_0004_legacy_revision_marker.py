"""Keep the former local schema revision resolvable after feature removal.

Revision ID: 20260716_0004
Revises: 20260713_0003
"""

from __future__ import annotations


revision: str = "20260716_0004"
down_revision: str | None = "20260713_0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
