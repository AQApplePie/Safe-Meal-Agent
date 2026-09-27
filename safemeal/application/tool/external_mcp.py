"""External tool adapter; transport supplied by the composition service."""

from safemeal.application.ports.tools.handler import ToolHandler
from safemeal.application.contracts.tools.payloads import ExternalMcpCallArgs
from safemeal.application.ports.tools.backends import McpGateway
from safemeal.shared.types import JsonObject


class ExternalMcpTool(ToolHandler[ExternalMcpCallArgs]):
    name = "external_mcp_call"
    description = (
        "通过已配置并授权的外部 MCP Server 调用工具。必须明确提供 server_name、"
        "tool_name 和符合远端 Schema 的 arguments。"
    )
    args_schema = ExternalMcpCallArgs

    def __init__(self, gateway: McpGateway) -> None:
        self._gateway = gateway

    async def run(self, arguments: ExternalMcpCallArgs) -> JsonObject:
        return await self._gateway.call_tool(
            arguments.server_name,
            arguments.tool_name,
            arguments.arguments,
        )
