"""实现持久化基础设施适配。"""

import json
import msgpack
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

_MODULES = {
    "safemeal.modules.recipe_catalog.recipe_models": "safemeal.modules.recipe.contracts.models",
    "safemeal.modules.recipe_catalog.generated_recipe": "safemeal.modules.recipe.contracts.generated",
    "safemeal.modules.user_memory.memory_models": "safemeal.modules.conversation.contracts.memory.extraction",
    "safemeal.modules.dietary_safety.dietary_constraints": "safemeal.modules.dietary.contracts.constraints",
    "safemeal.modules.dietary_safety.recipe_safety": "safemeal.modules.dietary.contracts.models",
    "safemeal.shared.contracts.tools": "safemeal.agent.runtime.tools.contracts.base",
    "safemeal.shared.contracts.agent_conversation": "safemeal.modules.conversation.contracts.conversation.models",
    "safemeal.shared.contracts.agent_context": "safemeal.agent.contracts.context",
    "safemeal.shared.contracts.memory": "safemeal.modules.conversation.contracts.memory.models",
    "safemeal.agent.contracts": "safemeal.agent.contracts.api",
    "safemeal.agent.contracts_context": "safemeal.agent.contracts.context",
    "safemeal.agent.contracts_state": "safemeal.agent.contracts.state",
    "safemeal.agent.contracts_decisions": "safemeal.agent.contracts.decisions",
    "safemeal.application.contracts.prompts": "safemeal.agent.contracts.prompts",
    "safemeal.agent.contracts_conversation": "safemeal.modules.conversation.contracts.conversation.models",
    "safemeal.agent.contracts.workflow": "safemeal.agent.contracts.workflow.models",
    "safemeal.application.contracts.stream": "safemeal.agent.contracts.workflow.stream",
    "safemeal.modules.conversation.contracts.chat": "safemeal.modules.conversation.contracts.chat.messages",
    "safemeal.modules.conversation.contracts.chat_turn": "safemeal.modules.conversation.contracts.chat.turn",
    "safemeal.application.contracts.recipe_catalog": "safemeal.modules.recipe.contracts.catalog",
    "safemeal.application.contracts.recipe_generation": "safemeal.modules.recipe.contracts.generation",
    "safemeal.agent.runtime.tools.contracts": "safemeal.agent.runtime.tools.contracts.base",
    "safemeal.application.contracts.tool_payloads": "safemeal.agent.runtime.tools.contracts.payloads",
    "safemeal.modules.conversation.contracts.memory": "safemeal.modules.conversation.contracts.memory.models",
    "safemeal.modules.knowledge.contracts": "safemeal.modules.knowledge.contracts.models",
    "safemeal.application.contracts.ingestion": "safemeal.modules.knowledge.contracts.ingestion",
}


def _rewrite_extension(code, payload):


    value = msgpack.unpackb(payload, ext_hook=_rewrite_extension, strict_map_key=False)
    if isinstance(value, list) and len(value) >= 2 and isinstance(value[0], str):
        value[0] = _MODULES.get(value[0], value[0])
    return msgpack.ExtType(code, msgpack.packb(value, use_bin_type=True))


def _rewrite_json(value):
    if isinstance(value, dict):
        if value.get("lc") == 2 and value.get("type") == "constructor":
            parts = value.get("id", [])
            if isinstance(parts, list) and len(parts) > 1:
                module = ".".join(parts[:-1])
                if module in _MODULES:
                    value["id"] = [*_MODULES[module].split("."), parts[-1]]
        return {key: _rewrite_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_rewrite_json(item) for item in value]
    return value


class ContractCheckpointSerializer(JsonPlusSerializer):
    def loads_typed(self, data):
        kind, payload = data
        if kind == "msgpack":
            raw = msgpack.unpackb(
                payload, ext_hook=_rewrite_extension, strict_map_key=False
            )
            payload = msgpack.packb(raw, use_bin_type=True)
        elif kind == "json":
            payload = json.dumps(_rewrite_json(json.loads(payload))).encode()
        return super().loads_typed((kind, payload))
