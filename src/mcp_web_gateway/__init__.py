"""MCP Web Gateway - A gateway for web resources to be exposed to MCP agents."""

from .openapi_handler import OpenAPIHandler
from .server import McpWebGateway

__all__ = ["McpWebGateway", "OpenAPIHandler"]
