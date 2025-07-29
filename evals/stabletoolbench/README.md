# StableToolBench Evaluation Server

StableToolBench is a benchmark for evaluating LLM tool usage, containing thousands of real-world APIs from RapidAPI marketplace. This directory provides a REST server which exposes these APIs. Original Sources:

- [StableToolBench](https://github.com/THUNLP-MT/StableToolBench)
- [ToolBench](https://github.com/OpenBMB/ToolBench)

## Overview

### Setup

1. **Prepare the data** (first time only):
   ```bash
   ./prepare_data.sh
   ```
   This downloads and extracts the StableToolBench dataset.

2. **Configure environment**:
   Make sure there `.env` file in the project root (../../) with:
   ```
   OPENAI_API_KEY=your-openai-api-key
   ```

3. **Start the server**:
   ```bash
   docker-compose up -d
   ```

4. **Verify it's running**:
   ```bash
   curl http://localhost:8080/health
   ```

## Usage

### Authentication

All API endpoints require an API key header:
```bash
-H "X-API-Key: test_key"
```

### Example Requests

**GET request:**
```bash
curl -s http://localhost:8080/entertainment/dad_jokes_by_api_ninjas/v1_dadjokes \
  -H "X-API-Key: test_key" | jq .
```

**POST request:**
```bash
curl -s -X POST http://localhost:8080/commerce/bin_packer/pack \
  -H "X-API-Key: test_key" \
  -H "Content-Type: application/json" \
  -d '{
    "containers": [{"width": 10, "height": 10, "depth": 10, "quantity": 2}],
    "items": [{"width": 5, "height": 5, "depth": 5, "quantity": 3}]
  }' | jq .
```

**DELETE request (uses query parameters):**
```bash
curl -s -X DELETE "http://localhost:8080/commerce/odee/deleteproduk?product_id=12345" \
  -H "X-API-Key: test_key" | jq .
```

### OpenAPI Specification

Get the full OpenAPI spec:
```bash
curl http://localhost:8080/openapi.json | jq .
```

## Architecture

### How It Works

1. **Tool Loading**: On startup, the server loads all tool definitions from `data/tools/`
2. **Endpoint Generation**: Each tool's APIs are exposed as REST endpoints at `/{category}/{tool_name}/{api_name}`
3. **Request Handling**: 
   - GET/DELETE: Parameters from query string
   - POST/PUT/PATCH: Parameters from request body
4. **Response Generation**: Uses GPT-4.1-mini to generate contextually appropriate fake responses based on:
   - API documentation
   - Input parameters
   - HTTP method semantics

## Experiment: Tool Count Limits

This server demonstrates why traditional MCP approaches fail at scale. StableToolBench contains ~50,000 endpoints across 10,000+ tools, which exceeds practical tool limits:

- **Recommended**: ~20 tools or less
- **Soft limits**: ~40-50 tools (Cursor/Claude users report degraded performance)  
- **Hard limits**: 128 tools (OpenAI models)

### Running the Experiment

The `mcp_server.py` script implements three strategies:

```bash
# 1. Convert everything to tools: Each HTTP method + path becomes a separate tool
#    Result: >10,000 tools - exceeds all limits
fastmcp run -t http evals/stabletoolbench/mcp_server.py -- --strategy=all-tools

# 2. MCP Specification recommendation: Convert GET requests to resources/resource 
#    templates, all other methods (POST/PUT/PATCH/DELETE) become tools
#    Result: >10,000 tools - exceeds all limits  
fastmcp run -t http evals/stabletoolbench/mcp_server.py -- --strategy=spec-recommend

# 3. Web Gateway: Expose HTTP routes as resources with their original URIs,
#    provide generic REST tools that operate on these resources
#    Result: Tractable - works with all models
fastmcp run -t http evals/stabletoolbench/mcp_server.py
```

The experiment shows that while MCP servers can expose thousands of tools, language models cannot consume them effectively. Only the Web Gateway approach remains tractable at this scale.
