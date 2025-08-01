"""Integration tests for MCP Web Gateway with FastAPI applications."""

from typing import List, Tuple

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastmcp import Client
from pydantic import BaseModel

from mcp_web_gateway import McpWebGateway


class Item(BaseModel):
    """Item model for the test API."""

    name: str
    description: str | None = None
    price: float
    tax: float | None = None


class MethodTracker:
    """Track HTTP method invocations."""

    def __init__(self):
        self.invocations: List[Tuple[str, str]] = []  # List of (method, path) tuples

    def track(self, method: str, path: str):
        """Record a method invocation."""
        self.invocations.append((method, path))

    def clear(self):
        """Clear all invocations."""
        self.invocations.clear()

    def get_invocations(
        self, method: str = None, path: str = None
    ) -> List[Tuple[str, str]]:
        """Get invocations, optionally filtered by method or path."""
        result = self.invocations
        if method:
            result = [(m, p) for m, p in result if m == method]
        if path:
            result = [(m, p) for m, p in result if p == path]
        return result


@pytest.fixture
def fastapi_app():
    """Create a FastAPI application for testing."""
    app = FastAPI(title="Test Item API", version="1.0.0")

    # In-memory storage
    items = {}
    next_id = 1

    @app.get("/items")
    async def list_items(limit: int = 10, min_price: float | None = None):
        """List all items with optional filtering."""
        result = list(items.values())

        # Apply filters
        if min_price is not None:
            result = [item for item in result if item["price"] >= min_price]

        # Apply limit
        return result[:limit]

    @app.post("/items", status_code=201)
    async def create_item(item: Item):
        """Create a new item."""
        nonlocal next_id
        item_dict = item.dict()
        item_dict["id"] = next_id
        items[next_id] = item_dict
        next_id += 1
        return item_dict

    @app.get("/items/{item_id}")
    async def get_item(item_id: int):
        """Get a specific item by ID."""
        if item_id not in items:
            raise HTTPException(status_code=404, detail="Item not found")
        return items[item_id]

    @app.put("/items/{item_id}")
    async def update_item(item_id: int, item: Item):
        """Update an existing item."""
        if item_id not in items:
            raise HTTPException(status_code=404, detail="Item not found")
        item_dict = item.dict()
        item_dict["id"] = item_id
        items[item_id] = item_dict
        return item_dict

    @app.patch("/items/{item_id}")
    async def patch_item(item_id: int, patch_data: dict):
        """Partially update an existing item."""
        if item_id not in items:
            raise HTTPException(status_code=404, detail="Item not found")
        # Update only provided fields
        for key, value in patch_data.items():
            if key in items[item_id]:
                items[item_id][key] = value
        return items[item_id]

    @app.delete("/items/{item_id}", status_code=204)
    async def delete_item(item_id: int):
        """Delete an item."""
        if item_id not in items:
            raise HTTPException(status_code=404, detail="Item not found")
        del items[item_id]

    # Also test that we don't create tools for non-standard methods
    @app.head("/items")
    async def head_items():
        """HEAD endpoint (should not create a tool)."""
        return None

    @app.options("/items")
    async def options_items():
        """OPTIONS endpoint (should not create a tool)."""
        return {"methods": ["GET", "POST", "HEAD", "OPTIONS"]}

    return app


@pytest.fixture
def fastapi_app_with_tracking(fastapi_app):
    """Add method tracking to the FastAPI app."""
    tracker = MethodTracker()

    # Store tracker on app for access in tests
    fastapi_app.state.tracker = tracker

    @fastapi_app.middleware("http")
    async def track_methods(request: Request, call_next):
        """Middleware to track HTTP method calls."""
        tracker.track(request.method, request.url.path)
        response = await call_next(request)
        return response

    return fastapi_app


@pytest.fixture
async def gateway_and_client(fastapi_app):
    """Create gateway and client for testing."""
    gateway = McpWebGateway.from_fastapi(fastapi_app)
    async with Client(gateway) as client:
        yield gateway, client


