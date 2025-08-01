"""MCP Web Gateway server implementation.

This server exposes OpenAPI operations as resources with their original HTTP URIs
and provides generic REST tools to execute requests.
"""

from typing import Any

import httpx
from fastmcp.server import FastMCP
from fastmcp.tools.tool import ToolResult
from fastmcp.utilities.logging import get_logger

from .http_resource_manager import HttpResourceManager
from .openapi_handler import OpenAPIHandler

logger = get_logger(__name__)


class McpWebGateway(FastMCP[Any]):
    """MCP Web Gateway server that exposes OpenAPI operations as resources.

    This implementation takes a web gateway approach:
    - All routes become resources or resource templates (never tools)
    - Resources use plain HTTP URIs without method prefixes
    - Generic REST tools (GET, POST, PUT, PATCH, DELETE, OPTIONS) operate on these resources
    - Resources return OpenAPI schema when read, showing all available methods
    """

    def __init__(
        self,
        openapi_spec: dict[str, Any],
        client: httpx.AsyncClient,
        name: str | None = None,
        add_rest_tools: bool = True,
        open_world: bool = False,
        route_maps: list[Any] | None = None,
    ):
        """Initialize MCP Web Gateway server.

        Args:
            openapi_spec: OpenAPI specification dictionary
            client: HTTP client for making requests
            name: Server name (defaults to "MCP Web Gateway")
            add_rest_tools: Whether to add generic REST tools (default: True)
            open_world: Allow tools to access any URL, not just defined resources (default: False)
            route_maps: Custom route mapping rules (defaults to WEB_GATEWAY_ROUTE_MAPPINGS)
        """
        # Initialize FastMCP
        super().__init__(name or "MCP Web Gateway")

        # Store core components
        self._client = client
        self._add_rest_tools = add_rest_tools

        # Create OpenAPI handler
        self._openapi = OpenAPIHandler(openapi_spec)

        # Determine base URL once during initialization
        client_base_url = str(self._client.base_url) if self._client.base_url else None
        self._base_url = self._openapi.determine_base_url(client_base_url)

        # Create HTTP resource manager and populate resources
        self._http_resource_manager = HttpResourceManager.from_openapi(
            openapi_handler=self._openapi,
            base_url=self._base_url,
            client=self._client,
            route_maps=route_maps,
            open_world=open_world,
        )

        # Log summary
        logger.info("Created MCP Web Gateway server")

        # Transfer resources to this server
        for uri, resource in self._http_resource_manager._resources.items():
            self._resource_manager.add_resource(resource)
        for uri, template in self._http_resource_manager._templates.items():
            self._resource_manager.add_template(template)

        # Add generic REST tools if requested
        if self._add_rest_tools:
            self.add_rest_tools()

    @classmethod
    def from_fastapi(  # type: ignore[override]
        cls,
        app: Any,
        name: str | None = None,
        add_rest_tools: bool = True,
        open_world: bool = False,
        **kwargs: Any,
    ) -> "McpWebGateway":
        """Create an MCP Web Gateway from a FastAPI application.

        Args:
            app: FastAPI application instance
            name: Optional name for the gateway
            add_rest_tools: Whether to add REST tools (default: True)
            open_world: Whether to allow access to any URL (default: False)
            **kwargs: Additional arguments passed to constructor

        Returns:
            McpWebGateway instance
        """
        # Check for unsupported parameters
        if "route_map_fn" in kwargs:
            raise NotImplementedError(
                "McpWebGateway does not support custom route_map_fn"
            )
        if "mcp_component_fn" in kwargs:
            raise NotImplementedError(
                "McpWebGateway does not support custom mcp_component_fn"
            )

        # Create httpx client with ASGI transport
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://fastapi",
        )

        # Get OpenAPI spec from FastAPI
        openapi_spec = app.openapi()

        # Create gateway
        return cls(
            openapi_spec=openapi_spec,
            client=client,
            name=name or getattr(app, "title", "FastAPI App"),
            add_rest_tools=add_rest_tools,
            open_world=open_world,
            **kwargs,
        )

    def add_rest_tools(self) -> None:
        """Add the generic REST tools to the server."""

        @self.tool(
            name="GET",
            description="Execute a GET request on a URL",
            annotations={"openWorldHint": self._http_resource_manager._open_world},
        )
        async def get_tool(url: str, params: dict[str, Any] | None = None) -> Any:
            result = await self._http_resource_manager.execute_http_method(
                "GET", url, params=params
            )
            # Handle empty responses specially
            if result == {}:
                return ToolResult(content="")
            return ToolResult(structured_content=result)

        @self.tool(
            name="POST",
            description="Execute a POST request on a URL",
            annotations={"openWorldHint": self._http_resource_manager._open_world},
        )
        async def post_tool(
            url: str,
            body: dict[str, Any] | None = None,
            params: dict[str, Any] | None = None,
        ) -> Any:
            result = await self._http_resource_manager.execute_http_method(
                "POST", url, body=body, params=params
            )
            # Handle empty responses specially
            if result == {}:
                return ToolResult(content="")
            return ToolResult(structured_content=result)

        @self.tool(
            name="PUT",
            description="Execute a PUT request on a URL",
            annotations={"openWorldHint": self._http_resource_manager._open_world},
        )
        async def put_tool(
            url: str,
            body: dict[str, Any] | None = None,
            params: dict[str, Any] | None = None,
        ) -> Any:
            result = await self._http_resource_manager.execute_http_method(
                "PUT", url, body=body, params=params
            )
            # Handle empty responses specially
            if result == {}:
                return ToolResult(content="")
            return ToolResult(structured_content=result)

        @self.tool(
            name="PATCH",
            description="Execute a PATCH request on a URL",
            annotations={"openWorldHint": self._http_resource_manager._open_world},
        )
        async def patch_tool(
            url: str,
            body: dict[str, Any] | None = None,
            params: dict[str, Any] | None = None,
        ) -> Any:
            result = await self._http_resource_manager.execute_http_method(
                "PATCH", url, body=body, params=params
            )
            # Handle empty responses specially
            if result == {}:
                return ToolResult(content="")
            return ToolResult(structured_content=result)

        @self.tool(
            name="DELETE",
            description="Execute a DELETE request on a URL",
            annotations={"openWorldHint": self._http_resource_manager._open_world},
        )
        async def delete_tool(url: str, params: dict[str, Any] | None = None) -> Any:
            result = await self._http_resource_manager.execute_http_method(
                "DELETE", url, params=params
            )
            # Handle empty responses (like 204 No Content) specially
            if result == {}:
                return ToolResult(content="")
            return ToolResult(structured_content=result)

        @self.tool(
            name="OPTIONS",
            description="Execute an OPTIONS request on a URL",
            annotations={"openWorldHint": self._http_resource_manager._open_world},
        )
        async def options_tool(url: str, params: dict[str, Any] | None = None) -> Any:
            result = await self._http_resource_manager.execute_http_method(
                "OPTIONS", url, params=params
            )
            # Handle empty responses specially
            if result == {}:
                return ToolResult(content="")
            return ToolResult(structured_content=result)

    @property
    def base_url(self) -> str:
        """Get the base URL determined during initialization."""
        return self._base_url


__all__ = ["McpWebGateway"]
