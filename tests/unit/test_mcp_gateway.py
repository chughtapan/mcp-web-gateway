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

    async def test_rest_tools_include_options(self, petstore_openapi_spec):
        """Test that REST tools include OPTIONS method."""
        client = httpx.AsyncClient(base_url="https://petstore.example.com/api")
        server = McpWebGateway(petstore_openapi_spec, client)

        async with Client(server) as mcp_client:
            tools = await mcp_client.list_tools()
            tool_names = {tool.name for tool in tools}

            # Check all REST tools are present including OPTIONS
            assert "GET" in tool_names
            assert "POST" in tool_names
            assert "PUT" in tool_names
            assert "PATCH" in tool_names
            assert "DELETE" in tool_names
            assert "OPTIONS" in tool_names

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

        # Should only have the 6 REST tools (default behavior)
        assert len(tool_names) == 6
        assert set(tool_names) == {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}

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

        # Now should have the 6 REST tools
        tools = await server.get_tools()
        tool_names = list(tools.keys())
        assert len(tool_names) == 6
        assert set(tool_names) == {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}

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
        mock_response.json.return_value = [
            {"id": 1, "name": "Fluffy", "species": "cat"},
            {"id": 2, "name": "Buddy", "species": "dog"},
        ]
        mock_response.raise_for_status = Mock()

        # Create mock client
        mock_client = AsyncMock()
        mock_client.base_url = "https://petstore.example.com/api"
        mock_client.request = AsyncMock(return_value=mock_response)

        server = McpWebGateway(petstore_openapi_spec, mock_client)

        # Use plain URL without method prefix - use /pets which is a registered resource
        async with Client(server) as client:
            result = await client.call_tool(
                "GET", {"url": "https://petstore.example.com/api/pets"}  # Plain URL
            )

        # Check the request was made correctly
        mock_client.request.assert_called_once_with(
            method="GET",
            url="https://petstore.example.com/api/pets",
        )

        # Check the result (arrays are wrapped)
        assert "result" in result.structured_content
        pets = result.structured_content["result"]
        assert len(pets) == 2
        assert pets[0]["name"] == "Fluffy"

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

        # Create a simple OpenAPI spec for testing
        test_openapi_spec = {
            "openapi": "3.0.0",
            "paths": {
                "/test": {
                    "get": {
                        "operationId": "test_get",
                        "summary": "Test GET",
                        "tags": ["tag1"],
                    },
                    "post": {
                        "operationId": "test_post",
                        "summary": "Test POST",
                        "tags": ["tag3"],
                    },
                }
            },
        }

        # Extract schema for the resource
        schema = {
            "openapi": "3.0.0",
            "paths": {"/test": {"get": test_openapi_spec["paths"]["/test"]["get"]}},
        }

        resource = WebResource(
            route=route1,
            uri="https://example.com/test",
            name="test_resource",
            description="Test resource",
            tags={"tag1"},
            meta=schema,
        )

        # Try to add the same method
        route2 = HTTPRoute(
            method="GET", path="/test", operation_id="test_get_2", tags=["tag2"]
        )

        # Extract method schema for the route
        method_schema = test_openapi_spec["paths"]["/test"]["get"]
        resource.add_route(route2, method_schema)

        # Should still have only one GET route
        assert len(resource._routes) == 1
        assert resource._routes[0] == route1

        # Tags should not be updated since route wasn't added
        assert resource.tags == {"tag1"}

        # Now add a different method
        route3 = HTTPRoute(
            method="POST", path="/test", operation_id="test_post", tags=["tag3"]
        )

        # Extract method schema for the route
        method_schema = test_openapi_spec["paths"]["/test"]["post"]
        resource.add_route(route3, method_schema)

        # Should now have two routes
        assert len(resource._routes) == 2
        methods = {r.method for r in resource._routes}
        assert methods == {"GET", "POST"}

        # Tags should include tag3
        assert resource.tags >= {"tag1", "tag3"}


