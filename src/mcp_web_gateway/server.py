"""MCP Web Gateway server implementation.

This server exposes OpenAPI operations as resources with their original HTTP URIs
and provides generic REST tools to execute requests.
"""

import json
from typing import Any
from urllib.parse import urljoin

import httpx
from fastmcp.experimental.server.openapi import FastMCPOpenAPI
from fastmcp.experimental.utilities.openapi import (
    HTTPRoute,
    format_description_with_responses,
)
from fastmcp.resources.template import match_uri_template
from fastmcp.tools.tool import ToolResult
from fastmcp.utilities.logging import get_logger

from .components import WebResource, WebResourceTemplate
from .openapi_utils import OpenAPISchemaExtractor, PathMatcher
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
        open_world: bool = False,
        **settings: Any,
    ):
        """Initialize an MCP Web Gateway server from an OpenAPI schema.

        Args:
            openapi_spec: OpenAPI specification dictionary
            client: HTTP client for making requests
            name: Optional name for the server
            add_rest_tools: Whether to automatically add REST tools (default True)
            open_world: Whether REST tools can access URLs outside defined resources (default False)
            **settings: Additional settings passed to parent class
        """
        # Check for unsupported settings
        self._check_unsupported_settings(**settings)

        # Store the original OpenAPI spec for later use
        self._openapi_spec = openapi_spec
        # Create schema extractor
        self._schema_extractor = OpenAPISchemaExtractor(openapi_spec)

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
            self.add_rest_tools(open_world)

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
        open_world: bool = False,
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
            open_world: Whether REST tools can access URLs outside defined resources (default False)
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
            open_world=open_world,
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

    def _extract_method_schema(self, route: HTTPRoute) -> dict[str, Any]:
        """Extract the OpenAPI schema for a specific method from a route."""
        # Get the path item from the original spec
        paths = self._openapi_spec.get("paths", {})
        path_item = paths.get(route.path, {})
        # Return the method schema
        method_schema: dict[str, Any] = path_item.get(route.method.lower(), {})
        return method_schema

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
            # Extract method schema for this route
            method_schema = self._extract_method_schema(route)
            # Add the route to the existing resource
            existing_resource.add_route(route, method_schema)
            logger.debug(
                f"Added route {route.method} to existing resource: {resource_uri}"
            )
        else:
            # Create new resource
            resource_name = self._get_unique_name(name, "resource")
            description = self._create_enhanced_description(route, "Represents")

            # Extract schema for this resource
            schema = self._schema_extractor.extract_path_schema(
                route.path, [route.method]
            )

            resource = WebResource(
                route=route,
                uri=resource_uri,
                name=resource_name,
                description=description,
                tags=set(route.tags or []) | tags,
                meta=schema,
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
            # Extract method schema for this route
            method_schema = self._extract_method_schema(route)
            # Add the route to the existing template
            existing_template.add_route(route, method_schema)
            logger.debug(
                f"Added route {route.method} to existing template: {uri_template}"
            )
        else:
            # Create new template
            template_name = self._get_unique_name(name, "resource_template")
            description = self._create_enhanced_description(route, "Template for")
            template_params_schema = self._build_template_parameter_schema(route)

            # Extract schema for this template
            schema = self._schema_extractor.extract_path_schema(
                route.path, [route.method]
            )

            template = WebResourceTemplate(
                route=route,
                uri_template=uri_template,
                name=template_name,
                description=description,
                parameters=template_params_schema,
                tags=set(route.tags or []) | tags,
                meta=schema,
            )

            # Register the template
            self._resource_manager._templates[uri_template] = template
            logger.debug(
                f"Registered Web Template: {uri_template} ({route.method} {route.path})"
            )

    def add_rest_tools(self, open_world: bool = False) -> None:
        """Add the generic REST tools to the server.

        Args:
            open_world: Whether REST tools can access URLs outside defined resources (default False)
        """

        async def execute_request(
            method: str,
            url: str,
            body: dict[str, Any] | None = None,
            params: dict[str, Any] | None = None,
        ) -> ToolResult:
            """Common logic for executing REST requests."""
            return await self._execute_rest_method(
                method, url, body=body, params=params, open_world=open_world
            )

        @self.tool(
            name="GET",
            description="Execute a GET request on a URL. First reads the resource to get OpenAPI schema, then executes the request.",
            annotations={"openWorldHint": open_world},
        )
        async def get_tool(url: str, params: dict[str, Any] | None = None) -> Any:
            return await execute_request("GET", url, params=params)

        @self.tool(
            name="POST",
            description="Execute a POST request on a URL. First reads the resource to get OpenAPI schema, then executes the request.",
            annotations={"openWorldHint": open_world},
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
            annotations={"openWorldHint": open_world},
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
            annotations={"openWorldHint": open_world},
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
            annotations={"openWorldHint": open_world},
        )
        async def delete_tool(url: str, params: dict[str, Any] | None = None) -> Any:
            return await execute_request("DELETE", url, params=params)

        @self.tool(
            name="OPTIONS",
            description="Execute an OPTIONS request on a URL. If OPTIONS is defined in the schema, executes it. Otherwise returns schema for exact matches or lists matching routes for prefix matches.",
            annotations={"openWorldHint": open_world},
        )
        async def options_tool(url: str, params: dict[str, Any] | None = None) -> Any:
            return await self._execute_options_method(
                url, params=params, open_world=open_world
            )

    async def _read_resource_schema(self, url: str) -> dict[str, Any] | None:
        """Read resource to get OpenAPI schema."""
        # Check if it's a direct resource
        if url in self._resource_manager._resources:
            resource = self._resource_manager._resources[url]
            # Directly access the meta field which contains the schema
            if hasattr(resource, "meta") and isinstance(resource.meta, dict):
                return resource.meta
            return None

        # Check templates
        for template_uri, template in self._resource_manager._templates.items():
            # Check if URL matches template pattern using FastMCP's match_uri_template
            if match_uri_template(url, template_uri):
                # For template instances, access the template's meta directly
                if hasattr(template, "meta") and isinstance(template.meta, dict):
                    return template.meta
                return None

        return None

    def _is_method_supported(self, method: str, schema: dict[str, Any]) -> bool:
        """Check if the HTTP method is supported in the OpenAPI schema."""
        paths = schema.get("paths", {})
        for path, operations in paths.items():
            if isinstance(operations, dict) and method.lower() in operations:
                logger.debug(f"Found OpenAPI schema with {method} method supported")
                return True
        return False

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
        open_world: bool = False,
    ) -> ToolResult:
        """Execute a REST request for the specified URL."""
        try:
            # Try to read resource schema first
            schema = await self._read_resource_schema(url)
            if schema:
                if not self._is_method_supported(method, schema):
                    # Get available methods for error message
                    paths = schema.get("paths", {})
                    available_methods: set[str] = set()
                    for path, operations in paths.items():
                        if isinstance(operations, dict):
                            available_methods.update(
                                m.upper()
                                for m in operations.keys()
                                if m != "description"
                            )
                    raise ValueError(
                        f"Method {method} not supported for {url}. "
                        f"Available methods: {', '.join(sorted(available_methods))}"
                    )
            elif not open_world:
                # In closed-world mode, we require the URL to match a known resource
                raise ValueError(f"URL '{url}' does not match any known resource")
            else:
                logger.warning(
                    f"No resource found for {url}, proceeding with direct request in open-world mode"
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

    async def _execute_options_method(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        open_world: bool = False,
    ) -> ToolResult:
        """Execute OPTIONS request with special handling for schema discovery.

        Priority:
        1. If OPTIONS method is defined in schema, execute it
        2. If exact resource match, return OpenAPI schema
        3. If prefix match, return list of matching routes
        4. If open-world mode, execute OPTIONS directly
        5. Otherwise, raise error
        """
        # Check if resource exists and get its schema
        schema = await self._read_resource_schema(url)

        if schema:
            # Check if OPTIONS method is explicitly defined
            if self._is_method_supported("OPTIONS", schema):
                logger.debug(f"OPTIONS method defined for {url}, executing request")
                return await self._execute_rest_method(
                    "OPTIONS", url, params=params, open_world=open_world
                )

            # No OPTIONS method defined, return the schema for exact match
            logger.debug(f"Returning OpenAPI schema for {url}")
            return ToolResult(structured_content=schema)

        # No exact match, try prefix matching
        matching_routes = self._find_matching_routes(url)

        if matching_routes:
            logger.debug(f"Found {len(matching_routes)} routes matching prefix: {url}")
            return self._create_prefix_match_result(matching_routes, url)

        # Handle open-world mode
        if open_world:
            logger.warning(
                f"No resource found for {url}, attempting direct OPTIONS request in open-world mode"
            )
            return await self._execute_rest_method(
                "OPTIONS", url, params=params, open_world=True
            )

        # No matches found in closed-world mode
        raise ValueError(f"No resources found matching URL: {url}")

    def _create_prefix_match_result(
        self, matching_routes: list[dict[str, Any]], url: str
    ) -> ToolResult:
        """Create a structured result for prefix matching."""
        return ToolResult(
            structured_content={
                "matching_routes": matching_routes,
                "description": f"Routes matching prefix: {url}",
                "count": len(matching_routes),
            }
        )

    def _find_matching_routes(self, url_prefix: str) -> list[dict[str, Any]]:
        """Find all routes that match the given URL prefix.

        Returns routes sorted by URL length (most specific first).
        """
        matching = []

        # Find matching resources using PathMatcher
        resource_paths = PathMatcher.find_matching_paths(
            self._resource_manager._resources, url_prefix
        )
        for resource_url in resource_paths:
            resource = self._resource_manager._resources[resource_url]
            # WebResource has _routes attribute
            if hasattr(resource, "_routes"):
                methods = [route.method for route in resource._routes]
                matching.append(
                    PathMatcher.create_route_info(resource_url, methods, "resource")
                )

        # Find matching templates using PathMatcher
        template_paths = PathMatcher.find_matching_paths(
            self._resource_manager._templates, url_prefix
        )
        for template_url in template_paths:
            template = self._resource_manager._templates[template_url]
            # WebResourceTemplate has _routes attribute
            if hasattr(template, "_routes"):
                methods = [route.method for route in template._routes]
                matching.append(
                    PathMatcher.create_route_info(template_url, methods, "template")
                )

        # Sort by breadth-first lexicographical order
        # First by depth (number of path segments), then lexicographically
        def sort_key(route_info: dict[str, Any]) -> tuple[int, str]:
            url = route_info["url"]
            # Remove the base URL to get just the path
            path = url.replace(self.base_url, "")
            # Count the depth (number of segments)
            depth = path.count("/")
            # Return tuple for sorting: (depth, url)
            return (depth, url)

        matching.sort(key=sort_key)

        return matching

    @property
    def base_url(self) -> str:
        """Get the base URL from the HTTP client."""
        return str(self._client.base_url)


# Export public symbols
__all__ = ["McpWebGateway"]
