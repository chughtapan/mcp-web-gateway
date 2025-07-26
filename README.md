# MCP Web Gateway
         
The MCP Web Gateway enables AI Agents to connect Web Services by accessing API directly.

- **All HTTP endpoints** are exposed as MCP resources with their original HTTP URLs.
- **Generic REST tools** (GET, POST, PUT, PATCH, DELETE) are provided for executing requests

This design changes the abstraction for the developers: instead of writing MCP servers, they write Web APIs using familiar REST semantics. 

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

### 1. Connecting through OpenAPI specs

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
gateway = McpWebGateway(openapi_spec, client)

# The gateway is now ready to be used by MCP clients!
```

### 3. Using the Gateway with an MCP Client

```python
from fastmcp import Client

# Connect to the gateway
async with Client(gateway) as client:
    # Discover available resources
    resources = await client.list_resources()
    # Example: ['https+get://api.example.com/users', 'https+post://api.example.com/users']
    
    # Execute a GET request
    users = await client.call_tool("GET", {
        "url": "https+get://api.example.com/users"
    })
    
    # Execute a POST request
    new_user = await client.call_tool("POST", {
        "url": "https+post://api.example.com/users",
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