class TestMcpWebGatewayEdgeCases:
    """Test edge cases and error handling."""

    async def test_url_without_resources_in_spec(self):
        """Test that URLs are rejected in closed-world mode when spec has no paths."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {},
        }

        mock_client = AsyncMock()
        mock_client.base_url = "https://api.example.com"

        server = McpWebGateway(spec, mock_client)

        async with Client(server) as mcp_client:
            with pytest.raises(Exception) as exc_info:
                await mcp_client.call_tool(
                    "GET", {"url": "https://api.example.com/nonexistent"}
                )

            # In closed-world mode, should reject unknown resources
            assert "does not match any known resource" in str(exc_info.value)

    @pytest.fixture
    def complex_spec(self):
        """Create a complex OpenAPI spec with various edge cases."""
        return {
            "openapi": "3.0.0",
            "info": {"title": "Complex API", "version": "1.0.0"},
            "servers": [{"url": "https://api.example.com"}],
            "paths": {
                "/": {
                    "get": {
                        "operationId": "get_root",
                        "responses": {"200": {"description": "Success"}},
                    }
                },
                "/api": {
                    "get": {
                        "operationId": "get_api",
                        "responses": {"200": {"description": "Success"}},
                    }
                },
                "/api/v1": {
                    "get": {
                        "operationId": "get_v1",
                        "responses": {"200": {"description": "Success"}},
                    }
                },
                "/api/v1/users": {
                    "get": {
                        "operationId": "list_users",
                        "responses": {"200": {"description": "Success"}},
                    },
                    "post": {
                        "operationId": "create_user",
                        "responses": {"201": {"description": "Created"}},
                    },
                },
                "/api/v1/users/{userId}": {
                    "get": {
                        "operationId": "get_user",
                        "parameters": [
                            {
                                "name": "userId",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"},
                            }
                        ],
                        "responses": {"200": {"description": "Success"}},
                    }
                },
                "/special%20path": {
                    "get": {
                        "operationId": "get_special",
                        "responses": {"200": {"description": "Success"}},
                    }
                },
                "/unicode/测试": {
                    "get": {
                        "operationId": "get_unicode",
                        "responses": {"200": {"description": "Success"}},
                    }
                },
            },
        }

    async def test_options_root_path(self, complex_spec):
        """Test OPTIONS on root path."""
        mock_client = AsyncMock()
        mock_client.base_url = "https://api.example.com"

        server = McpWebGateway(complex_spec, mock_client)

        async with Client(server) as mcp_client:
            # Exact match on root
            result = await mcp_client.call_tool(
                "OPTIONS", {"url": "https://api.example.com/"}
            )

            # Should return schema for root path
            assert "openapi" in result.structured_content
            assert "/" in result.structured_content["paths"]

    async def test_options_hierarchical_paths(self, complex_spec):
        """Test OPTIONS with hierarchical path structure."""
        mock_client = AsyncMock()
        mock_client.base_url = "https://api.example.com"

        server = McpWebGateway(complex_spec, mock_client)

        async with Client(server) as mcp_client:
            # Test prefix matching at different levels
            result1 = await mcp_client.call_tool(
                "OPTIONS", {"url": "https://api.example.com/api/v"}
            )
            routes1 = result1.structured_content["matching_routes"]

            # Should match /api/v1 and its sub-paths
            assert len(routes1) == 3  # /api/v1, /api/v1/users, /api/v1/users/{userId}

            # Verify ordering (breadth-first)
            urls = [r["url"] for r in routes1]
            assert urls[0] == "https://api.example.com/api/v1"  # Depth 2
            assert urls[1] == "https://api.example.com/api/v1/users"  # Depth 3
            assert urls[2] == "https://api.example.com/api/v1/users/{userId}"  # Depth 4

    async def test_options_special_characters_in_path(self, complex_spec):
        """Test OPTIONS with special characters in URL."""
        mock_client = AsyncMock()
        mock_client.base_url = "https://api.example.com"

        server = McpWebGateway(complex_spec, mock_client)

        async with Client(server) as mcp_client:
            # Test URL with encoded space
            result = await mcp_client.call_tool(
                "OPTIONS", {"url": "https://api.example.com/special%20path"}
            )

            # Should return schema
            assert "openapi" in result.structured_content
            assert "/special%20path" in result.structured_content["paths"]

    async def test_options_unicode_in_path(self, complex_spec):
        """Test OPTIONS with Unicode characters in URL."""
        mock_client = AsyncMock()
        mock_client.base_url = "https://api.example.com"

        server = McpWebGateway(complex_spec, mock_client)

        async with Client(server) as mcp_client:
            # Test URL with Unicode characters
            result = await mcp_client.call_tool(
                "OPTIONS", {"url": "https://api.example.com/unicode/测试"}
            )

            # Should return schema
            assert "openapi" in result.structured_content
            assert "/unicode/测试" in result.structured_content["paths"]


class TestOpenWorldBehavior:
    """Test open_world parameter behavior for REST tools."""

    @pytest.fixture
    def minimal_spec(self):
        """Create a minimal OpenAPI spec with one resource."""
        return {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0"},
            "paths": {
                "/users": {
                    "get": {
                        "operationId": "list_users",
                        "responses": {"200": {"description": "Success"}},
                    }
                }
            },
        }

    async def test_closed_world_blocks_unknown_resources(self, minimal_spec):
        """Test that closed-world mode (default) blocks access to unknown resources."""
        mock_client = AsyncMock()
        mock_client.base_url = "https://api.example.com"

        # Create server with default open_world=False
        server = McpWebGateway(minimal_spec, mock_client)

        async with Client(server) as mcp_client:
            # Try to access a resource that doesn't exist in the spec
            with pytest.raises(Exception) as exc_info:
                await mcp_client.call_tool(
                    "GET", {"url": "https://api.example.com/unknown"}
                )

            # Should get a clear error about resource not found
            error_msg = str(exc_info.value)
            assert "does not match any known resource" in error_msg

    async def test_open_world_allows_unknown_resources(self, minimal_spec):
        """Test that open-world mode allows access to any URL."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": "from unknown resource"}
        mock_response.raise_for_status = Mock()

        mock_client = AsyncMock()
        mock_client.base_url = "https://api.example.com"
        mock_client.request = AsyncMock(return_value=mock_response)

        # Create server with open_world=True
        server = McpWebGateway(minimal_spec, mock_client, open_world=True)

        async with Client(server) as mcp_client:
            # Should be able to access a resource not in the spec
            result = await mcp_client.call_tool(
                "GET", {"url": "https://api.example.com/unknown"}
            )

            assert result.structured_content == {"data": "from unknown resource"}

            # Verify the request was made
            mock_client.request.assert_called_once_with(
                method="GET",
                url="https://api.example.com/unknown",
            )

    async def test_tool_annotations_reflect_open_world_setting(self, minimal_spec):
        """Test that tool annotations correctly reflect the open_world setting."""
        # Create a proper mock client with base_url
        mock_client = AsyncMock()
        mock_client.base_url = "https://api.example.com"

        # Test with default (closed world)
        server_closed = McpWebGateway(minimal_spec, mock_client)
        async with Client(server_closed) as mcp_client:
            tools = await mcp_client.list_tools()
            get_tool = next(t for t in tools if t.name == "GET")
            assert get_tool.annotations is not None
            assert get_tool.annotations.openWorldHint is False

        # Test with open world
        server_open = McpWebGateway(minimal_spec, mock_client, open_world=True)
        async with Client(server_open) as mcp_client:
            tools = await mcp_client.list_tools()
            get_tool = next(t for t in tools if t.name == "GET")
            assert get_tool.annotations is not None
            assert get_tool.annotations.openWorldHint is True

    async def test_from_fastapi_respects_open_world_parameter(self):
        """Test that from_fastapi method respects the open_world parameter."""
        from fastapi import FastAPI

        app = FastAPI()

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        # Create with default (closed world)
        mcp_closed = McpWebGateway.from_fastapi(app)
        async with Client(mcp_closed) as mcp_client:
            tools = await mcp_client.list_tools()
            get_tool = next(t for t in tools if t.name == "GET")
            assert get_tool.annotations.openWorldHint is False

        # Create with open world
        mcp_open = McpWebGateway.from_fastapi(app, open_world=True)
        async with Client(mcp_open) as mcp_client:
            tools = await mcp_client.list_tools()
            get_tool = next(t for t in tools if t.name == "GET")
            assert get_tool.annotations.openWorldHint is True

    async def test_closed_world_with_no_resources_shows_helpful_message(self):
        """Test that closed-world mode with no resources shows a helpful error message."""
        empty_spec = {
            "openapi": "3.0.0",
            "info": {"title": "Empty API", "version": "1.0"},
            "paths": {},
        }

        mock_client = AsyncMock()
        mock_client.base_url = "https://api.example.com"

        server = McpWebGateway(empty_spec, mock_client)

        async with Client(server) as mcp_client:
            with pytest.raises(Exception) as exc_info:
                await mcp_client.call_tool(
                    "GET", {"url": "https://api.example.com/anything"}
                )

            error_msg = str(exc_info.value)
            assert "does not match any known resource" in error_msg


