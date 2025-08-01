"""
Modified RapidAPI Server with REST Endpoints for MCP Web Gateway Integration

This server extends BuildYourOwnRapidAPIServer to expose individual REST endpoints
for each tool/API combination, making it compatible with MCP Web Gateway.
"""

import glob
import json
import keyword
import os
import re
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import create_model
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# Import from the copied RapidAPI server
from toolbench_main import Info, get_fake_rapidapi_response, get_rapidapi_response
from utils import change_name, standardize

# Configuration
USE_FAKE_RESPONSES = True  # Always use fake responses for testing

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


def get_python_type(param_type: str, is_query_param: bool = False):
    """Convert parameter type string to Python type.

    Args:
        param_type: The parameter type from the API definition (e.g., "string", "integer")
        is_query_param: True if this is a query parameter (affects object handling)

    Returns:
        Tuple of (Python type object, type name as string for code generation)
    """
    # Map API parameter types to Python types
    # First element is the actual type, second is the string representation for code generation
    type_mapping = {
        "string": (str, "str"),
        "integer": (int, "int"),
        "number": (float, "float"),
        "boolean": (bool, "bool"),
        "array": (List[Any], "List[Any]"),
        "object": (Dict[str, Any], "Dict[str, Any]"),
    }

    # Handle uppercase types (some APIs use "String" instead of "string")
    param_type_lower = param_type.lower() if param_type else "string"

    # Special handling for query parameters:
    # Objects in query strings must be serialized (e.g., as JSON strings)
    if is_query_param and param_type_lower == "object":
        return (str, "str")

    # Default to string for unknown types (safer than failing)
    return type_mapping.get(param_type_lower, (str, "str"))


def create_endpoint_handler(category: str, tool_name: str, api: dict, tool_data: dict):
    """Create the core handler logic that processes requests"""

    async def handler(request: Request, tool_input: dict):
        """Core endpoint handler logic"""
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

    return handler


def create_rest_endpoint(category: str, tool_name: str, api: dict, tool_data: dict):
    """Create a REST endpoint function for a specific API"""

    # Standardize names
    api_name = change_name(standardize(api["name"]))
    method = api.get("method", "GET").upper()

    # Get the core handler
    handler = create_endpoint_handler(category, tool_name, api, tool_data)

    if method in ["GET", "DELETE"]:
        # For GET/DELETE, create endpoint with query parameters
        return create_get_delete_endpoint(handler, api, tool_name, api_name)
    else:
        # For POST/PUT/PATCH, create endpoint with body
        return create_post_put_patch_endpoint(handler, api, tool_name, api_name)


def sanitize_param_name(name: str) -> str:
    """Convert parameter name to valid Python identifier.

    This is necessary because API parameter names might:
    - Contain hyphens, dots, or other special characters (e.g., "user-id", "api.key")
    - Start with numbers (e.g., "3rd_party_id")
    - Be Python reserved keywords (e.g., "class", "return")
    - Conflict with FastAPI's special parameters

    Args:
        name: The original parameter name from the API

    Returns:
        A valid Python identifier that can be used as a function parameter
    """
    # Step 1: Replace all non-alphanumeric characters with underscores
    # "user-id" → "user_id", "api.key" → "api_key"
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", name)

    # Step 2: Remove consecutive underscores for cleanliness
    # "user__id" → "user_id"
    sanitized = re.sub(r"_+", "_", sanitized)

    # Step 3: Remove leading/trailing underscores
    # "_user_id_" → "user_id"
    sanitized = sanitized.strip("_")

    # Step 4: Ensure it starts with a letter or underscore (Python requirement)
    # "3rd_party" → "param_3rd_party"
    if sanitized and sanitized[0].isdigit():
        sanitized = f"param_{sanitized}"

    # Step 5: Handle empty result (e.g., if original was just special chars like "***")
    if not sanitized:
        sanitized = "param"

    # Step 6: Handle Python reserved keywords
    # "class" → "class_param", "return" → "return_param"
    if keyword.iskeyword(sanitized):
        sanitized = f"{sanitized}_param"

    # Step 7: Handle special FastAPI parameter names that would conflict
    # "request" → "request_param" (since FastAPI injects Request object)
    if sanitized in ["request", "response", "background_tasks", "dependencies"]:
        sanitized = f"{sanitized}_param"

    return sanitized


