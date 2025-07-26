"""MCP Web Gateway server implementation.

This server exposes OpenAPI operations as resources with their original HTTP URIs
and provides generic REST tools to execute requests.
"""

import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from fastmcp.experimental.server.openapi import FastMCPOpenAPI
from fastmcp.experimental.utilities.openapi import (
    HTTPRoute,
    format_description_with_responses,
)
from fastmcp.tools.tool import ToolResult
from fastmcp.utilities.logging import get_logger

from .components import WebResource, WebResourceTemplate
from .routing import WEB_GATEWAY_ROUTE_MAPPINGS

logger = get_logger(__name__)


class McpWebGateway(FastMCPOpenAPI):
    """
    MCP Web Gateway server that exposes OpenAPI operations as resources with HTTP URIs.

    This implementation takes a different approach from the base FastMCPOpenAPI:
    - All routes become resources or resource templates (never tools)
    - Resources use the full HTTP URI with optional method prefix
    - Generic REST tools (GET, POST, PUT, PATCH, DELETE) operate on these resources
    - Resources store HTTP metadata in annotations

    Example:
        ```python
        from mcp_web_gateway import McpWebGateway
        import httpx

        spec = load_openapi_spec()
        client = httpx.AsyncClient(base_url="https://api.example.com")
        server = McpWebGateway(spec, client)

        # Resources are created with HTTP URIs:
        # GET /users -> https+get://api.example.com/users
        # POST /users -> https+post://api.example.com/users

        # Use REST tools to execute requests:
        async with Client(server) as client:
            # With method prefix
            result = await client.call_tool("GET", {"url": "https+get://api.example.com/users"})
            # Without method prefix (uses tool name as method)
            result = await client.call_tool("GET", {"url": "https://api.example.com/users"})
        ```
    """

    def __init__(
        self,
        openapi_spec: dict[str, Any],
        client: httpx.AsyncClient,
        name: str | None = None,
        **settings: Any,
    ):
        """Initialize an MCP Web Gateway server from an OpenAPI schema."""
        # Override route_maps with web gateway mappings
        settings["route_maps"] = WEB_GATEWAY_ROUTE_MAPPINGS

        # Initialize the parent class
        super().__init__(
            openapi_spec=openapi_spec,
            client=client,
            name=name or "MCP Web Gateway",
            **settings,
        )

        # Add the generic REST tools
        self._add_rest_tools()

        logger.info(
            f"Created MCP Web Gateway server with {len(self._resource_manager._resources)} resources "
            f"and {len(self._resource_manager._templates)} templates"
        )

    def _create_resource_uri(self, route: HTTPRoute, base_url: str) -> str:
        """Create a resource URI with method prefix."""
        uri_parts = urlparse(base_url)
        method_scheme = f"{uri_parts.scheme}+{route.method.lower()}"
        return f"{method_scheme}://{uri_parts.netloc}{uri_parts.path.rstrip('/')}{route.path}"

    def _create_annotations(self, route: HTTPRoute) -> dict[str, Any]:
        """Create annotations with HTTP metadata."""
        annotations: dict[str, Any] = {
            "httpMethod": route.method,
            "httpPath": route.path,
        }

        if route.operation_id:
            annotations["operationId"] = route.operation_id

        if route.parameters:
            annotations["parameters"] = [p.model_dump() for p in route.parameters]

        if route.request_body:
            annotations["requestBody"] = route.request_body.model_dump()

        if route.responses:
            annotations["responses"] = {
                str(code): resp.model_dump() for code, resp in route.responses.items()
            }

        return annotations

    def _create_openapi_resource(
        self,
        route: HTTPRoute,
        name: str,
        tags: set[str],
    ) -> None:
        """Creates and registers a WebResource with HTTP URI and annotations."""
        base_url = (
            str(self._client.base_url) if self._client.base_url else "http://localhost"
        )
        resource_uri = self._create_resource_uri(route, base_url)
        resource_name = self._get_unique_name(name, "resource")

        description = format_description_with_responses(
            base_description=route.description
            or route.summary
            or f"Represents {route.method} {route.path}",
            responses=route.responses,
            parameters=route.parameters,
            request_body=route.request_body,
        )

        resource = WebResource(
            client=self._client,
            route=route,
            director=self._director,
            uri=resource_uri,
            name=resource_name,
            description=description,
            tags=set(route.tags or []) | tags,
            timeout=self._timeout,
            annotations=self._create_annotations(route),
        )

        # Call component_fn if provided
        if self._mcp_component_fn:
            try:
                self._mcp_component_fn(route, resource)
                logger.debug(f"Resource {resource_uri} customized by component_fn")
            except Exception as e:
                logger.warning(
                    f"Error in component_fn for resource {resource_uri}: {e}"
                )

        # Register the resource
        self._resource_manager._resources[resource_uri] = resource
        logger.debug(
            f"Registered Web Resource: {resource_uri} ({route.method} {route.path})"
        )

    def _create_openapi_template(
        self,
        route: HTTPRoute,
        name: str,
        tags: set[str],
    ) -> None:
        """Creates and registers a WebResourceTemplate with HTTP URI template and annotations."""
        base_url = (
            str(self._client.base_url) if self._client.base_url else "http://localhost"
        )
        uri_template = self._create_resource_uri(route, base_url)
        template_name = self._get_unique_name(name, "resource_template")

        description = format_description_with_responses(
            base_description=route.description
            or route.summary
            or f"Template for {route.method} {route.path}",
            responses=route.responses,
            parameters=route.parameters,
            request_body=route.request_body,
        )

        # Create parameter schema for path parameters only
        path_params = [p for p in route.parameters if p.location == "path"]
        template_params_schema = {
            "type": "object",
            "properties": {
                p.name: {
                    **(p.schema_.copy() if isinstance(p.schema_, dict) else {}),
                    **({"description": p.description} if p.description else {}),
                }
                for p in path_params
            },
            "required": [p.name for p in path_params if p.required],
        }

        template = WebResourceTemplate(
            client=self._client,
            route=route,
            director=self._director,
            uri_template=uri_template,
            name=template_name,
            description=description,
            parameters=template_params_schema,
            tags=set(route.tags or []) | tags,
            timeout=self._timeout,
            annotations=self._create_annotations(route),
        )

        # Call component_fn if provided
        if self._mcp_component_fn:
            try:
                self._mcp_component_fn(route, template)
                logger.debug(f"Template {uri_template} customized by component_fn")
            except Exception as e:
                logger.warning(
                    f"Error in component_fn for template {uri_template}: {e}"
                )

        # Register the template
        self._resource_manager._templates[uri_template] = template
        logger.debug(
            f"Registered Web Template: {uri_template} ({route.method} {route.path})"
        )

    def _add_rest_tools(self) -> None:
        """Add the generic REST tools to the server."""

        async def execute_request(
            method: str,
            url: str,
            body: dict[str, Any] | None = None,
            params: dict[str, Any] | None = None,
        ) -> ToolResult:
            """Common logic for executing REST requests."""
            return await self._execute_rest_method(
                method, url, body=body, params=params
            )

        @self.tool(
            name="GET",
            description="Execute a GET request on a URL. The URL can include an optional method prefix (e.g., https+get://api.example.com/users) or be a plain URL.",
        )
        async def get_tool(url: str, params: dict[str, Any] | None = None) -> Any:
            return await execute_request("GET", url, params=params)

        @self.tool(
            name="POST",
            description="Execute a POST request on a URL. The URL can include an optional method prefix (e.g., https+post://api.example.com/users) or be a plain URL.",
        )
        async def post_tool(
            url: str,
            body: dict[str, Any] | None = None,
            params: dict[str, Any] | None = None,
        ) -> Any:
            return await execute_request("POST", url, body=body, params=params)

        @self.tool(
            name="PUT",
            description="Execute a PUT request on a URL. The URL can include an optional method prefix (e.g., https+put://api.example.com/users/123) or be a plain URL.",
        )
        async def put_tool(
            url: str,
            body: dict[str, Any] | None = None,
            params: dict[str, Any] | None = None,
        ) -> Any:
            return await execute_request("PUT", url, body=body, params=params)

        @self.tool(
            name="PATCH",
            description="Execute a PATCH request on a URL. The URL can include an optional method prefix (e.g., https+patch://api.example.com/users/123) or be a plain URL.",
        )
        async def patch_tool(
            url: str,
            body: dict[str, Any] | None = None,
            params: dict[str, Any] | None = None,
        ) -> Any:
            return await execute_request("PATCH", url, body=body, params=params)

        @self.tool(
            name="DELETE",
            description="Execute a DELETE request on a URL. The URL can include an optional method prefix (e.g., https+delete://api.example.com/users/123) or be a plain URL.",
        )
        async def delete_tool(url: str, params: dict[str, Any] | None = None) -> Any:
            return await execute_request("DELETE", url, params=params)

    def _parse_url(self, url: str, expected_method: str) -> tuple[str, str, str]:
        """Parse URL to extract method and actual URL.

        Returns:
            Tuple of (parsed_method, actual_url, resource_key)
        """
        # Try to match URL with method prefix
        match = re.match(r"^(https?)\+(\w+)://(.+)$", url)
        if match:
            scheme, method, rest = match.groups()
            parsed_method = method.upper()
            actual_url = f"{scheme}://{rest}"
            resource_key = url  # Use the full URL with prefix as key
        else:
            # Plain URL - use the tool's method
            parsed_method = expected_method
            actual_url = url
            # Create resource key with method prefix for lookup
            parsed = urlparse(url)
            resource_key = f"{parsed.scheme}+{expected_method.lower()}://{parsed.netloc}{parsed.path}"

        return parsed_method, actual_url, resource_key

    def _find_resource_annotations(self, resource_key: str) -> dict[str, Any] | None:
        """Find annotations for a resource by its key."""
        # Check resources
        if resource_key in self._resource_manager._resources:
            resource = self._resource_manager._resources[resource_key]
            return getattr(resource, "annotations", None)

        # Check templates - simple prefix matching
        for template_uri, template in self._resource_manager._templates.items():
            if resource_key.startswith(template_uri.split("{")[0]):
                return getattr(template, "annotations", None)

        return None

    async def _execute_rest_method(
        self,
        method: str,
        url: str,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Execute a REST request for the specified URL."""
        try:
            # Parse the URL
            parsed_method, actual_url, resource_key = self._parse_url(url, method)

            # Verify method matches if specified in URL
            if parsed_method != method:
                raise ValueError(
                    f"Method mismatch: Tool {method} called on {parsed_method} resource"
                )

            # Find resource annotations (optional - we can proceed without them)
            annotations = self._find_resource_annotations(resource_key)
            if not annotations:
                logger.warning(
                    f"No annotations found for {resource_key}, proceeding with request"
                )

            # Build and execute the request
            request_args: dict[str, Any] = {
                "method": method,
                "url": actual_url,
            }

            if params:
                request_args["params"] = params

            if body and method in ["POST", "PUT", "PATCH"]:
                request_args["json"] = body

            response = await self._client.request(**request_args)
            response.raise_for_status()

            # Parse response
            try:
                result = response.json()
                # Wrap non-dict results
                if isinstance(result, dict):
                    return ToolResult(structured_content=result)
                else:
                    return ToolResult(structured_content={"result": result})
            except json.JSONDecodeError:
                return ToolResult(content=response.text)

        except httpx.HTTPStatusError as e:
            error_message = (
                f"HTTP error {e.response.status_code}: {e.response.reason_phrase}"
            )
            try:
                error_data = e.response.json()
                error_message += f" - {error_data}"
            except (json.JSONDecodeError, ValueError):
                if e.response.text:
                    error_message += f" - {e.response.text}"
            raise ValueError(error_message)

        except httpx.RequestError as e:
            raise ValueError(f"Request error: {str(e)}")

    @classmethod
    def from_fastapi(
        cls,
        app: Any,
        name: str | None = None,
        route_maps: list[Any] | None = None,
        route_map_fn: Any | None = None,
        mcp_component_fn: Any | None = None,
        mcp_names: dict[str, str] | None = None,
        httpx_client_kwargs: dict[str, Any] | None = None,
        tags: set[str] | None = None,
        **settings: Any,
    ) -> "McpWebGateway":
        """Create an MCP Web Gateway from a FastAPI application.

        Note: This implementation does not support custom route_maps, route_map_fn,
        or mcp_component_fn as it uses the Web Gateway's specific routing behavior.

        Args:
            app: FastAPI application instance
            name: Optional name for the gateway (defaults to app.title)
            route_maps: Not supported - raises NotImplementedError if provided
            route_map_fn: Not supported - raises NotImplementedError if provided
            mcp_component_fn: Not supported - raises NotImplementedError if provided
            mcp_names: Optional mapping of operation IDs to custom names
            httpx_client_kwargs: Optional kwargs for httpx.AsyncClient
            tags: Optional tags to add to all components
            **settings: Additional settings passed to McpWebGateway

        Returns:
            McpWebGateway instance configured for the FastAPI app

        Raises:
            NotImplementedError: If route_maps, route_map_fn, or mcp_component_fn are provided
        """
        if route_maps is not None:
            raise NotImplementedError(
                "McpWebGateway does not support custom route_maps. "
                "It uses WEB_GATEWAY_ROUTE_MAPPINGS to expose all routes as resources."
            )
        if route_map_fn is not None:
            raise NotImplementedError(
                "McpWebGateway does not support custom route_map_fn. "
                "It uses a fixed routing strategy."
            )
        if mcp_component_fn is not None:
            raise NotImplementedError(
                "McpWebGateway does not support custom mcp_component_fn. "
                "It creates WebResource and WebResourceTemplate components."
            )

        # Set up httpx client with ASGI transport
        if httpx_client_kwargs is None:
            httpx_client_kwargs = {}
        httpx_client_kwargs.setdefault("base_url", "http://fastapi")

        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            **httpx_client_kwargs,
        )

        # Get name from app if not provided
        name = name or getattr(app, "title", "FastAPI App")

        # Get OpenAPI spec from FastAPI app
        openapi_spec = app.openapi()

        # Create McpWebGateway with our settings
        return cls(
            openapi_spec=openapi_spec,
            client=client,
            name=name,
            tags=tags,
            mcp_names=mcp_names,
            **settings,
        )


# Export public symbols
__all__ = ["McpWebGateway"]
