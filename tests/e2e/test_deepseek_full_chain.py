"""Pytest entry point for the real authenticated DeepSeek conversation flow."""

from __future__ import annotations

import os
from pathlib import Path
import runpy

import pytest


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.getenv("RUN_DEEPSEEK_E2E") != "1",
        reason="set RUN_DEEPSEEK_E2E=1 against an explicitly configured live API",
    ),
]


def test_register_login_and_three_memory_aware_turns() -> None:
    """Run the user-authored three-turn flow without altering model prompts."""

    driver = Path(__file__).with_name("deepseek_full_chain.py")
    namespace = runpy.run_path(str(driver))
    assert namespace["main"]() == 0
