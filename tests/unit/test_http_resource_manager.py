"""Unit tests for HttpResourceManager."""

from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastmcp.experimental.server.openapi.routing import MCPType, RouteMap

from mcp_web_gateway.http_resource_manager import (
    WEB_GATEWAY_ROUTE_MAPPINGS,
    HttpResourceManager,
)


class TestHttpResourceManager:
    """Test the HttpResourceManager class."""

    @pytest.fixture
    def mock_openapi_handler(self):
        """Create a mock OpenAPI handler."""
        handler = Mock()
        handler.get_path_info.return_value = (["GET"], set())
        handler.build_full_uri.return_value = "https://api.example.com/test"
        return handler

    @pytest.fixture
    def base_url(self):
        """Test base URL."""
        return "https://api.example.com"

    @pytest.fixture
    def mock_client(self):
        """Create a mock HTTP client."""
        client = Mock(spec=httpx.AsyncClient)
        client.request = AsyncMock()
        return client

    def test_default_route_mappings(self, mock_openapi_handler, base_url, mock_client):
        """Test that default route mappings are correct."""
        mapper = HttpResourceManager(mock_openapi_handler, base_url, mock_client)

        # Should use default mappings
        assert mapper._route_maps == WEB_GATEWAY_ROUTE_MAPPINGS
        assert len(mapper._route_maps) == 2

    def test_custom_route_mappings(self, mock_openapi_handler, base_url, mock_client):
        """Test using custom route mappings."""
        custom_maps = [
            RouteMap(
                methods="*",
                pattern=r".*",
                mcp_type=MCPType.RESOURCE,
            ),
        ]

        mapper = HttpResourceManager(
            mock_openapi_handler, base_url, mock_client, custom_maps
        )
        assert mapper._route_maps == custom_maps

    def test_validate_route_maps_rejects_tools(
        self, mock_openapi_handler, base_url, mock_client
    ):
        """Test that route maps creating tools are rejected."""
        invalid_maps = [
            RouteMap(
                methods="*",
                pattern=r".*",
                mcp_type=MCPType.TOOL,
            ),
        ]

        with pytest.raises(ValueError) as exc_info:
            HttpResourceManager(
                mock_openapi_handler, base_url, mock_client, invalid_maps
            )

        assert "only supports RESOURCE and RESOURCE_TEMPLATE" in str(exc_info.value)

    def test_has_path_parameters(self, mock_openapi_handler, base_url, mock_client):
        """Test path parameter detection."""
        mapper = HttpResourceManager(mock_openapi_handler, base_url, mock_client)

        # Paths with parameters
        assert mapper._has_path_parameters("/users/{id}")
        assert mapper._has_path_parameters("/users/{id}/posts/{postId}")
        assert mapper._has_path_parameters("/{param}")

        # Paths without parameters
        assert not mapper._has_path_parameters("/users")
        assert not mapper._has_path_parameters("/users/123")
        assert not mapper._has_path_parameters("/")
        assert not mapper._has_path_parameters("/users{")
        assert not mapper._has_path_parameters("/users}")

    def test_extract_path_parameters(self, mock_openapi_handler, base_url, mock_client):
        """Test extracting path parameter schemas."""
        mapper = HttpResourceManager(mock_openapi_handler, base_url, mock_client)

        # Single parameter
        schema = mapper._extract_path_parameters("/users/{id}")
        assert schema["type"] == "object"
        assert "id" in schema["properties"]
        assert schema["properties"]["id"]["type"] == "string"
        assert schema["required"] == ["id"]

        # Multiple parameters
        schema = mapper._extract_path_parameters("/users/{userId}/posts/{postId}")
        assert "userId" in schema["properties"]
        assert "postId" in schema["properties"]
        assert set(schema["required"]) == {"userId", "postId"}

        # No parameters
        schema = mapper._extract_path_parameters("/users")
        assert schema == {}

    def test_classify_path_with_parameters(
        self, mock_openapi_handler, base_url, mock_client
    ):
        """Test path classification for paths with parameters."""
        mapper = HttpResourceManager(mock_openapi_handler, base_url, mock_client)

        # Mock the get_path_info to return some methods
        mock_openapi_handler.get_path_info.return_value = (["GET", "PUT"], set())

        # Path with parameters should be RESOURCE_TEMPLATE
        mcp_type = mapper._classify_path("/users/{id}")
        assert mcp_type == MCPType.RESOURCE_TEMPLATE

    def test_classify_path_without_parameters(
        self, mock_openapi_handler, base_url, mock_client
    ):
        """Test path classification for paths without parameters."""
        mapper = HttpResourceManager(mock_openapi_handler, base_url, mock_client)

        # Mock the get_path_info to return some methods
        mock_openapi_handler.get_path_info.return_value = (["GET", "POST"], set())

        # Path without parameters should be RESOURCE
        mcp_type = mapper._classify_path("/users")
        assert mcp_type == MCPType.RESOURCE

    def test_classify_path_with_method_filter(
        self, mock_openapi_handler, base_url, mock_client
    ):
        """Test path classification with method filtering."""
        custom_maps = [
            RouteMap(
                methods=["GET"],
                pattern=r".*",
                mcp_type=MCPType.RESOURCE,
            ),
            RouteMap(
                methods=["POST"],
                pattern=r".*",
                mcp_type=MCPType.RESOURCE_TEMPLATE,
            ),
        ]

        mapper = HttpResourceManager(
            mock_openapi_handler, base_url, mock_client, custom_maps
        )

        # GET should match first rule
        mock_openapi_handler.get_path_info.return_value = (["GET"], set())
        assert mapper._classify_path("/test") == MCPType.RESOURCE

        # POST should match second rule
        mock_openapi_handler.get_path_info.return_value = (["POST"], set())
        assert mapper._classify_path("/test") == MCPType.RESOURCE_TEMPLATE

        # PUT doesn't match any rule, should default to RESOURCE
        mock_openapi_handler.get_path_info.return_value = (["PUT"], set())
        assert mapper._classify_path("/test") == MCPType.RESOURCE

    def test_classify_path_with_tags(self, mock_openapi_handler, base_url, mock_client):
        """Test path classification with tag filtering."""
        custom_maps = [
            RouteMap(
                methods="*",
                pattern=r".*",
                tags={"admin"},
                mcp_type=MCPType.RESOURCE_TEMPLATE,
            ),
            RouteMap(
                methods="*",
                pattern=r".*",
                mcp_type=MCPType.RESOURCE,
            ),
        ]

        mapper = HttpResourceManager(
            mock_openapi_handler, base_url, mock_client, custom_maps
        )

        # With admin tag should match first rule
        mock_openapi_handler.get_path_info.return_value = (["GET"], {"admin"})
        assert mapper._classify_path("/test") == MCPType.RESOURCE_TEMPLATE

        # Without admin tag should match second rule
        mock_openapi_handler.get_path_info.return_value = (["GET"], {"user"})
        assert mapper._classify_path("/test") == MCPType.RESOURCE

        mock_openapi_handler.get_path_info.return_value = (["GET"], set())
        assert mapper._classify_path("/test") == MCPType.RESOURCE
