"""External MCP tool discovery and invocation adapter."""

from __future__ import annotations

from dataclasses import dataclass
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from safemeal.shared.types import JsonObject, to_json_object


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