@pytest.fixture
async def gateway_and_client_with_tracking(fastapi_app_with_tracking):
    """Create gateway and client with method tracking."""
    gateway = McpWebGateway.from_fastapi(fastapi_app_with_tracking)
    async with Client(gateway) as client:
        yield gateway, client, fastapi_app_with_tracking.state.tracker


class TestFastAPIIntegration:
    """Test MCP Web Gateway integration with FastAPI."""

    async def test_custom_route_maps_validation(self, fastapi_app):
        """Test that custom route maps are validated for correct types."""
        from fastmcp.experimental.server.openapi.routing import MCPType, RouteMap

        # Valid route maps should work
        valid_maps = [
            RouteMap(methods="*", mcp_type=MCPType.RESOURCE),
            RouteMap(
                methods="*",
                pattern=r".*\{[^}]+\}.*",
                mcp_type=MCPType.RESOURCE_TEMPLATE,
            ),
        ]
        gateway = McpWebGateway.from_fastapi(fastapi_app, route_maps=valid_maps)
        assert gateway is not None

        # Invalid route maps should raise ValueError
        invalid_maps = [
            RouteMap(methods="*", mcp_type=MCPType.TOOL),
        ]
        with pytest.raises(
            ValueError, match="only supports RESOURCE and RESOURCE_TEMPLATE types"
        ):
            McpWebGateway.from_fastapi(fastapi_app, route_maps=invalid_maps)

    async def test_custom_route_map_fn_not_supported(self, fastapi_app):
        """Test that custom route_map_fn raises NotImplementedError."""
        with pytest.raises(
            NotImplementedError, match="does not support custom route_map_fn"
        ):
            McpWebGateway.from_fastapi(fastapi_app, route_map_fn=lambda x: None)

    async def test_custom_mcp_component_fn_not_supported(self, fastapi_app):
        """Test that custom mcp_component_fn raises NotImplementedError."""
        with pytest.raises(
            NotImplementedError, match="does not support custom mcp_component_fn"
        ):
            McpWebGateway.from_fastapi(fastapi_app, mcp_component_fn=lambda x, y: None)

    async def test_resources_created_from_fastapi(self, gateway_and_client):
        """Test that resources are created correctly from FastAPI app."""
        gateway, client = gateway_and_client

        # List resources
        resources = await client.list_resources()
        resource_uris = {str(r.uri) for r in resources}

        # Verify resources created with plain HTTP URIs (no method prefixes)
        assert "http://fastapi/items" in resource_uris

        # List templates
        templates = await client.list_resource_templates()
        template_uris = {str(t.uriTemplate) for t in templates}

        assert "http://fastapi/items/{item_id}" in template_uris

    async def test_only_rest_tools_available(self, gateway_and_client):
        """Test that only REST tools are available."""
        gateway, client = gateway_and_client

        tools = await client.list_tools()
        tool_names = {t.name for t in tools}

        # Should only have REST tools
        assert tool_names == {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}

    async def test_list_items_empty(self, gateway_and_client):
        """Test listing items when store is empty."""
        gateway, client = gateway_and_client

        result = await client.call_tool("GET", {"url": "http://fastapi/items"})

        # Empty list should be wrapped
        assert result.structured_content == {"result": []}

    async def test_create_and_get_item(self, gateway_and_client):
        """Test creating an item and retrieving it."""
        gateway, client = gateway_and_client

        # Create item
        create_result = await client.call_tool(
            "POST",
            {
                "url": "http://fastapi/items",
                "body": {
                    "name": "Widget",
                    "description": "A useful widget",
                    "price": 19.99,
                    "tax": 1.50,
                },
            },
        )

        assert create_result.structured_content["name"] == "Widget"
        assert create_result.structured_content["price"] == 19.99
        assert "id" in create_result.structured_content

        item_id = create_result.structured_content["id"]

        # Get the created item
        get_result = await client.call_tool(
            "GET", {"url": f"http://fastapi/items/{item_id}"}  # Plain URL
        )

        assert get_result.structured_content["id"] == item_id
        assert get_result.structured_content["name"] == "Widget"

    async def test_update_item(self, gateway_and_client):
        """Test updating an existing item."""
        gateway, client = gateway_and_client

        # Create item first
        create_result = await client.call_tool(
            "POST",
            {
                "url": "http://fastapi/items",
                "body": {"name": "Original", "price": 10.00},
            },
        )

        item_id = create_result.structured_content["id"]

        # Update the item
        update_result = await client.call_tool(
            "PUT",
            {
                "url": f"http://fastapi/items/{item_id}",
                "body": {
                    "name": "Updated",
                    "description": "Now with description",
                    "price": 15.00,
                },
            },
        )

        assert update_result.structured_content["name"] == "Updated"
        assert update_result.structured_content["description"] == "Now with description"
        assert update_result.structured_content["price"] == 15.00

    async def test_patch_item(self, gateway_and_client):
        """Test partially updating an item with PATCH."""
        gateway, client = gateway_and_client

        # Create item first
        create_result = await client.call_tool(
            "POST",
            {
                "url": "http://fastapi/items",
                "body": {"name": "Original", "price": 10.00},
            },
        )

        item_id = create_result.structured_content["id"]

        # Patch the item (only update price)
        patch_result = await client.call_tool(
            "PATCH",
            {
                "url": f"http://fastapi/items/{item_id}",
                "body": {"price": 12.00},  # Only update price
            },
        )

        assert patch_result.structured_content["name"] == "Original"  # Unchanged
        assert patch_result.structured_content["price"] == 12.00  # Updated

    async def test_delete_item(self, gateway_and_client):
        """Test deleting an item."""
        gateway, client = gateway_and_client

        # Create item first
        create_result = await client.call_tool(
            "POST",
            {
                "url": "http://fastapi/items",
                "body": {"name": "To Delete", "price": 5.00},
            },
        )

        item_id = create_result.structured_content["id"]

        # Delete the item
        delete_result = await client.call_tool(
            "DELETE", {"url": f"http://fastapi/items/{item_id}"}
        )

        # 204 returns empty content
        assert len(delete_result.content) == 1
        assert delete_result.content[0].text == ""

        # Verify item is gone
        with pytest.raises(Exception) as exc_info:
            await client.call_tool("GET", {"url": f"http://fastapi/items/{item_id}"})
        assert "404" in str(exc_info.value)

    async def test_query_parameters(self, gateway_and_client):
        """Test that query parameters work correctly."""
        gateway, client = gateway_and_client

        # Create several items
        for i in range(5):
            await client.call_tool(
                "POST",
                {
                    "url": "http://fastapi/items",
                    "body": {"name": f"Item {i}", "price": float(i * 10)},
                },
            )

        # Test limit parameter
        result = await client.call_tool(
            "GET", {"url": "http://fastapi/items", "params": {"limit": 3}}
        )

        items = result.structured_content["result"]
        assert len(items) == 3

        # Test min_price parameter
        result = await client.call_tool(
            "GET", {"url": "http://fastapi/items", "params": {"min_price": 20.0}}
        )

        items = result.structured_content["result"]
        assert all(item["price"] >= 20.0 for item in items)

    async def test_error_handling(self, gateway_and_client):
        """Test error handling for non-existent resources."""
        gateway, client = gateway_and_client

        # Try to get non-existent item
        with pytest.raises(Exception) as exc_info:
            await client.call_tool("GET", {"url": "http://fastapi/items/999"})

        assert "404" in str(exc_info.value)
        assert "Item not found" in str(exc_info.value)

    async def test_unsupported_method_error(self, gateway_and_client):
        """Test that using unsupported HTTP method raises error."""
        gateway, client = gateway_and_client

        # Try to use PATCH tool on the root /items resource (which only supports GET and POST)
        with pytest.raises(Exception) as exc_info:
            await client.call_tool(
                "PATCH",
                {"url": "http://fastapi/items"},
            )

        assert "Method PATCH not supported" in str(exc_info.value)

    async def test_head_and_options_merged_into_resources(self, gateway_and_client):
        """Test that HEAD and OPTIONS methods are merged into resources and available in schema."""
        gateway, client = gateway_and_client

        # Read the /items resource to get its schema
        items_resource_content = await client.read_resource("http://fastapi/items")

        # Parse the schema to check available methods
        import json

        schema = json.loads(items_resource_content[0].text)

        # Check that HEAD and OPTIONS methods are included in the schema
        items_operations = schema["paths"]["/items"]

        # FastAPI automatically adds HEAD for GET endpoints and OPTIONS for all endpoints
        assert "get" in items_operations, "GET method should be present"
        assert "post" in items_operations, "POST method should be present"
        assert "head" in items_operations, "HEAD method should be present"
        assert "options" in items_operations, "OPTIONS method should be present"

        # OPTIONS should have a corresponding tool, but HEAD should not
        tools = await client.list_tools()
        tool_names = {t.name for t in tools}

        # Standard REST tools including OPTIONS should exist
        assert tool_names == {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
        assert "HEAD" not in tool_names  # HEAD still not a tool


class TestFastAPIMethodInvocation:
    """Test that the correct HTTP methods are invoked on FastAPI endpoints."""

    async def test_get_method_invoked(self, gateway_and_client_with_tracking):
        """Test that GET tool invokes GET method on FastAPI."""
        gateway, client, tracker = gateway_and_client_with_tracking
        tracker.clear()

        # Call GET tool
        await client.call_tool("GET", {"url": "http://fastapi/items"})

        # Verify GET method was called
        invocations = tracker.get_invocations()
        assert len(invocations) == 1
        assert invocations[0] == ("GET", "/items")

    async def test_post_method_invoked(self, gateway_and_client_with_tracking):
        """Test that POST tool invokes POST method on FastAPI."""
        gateway, client, tracker = gateway_and_client_with_tracking
        tracker.clear()

        # Call POST tool
        await client.call_tool(
            "POST",
            {
                "url": "http://fastapi/items",
                "body": {"name": "Test Item", "price": 9.99},
            },
        )

        # Verify POST method was called
        invocations = tracker.get_invocations()
        assert len(invocations) == 1
        assert invocations[0] == ("POST", "/items")

    async def test_put_method_invoked(self, gateway_and_client_with_tracking):
        """Test that PUT tool invokes PUT method on FastAPI."""
        gateway, client, tracker = gateway_and_client_with_tracking

        # First create an item
        result = await client.call_tool(
            "POST",
            {
                "url": "http://fastapi/items",
                "body": {"name": "Original", "price": 10.00},
            },
        )
        item_id = result.structured_content["id"]

        tracker.clear()

        # Call PUT tool
        await client.call_tool(
            "PUT",
            {
                "url": f"http://fastapi/items/{item_id}",
                "body": {"name": "Updated", "price": 15.00},
            },
        )

        # Verify PUT method was called
        invocations = tracker.get_invocations()
        assert len(invocations) == 1
        assert invocations[0] == ("PUT", f"/items/{item_id}")

    async def test_patch_method_invoked(self, gateway_and_client_with_tracking):
        """Test that PATCH tool invokes PATCH method on FastAPI."""
        gateway, client, tracker = gateway_and_client_with_tracking

        # First create an item
        result = await client.call_tool(
            "POST",
            {
                "url": "http://fastapi/items",
                "body": {"name": "Original", "price": 10.00},
            },
        )
        item_id = result.structured_content["id"]

        tracker.clear()

        # Call PATCH tool
        await client.call_tool(
            "PATCH",
            {
                "url": f"http://fastapi/items/{item_id}",
                "body": {"price": 12.00},  # Only update price
            },
        )

        # Verify PATCH method was called
        invocations = tracker.get_invocations()
        assert len(invocations) == 1
        assert invocations[0] == ("PATCH", f"/items/{item_id}")

    async def test_delete_method_invoked(self, gateway_and_client_with_tracking):
        """Test that DELETE tool invokes DELETE method on FastAPI."""
        gateway, client, tracker = gateway_and_client_with_tracking

        # First create an item
        result = await client.call_tool(
            "POST",
            {
                "url": "http://fastapi/items",
                "body": {"name": "To Delete", "price": 5.00},
            },
        )
        item_id = result.structured_content["id"]

        tracker.clear()

        # Call DELETE tool
        await client.call_tool("DELETE", {"url": f"http://fastapi/items/{item_id}"})

        # Verify DELETE method was called
        invocations = tracker.get_invocations()
        assert len(invocations) == 1
        assert invocations[0] == ("DELETE", f"/items/{item_id}")

    async def test_plain_url_uses_tool_method(self, gateway_and_client_with_tracking):
        """Test that plain URLs use the tool's method."""
        gateway, client, tracker = gateway_and_client_with_tracking
        tracker.clear()

        # Use GET tool with plain URL
        await client.call_tool(
            "GET", {"url": "http://fastapi/items"}  # No method prefix
        )

        # Should invoke GET method
        invocations = tracker.get_invocations()
        assert len(invocations) == 1
        assert invocations[0] == ("GET", "/items")

        tracker.clear()

        # Use POST tool with plain URL
        await client.call_tool(
            "POST",
            {
                "url": "http://fastapi/items",  # No method prefix
                "body": {"name": "Plain URL Item", "price": 7.50},
            },
        )

        # Should invoke POST method
        invocations = tracker.get_invocations()
        assert len(invocations) == 1
        assert invocations[0] == ("POST", "/items")

    async def test_unsupported_method_raises_error(
        self, gateway_and_client_with_tracking
    ):
        """Test that using unsupported method raises error."""
        gateway, client, tracker = gateway_and_client_with_tracking
        tracker.clear()

        # Try to use PUT tool on /items (which only supports GET and POST)
        with pytest.raises(Exception) as exc_info:
            await client.call_tool(
                "PUT",
                {"url": "http://fastapi/items"},
            )

        # Should not have made any HTTP calls to the actual endpoint
        assert len(tracker.get_invocations()) == 0
        assert "Method PUT not supported" in str(exc_info.value)

    async def test_multiple_requests_tracked_correctly(
        self, gateway_and_client_with_tracking
    ):
        """Test that multiple requests are tracked in order."""
        gateway, client, tracker = gateway_and_client_with_tracking
        tracker.clear()

        # Make several requests
        await client.call_tool("GET", {"url": "http://fastapi/items"})

        result = await client.call_tool(
            "POST",
            {"url": "http://fastapi/items", "body": {"name": "Item 1", "price": 10.00}},
        )
        item_id = result.structured_content["id"]

        await client.call_tool("GET", {"url": f"http://fastapi/items/{item_id}"})
        await client.call_tool("DELETE", {"url": f"http://fastapi/items/{item_id}"})

        # Verify all methods were called in order
        invocations = tracker.get_invocations()
        assert len(invocations) == 4
        assert invocations[0] == ("GET", "/items")
        assert invocations[1] == ("POST", "/items")
        assert invocations[2] == ("GET", f"/items/{item_id}")
        assert invocations[3] == ("DELETE", f"/items/{item_id}")


class TestOpenWorldIntegration:
    """Test open_world parameter with FastAPI integration."""

    @pytest.fixture
    def simple_app(self):
        """Create a simple FastAPI app with limited endpoints."""
        app = FastAPI()

        @app.get("/known")
        def get_known():
            return {"message": "This is a known endpoint"}

        return app

    async def test_closed_world_blocks_unknown_endpoints(self, simple_app):
        """Test that closed-world mode blocks access to endpoints not in OpenAPI spec."""
        # Create gateway with default closed-world mode
        mcp = McpWebGateway.from_fastapi(simple_app)

        async with Client(mcp) as client:
            # Should be able to access known endpoint
            result = await client.call_tool("GET", {"url": "http://fastapi/known"})
            assert result.structured_content == {"message": "This is a known endpoint"}

            # Should NOT be able to access unknown endpoint
            with pytest.raises(Exception) as exc_info:
                await client.call_tool("GET", {"url": "http://fastapi/unknown"})

            error_msg = str(exc_info.value)
            assert "does not match any known resource" in error_msg

    async def test_open_world_allows_unknown_endpoints(self, simple_app):
        """Test that open-world mode allows access to any endpoint."""

        # Add a handler that catches all routes for testing
        @simple_app.get("/{path:path}")
        def catch_all(path: str):
            return {"message": f"Caught unknown path: {path}"}

        # Create gateway with open-world mode
        mcp = McpWebGateway.from_fastapi(simple_app, open_world=True)

        async with Client(mcp) as client:
            # Should be able to access known endpoint
            result = await client.call_tool("GET", {"url": "http://fastapi/known"})
            assert result.structured_content == {"message": "This is a known endpoint"}

            # Should ALSO be able to access unknown endpoint
            result = await client.call_tool(
                "GET", {"url": "http://fastapi/totally/unknown/path"}
            )
            assert result.structured_content == {
                "message": "Caught unknown path: totally/unknown/path"
            }

    async def test_open_world_with_method_tracking(self, fastapi_app):
        """Test open-world mode with method tracking."""
        tracker = MethodTracker()

        # Add middleware to track methods
        @fastapi_app.middleware("http")
        async def track_methods(request: Request, call_next):
            tracker.track(request.method, request.url.path)
            response = await call_next(request)
            return response

        # Add a catch-all route
        @fastapi_app.get("/{path:path}")
        def catch_all(path: str):
            return {"message": f"Unknown path: {path}"}

        # Create gateway with open-world mode
        mcp = McpWebGateway.from_fastapi(fastapi_app, open_world=True)

        async with Client(mcp) as client:
            tracker.clear()

            # Access known endpoint
            await client.call_tool("GET", {"url": "http://fastapi/items"})

            # Access unknown endpoint
            await client.call_tool("GET", {"url": "http://fastapi/unknown/endpoint"})

            # Verify both were called
            invocations = tracker.get_invocations()
            assert len(invocations) == 2
            assert invocations[0] == ("GET", "/items")
            assert invocations[1] == ("GET", "/unknown/endpoint")

    async def test_all_rest_tools_respect_open_world_setting(self, simple_app):
        """Test that all REST tools (GET, POST, PUT, PATCH, DELETE, OPTIONS) respect open_world."""
        # Create gateway with closed world
        mcp_closed = McpWebGateway.from_fastapi(simple_app)

        async with Client(mcp_closed) as client:
            tools = await client.list_tools()

            # Verify all REST tools have openWorldHint=False
            for tool_name in ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]:
                tool = next(t for t in tools if t.name == tool_name)
                assert tool.annotations is not None
                assert tool.annotations.openWorldHint is False

        # Create gateway with open world
        mcp_open = McpWebGateway.from_fastapi(simple_app, open_world=True)

        async with Client(mcp_open) as client:
            tools = await client.list_tools()

            # Verify all REST tools have openWorldHint=True
            for tool_name in ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]:
                tool = next(t for t in tools if t.name == tool_name)
                assert tool.annotations is not None
                assert tool.annotations.openWorldHint is True