def create_get_delete_endpoint(handler, api: dict, tool_name: str, api_name: str):
    """Create GET/DELETE endpoint with query parameters.

    For GET/DELETE requests, parameters come from the URL query string.
    FastAPI needs to see these as function parameters to:
    - Validate them
    - Convert types (e.g., "123" → 123 for integers)
    - Generate OpenAPI documentation

    Args:
        handler: The core request handler function
        api: API definition with parameters
        tool_name: Name of the tool (e.g., "RealEstate")
        api_name: Name of the API endpoint (e.g., "searchProperties")
    """

    # Check if we have any parameters
    has_params = bool(api.get("required_parameters") or api.get("optional_parameters"))

    if not has_params:
        # No parameters, create simple endpoint
        async def endpoint(request: Request):
            """Dynamic endpoint handler"""
            return await handler(request, {})

        endpoint.__name__ = f"{tool_name}_{api_name}"
        endpoint.__doc__ = api.get(
            "description", f"Execute {api['name']} from {tool_name}"
        )
        endpoint.__module__ = __name__
        endpoint.__qualname__ = endpoint.__name__
        return endpoint

    # We need to dynamically create a function with the exact parameters the API expects.
    # This is where code generation comes in - we're building Python code as a string
    # that will create a function with the right signature.
    #
    # Example: If the API expects parameters "user-id" (required) and "limit" (optional),
    # we'll generate:
    #   async def endpoint(request: Request,
    #                     user_id: str = Query(..., alias='user-id'),
    #                     limit: Optional[int] = Query(10)):
    #
    # Start building the function signature
    func_code = "async def endpoint(request: Request"

    # Track parameter names to avoid duplicates
    seen_params = set()
    param_mapping = {}  # Map sanitized names to original names

    # Process required parameters first
    for param in api.get("required_parameters", []):
        param_name = param.get("name", "")
        if not param_name:
            continue

        # Convert "user-id" to "user_id" so it's a valid Python parameter name
        sanitized_name = sanitize_param_name(param_name)

        if sanitized_name in seen_params:
            continue  # Skip duplicate parameter names
        seen_params.add(sanitized_name)
        param_mapping[sanitized_name] = param_name  # Remember: user_id → "user-id"

        # Get the Python type for this parameter
        param_type_obj, param_type_name = get_python_type(
            param.get("type", "string"), is_query_param=True
        )

        # Prepare the description for use in generated code
        # We need to escape special characters that would break the Python string
        param_desc = param.get("description", "")
        param_desc = param_desc.replace("\\", "\\\\")  # Escape backslashes first
        param_desc = param_desc.replace('"', '\\"')  # Then escape quotes
        param_desc = param_desc.replace("\n", " ")  # Replace newlines with spaces
        param_desc = param_desc.replace("\r", " ")  # Replace carriage returns

        # The 'alias' tells FastAPI to accept "user-id" in the URL but pass it as user_id
        param_name_escaped = param_name.replace("'", "\\'")
        func_code += f", {sanitized_name}: {param_type_name} = Query(..., alias='{param_name_escaped}', description=\"{param_desc}\")"

    # Process optional parameters (same process but with default values)
    for param in api.get("optional_parameters", []):
        param_name = param.get("name", "")
        if not param_name:
            continue

        # Convert parameter name to valid Python identifier
        sanitized_name = sanitize_param_name(param_name)

        if sanitized_name in seen_params:
            continue  # Skip duplicate parameter names
        seen_params.add(sanitized_name)
        param_mapping[sanitized_name] = param_name

        param_type_obj, param_type_name = get_python_type(
            param.get("type", "string"), is_query_param=True
        )
        param_default = param.get("default", None)

        # Prepare description (same escaping as required params)
        param_desc = param.get("description", "")
        param_desc = param_desc.replace("\\", "\\\\")  # Escape backslashes first
        param_desc = param_desc.replace('"', '\\"')  # Then escape quotes
        param_desc = param_desc.replace("\n", " ")  # Replace newlines with spaces
        param_desc = param_desc.replace("\r", " ")  # Replace carriage returns

        # Escape single quotes in parameter name for the alias
        param_name_escaped = param_name.replace("'", "\\'")

        # Optional parameters use Optional[type] and have a default value
        if param_default is None:
            func_code += f", {sanitized_name}: Optional[{param_type_name}] = Query(None, alias='{param_name_escaped}', description=\"{param_desc}\")"
        else:
            # repr() safely converts the default value to a Python literal
            func_code += f", {sanitized_name}: Optional[{param_type_name}] = Query({repr(param_default)}, alias='{param_name_escaped}', description=\"{param_desc}\")"

    # Complete the function signature and add the body
    func_code += "):\n"
    func_code += "    # Collect all parameters into a dictionary for the handler\n"
    func_code += "    tool_input = {}\n"

    # Generate code to collect parameters using their original names
    # This maps from Python parameter names back to API parameter names
    for sanitized_name, original_name in param_mapping.items():
        func_code += f"    if {sanitized_name} is not None:\n"
        func_code += f"        tool_input['{original_name}'] = {sanitized_name}\n"

    func_code += "    return await handler(request, tool_input)\n"

    # Now we execute the generated code to create the actual function
    # We provide a namespace with all the imports and objects the code needs
    namespace = {
        "Request": Request,
        "Query": Query,
        "Optional": Optional,
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "List": List,
        "Dict": Dict,
        "Any": Any,
        "handler": handler,  # The actual handler that does the work
    }

    # This is where the magic happens - exec() runs our generated code
    # and creates the function with the exact signature we built
    exec(func_code, namespace)
    endpoint = namespace["endpoint"]  # Get the function we just created

    # Set metadata
    endpoint.__name__ = f"{tool_name}_{api_name}"
    endpoint.__doc__ = api.get("description", f"Execute {api['name']} from {tool_name}")
    endpoint.__module__ = __name__
    endpoint.__qualname__ = endpoint.__name__
    endpoint.__module__ = __name__
    endpoint.__qualname__ = endpoint.__name__

    return endpoint


