"""Public progress events contain status only, never model drafts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowProgress:
    stage: str
    message: str
