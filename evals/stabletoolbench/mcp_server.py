#!/usr/bin/env python
"""
MCP server for StableToolBench REST API with multiple approach options.

Run with:
  fastmcp run -t http evals/stabletoolbench/mcp_server.py                                # Default: Web Gateway approach
  fastmcp run -t http evals/stabletoolbench/mcp_server.py -- --strategy=all-tools       # All operations as tools
  fastmcp run -t http evals/stabletoolbench/mcp_server.py -- --strategy=spec-recommend  # MCP spec recommendation
"""

import argparse
import sys
from typing import Any

import httpx
from fastmcp.experimental.server.openapi import FastMCPOpenAPI, MCPType, RouteMap

from mcp_web_gateway import McpWebGateway


# Parse arguments - deferred to avoid issues with fastmcp import
def get_strategy() -> str:
    """Parse command line arguments and return strategy."""
    parser = argparse.ArgumentParser(
        description="MCP server for StableToolBench",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Strategies:
  web-gateway      Web Gateway approach - exposes HTTP routes as resources with 
                   their original URIs and provides generic REST tools (GET, POST,
                   PUT, PATCH, DELETE). Resources return OpenAPI schema when read.

  all-tools        All Tools approach - converts every OpenAPI operation into
                   an individual MCP tool. Each HTTP method + path combination
                   becomes a separate tool.

  spec-recommend   MCP Spec Recommendation - follows the official MCP spec
                   guidelines: GET requests become resources (or resource templates
                   if they have path parameters), while POST/PUT/PATCH/DELETE
                   become tools.
        """,
    )
    parser.add_argument(
        "--strategy",
        choices=["web-gateway", "all-tools", "spec-recommend"],
        default="web-gateway",
        help="Strategy for exposing APIs (default: web-gateway)",
    )

    # Only parse if we have meaningful arguments
    if len(sys.argv) > 1 and sys.argv[0].endswith("mcp_server.py"):
        args = parser.parse_args()
        return str(args.strategy)
    else:
        # Default when imported by fastmcp
        return "web-gateway"


# Get strategy (deferred parsing)
strategy = get_strategy()


def load_openapi_spec(
    url: str = "http://localhost:8080/openapi.json",
) -> dict[str, Any]:
    """Load OpenAPI specification from the server."""
    response = httpx.get(url)
    result = response.json()
    return dict(result)


def create_all_tools_server(
    openapi_spec: dict[str, Any], client: httpx.AsyncClient
) -> FastMCPOpenAPI:
    """Create MCP server that converts all operations to tools."""
    route_mappings = [
        RouteMap(mcp_type=MCPType.TOOL),
    ]
    return FastMCPOpenAPI(
        openapi_spec=openapi_spec,
        client=client,
        name="stabletoolbench-all-tools",
        route_maps=route_mappings,
    )


def create_spec_recommend_server(
    openapi_spec: dict[str, Any], client: httpx.AsyncClient
) -> FastMCPOpenAPI:
    """Create MCP server following spec recommendations."""
    route_mappings = [
        # GET with path parameters -> ResourceTemplate
        RouteMap(
            methods=["GET"],
            pattern=r".*\{.*\}.*",  # Contains path parameters
            mcp_type=MCPType.RESOURCE_TEMPLATE,
        ),
        # GET without path parameters -> Resource
        RouteMap(methods=["GET"], mcp_type=MCPType.RESOURCE),
        # Everything else -> Tool
        RouteMap(mcp_type=MCPType.TOOL),
    ]
    return FastMCPOpenAPI(
        openapi_spec=openapi_spec,
        client=client,
        name="stabletoolbench-spec-recommend",
        route_maps=route_mappings,
    )


def create_web_gateway_server(
    openapi_spec: dict[str, Any], client: httpx.AsyncClient
) -> McpWebGateway:
    """Create MCP Web Gateway server with resources and REST tools."""
    return McpWebGateway(
        openapi_spec=openapi_spec,
        client=client,
        name="stabletoolbench-web-gateway",
        # add_rest_tools defaults to True
    )


# Load OpenAPI spec and create client
openapi_spec = load_openapi_spec()
# Add a fake API key header that ToolBench APIs expect
client = httpx.AsyncClient(
    base_url="http://localhost:8080", headers={"X-API-Key": "test_key"}
)

# Create appropriate MCP server based on strategy
if strategy == "all-tools":
    mcp = create_all_tools_server(openapi_spec, client)
elif strategy == "spec-recommend":
    mcp = create_spec_recommend_server(openapi_spec, client)
else:
    mcp = create_web_gateway_server(openapi_spec, client)
