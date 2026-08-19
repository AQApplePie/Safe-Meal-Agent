"""External MCP tool discovery and invocation adapter."""

from __future__ import annotations

from dataclasses import dataclass
from pydantic import BaseModel, ConfigDict, Field
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from safemeal.shared.types import JsonObject, to_json_object
from safemeal.infrastructure.tools.tool_executor import ToolHandler


@dataclass(frozen=True, slots=True)
class McpServerConfig:
    name: str
    url: str
    headers: dict[str, str]


class McpClientGateway:
    """Stateless MCP client suitable for low-frequency external tools."""

    def __init__(self, servers: list[McpServerConfig]) -> None:
        self._servers = {server.name: server for server in servers}

    async def list_tools(self) -> list[JsonObject]:
        result: list[JsonObject] = []
        for server in self._servers.values():
            async with streamablehttp_client(
                server.url, headers=server.headers
            ) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    page = await session.list_tools()
                    result.extend(
                        {
                            "server": server.name,
                            "name": tool.name,
                            "description": tool.description or "",
                            "input_schema": to_json_object(tool.inputSchema),
                        }
                        for tool in page.tools
                    )
        return result

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: JsonObject
    ) -> JsonObject:
        server = self._servers[server_name]
        async with streamablehttp_client(server.url, headers=server.headers) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=arguments)
                return to_json_object(result.model_dump(mode="json"))


class ExternalMcpCallArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    server_name: str = Field(min_length=1, max_length=128)
    tool_name: str = Field(min_length=1, max_length=128)
    arguments: JsonObject = Field(default_factory=dict)


class ExternalMcpTool(ToolHandler[ExternalMcpCallArgs]):
    name = "external_mcp_call"
    description = (
        "通过已配置并授权的外部 MCP Server 调用工具。必须明确提供 server_name、"
        "tool_name 和符合远端 Schema 的 arguments。"
    )
    args_schema = ExternalMcpCallArgs

    def __init__(self, gateway: McpClientGateway) -> None:
        self._gateway = gateway

    async def run(self, arguments: ExternalMcpCallArgs) -> JsonObject:
        return await self._gateway.call_tool(
            arguments.server_name,
            arguments.tool_name,
            arguments.arguments,
        )


__all__ = [
    "ExternalMcpCallArgs",
    "ExternalMcpTool",
    "McpClientGateway",
    "McpServerConfig",
]
