# MCP Web Gateway
         
The MCP Web Gateway enables AI Agents to connect Web Services by accessing API directly.

- **All HTTP endpoints** are exposed as MCP resources with their original HTTP URLs
- **Generic REST tools** (GET, POST, PUT, PATCH, DELETE) are provided for executing requests
- **Resources are readable** - they return OpenAPI schema showing all available HTTP methods
- **One resource per path** - all HTTP methods for a path are grouped into a single resource

This design changes the abstraction for the developers: instead of writing MCP servers, they write Web APIs using familiar REST semantics.

## How It Works

1. **Resource Discovery**: Each unique API path becomes a resource with a plain HTTP URL
   - `/users` → `https://api.example.com/users` (supports GET, POST)
   - `/users/{id}` → `https://api.example.com/users/{id}` (supports GET, PUT, DELETE)

2. **Schema Inspection**: Resources can be read to discover available operations
   ```python
   schema = await client.read_resource("https://api.example.com/users")
   # Returns OpenAPI schema showing which HTTP methods are available
   ```

3. **Request Execution**: Use generic REST tools to execute requests
   ```python
   # The tool validates that the method is supported before executing
   result = await client.call_tool("GET", {"url": "https://api.example.com/users"})
   ``` 

## Installation

```bash
# Basic installation
pip install mcp-web-gateway

# With agent support for running autonomous agents
pip install mcp-web-gateway[agent]

# With development dependencies
pip install mcp-web-gateway[dev]
```

## Quick Start

### 1. Direct FastAPI Integration

```python
from fastapi import FastAPI
from mcp_web_gateway import McpWebGateway

# Your existing FastAPI app
app = FastAPI()

@app.get("/users")
async def list_users():
    return [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]

@app.post("/users")
async def create_user(name: str):
    return {"id": 3, "name": name}

# Create MCP gateway from FastAPI app
mcp = McpWebGateway.from_fastapi(
    app,
    httpx_client_kwargs={"base_url": "http://localhost:8000"}
)
```

### 2. Connecting through OpenAPI specs

```python
from mcp_web_gateway import McpWebGateway
import httpx
import json

# Load your OpenAPI spec
with open("openapi.json") as f:
    openapi_spec = json.load(f)

# Create HTTP client
client = httpx.AsyncClient(base_url="https://api.example.com")

# Create gateway server
mcp = McpWebGateway(openapi_spec, client)

# The gateway is now ready to be used by MCP clients!
```

### 3. Using the Gateway with an MCP Client

```python
from fastmcp import Client

# Connect to the gateway
async with Client(gateway) as client:
    # Discover available resources
    resources = await client.list_resources()
    # Example: ['https://api.example.com/users', 'https://api.example.com/users/{id}']
    
    # Read a resource to see available methods
    schema = await client.read_resource("https://api.example.com/users")
    # Returns OpenAPI schema showing GET and POST are available
    
    # Execute a GET request
    users = await client.call_tool("GET", {
        "url": "https://api.example.com/users"
    })
    
    # Execute a POST request
    new_user = await client.call_tool("POST", {
        "url": "https://api.example.com/users",
        "body": {"name": "Charlie"}
    })
```

## Running the Server and Agent

### Start the MCP Server

```bash
# Using the FastAPI example
fastmcp run -t streamable-http examples/fastapi_example.py

# The server will start on http://localhost:8000
# MCP endpoint will be available at http://localhost:8000/mcp/
```

### Start an Autonomous Agent

```bash
# Ensure OPENAI_API_KEY is set in environment or fast-agent.secrets.yaml
export OPENAI_API_KEY=your-api-key

# Run the agent with the provided instructions
fast-agent go \
  -i agent/instructions.md \
  --url=http://127.0.0.1:8000/mcp/ \
  --model=gpt-4.1-mini
```

The agent will:
1. Connect to your MCP Web Gateway
2. Discover available API endpoints
3. Interact with users to understand their needs
4. Execute API operations on their behalf


## Web Agents 
    
The `agent/instructions.md` file contains an initial set of instructions for LLM agents to:

- Discover available endpoints by checking `/`, `/llms.txt`, and API documentation
- Understand API structure through systematic exploration
- Execute operations following a clear methodology: Discover → Read → Understand → Plan → Execute → Validate
- Handle errors gracefully and learn from API responses

## Advanced Usage

### Open World Mode

By default, the gateway operates in "closed world" mode where REST tools can only access URLs that correspond to defined resources in your OpenAPI specification. This provides safety by preventing access to arbitrary URLs.

You can enable "open world" mode to allow REST tools to access any URL:

```python
# Enable open world mode - REST tools can access any URL
mcp = McpWebGateway.from_fastapi(app, open_world=True)

# Or with OpenAPI spec
mcp = McpWebGateway(openapi_spec, client, open_world=True)
```

This is useful when you want to use the gateway as a general HTTP client;

The `open_world` setting is reflected in the tool annotations as `openWorldHint`, allowing MCP clients to understand the tool's behavior.

### Adding Custom Tools

By default, the gateway automatically adds REST tools (GET, POST, PUT, PATCH, DELETE). You can disable this and add your own custom tools:

```python
# Create gateway without default REST tools
mcp = McpWebGateway(openapi_spec, client, add_rest_tools=False)

# Add your own custom tools
@mcp.tool(name="custom_search")
async def custom_search(query: str) -> dict:
    # Your custom implementation
    return {"results": []}

# Optionally add the default REST tools later
mcp.add_rest_tools()
```

### Custom HTTP Client Configuration

```python
# Configure authentication, headers, etc.
client = httpx.AsyncClient(
    base_url="https://api.example.com",
    headers={"Authorization": "Bearer token"},
    timeout=30.0
)

mcp = McpWebGateway(openapi_spec, client)
```

## Examples

Check out the `examples/` directory for:

- `fastapi_example.py` - Complete FastAPI integration with a Todo API
- More examples coming soon!

## Development

### Setup Development Environment

```bash
# Clone the repository
git clone https://github.com/chughtapan/mcp-web-gateway
cd mcp-web-gateway

# Install with development dependencies
pip install -e ".[dev]"
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=mcp_web_gateway

# Run specific test file
pytest tests/unit/test_mcp_gateway.py -xvs
```

### Code Quality

```bash
# Format code
black src/ tests/
isort src/ tests/

# Type checking
mypy src/
```

## Acknowledgments

Built on top of the excellent [FastMCP](https://github.com/jlowin/fastmcp) framework. 

---

**Note**: This project is in active development.
