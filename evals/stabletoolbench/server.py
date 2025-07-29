"""
Modified RapidAPI Server with REST Endpoints for MCP Web Gateway Integration

This server extends BuildYourOwnRapidAPIServer to expose individual REST endpoints
for each tool/API combination, making it compatible with MCP Web Gateway.
"""

import glob
import json
import os
from typing import Any, Dict

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Import from the copied RapidAPI server
from toolbench_main import (
    Info,
    get_fake_rapidapi_response,
    get_rapidapi_response,
    prepare_tool_name_and_url,
)
from utils import change_name, standardize

# Configuration
USE_FAKE_RESPONSES = True  # Always use fake responses for testing

from slowapi import Limiter, _rate_limit_exceeded_handler

# Import rate limiting
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

app = FastAPI(title="ToolBench REST API Server", version="1.0.0")

# Configure rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Load API keys
user_keys = []
rapidapi_keys = []
if os.path.exists("./user_keys.txt"):
    user_keys = [line.strip() for line in open("./user_keys.txt", "r")]
if os.path.exists("./rapidapi_keys.txt"):
    rapidapi_keys = [line.strip() for line in open("./rapidapi_keys.txt", "r")]


def load_tool_definitions(toolenv_path: str) -> Dict[str, Any]:
    """Load all tool definitions from toolenv directory"""
    tools = {}
    tools_dir = os.path.join(toolenv_path, "tools")

    if not os.path.exists(tools_dir):
        return tools

    for category in os.listdir(tools_dir):
        category_path = os.path.join(tools_dir, category)
        if not os.path.isdir(category_path):
            continue

        tools[category] = {}

        # Find all JSON files in this category
        for json_file in glob.glob(os.path.join(category_path, "*.json")):
            with open(json_file, "r") as f:
                tool_data = json.load(f)
                tool_name = standardize(tool_data["tool_name"])
                tools[category][tool_name] = tool_data

    return tools


def create_rest_endpoint(category: str, tool_name: str, api: dict, tool_data: dict):
    """Create a REST endpoint function for a specific API"""

    # Standardize names
    api_name = change_name(standardize(api["name"]))
    method = api.get("method", "GET").upper()

    async def endpoint(request: Request):
        """Dynamic endpoint handler"""
        # Get API key from header
        toolbench_key = request.headers.get("X-API-Key", "")

        # Check authorization
        if toolbench_key not in user_keys:
            return JSONResponse(
                status_code=401,
                content={
                    "error": "Unauthorized",
                    "message": "Invalid API key. Please provide a valid X-API-Key header.",
                },
            )

        # Prepare tool input based on method
        if method in ["GET", "DELETE"]:
            # Query parameters for GET/DELETE
            tool_input = dict(request.query_params)
        else:
            # Body for POST/PUT/PATCH
            try:
                body = await request.json()
                tool_input = body if isinstance(body, dict) else {}
            except:
                tool_input = {}

        # Handle path parameters if any
        if hasattr(request, "path_params"):
            tool_input.update(request.path_params)

        # Create Info object for RapidAPI
        info = Info(
            category=category,
            tool_name=tool_data["tool_name"],  # Use original tool name
            api_name=api["name"],  # Use original API name
            tool_input=json.dumps(tool_input) if tool_input else "{}",
            strip="filter",
            toolbench_key=toolbench_key,
        )

        # Call the appropriate handler based on configuration
        if USE_FAKE_RESPONSES:
            result = get_fake_rapidapi_response(request, info)
        else:
            result = get_rapidapi_response(request, info)

        # Convert response
        if isinstance(result, dict):
            if result.get("error"):
                return JSONResponse(
                    status_code=500,
                    content={
                        "error": result["error"],
                        "message": result.get("response", ""),
                    },
                )
            else:
                return JSONResponse(content=result.get("response", {}))

        return result

    # Set function metadata for FastAPI
    endpoint.__name__ = f"{tool_name}_{api_name}"
    endpoint.__doc__ = api.get(
        "description", f"Execute {api['name']} from {tool_data['tool_name']}"
    )

    return endpoint