class TestOptionsIntegration:
    """Test OPTIONS method integration with FastAPI."""

    async def test_options_method_invoked(self, gateway_and_client_with_tracking):
        """Test that OPTIONS tool invokes OPTIONS method on FastAPI."""
        gateway, client, tracker = gateway_and_client_with_tracking
        tracker.clear()

        # Call OPTIONS tool
        await client.call_tool("OPTIONS", {"url": "http://fastapi/items"})

        # Should return schema (since OPTIONS is defined in the FastAPI app)
        # Verify OPTIONS method was called
        invocations = tracker.get_invocations()
        assert len(invocations) == 1
        assert invocations[0] == ("OPTIONS", "/items")

    async def test_options_defined_endpoint_execution(self, gateway_and_client):
        """Test OPTIONS when it's explicitly defined returns correct response."""
        gateway, client = gateway_and_client

        # Call OPTIONS on /items (which has OPTIONS defined)
        result = await client.call_tool("OPTIONS", {"url": "http://fastapi/items"})

        # Should return the OPTIONS response
        assert result.structured_content == {
            "methods": ["GET", "POST", "HEAD", "OPTIONS"]
        }

    async def test_options_template_returns_full_schema(self, gateway_and_client):
        """Test OPTIONS on template returns full schema."""
        gateway, client = gateway_and_client

        # Call OPTIONS on the template URL itself
        result = await client.call_tool(
            "OPTIONS", {"url": "http://fastapi/items/{item_id}"}
        )

        # Should return full OpenAPI schema for templates
        assert "openapi" in result.structured_content
        assert "paths" in result.structured_content
        assert "/items/{item_id}" in result.structured_content["paths"]

        # For templates, we get all methods documented
        item_operations = result.structured_content["paths"]["/items/{item_id}"]
        assert "get" in item_operations
        assert "put" in item_operations
        assert "patch" in item_operations
        assert "delete" in item_operations

    async def test_options_prefix_match_fastapi(self, gateway_and_client):
        """Test OPTIONS prefix matching with FastAPI routes."""
        gateway, client = gateway_and_client

        # Use base URL as prefix
        result = await client.call_tool("OPTIONS", {"url": "http://fastapi/"})

        # Should return matching routes
        assert "matching_routes" in result.structured_content
        routes = result.structured_content["matching_routes"]

        # Check we have both resources and templates
        resource_urls = [r["url"] for r in routes if r["type"] == "resource"]
        template_urls = [r["url"] for r in routes if r["type"] == "template"]

        assert "http://fastapi/items" in resource_urls
        assert "http://fastapi/items/{item_id}" in template_urls

    async def test_options_with_query_params_fastapi(
        self, gateway_and_client_with_tracking
    ):
        """Test OPTIONS with query parameters on FastAPI endpoint."""
        gateway, client, tracker = gateway_and_client_with_tracking
        tracker.clear()

        # Call OPTIONS with query params
        await client.call_tool(
            "OPTIONS",
            {
                "url": "http://fastapi/items",
                "params": {"format": "json"},
            },
        )

        # Should have passed query params to the OPTIONS request
        invocations = tracker.get_invocations()
        assert len(invocations) == 1
        assert invocations[0] == ("OPTIONS", "/items")

    @pytest.fixture
    def dynamic_fastapi_app(self):
        """Create a FastAPI app that we can modify during tests."""
        app = FastAPI(title="Dynamic Test API")

        @app.get("/products")
        def list_products():
            return {"products": []}

        return app

    async def test_options_dynamic_route_addition(self, dynamic_fastapi_app):
        """Test OPTIONS behavior when routes are added after MCP creation."""
        # Create MCP server with initial routes
        mcp = McpWebGateway.from_fastapi(dynamic_fastapi_app)

        # Add a new route after MCP creation
        @dynamic_fastapi_app.post("/products")
        def create_product(name: str):
            return {"name": name, "id": 1}

        async with Client(mcp) as client:
            # OPTIONS should still only see the original route
            result = await client.call_tool(
                "OPTIONS", {"url": "http://fastapi/products"}
            )

            # Should return schema with only GET (not POST)
            assert "openapi" in result.structured_content
            products_ops = result.structured_content["paths"]["/products"]
            assert "get" in products_ops
            assert "post" not in products_ops  # POST was added after MCP creation

    async def test_options_no_match_fastapi(self, gateway_and_client):
        """Test OPTIONS with non-existent FastAPI endpoint."""
        gateway, client = gateway_and_client

        # Check what the response is
        result = await client.call_tool(
            "OPTIONS", {"url": "http://fastapi/nonexistent"}
        )
        print(f"OPTIONS response: {result.structured_content}")

        # It seems the current implementation returns an error in the response
        # rather than raising an exception
        assert "error" in result.structured_content
        assert "No resources found" in result.structured_content["error"]
