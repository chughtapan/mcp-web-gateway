"""Web Gateway routing configuration.

This module defines routing rules that map all OpenAPI operations to resources
or resource templates, never to tools.
"""

from fastmcp.experimental.server.openapi.routing import MCPType, RouteMap

# Web Gateway approach: All routes become resources or resource templates
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

__all__ = ["WEB_GATEWAY_ROUTE_MAPPINGS"]
