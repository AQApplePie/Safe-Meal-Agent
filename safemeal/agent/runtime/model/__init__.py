"""定义智能体使用的模型能力接口。"""

from .protocol import AgentModelGateway
from .intent_classifier import IntentClassifier

__all__ = ["AgentModelGateway", "IntentClassifier"]
