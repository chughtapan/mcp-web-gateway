"""MCP Web Gateway server implementation.

This server exposes OpenAPI operations as resources with their original HTTP URIs
and provides generic REST tools to execute requests.
"""

import json
import re
from typing import Any
from urllib.parse import urljoin, urlparse

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
    - Resources use plain HTTP URIs without method prefixes
    - Generic REST tools (GET, POST, PUT, PATCH, DELETE) operate on these resources
    - Resources return OpenAPI schema when read, showing all available methods

    Example:
        ```python
        from mcp_web_gateway import McpWebGateway
        import httpx

        spec = load_openapi_spec()
        client = httpx.AsyncClient(base_url="https://api.example.com")
        server = McpWebGateway(spec, client)

        # Resources are created with HTTP URIs:
        # All methods on /users -> https://api.example.com/users

        # Use REST tools to execute requests:
        async with Client(server) as client:
            # Read resource to see available methods
            schema = await client.read_resource("https://api.example.com/users")

            # Execute requests
            result = await client.call_tool("GET", {"url": "https://api.example.com/users"})
            result = await client.call_tool("POST", {"url": "https://api.example.com/users", "body": {...}})
        ```
    """

    def __init__(
        self,
        openapi_spec: dict[str, Any],
        client: httpx.AsyncClient,
        name: str | None = None,
        add_rest_tools: bool = True,
        **settings: Any,
    ):
        """Initialize an MCP Web Gateway server from an OpenAPI schema."""
        # Check for unsupported settings
        self._check_unsupported_settings(**settings)

        # Override route_maps with web gateway mappings
        settings["route_maps"] = WEB_GATEWAY_ROUTE_MAPPINGS

        # Initialize the parent class
        super().__init__(
            openapi_spec=openapi_spec,
            client=client,
            name=name or "MCP Web Gateway",
            **settings,
        )

        # Add the generic REST tools if requested
        if add_rest_tools:
            self.add_rest_tools()

        logger.info(
            f"Created MCP Web Gateway server with {len(self._resource_manager._resources)} resources "
            f"and {len(self._resource_manager._templates)} templates"
        )

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
        add_rest_tools: bool = True,
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
            add_rest_tools: Whether to automatically add REST tools (default True)
            **settings: Additional settings passed to McpWebGateway

        Returns:
            McpWebGateway instance configured for the FastAPI app

        Raises:
            NotImplementedError: If route_maps, route_map_fn, or mcp_component_fn are provided
        """
        # Check for unsupported settings
        cls._check_unsupported_settings(
            route_maps=route_maps,
            route_map_fn=route_map_fn,
            mcp_component_fn=mcp_component_fn,
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
            add_rest_tools=add_rest_tools,
            **settings,
        )

    @staticmethod
    def _check_unsupported_settings(**settings: Any) -> None:
        """Check for unsupported settings and raise NotImplementedError if found."""
        if "route_maps" in settings and settings["route_maps"] is not None:
            raise NotImplementedError(
                "McpWebGateway does not support custom route_maps. "
                "It uses WEB_GATEWAY_ROUTE_MAPPINGS to expose all routes as resources."
            )
        if "route_map_fn" in settings and settings["route_map_fn"] is not None:
            raise NotImplementedError(
                "McpWebGateway does not support custom route_map_fn. "
                "It uses a fixed routing strategy."
            )
        if "mcp_component_fn" in settings and settings["mcp_component_fn"] is not None:
            raise NotImplementedError(
                "McpWebGateway does not support custom mcp_component_fn. "
                "It creates WebResource and WebResourceTemplate components with fixed behavior."
            )

    def _create_resource_uri(self, route: HTTPRoute) -> str:
        """Create a resource URI without method prefix."""
        # Ensure base_url ends with / for proper urljoin behavior
        base = self.base_url.rstrip("/") + "/"
        # Remove leading / from route.path since urljoin will handle it
        path = route.path.lstrip("/")
        return urljoin(base, path)

    def _create_enhanced_description(
        self, route: HTTPRoute, component_type: str
    ) -> str:
        """Create an enhanced description for a component."""
        base_description = (
            route.description
            or route.summary
            or f"{component_type} {route.method} {route.path}"
        )
        return format_description_with_responses(
            base_description=base_description,
            responses=route.responses,
            parameters=route.parameters,
            request_body=route.request_body,
        )

    def _build_template_parameter_schema(self, route: HTTPRoute) -> dict[str, Any]:
        """Build parameter schema for path parameters only."""
        path_params = [p for p in route.parameters if p.location == "path"]
        return {
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

    def _create_openapi_resource(
        self,
        route: HTTPRoute,
        name: str,
        tags: set[str],
    ) -> None:
        """Creates and registers a WebResource with HTTP URI, merging if it already exists."""
        resource_uri = self._create_resource_uri(route)

        # Check if resource already exists
        existing_resource = self._resource_manager._resources.get(resource_uri)

        if existing_resource and isinstance(existing_resource, WebResource):
            # Add the route to the existing resource
            existing_resource.add_route(route)
            logger.debug(
                f"Added route {route.method} to existing resource: {resource_uri}"
            )
        else:
            # Create new resource
            resource_name = self._get_unique_name(name, "resource")
            description = self._create_enhanced_description(route, "Represents")

            resource = WebResource(
                client=self._client,
                route=route,
                director=self._director,
                uri=resource_uri,
                name=resource_name,
                description=description,
                tags=set(route.tags or []) | tags,
                timeout=self._timeout,
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
        """Creates and registers a WebResourceTemplate with HTTP URI template, merging if it already exists."""
        uri_template = self._create_resource_uri(route)

        # Check if template already exists
        existing_template = self._resource_manager._templates.get(uri_template)

        if existing_template and isinstance(existing_template, WebResourceTemplate):
            # Add the route to the existing template
            existing_template.add_route(route)
            logger.debug(
                f"Added route {route.method} to existing template: {uri_template}"
            )
        else:
            # Create new template
            template_name = self._get_unique_name(name, "resource_template")
            description = self._create_enhanced_description(route, "Template for")
            template_params_schema = self._build_template_parameter_schema(route)

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
            )

            # Register the template
            self._resource_manager._templates[uri_template] = template
            logger.debug(
                f"Registered Web Template: {uri_template} ({route.method} {route.path})"
            )

    def add_rest_tools(self) -> None:
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
            description="Execute a GET request on a URL. First reads the resource to get OpenAPI schema, then executes the request.",
        )
        async def get_tool(url: str, params: dict[str, Any] | None = None) -> Any:
            return await execute_request("GET", url, params=params)

        @self.tool(
            name="POST",
            description="Execute a POST request on a URL. First reads the resource to get OpenAPI schema, then executes the request.",
        )
        async def post_tool(
            url: str,
            body: dict[str, Any] | None = None,
            params: dict[str, Any] | None = None,
        ) -> Any:
            return await execute_request("POST", url, body=body, params=params)

        @self.tool(
            name="PUT",
            description="Execute a PUT request on a URL. First reads the resource to get OpenAPI schema, then executes the request.",
        )
        async def put_tool(
            url: str,
            body: dict[str, Any] | None = None,
            params: dict[str, Any] | None = None,
        ) -> Any:
            return await execute_request("PUT", url, body=body, params=params)

        @self.tool(
            name="PATCH",
            description="Execute a PATCH request on a URL. First reads the resource to get OpenAPI schema, then executes the request.",
        )
        async def patch_tool(
            url: str,
            body: dict[str, Any] | None = None,
            params: dict[str, Any] | None = None,
        ) -> Any:
            return await execute_request("PATCH", url, body=body, params=params)

        @self.tool(
            name="DELETE",
            description="Execute a DELETE request on a URL. First reads the resource to get OpenAPI schema, then executes the request.",
        )
        async def delete_tool(url: str, params: dict[str, Any] | None = None) -> Any:
            return await execute_request("DELETE", url, params=params)

    async def _read_resource_schema(self, url: str) -> dict[str, Any] | None:
        """Read resource to get OpenAPI schema."""
        # Check if it's a direct resource
        if url in self._resource_manager._resources:
            resource = self._resource_manager._resources[url]
            schema_json = await resource.read()
            if isinstance(schema_json, str):
                parsed_schema = json.loads(schema_json)
                if isinstance(parsed_schema, dict):
                    return parsed_schema
            return None

        # Check templates
        for template_uri, template in self._resource_manager._templates.items():
            # Simple check if URL matches template pattern
            template_path = urlparse(template_uri).path
            url_path = urlparse(url).path

            # Basic pattern matching (this could be improved)
            if "{" in template_path:
                pattern = re.escape(template_path)
                pattern = pattern.replace(r"\{[^}]+\}", r"[^/]+")
                if re.match(f"^{pattern}$", url_path):
                    # For templates, we can't read the schema directly
                    # Return a basic schema indicating the template exists
                    return {
                        "openapi": "3.0.0",
                        "paths": {
                            template_path: {"description": "Template-based resource"}
                        },
                    }

        return None

    def _validate_method_supported(
        self, method: str, url: str, schema: dict[str, Any]
    ) -> None:
        """Validate that the HTTP method is supported for the given URL schema."""
        paths = schema.get("paths", {})
        for path, operations in paths.items():
            if method.lower() not in operations:
                available_methods = [
                    m.upper() for m in operations.keys() if m != "description"
                ]
                raise ValueError(
                    f"Method {method} not supported for {url}. "
                    f"Available methods: {', '.join(available_methods)}"
                )
            logger.debug(
                f"Found OpenAPI schema for {url}, method {method} is supported"
            )

    def _build_request_args(
        self,
        method: str,
        url: str,
        body: dict[str, Any] | None,
        params: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Build request arguments for the HTTP client."""
        request_args: dict[str, Any] = {
            "method": method,
            "url": url,
        }

        if params:
            request_args["params"] = params

        if body and method in ["POST", "PUT", "PATCH"]:
            request_args["json"] = body

        return request_args

    def _handle_response(self, response: httpx.Response) -> ToolResult:
        """Handle HTTP response and return appropriate ToolResult."""
        try:
            result = response.json()
            # Wrap non-dict results
            if isinstance(result, dict):
                return ToolResult(structured_content=result)
            else:
                return ToolResult(structured_content={"result": result})
        except json.JSONDecodeError:
            return ToolResult(content=response.text)

    def _format_http_error(self, e: httpx.HTTPStatusError) -> str:
        """Format HTTP status error with detailed information."""
        error_message = (
            f"HTTP error {e.response.status_code}: {e.response.reason_phrase}"
        )
        try:
            error_data = e.response.json()
            error_message += f" - {error_data}"
        except (json.JSONDecodeError, ValueError):
            if e.response.text:
                error_message += f" - {e.response.text}"
        return error_message

    async def _execute_rest_method(
        self,
        method: str,
        url: str,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Execute a REST request for the specified URL."""
        try:
            # Try to read resource schema first
            schema = await self._read_resource_schema(url)
            if schema:
                self._validate_method_supported(method, url, schema)
            else:
                logger.warning(
                    f"No resource found for {url}, proceeding with direct request"
                )

            # Build and execute the request
            request_args = self._build_request_args(method, url, body, params)
            response = await self._client.request(**request_args)
            response.raise_for_status()

            # Handle response
            return self._handle_response(response)

        except httpx.HTTPStatusError as e:
            error_message = self._format_http_error(e)
            raise ValueError(error_message)

        except httpx.RequestError as e:
            raise ValueError(f"Request error: {str(e)}")

    @property
    def base_url(self) -> str:
        """Get the base URL from the HTTP client."""
        return str(self._client.base_url)


# Export public symbols
__all__ = ["McpWebGateway"]
