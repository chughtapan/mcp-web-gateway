"""Comprehensive tests for the MCP Web Gateway."""

import json
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastmcp.client import Client

from mcp_web_gateway import McpWebGateway


class TestMcpWebGateway:
    """Test MCP Web Gateway functionality."""

    @pytest.fixture
    async def server_and_client(self, petstore_openapi_spec, mock_http_client):
        """Create server and client for testing."""
        server = McpWebGateway(
            petstore_openapi_spec, mock_http_client, name="Pet Store API"
        )
        async with Client(server) as mcp_client:
            yield server, mcp_client

    async def test_resources_created_with_http_uris(self, petstore_openapi_spec):
        """Test that resources are created with plain HTTP URIs."""
        client = httpx.AsyncClient(base_url="https://petstore.example.com/api")
        server = McpWebGateway(petstore_openapi_spec, client)

        # Check that resources were created
        resources = server._resource_manager._resources
        templates = server._resource_manager._templates

        # Should have 1 resource for /pets (combining GET and POST)
        assert len(resources) == 1

        # Should have 1 template for /pets/{petId} (combining GET, PUT, DELETE)
        assert len(templates) == 1

        # Check resource URIs are plain HTTP URLs
        assert "https://petstore.example.com/api/pets" in resources

        # Check template URIs are plain HTTP URLs
        assert "https://petstore.example.com/api/pets/{petId}" in templates

    async def test_resource_read_returns_schema(self, petstore_openapi_spec):
        """Test that reading a resource returns OpenAPI schema."""
        client = httpx.AsyncClient(base_url="https://petstore.example.com/api")
        server = McpWebGateway(petstore_openapi_spec, client)

        # Get the /pets resource
        pets_resource = server._resource_manager._resources[
            "https://petstore.example.com/api/pets"
        ]

        # Read the resource
        schema_json = await pets_resource.read()
        schema = json.loads(schema_json)

        # Check schema structure
        assert "openapi" in schema
        assert "paths" in schema
        assert "/pets" in schema["paths"]

        # Check that both GET and POST methods are in the schema
        pets_operations = schema["paths"]["/pets"]
        assert "get" in pets_operations
        assert "post" in pets_operations

        # Check GET operation details
        assert pets_operations["get"]["operationId"] == "list_pets"

        # Check POST operation details
        assert pets_operations["post"]["operationId"] == "create_pet"
        assert "requestBody" in pets_operations["post"]
        assert "responses" in pets_operations["post"]

    async def test_template_read_returns_schema(self, petstore_openapi_spec):
        """Test that reading a template resource returns OpenAPI schema."""
        client = httpx.AsyncClient(base_url="https://petstore.example.com/api")
        server = McpWebGateway(petstore_openapi_spec, client)

        # Get the /pets/{petId} template
        pet_template = server._resource_manager._templates[
            "https://petstore.example.com/api/pets/{petId}"
        ]

        # Create a resource instance
        pet_resource = await pet_template.create_resource(
            "https://petstore.example.com/api/pets/123", {"petId": "123"}
        )

        # Read the resource
        schema_json = await pet_resource.read()
        schema = json.loads(schema_json)

        # Check that all methods are in the schema
        pet_operations = schema["paths"]["/pets/{petId}"]
        assert "get" in pet_operations
        assert "put" in pet_operations
        assert "delete" in pet_operations

    async def test_only_rest_tools_created(self, petstore_openapi_spec):
        """Test that only REST tools are created, no operation-specific tools."""
        client = httpx.AsyncClient(base_url="https://petstore.example.com/api")
        server = McpWebGateway(petstore_openapi_spec, client)

        tools = await server.get_tools()
        tool_names = list(tools.keys())

        # Should only have the 5 REST tools (default behavior)
        assert len(tool_names) == 5
        assert set(tool_names) == {"GET", "POST", "PUT", "PATCH", "DELETE"}

        # Should not have operation-specific tools
        assert "list_pets" not in tool_names
        assert "create_pet" not in tool_names
        assert "get_pet" not in tool_names
        assert "update_pet" not in tool_names
        assert "delete_pet" not in tool_names

    async def test_no_rest_tools_when_disabled(self, petstore_openapi_spec):
        """Test that REST tools are not created when add_rest_tools=False."""
        client = httpx.AsyncClient(base_url="https://petstore.example.com/api")
        server = McpWebGateway(petstore_openapi_spec, client, add_rest_tools=False)

        tools = await server.get_tools()
        tool_names = list(tools.keys())

        # Should have no tools at all
        assert len(tool_names) == 0

    async def test_explicit_add_rest_tools(self, petstore_openapi_spec):
        """Test that add_rest_tools() method works when called explicitly."""
        client = httpx.AsyncClient(base_url="https://petstore.example.com/api")
        server = McpWebGateway(petstore_openapi_spec, client, add_rest_tools=False)

        # Initially no tools
        tools = await server.get_tools()
        assert len(tools) == 0

        # Add REST tools explicitly
        server.add_rest_tools()

        # Now should have the 5 REST tools
        tools = await server.get_tools()
        tool_names = list(tools.keys())
        assert len(tool_names) == 5
        assert set(tool_names) == {"GET", "POST", "PUT", "PATCH", "DELETE"}

    async def test_get_tool_execution(self, petstore_openapi_spec):
        """Test executing a GET request through the GET tool."""
        # Create a mock response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"id": 1, "name": "Fluffy", "species": "cat"},
            {"id": 2, "name": "Buddy", "species": "dog"},
        ]
        mock_response.text = '[{"id": 1, "name": "Fluffy", "species": "cat"}, {"id": 2, "name": "Buddy", "species": "dog"}]'
        mock_response.raise_for_status = Mock()

        # Create mock client
        mock_client = AsyncMock()
        mock_client.base_url = "https://petstore.example.com/api"
        mock_client.request = AsyncMock(return_value=mock_response)

        server = McpWebGateway(petstore_openapi_spec, mock_client)

        # Use in-memory client to call the tool
        async with Client(server) as client:
            result = await client.call_tool(
                "GET", {"url": "https://petstore.example.com/api/pets"}
            )

        # Check the request was made correctly
        mock_client.request.assert_called_once_with(
            method="GET",
            url="https://petstore.example.com/api/pets",
        )

        # Check the result (arrays are wrapped in a dict)
        assert result.structured_content == {
            "result": [
                {"id": 1, "name": "Fluffy", "species": "cat"},
                {"id": 2, "name": "Buddy", "species": "dog"},
            ]
        }

    async def test_post_tool_execution(self, petstore_openapi_spec):
        """Test executing a POST request through the POST tool."""
        # Create a mock response
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "id": 4,
            "name": "Max",
            "species": "dog",
            "breed": "Labrador",
        }
        mock_response.raise_for_status = Mock()

        # Create mock client
        mock_client = AsyncMock()
        mock_client.base_url = "https://petstore.example.com/api"
        mock_client.request = AsyncMock(return_value=mock_response)

        server = McpWebGateway(petstore_openapi_spec, mock_client)

        # Use in-memory client to call the tool
        async with Client(server) as client:
            result = await client.call_tool(
                "POST",
                {
                    "url": "https://petstore.example.com/api/pets",
                    "body": {"name": "Max", "species": "dog", "breed": "Labrador"},
                },
            )

        # Check the request was made correctly
        mock_client.request.assert_called_once_with(
            method="POST",
            url="https://petstore.example.com/api/pets",
            json={"name": "Max", "species": "dog", "breed": "Labrador"},
        )

        # Check the result
        assert result.structured_content["id"] == 4
        assert result.structured_content["name"] == "Max"

    async def test_method_not_supported_error(self, petstore_openapi_spec):
        """Test that using unsupported method raises error."""
        mock_client = AsyncMock()
        mock_client.base_url = "https://petstore.example.com/api"

        server = McpWebGateway(petstore_openapi_spec, mock_client)

        # Try to use PATCH tool on a resource that doesn't support it
        async with Client(server) as client:
            with pytest.raises(Exception) as exc_info:
                await client.call_tool(
                    "PATCH", {"url": "https://petstore.example.com/api/pets"}
                )

            assert "Method PATCH not supported" in str(exc_info.value)

    async def test_query_parameters(self, petstore_openapi_spec):
        """Test that query parameters are passed correctly."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_response.raise_for_status = Mock()

        mock_client = AsyncMock()
        mock_client.base_url = "https://petstore.example.com/api"
        mock_client.request = AsyncMock(return_value=mock_response)

        server = McpWebGateway(petstore_openapi_spec, mock_client)

        async with Client(server) as client:
            await client.call_tool(
                "GET",
                {
                    "url": "https://petstore.example.com/api/pets",
                    "params": {"limit": 10, "status": "available"},
                },
            )

        # Check params were passed
        mock_client.request.assert_called_once_with(
            method="GET",
            url="https://petstore.example.com/api/pets",
            params={"limit": 10, "status": "available"},
        )

    async def test_plain_url_without_method_prefix(self, petstore_openapi_spec):
        """Test that plain URLs without method prefix work correctly."""
        # Create a mock response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": 1, "name": "Fluffy", "species": "cat"}
        mock_response.raise_for_status = Mock()

        # Create mock client
        mock_client = AsyncMock()
        mock_client.base_url = "https://petstore.example.com/api"
        mock_client.request = AsyncMock(return_value=mock_response)

        server = McpWebGateway(petstore_openapi_spec, mock_client)

        # Use plain URL without method prefix
        async with Client(server) as client:
            result = await client.call_tool(
                "GET", {"url": "https://petstore.example.com/api/pets/1"}  # Plain URL
            )

        # Check the request was made correctly
        mock_client.request.assert_called_once_with(
            method="GET",
            url="https://petstore.example.com/api/pets/1",
        )

        # Check the result
        assert result.structured_content["id"] == 1
        assert result.structured_content["name"] == "Fluffy"

    async def test_get_tool_with_query_params_integration(self, server_and_client):
        """Test GET tool execution with query parameters using mock HTTP client."""
        server, mcp_client = server_and_client

        result = await mcp_client.call_tool(
            "GET",
            {
                "url": "https://petstore.example.com/api/pets",
                "params": {"limit": 2, "status": "available"},
            },
        )

        # Arrays are wrapped
        assert "result" in result.structured_content
        pets = result.structured_content["result"]
        assert len(pets) == 2
        assert all(p["status"] == "available" for p in pets)

    async def test_post_tool_with_request_body_integration(self, server_and_client):
        """Test POST tool execution with request body using mock HTTP client."""
        server, mcp_client = server_and_client

        result = await mcp_client.call_tool(
            "POST",
            {
                "url": "https://petstore.example.com/api/pets",
                "body": {
                    "name": "Max",
                    "species": "dog",
                    "breed": "Labrador",
                    "age": 2,
                },
            },
        )

        assert result.structured_content["name"] == "Max"
        assert result.structured_content["species"] == "dog"
        assert "id" in result.structured_content

    async def test_put_tool_with_path_params(self, server_and_client):
        """Test PUT tool execution with path parameters."""
        server, mcp_client = server_and_client

        result = await mcp_client.call_tool(
            "PUT",
            {
                "url": "https://petstore.example.com/api/pets/1",
                "body": {"status": "pending"},
            },
        )

        assert result.structured_content["id"] == 1
        assert result.structured_content["status"] == "pending"

    async def test_delete_tool_returns_empty_content(self, server_and_client):
        """Test DELETE tool execution returns empty content for 204."""
        server, mcp_client = server_and_client

        # Delete pet
        result = await mcp_client.call_tool(
            "DELETE", {"url": "https://petstore.example.com/api/pets/3"}
        )

        # Should return empty content for 204
        assert len(result.content) == 1
        assert result.content[0].text == ""

        # Verify pet is gone
        with pytest.raises(Exception) as exc_info:
            await mcp_client.call_tool(
                "GET", {"url": "https://petstore.example.com/api/pets/3"}
            )
        assert "404" in str(exc_info.value)

    async def test_list_resources_and_templates(self, server_and_client):
        """Test listing resources and templates through MCP client."""
        server, mcp_client = server_and_client

        # List resources
        resources = await mcp_client.list_resources()
        resource_uris = {str(r.uri) for r in resources}

        # Check resources exist (only one per path now)
        assert "https://petstore.example.com/api/pets" in resource_uris
        assert (
            len([uri for uri in resource_uris if "/pets" in uri and "{" not in uri])
            == 1
        )

        # List templates
        templates = await mcp_client.list_resource_templates()
        template_uris = {str(t.uriTemplate) for t in templates}

        # Check templates exist (only one per path now)
        assert "https://petstore.example.com/api/pets/{petId}" in template_uris
        assert len([uri for uri in template_uris if "/pets/{petId}" in uri]) == 1

    async def test_resource_merging_on_collision(self, petstore_openapi_spec):
        """Test that resources with the same path are merged into one."""
        client = httpx.AsyncClient(base_url="https://petstore.example.com/api")
        server = McpWebGateway(petstore_openapi_spec, client)

        # Get the /pets resource
        pets_resource = server._resource_manager._resources[
            "https://petstore.example.com/api/pets"
        ]

        # Check that it has both GET and POST routes
        assert hasattr(pets_resource, "_routes")
        methods = {route.method for route in pets_resource._routes}
        assert methods == {"GET", "POST"}

        # Check that tags were merged
        all_tags = set()
        for route in pets_resource._routes:
            if route.tags:
                all_tags.update(route.tags)
        assert pets_resource.tags >= all_tags

    async def test_template_merging_on_collision(self, petstore_openapi_spec):
        """Test that templates with the same path are merged into one."""
        client = httpx.AsyncClient(base_url="https://petstore.example.com/api")
        server = McpWebGateway(petstore_openapi_spec, client)

        # Get the /pets/{petId} template
        pet_template = server._resource_manager._templates[
            "https://petstore.example.com/api/pets/{petId}"
        ]

        # Check that it has GET, PUT, and DELETE routes
        assert hasattr(pet_template, "_routes")
        methods = {route.method for route in pet_template._routes}
        assert methods == {"GET", "PUT", "DELETE"}

    async def test_merged_resource_schema_contains_all_methods(
        self, petstore_openapi_spec
    ):
        """Test that reading a merged resource returns schema for all methods."""
        client = httpx.AsyncClient(base_url="https://petstore.example.com/api")
        server = McpWebGateway(petstore_openapi_spec, client)

        # Get the /pets resource which should have both GET and POST
        pets_resource = server._resource_manager._resources[
            "https://petstore.example.com/api/pets"
        ]

        # Read the schema
        schema_json = await pets_resource.read()
        schema = json.loads(schema_json)

        # Verify both methods are present
        pets_ops = schema["paths"]["/pets"]
        assert "get" in pets_ops
        assert "post" in pets_ops

        # Verify operation details are preserved
        assert pets_ops["get"]["operationId"] == "list_pets"
        assert pets_ops["post"]["operationId"] == "create_pet"
        assert "parameters" in pets_ops["get"]
        assert "requestBody" in pets_ops["post"]

    async def test_add_route_prevents_duplicates(self, petstore_openapi_spec):
        """Test that add_route doesn't add duplicate methods."""
        from fastmcp.experimental.utilities.openapi import HTTPRoute

        from mcp_web_gateway.components import WebResource

        # Create a resource with one route
        route1 = HTTPRoute(
            method="GET", path="/test", operation_id="test_get", tags=["tag1"]
        )

        resource = WebResource(
            client=httpx.AsyncClient(),
            route=route1,
            director=None,
            uri="https://example.com/test",
            name="test_resource",
            description="Test resource",
            tags={"tag1"},
        )

        # Try to add the same method
        route2 = HTTPRoute(
            method="GET", path="/test", operation_id="test_get_2", tags=["tag2"]
        )

        resource.add_route(route2)

        # Should still have only one GET route
        assert len(resource._routes) == 1
        assert resource._routes[0] == route1

        # Tags should not be updated since route wasn't added
        assert resource.tags == {"tag1"}

        # Now add a different method
        route3 = HTTPRoute(
            method="POST", path="/test", operation_id="test_post", tags=["tag3"]
        )

        resource.add_route(route3)

        # Should now have two routes
        assert len(resource._routes) == 2
        methods = {r.method for r in resource._routes}
        assert methods == {"GET", "POST"}

        # Tags should include tag3
        assert resource.tags >= {"tag1", "tag3"}


class TestMcpWebGatewayEdgeCases:
    """Test edge cases and error handling."""

    async def test_url_without_annotations_warning(self):
        """Test that URLs without annotations in registry still work but log warning."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {},
        }

        # Create mock client that will return 404
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.reason_phrase = "Not Found"
        mock_response.json.side_effect = ValueError()
        mock_response.text = "Not found"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404 Not Found", request=None, response=mock_response
        )

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)

        server = McpWebGateway(spec, mock_client)

        async with Client(server) as mcp_client:
            with pytest.raises(Exception) as exc_info:
                await mcp_client.call_tool(
                    "GET", {"url": "https://api.example.com/nonexistent"}
                )

            # Should get HTTP error, not resource not found
            assert "HTTP error 404" in str(exc_info.value)
