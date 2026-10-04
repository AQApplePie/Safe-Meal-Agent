"""Agent model layer.

This layer defines semantic model capabilities used by planning, reflection and
answer composition. Provider SDKs remain in ``infrastructure/llm``.
"""

from .protocol import AgentModelGateway
from .intent_classifier import IntentClassifier

__all__ = ["AgentModelGateway", "IntentClassifier"]