class TestOptionsMethod:
    """Test OPTIONS method functionality."""

    @pytest.fixture
    def petstore_spec_with_options(self, petstore_openapi_spec):
        """Create a petstore spec with OPTIONS method defined."""
        spec = petstore_openapi_spec.copy()
        spec["paths"]["/pets"]["options"] = {
            "operationId": "options_pets",
            "summary": "Get CORS headers for pets endpoint",
            "responses": {
                "200": {
                    "description": "Success",
                    "headers": {
                        "Allow": {"description": "Allowed methods"},
                        "Access-Control-Allow-Origin": {"description": "CORS origin"},
                    },
                }
            },
        }
        return spec

    async def test_options_with_defined_method(self, petstore_spec_with_options):
        """Test OPTIONS when it's explicitly defined in the OpenAPI spec."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        mock_response.headers = {
            "Allow": "GET, POST, OPTIONS",
            "Access-Control-Allow-Origin": "*",
        }
        mock_response.raise_for_status = Mock()

        mock_client = AsyncMock()
        mock_client.base_url = "https://petstore.example.com/api"
        mock_client.request = AsyncMock(return_value=mock_response)

        server = McpWebGateway(petstore_spec_with_options, mock_client)

        async with Client(server) as mcp_client:
            await mcp_client.call_tool(
                "OPTIONS", {"url": "https://petstore.example.com/api/pets"}
            )

            # Should have made an OPTIONS request
            mock_client.request.assert_called_once_with(
                method="OPTIONS",
                url="https://petstore.example.com/api/pets",
            )

    async def test_options_exact_match_returns_schema(self, petstore_openapi_spec):
        """Test OPTIONS returns schema for exact resource match without OPTIONS method."""
        mock_client = AsyncMock()
        mock_client.base_url = "https://petstore.example.com/api"

        server = McpWebGateway(petstore_openapi_spec, mock_client)

        async with Client(server) as mcp_client:
            result = await mcp_client.call_tool(
                "OPTIONS", {"url": "https://petstore.example.com/api/pets"}
            )

            # Should return the OpenAPI schema
            assert result.structured_content["openapi"] == "3.0.0"
            assert "paths" in result.structured_content
            assert "/pets" in result.structured_content["paths"]

            # Check both GET and POST are documented
            pets_path = result.structured_content["paths"]["/pets"]
            assert "get" in pets_path
            assert "post" in pets_path
            assert pets_path["get"]["operationId"] == "list_pets"
            assert pets_path["post"]["operationId"] == "create_pet"

    async def test_options_prefix_match(self, petstore_openapi_spec):
        """Test OPTIONS with prefix matching returns list of matching routes."""
        mock_client = AsyncMock()
        mock_client.base_url = "https://petstore.example.com/api"

        server = McpWebGateway(petstore_openapi_spec, mock_client)

        async with Client(server) as mcp_client:
            # Use base API URL as prefix
            result = await mcp_client.call_tool(
                "OPTIONS", {"url": "https://petstore.example.com/api/"}
            )

            # Should return matching routes
            assert "matching_routes" in result.structured_content
            assert "description" in result.structured_content
            assert "Routes matching prefix:" in result.structured_content["description"]

            routes = result.structured_content["matching_routes"]
            assert len(routes) == 2  # /pets and /pets/{petId}

            # Check /pets resource
            pets_route = next(r for r in routes if r["url"].endswith("/pets"))
            assert pets_route["type"] == "resource"
            assert set(pets_route["methods"]) == {"GET", "POST"}

            # Check /pets/{petId} template
            pet_id_route = next(r for r in routes if "{petId}" in r["url"])
            assert pet_id_route["type"] == "template"
            assert set(pet_id_route["methods"]) == {"GET", "PUT", "DELETE"}

    async def test_options_partial_path_prefix(self, petstore_openapi_spec):
        """Test OPTIONS with partial path as prefix."""
        mock_client = AsyncMock()
        mock_client.base_url = "https://petstore.example.com/api"

        server = McpWebGateway(petstore_openapi_spec, mock_client)

        async with Client(server) as mcp_client:
            # Use partial path
            result = await mcp_client.call_tool(
                "OPTIONS", {"url": "https://petstore.example.com/api/pet"}
            )

            # Should return both /pets routes since "pet" is a prefix of "pets"
            assert "matching_routes" in result.structured_content
            routes = result.structured_content["matching_routes"]
            assert len(routes) == 2
            assert all("/pets" in r["url"] for r in routes)

    async def test_options_no_matches(self, petstore_openapi_spec):
        """Test OPTIONS when no resources match the URL."""
        mock_client = AsyncMock()
        mock_client.base_url = "https://petstore.example.com/api"

        server = McpWebGateway(petstore_openapi_spec, mock_client)

        async with Client(server) as mcp_client:
            with pytest.raises(Exception) as exc_info:
                await mcp_client.call_tool(
                    "OPTIONS", {"url": "https://petstore.example.com/api/users"}
                )

            assert "No resources found matching URL" in str(exc_info.value)

    async def test_options_open_world_mode(self):
        """Test OPTIONS in open-world mode for external URLs."""
        minimal_spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/internal": {
                    "get": {
                        "operationId": "get_internal",
                        "responses": {"200": {"description": "Success"}},
                    }
                }
            },
        }

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        mock_response.headers = {"Allow": "GET, POST, PUT, DELETE, OPTIONS"}
        mock_response.raise_for_status = Mock()

        mock_client = AsyncMock()
        mock_client.base_url = "https://api.example.com"
        mock_client.request = AsyncMock(return_value=mock_response)

        # Create server with open_world=True
        server = McpWebGateway(minimal_spec, mock_client, open_world=True)

        async with Client(server) as mcp_client:
            # Try OPTIONS on external URL
            await mcp_client.call_tool(
                "OPTIONS", {"url": "https://external.com/api/resource"}
            )

            # Should have made the OPTIONS request
            mock_client.request.assert_called_once_with(
                method="OPTIONS",
                url="https://external.com/api/resource",
            )

    async def test_options_with_query_parameters(self, petstore_spec_with_options):
        """Test OPTIONS with query parameters when method is defined."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        mock_response.raise_for_status = Mock()

        mock_client = AsyncMock()
        mock_client.base_url = "https://petstore.example.com/api"
        mock_client.request = AsyncMock(return_value=mock_response)

        server = McpWebGateway(petstore_spec_with_options, mock_client)

        async with Client(server) as mcp_client:
            await mcp_client.call_tool(
                "OPTIONS",
                {
                    "url": "https://petstore.example.com/api/pets",
                    "params": {"format": "json"},
                },
            )

            # Should pass query parameters
            mock_client.request.assert_called_once_with(
                method="OPTIONS",
                url="https://petstore.example.com/api/pets",
                params={"format": "json"},
            )

    async def test_options_template_exact_match(self, petstore_openapi_spec):
        """Test OPTIONS on a template URL returns schema."""
        mock_client = AsyncMock()
        mock_client.base_url = "https://petstore.example.com/api"

        server = McpWebGateway(petstore_openapi_spec, mock_client)

        async with Client(server) as mcp_client:
            # OPTIONS on the template itself (not an instance)
            result = await mcp_client.call_tool(
                "OPTIONS", {"url": "https://petstore.example.com/api/pets/{petId}"}
            )

            # Should return schema with all template methods
            assert "openapi" in result.structured_content
            assert "paths" in result.structured_content
            # The path shows the template pattern (without base URL prefix)
            assert "/pets/{petId}" in result.structured_content["paths"]

            # Check that all methods are documented
            pet_operations = result.structured_content["paths"]["/pets/{petId}"]
            assert "get" in pet_operations
            assert "put" in pet_operations
            assert "delete" in pet_operations


