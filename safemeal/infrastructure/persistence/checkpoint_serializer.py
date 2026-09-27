"""Read existing checkpoints after contract relocation without restoring old code."""

import json
import msgpack
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

_MODULES = {
    "safemeal.shared.contracts.tools": "safemeal.application.contracts.tools.base",
    "safemeal.shared.contracts.agent_conversation": "safemeal.application.contracts.conversation.models",
    "safemeal.shared.contracts.agent_context": "safemeal.application.contracts.agent.context",
    "safemeal.shared.contracts.memory": "safemeal.application.contracts.memory.models",
    "safemeal.application.observability.trace_models": "safemeal.application.contracts.observability.trace",
    "safemeal.application.contracts.agent": "safemeal.application.contracts.agent.api",
    "safemeal.application.contracts.agent_context": "safemeal.application.contracts.agent.context",
    "safemeal.application.contracts.agent_state": "safemeal.application.contracts.agent.state",
    "safemeal.application.contracts.agent_decisions": "safemeal.application.contracts.agent.decisions",
    "safemeal.application.contracts.prompts": "safemeal.application.contracts.agent.prompts",
    "safemeal.application.contracts.agent_conversation": "safemeal.application.contracts.conversation.models",
    "safemeal.application.contracts.workflow": "safemeal.application.contracts.workflow.models",
    "safemeal.application.contracts.stream": "safemeal.application.contracts.workflow.stream",
    "safemeal.application.contracts.chat": "safemeal.application.contracts.chat.messages",
    "safemeal.application.contracts.chat_turn": "safemeal.application.contracts.chat.turn",
    "safemeal.application.contracts.recipe_catalog": "safemeal.application.contracts.recipes.catalog",
    "safemeal.application.contracts.recipe_generation": "safemeal.application.contracts.recipes.generation",
    "safemeal.application.contracts.tools": "safemeal.application.contracts.tools.base",
    "safemeal.application.contracts.tool_payloads": "safemeal.application.contracts.tools.payloads",
    "safemeal.application.contracts.memory": "safemeal.application.contracts.memory.models",
    "safemeal.application.contracts.upload": "safemeal.application.contracts.upload.models",
    "safemeal.application.contracts.ingestion": "safemeal.application.contracts.upload.ingestion",
    "safemeal.application.contracts.cost": "safemeal.application.contracts.observability.cost",
    "safemeal.application.contracts.trace": "safemeal.application.contracts.observability.trace",
    "safemeal.application.contracts.evaluation": "safemeal.application.contracts.evaluation.models",
}


def _rewrite_extension(code, payload):
    # Constructor extensions carry [module, class, arguments, ...]. Keep other
    # application strings unchanged and let the upstream serializer instantiate.
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