def generate_openapi_for_tool(tool_data: dict, api: dict, category: str) -> dict:
    """Generate OpenAPI operation for a tool API"""
    parameters = []

    # Add required parameters
    for param in api.get("required_parameters", []):
        parameters.append(
            {
                "name": param.get("name", ""),
                "in": (
                    "query"
                    if api.get("method", "GET").upper() in ["GET", "DELETE"]
                    else "formData"
                ),
                "required": True,
                "schema": {"type": param.get("type", "string").lower()},
                "description": param.get("description", ""),
            }
        )

    # Add optional parameters
    for param in api.get("optional_parameters", []):
        parameters.append(
            {
                "name": param.get("name", ""),
                "in": (
                    "query"
                    if api.get("method", "GET").upper() in ["GET", "DELETE"]
                    else "formData"
                ),
                "required": False,
                "schema": {
                    "type": param.get("type", "string").lower(),
                    "default": param.get("default", ""),
                },
                "description": param.get("description", ""),
            }
        )

    return {
        "summary": api.get("name", ""),
        "description": api.get("description", tool_data.get("tool_description", "")),
        "operationId": f"{standardize(tool_data['tool_name'])}_{change_name(standardize(api['name']))}",
        "parameters": parameters,
        "security": [{"ApiKeyAuth": []}],
        "responses": {
            "200": {
                "description": "Successful response",
                "content": {"application/json": {"schema": {"type": "object"}}},
            },
            "401": {"description": "Unauthorized - Invalid API key"},
            "500": {"description": "Server error"},
        },
        "tags": [category, tool_data.get("tool_name", "")],
    }


def setup_routes(toolenv_path: str):
    """Dynamically create routes for all tools"""
    tools = load_tool_definitions(toolenv_path)
    route_count = 0

    for category, category_tools in tools.items():
        for tool_name, tool_data in category_tools.items():
            for api in tool_data.get("api_list", []):
                # Create endpoint path
                api_name = change_name(standardize(api["name"]))
                path = f"/{category.lower()}/{tool_name}/{api_name}"

                # Get HTTP method
                method = api.get("method", "GET").upper()

                # Create endpoint function
                endpoint = create_rest_endpoint(category, tool_name, api, tool_data)

                # Add route to FastAPI
                if method == "GET":
                    app.get(path)(endpoint)
                elif method == "POST":
                    app.post(path)(endpoint)
                elif method == "PUT":
                    app.put(path)(endpoint)
                elif method == "DELETE":
                    app.delete(path)(endpoint)
                elif method == "PATCH":
                    app.patch(path)(endpoint)
                else:
                    # Default to POST for unknown methods
                    app.post(path)(endpoint)

                route_count += 1

    print(f"Created {route_count} REST endpoints from {len(tools)} categories")
    return tools


# Keep the original /rapidapi endpoint for backward compatibility
@app.post("/rapidapi")
@limiter.limit("999999/minute")
async def rapidapi_endpoint(request: Request, info: Info):
    """Original RapidAPI endpoint for backward compatibility"""
    return get_rapidapi_response(request, info)


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "ToolBench REST API Server"}


# OpenAPI customization
@app.get("/openapi.json")
async def get_openapi():
    """Get OpenAPI specification"""
    from fastapi.openapi.utils import get_openapi

    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title="ToolBench REST API Server",
        version="1.0.0",
        description="REST API server for ToolBench tools, compatible with MCP Web Gateway",
        routes=app.routes,
    )

    # Add security scheme
    openapi_schema["components"]["securitySchemes"] = {
        "ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"}
    }

    app.openapi_schema = openapi_schema
    return app.openapi_schema


def create_app(toolenv_path: str = None) -> FastAPI:
    """Create and configure the FastAPI app"""
    if toolenv_path is None:
        # Try multiple possible locations
        possible_paths = [
            "./toolenv",
            "./minimal_toolenv",
            "../../ToolBench/minimal_toolenv",
            "../../ToolBench/data/toolenv",
            "./data/toolenv",
        ]

        for path in possible_paths:
            if os.path.exists(os.path.join(path, "tools")):
                toolenv_path = path
                break

        if toolenv_path is None:
            print("Warning: Could not find toolenv directory. Starting with no tools.")
            return app

    print(f"Loading tools from: {toolenv_path}")
    setup_routes(toolenv_path)
    return app


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ToolBench REST API Server")
    parser.add_argument("--toolenv", type=str, help="Path to toolenv directory")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind to")

    args = parser.parse_args()

    # Create app with specified toolenv path
    app = create_app(args.toolenv)

    # Run server
    uvicorn.run(app, host=args.host, port=args.port)