class TestPathSorting:
    """Test path sorting functionality."""

    async def test_find_matching_routes_breadth_first_order(self):
        """Test that routes are sorted in breadth-first lexicographical order."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "servers": [{"url": "https://api.example.com"}],
            "paths": {
                "/users": {"get": {"responses": {"200": {"description": "OK"}}}},
                "/posts": {"get": {"responses": {"200": {"description": "OK"}}}},
                "/api": {"get": {"responses": {"200": {"description": "OK"}}}},
                "/users/{id}": {"get": {"responses": {"200": {"description": "OK"}}}},
                "/posts/{id}": {"get": {"responses": {"200": {"description": "OK"}}}},
                "/api/v1": {"get": {"responses": {"200": {"description": "OK"}}}},
                "/api/v2": {"get": {"responses": {"200": {"description": "OK"}}}},
                "/users/{id}/posts": {
                    "get": {"responses": {"200": {"description": "OK"}}}
                },
                "/api/v1/users": {"get": {"responses": {"200": {"description": "OK"}}}},
            },
        }

        client = httpx.AsyncClient(base_url="https://api.example.com")
        server = McpWebGateway(spec, client)

        # Get all routes
        routes = server._find_matching_routes("https://api.example.com/")

        # Extract just the paths for easier verification
        paths = [r["url"].replace("https://api.example.com", "") for r in routes]

        # Expected order: breadth-first, lexicographical within each depth
        # Depth 1: /api, /posts, /users
        # Depth 2: /api/v1, /api/v2, /posts/{id}, /users/{id}
        # Depth 3: /api/v1/users, /users/{id}/posts
        expected_order = [
            "/api",
            "/posts",
            "/users",
            "/api/v1",
            "/api/v2",
            "/posts/{id}",
            "/users/{id}",
            "/api/v1/users",
            "/users/{id}/posts",
        ]

        assert paths == expected_order

    async def test_find_matching_routes_with_root_path(self):
        """Test sorting handles root path correctly."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "servers": [{"url": "https://api.example.com"}],
            "paths": {
                "/": {"get": {"responses": {"200": {"description": "OK"}}}},
                "/api": {"get": {"responses": {"200": {"description": "OK"}}}},
                "/users": {"get": {"responses": {"200": {"description": "OK"}}}},
                "/api/v1": {"get": {"responses": {"200": {"description": "OK"}}}},
            },
        }

        client = httpx.AsyncClient(base_url="https://api.example.com")
        server = McpWebGateway(spec, client)

        routes = server._find_matching_routes("https://api.example.com/")
        paths = [r["url"].replace("https://api.example.com", "") for r in routes]

        # Root should come first (depth 0), then depth 1, then depth 2
        expected_order = [
            "/",  # Depth 0
            "/api",  # Depth 1
            "/users",  # Depth 1
            "/api/v1",  # Depth 2
        ]

        assert paths == expected_order
