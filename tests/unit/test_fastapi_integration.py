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

    async def test_custom_route_maps_not_supported(self, fastapi_app):
        """Test that custom route maps raise NotImplementedError."""
        with pytest.raises(
            NotImplementedError, match="does not support custom route_maps"
        ):
            McpWebGateway.from_fastapi(fastapi_app, route_maps=[])

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

        # Verify resources created with method prefixes
        assert "http+get://fastapi/items" in resource_uris
        assert "http+post://fastapi/items" in resource_uris

        # List templates
        templates = await client.list_resource_templates()
        template_uris = {str(t.uriTemplate) for t in templates}

        assert "http+get://fastapi/items/{item_id}" in template_uris
        assert "http+put://fastapi/items/{item_id}" in template_uris
        assert "http+patch://fastapi/items/{item_id}" in template_uris
        assert "http+delete://fastapi/items/{item_id}" in template_uris

    async def test_only_rest_tools_available(self, gateway_and_client):
        """Test that only REST tools are available."""
        gateway, client = gateway_and_client

        tools = await client.list_tools()
        tool_names = {t.name for t in tools}

        # Should only have REST tools
        assert tool_names == {"GET", "POST", "PUT", "PATCH", "DELETE"}

    async def test_list_items_empty(self, gateway_and_client):
        """Test listing items when store is empty."""
        gateway, client = gateway_and_client

        result = await client.call_tool("GET", {"url": "http+get://fastapi/items"})

        # Empty list should be wrapped
        assert result.structured_content == {"result": []}

    async def test_create_and_get_item(self, gateway_and_client):
        """Test creating an item and retrieving it."""
        gateway, client = gateway_and_client

        # Create item
        create_result = await client.call_tool(
            "POST",
            {
                "url": "http+post://fastapi/items",
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
                "url": "http+post://fastapi/items",
                "body": {"name": "Original", "price": 10.00},
            },
        )

        item_id = create_result.structured_content["id"]

        # Update the item
        update_result = await client.call_tool(
            "PUT",
            {
                "url": f"http+put://fastapi/items/{item_id}",
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
                "url": "http+post://fastapi/items",
                "body": {"name": "Original", "price": 10.00},
            },
        )

        item_id = create_result.structured_content["id"]

        # Patch the item (only update price)
        patch_result = await client.call_tool(
            "PATCH",
            {
                "url": f"http+patch://fastapi/items/{item_id}",
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
                "url": "http+post://fastapi/items",
                "body": {"name": "To Delete", "price": 5.00},
            },
        )

        item_id = create_result.structured_content["id"]

        # Delete the item
        delete_result = await client.call_tool(
            "DELETE", {"url": f"http+delete://fastapi/items/{item_id}"}
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
                    "url": "http+post://fastapi/items",
                    "body": {"name": f"Item {i}", "price": float(i * 10)},
                },
            )

        # Test limit parameter
        result = await client.call_tool(
            "GET", {"url": "http+get://fastapi/items", "params": {"limit": 3}}
        )

        items = result.structured_content["result"]
        assert len(items) == 3

        # Test min_price parameter
        result = await client.call_tool(
            "GET", {"url": "http+get://fastapi/items", "params": {"min_price": 20.0}}
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

    async def test_method_mismatch_error(self, gateway_and_client):
        """Test that method mismatch in URL raises error."""
        gateway, client = gateway_and_client

        # Try to use POST tool on a GET resource
        with pytest.raises(Exception) as exc_info:
            await client.call_tool(
                "POST",
                {"url": "http+get://fastapi/items"},  # GET prefix but using POST tool
            )

        assert "Method mismatch" in str(exc_info.value)

    async def test_head_and_options_exposed_as_resources(self, gateway_and_client):
        """Test that HEAD and OPTIONS endpoints are exposed as resources (not as tools)."""
        gateway, client = gateway_and_client

        # List all resources
        resources = await client.list_resources()
        resource_uris = {str(r.uri) for r in resources}

        # HEAD and OPTIONS should be exposed as resources
        head_resources = [uri for uri in resource_uris if "+head://" in uri]
        options_resources = [uri for uri in resource_uris if "+options://" in uri]

        assert len(head_resources) > 0, "HEAD endpoints should be exposed as resources"
        assert (
            len(options_resources) > 0
        ), "OPTIONS endpoints should be exposed as resources"

        # But they should NOT have corresponding tools
        tools = await client.list_tools()
        tool_names = {t.name for t in tools}

        # Only standard REST tools should exist
        assert tool_names == {"GET", "POST", "PUT", "PATCH", "DELETE"}
        assert "HEAD" not in tool_names
        assert "OPTIONS" not in tool_names


class TestFastAPIMethodInvocation:
    """Test that the correct HTTP methods are invoked on FastAPI endpoints."""

    async def test_get_method_invoked(self, gateway_and_client_with_tracking):
        """Test that GET tool invokes GET method on FastAPI."""
        gateway, client, tracker = gateway_and_client_with_tracking
        tracker.clear()

        # Call GET tool
        await client.call_tool("GET", {"url": "http+get://fastapi/items"})

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
                "url": "http+post://fastapi/items",
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
                "url": "http+post://fastapi/items",
                "body": {"name": "Original", "price": 10.00},
            },
        )
        item_id = result.structured_content["id"]

        tracker.clear()

        # Call PUT tool
        await client.call_tool(
            "PUT",
            {
                "url": f"http+put://fastapi/items/{item_id}",
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
                "url": "http+post://fastapi/items",
                "body": {"name": "Original", "price": 10.00},
            },
        )
        item_id = result.structured_content["id"]

        tracker.clear()

        # Call PATCH tool
        await client.call_tool(
            "PATCH",
            {
                "url": f"http+patch://fastapi/items/{item_id}",
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
                "url": "http+post://fastapi/items",
                "body": {"name": "To Delete", "price": 5.00},
            },
        )
        item_id = result.structured_content["id"]

        tracker.clear()

        # Call DELETE tool
        await client.call_tool(
            "DELETE", {"url": f"http+delete://fastapi/items/{item_id}"}
        )

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

    async def test_wrong_method_prefix_raises_error(
        self, gateway_and_client_with_tracking
    ):
        """Test that mismatched method prefix raises error."""
        gateway, client, tracker = gateway_and_client_with_tracking
        tracker.clear()

        # Try to use GET tool with POST prefix
        with pytest.raises(Exception) as exc_info:
            await client.call_tool(
                "GET",
                {"url": "http+post://fastapi/items"},  # POST prefix but using GET tool
            )

        # Should not have made any HTTP calls
        assert len(tracker.get_invocations()) == 0
        assert "Method mismatch" in str(exc_info.value)

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