def create_post_put_patch_endpoint(handler, api: dict, tool_name: str, api_name: str):
    """Create POST/PUT/PATCH endpoint with request body.

    For POST/PUT/PATCH requests, parameters come in the request body as JSON.
    We create a Pydantic model to:
    - Validate the JSON structure
    - Convert types automatically
    - Generate OpenAPI documentation

    Args:
        handler: The core request handler function
        api: API definition with parameters
        tool_name: Name of the tool
        api_name: Name of the API endpoint
    """

    # Check if we have parameters to create a body model
    has_params = bool(api.get("required_parameters") or api.get("optional_parameters"))

    if has_params:
        # We'll build a Pydantic model dynamically based on the API parameters
        # This model will validate incoming JSON bodies
        model_fields = {}
        seen_params = set()

        # Process required fields
        for param in api.get("required_parameters", []):
            param_name = param.get("name", "")
            if not param_name or param_name in seen_params:
                continue  # Skip empty or duplicate parameter names
            seen_params.add(param_name)

            param_type_obj, param_type_name = get_python_type(
                param.get("type", "string"), is_query_param=False
            )
            # The ... means "required field" in Pydantic
            model_fields[param_name] = (param_type_obj, ...)

        # Process optional fields
        for param in api.get("optional_parameters", []):
            param_name = param.get("name", "")
            if not param_name or param_name in seen_params:
                continue  # Skip empty or duplicate parameter names
            seen_params.add(param_name)

            param_type_obj, param_type_name = get_python_type(
                param.get("type", "string"), is_query_param=False
            )
            param_default = param.get("default", None)
            # Optional fields have Optional[type] and a default value
            model_fields[param_name] = (Optional[param_type_obj], param_default)

        # Create a Pydantic model class dynamically
        # This is like doing: class Request(BaseModel): name: str, age: Optional[int] = None
        RequestModel = create_model(f"{tool_name}_{api_name}_Request", **model_fields)

        # Create endpoint that uses the Pydantic model for validation
        async def endpoint(request: Request, body: RequestModel):
            """Dynamic endpoint handler with body"""
            # Pydantic model's dict() method gives us the validated data
            tool_input = body.dict()
            return await handler(request, tool_input)

    else:
        # No parameters defined - accept any JSON body
        # This is more flexible but provides no validation
        async def endpoint(request: Request):
            """Dynamic endpoint handler"""
            try:
                body = await request.json()
                tool_input = body if isinstance(body, dict) else {}
            except Exception:
                tool_input = {}
            return await handler(request, tool_input)

    # Set metadata
    endpoint.__name__ = f"{tool_name}_{api_name}"
    endpoint.__doc__ = api.get("description", f"Execute {api['name']} from {tool_name}")
    endpoint.__module__ = __name__
    endpoint.__qualname__ = endpoint.__name__

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
                try:
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
                except Exception as e:
                    print(f"WARNING: Skipping route {path} ({method}):")
                    print(f"  Tool: {tool_data.get('tool_name', 'unknown')}")
                    print(f"  API: {api.get('name', 'unknown')}")
                    print(f"  Error: {type(e).__name__}: {e}")
                    # Skip this route and continue with others
                    continue

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
