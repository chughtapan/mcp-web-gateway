"""HTTP resource management for MCP Web Gateway.

This module handles HTTP resource management, including:
- Creating resources/templates from OpenAPI specifications
- Executing HTTP methods on those resources
- Managing the lifecycle of HTTP-based MCP resources
"""

import json
import re
from typing import TYPE_CHECKING, Any, Pattern

import httpx
from fastmcp.experimental.server.openapi.routing import MCPType, RouteMap
from fastmcp.resources import ResourceManager
from fastmcp.utilities.logging import get_logger

from .components import HttpResource, HttpResourceTemplate

if TYPE_CHECKING:
    from .openapi_handler import OpenAPIHandler

logger = get_logger(__name__)

# Default route mappings for web gateway
WEB_GATEWAY_ROUTE_MAPPINGS = [
    # Routes with path parameters become resource templates
    RouteMap(
        methods="*",  # Any HTTP method
        pattern=r".*\{[^}]+\}.*",  # Contains {param} style parameters
        mcp_type=MCPType.RESOURCE_TEMPLATE,
    ),
    # All other routes become resources
    RouteMap(
        methods="*",  # Any HTTP method
        mcp_type=MCPType.RESOURCE,
    ),
]


class HttpResourceManager(ResourceManager):
    """Manages HTTP/OpenAPI resources and handles HTTP method execution."""

    def __init__(
        self,
        openapi_handler: "OpenAPIHandler",
        base_url: str,
        client: httpx.AsyncClient,
        route_maps: list[RouteMap] | None = None,
        open_world: bool = False,
        **kwargs: Any,
    ):
        """Initialize the HTTP resource manager.

        Args:
            openapi_handler: Handler for OpenAPI operations
            base_url: Base URL for building full URIs
            client: HTTP client for making requests
            route_maps: Custom route mapping rules (defaults to WEB_GATEWAY_ROUTE_MAPPINGS)
            open_world: Allow operations on any URL, not just defined resources
            **kwargs: Additional arguments passed to ResourceManager
        """
        super().__init__(**kwargs)
        self._openapi_handler = openapi_handler
        self._base_url = base_url
        self._client = client
        self._route_maps = route_maps or WEB_GATEWAY_ROUTE_MAPPINGS
        self._open_world = open_world
        self._validate_route_maps()

    def _validate_route_maps(self) -> None:
        """Ensure all route maps only create resources or resource templates."""
        for route_map in self._route_maps:
            if route_map.mcp_type not in (MCPType.RESOURCE, MCPType.RESOURCE_TEMPLATE):
                raise ValueError(
                    f"McpWebGateway only supports RESOURCE and RESOURCE_TEMPLATE types, "
                    f"got {route_map.mcp_type} in route map"
                )

    def _classify_path(self, path: str) -> MCPType:
        """Classify a path as either a resource or resource template.

        Args:
            path: The path to classify

        Returns:
            MCPType (RESOURCE or RESOURCE_TEMPLATE)
        """
        # Get methods and tags from openapi handler
        methods, tags = self._openapi_handler.get_path_info(path)
        for route_map in self._route_maps:
            # Check method match
            if route_map.methods != "*":
                if not any(m in route_map.methods for m in methods):
                    continue

            # Check pattern match
            if isinstance(route_map.pattern, str):
                pattern: Pattern[str] = re.compile(route_map.pattern)
            else:
                pattern = route_map.pattern

            if not pattern.match(path):
                continue

            # Check tags match
            if route_map.tags and not route_map.tags.issubset(tags):
                continue

            # This route map matches!
            return route_map.mcp_type

        # Default to RESOURCE if no match
        return MCPType.RESOURCE

    def _has_path_parameters(self, path: str) -> bool:
        """Check if a path contains parameters.

        Args:
            path: Path to check

        Returns:
            True if path contains {param} placeholders
        """
        return "{" in path and "}" in path

    def _extract_path_parameters(self, path: str) -> dict[str, Any]:
        """Extract path parameter schema for template paths.

        Args:
            path: Path string potentially containing {param} placeholders

        Returns:
            JSON Schema for path parameters
        """
        # Extract parameter names from path
        param_names = re.findall(r"\{(\w+)\}", path)

        if not param_names:
            return {}

        # Build parameter schema
        return {
            "type": "object",
            "properties": {param: {"type": "string"} for param in param_names},
            "required": param_names,
        }

    def _create_http_resource(self, path: str) -> HttpResource:
        """Create an HttpResource instance for the given path.

        Args:
            path: OpenAPI path

        Returns:
            HttpResource instance
        """
        # Get methods and tags from openapi handler
        methods, tags = self._openapi_handler.get_path_info(path)

        # Build full URI
        uri = self._openapi_handler.build_full_uri(self._base_url, path)

        return HttpResource(
            uri=uri,
            path=path,
            methods=methods,
            name=f"resource_{path.replace('/', '_')}",
            description=f"Resource for {path}",
            tags=tags,
            openapi_handler=self._openapi_handler,
        )

    def _create_http_template(self, path: str) -> HttpResourceTemplate:
        """Create an HttpResourceTemplate instance for the given path.

        Args:
            path: OpenAPI path template

        Returns:
            HttpResourceTemplate instance
        """
        # Get methods and tags from openapi handler
        methods, tags = self._openapi_handler.get_path_info(path)

        # Build full URI template
        uri_template = self._openapi_handler.build_full_uri(self._base_url, path)

        # Extract path parameters
        params = self._extract_path_parameters(path)

        return HttpResourceTemplate(
            uri_template=uri_template,
            path=path,
            methods=methods,
            name=f"template_{path.replace('/', '_').replace('{', '').replace('}', '')}",
            description=f"Resource template for {path}",
            parameters=params,
            tags=tags,
            openapi_handler=self._openapi_handler,
        )

    @classmethod
    def from_openapi(
        cls,
        openapi_handler: "OpenAPIHandler",
        base_url: str,
        client: httpx.AsyncClient,
        route_maps: list[RouteMap] | None = None,
        open_world: bool = False,
        **kwargs: Any,
    ) -> "HttpResourceManager":
        """Create HttpResourceManager and populate resources from OpenAPI specification.

        Args:
            openapi_handler: Handler for OpenAPI operations
            base_url: Base URL for building full URIs
            client: HTTP client for making requests
            route_maps: Custom route mapping rules (defaults to WEB_GATEWAY_ROUTE_MAPPINGS)
            open_world: Allow operations on any URL, not just defined resources
            **kwargs: Additional arguments passed to ResourceManager

        Returns:
            HttpResourceManager instance
        """
        # Create manager instance with handler, base URL, and client
        manager = cls(
            openapi_handler, base_url, client, route_maps, open_world, **kwargs
        )

        # Populate resources
        manager._create_resources()

        return manager

    def _create_resources(self) -> None:
        """Create all resources and templates from OpenAPI specification."""
        for path in self._openapi_handler.iter_paths():
            # Classify the path
            mcp_type = self._classify_path(path)

            # Create appropriate component
            if mcp_type == MCPType.RESOURCE_TEMPLATE:
                template = self._create_http_template(path)
                self.add_template(template)

            elif mcp_type == MCPType.RESOURCE:
                resource = self._create_http_resource(path)
                self.add_resource(resource)

    async def execute_http_method(
        self,
        method: str,
        url: str,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute an HTTP request for the specified URL.

        Special handling for OPTIONS:
        - If OPTIONS is explicitly defined in OpenAPI spec, executes it normally
        - Otherwise returns OpenAPI schema for exact matches
        - For prefix matches, returns list of matching routes
        - For no matches, returns error with available resources

        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE, OPTIONS)
            url: URL to request
            body: Request body for POST/PUT/PATCH
            params: Query parameters

        Returns:
            Response data as a dictionary

        Raises:
            ValueError: If URL doesn't match known resources or method not supported
        """
        # Handle OPTIONS method specially
        if method.upper() == "OPTIONS":
            return await self._handle_options_method(url, params)

        return await self._execute_standard_http_method(method, url, body, params)

    async def _execute_standard_http_method(
        self,
        method: str,
        url: str,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a standard HTTP request without special handling."""
        # Validate method unless in open world mode
        if not self._open_world:
            # Extract path from URL
            url_path = self._openapi_handler.extract_path_from_url(url, self._base_url)

            # Find matching OpenAPI path
            matches = self._openapi_handler.find_matching_paths(url_path)
            if not matches:
                raise ValueError(f"URL '{url}' does not match any known resource")

            openapi_path, path_params = matches[0]

            # Check if method is supported
            methods, _ = self._openapi_handler.get_path_info(openapi_path)
            if method.upper() not in methods:
                raise ValueError(
                    f"Method {method} not supported for {url}. "
                    f"Available methods: {', '.join(sorted(methods))}"
                )

        # Build and execute request
        request_args: dict[str, Any] = {
            "method": method,
            "url": url,
        }
        if params:
            request_args["params"] = params
        if body and method in ["POST", "PUT", "PATCH"]:
            request_args["json"] = body

        try:
            response = await self._client.request(**request_args)
            response.raise_for_status()

            # Handle response
            try:
                result = response.json()
                if isinstance(result, dict):
                    return result
                else:
                    return {"result": result}
            except json.JSONDecodeError:
                # For empty responses (like 204 No Content), return empty dict
                if not response.text:
                    return {}
                # For non-JSON text responses, wrap in content
                return {"content": response.text}

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

    async def _handle_options_method(
        self,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Handle OPTIONS request with special behavior.

        First tries to execute OPTIONS as a regular HTTP method.
        If OPTIONS is not explicitly defined in the OpenAPI spec, provides fallback behavior:
        - For exact matches: returns the OpenAPI schema for the path
        - For prefix matches: returns list of matching routes
        - For no matches: returns error with available resources

        Args:
            url: URL to request
            params: Query parameters

        Returns:
            Response data or OpenAPI schema for the path
        """
        # In open world mode, just execute the OPTIONS request
        if self._open_world:
            try:
                return await self._execute_standard_http_method(
                    "OPTIONS", url, params=params
                )
            except ValueError as e:
                # If it fails due to method not being supported, continue to fallback logic
                if "Method OPTIONS not supported" not in str(e):
                    raise

        # Extract path from URL for fallback handling
        url_path = self._openapi_handler.extract_path_from_url(url, self._base_url)

        # Find matching OpenAPI path
        matches = self._openapi_handler.find_matching_paths(url_path)

        if matches:
            openapi_path, path_params = matches[0]
            methods, _ = self._openapi_handler.get_path_info(openapi_path)

            # Check if OPTIONS is explicitly defined
            if "OPTIONS" in methods:
                # Execute it like any other HTTP method
                return await self._execute_standard_http_method(
                    "OPTIONS", url, params=params
                )
            else:
                # Fallback: Return the schema for this path
                schema = self._openapi_handler.get_operation_schema(
                    openapi_path, methods
                )
                return schema

        # Try prefix matching for discovery
        prefix_matches = self._openapi_handler.find_matching_paths(
            url_path, prefix_match=True
        )
        if prefix_matches:
            # Convert to the expected format
            matching_routes = []
            for spec_path, _ in prefix_matches:
                methods, _ = self._openapi_handler.get_path_info(spec_path)
                full_url = self._openapi_handler.build_full_uri(
                    self._base_url, spec_path
                )
                matching_routes.append(
                    {
                        "url": full_url,
                        "methods": methods,
                        "type": (
                            "template"
                            if self._has_path_parameters(spec_path)
                            else "resource"
                        ),
                    }
                )

            return {
                "matching_routes": matching_routes,
                "description": f"Routes matching prefix: Found {len(matching_routes)} routes starting with {url_path}",
            }

        # No matches found
        return {
            "error": f"No resources found for {url}",
            "available_resources": list(self._openapi_handler.paths.keys())[:10],
        }


__all__ = ["HttpResourceManager", "WEB_GATEWAY_ROUTE_MAPPINGS"]
