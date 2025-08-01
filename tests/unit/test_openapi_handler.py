"""Unit tests for OpenAPIHandler."""

import pytest

from mcp_web_gateway.openapi_handler import OpenAPIHandler


class TestBaseURLValidation:
    """Test base URL validation logic in OpenAPIHandler."""

    def test_client_url_must_match_server(self):
        """Test that client base_url must match one of the OpenAPI servers."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "servers": [
                {"url": "https://api.example.com"},
                {"url": "https://api.staging.example.com"},
            ],
            "paths": {"/test": {"get": {"responses": {"200": {"description": "OK"}}}}},
        }

        handler = OpenAPIHandler(spec)

        # Client URL that doesn't match any server should raise
        with pytest.raises(ValueError) as exc_info:
            handler.determine_base_url("https://other.example.com")

        assert "does not match any OpenAPI server" in str(exc_info.value)
        assert "api.example.com" in str(exc_info.value)

    def test_no_servers_requires_client_url(self):
        """Test that client base_url is required when no servers are defined."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {"/test": {"get": {"responses": {"200": {"description": "OK"}}}}},
        }

        handler = OpenAPIHandler(spec)

        # No servers and no client URL should raise
        with pytest.raises(ValueError) as exc_info:
            handler.determine_base_url(None)

        assert "No servers defined in OpenAPI spec" in str(exc_info.value)

    def test_no_servers_uses_client_url(self):
        """Test that client URL is used when no servers are defined."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {"/test": {"get": {"responses": {"200": {"description": "OK"}}}}},
        }

        handler = OpenAPIHandler(spec)

        # Should use client URL when no servers defined
        base_url = handler.determine_base_url("https://custom.example.com")
        assert base_url == "https://custom.example.com"

    def test_single_server_no_client_url(self):
        """Test that single server is used when no client URL provided."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "servers": [{"url": "https://api.example.com"}],
            "paths": {"/test": {"get": {"responses": {"200": {"description": "OK"}}}}},
        }

        handler = OpenAPIHandler(spec)

        # Should use the single server URL
        base_url = handler.determine_base_url(None)
        assert base_url == "https://api.example.com"

    def test_multiple_servers_uses_first(self):
        """Test that first server is used when multiple servers exist and no client URL."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "servers": [
                {"url": "https://prod.example.com"},
                {"url": "https://staging.example.com"},
            ],
            "paths": {"/test": {"get": {"responses": {"200": {"description": "OK"}}}}},
        }

        handler = OpenAPIHandler(spec)

        # Should use first server (warning is logged but we've verified that visually)
        base_url = handler.determine_base_url(None)
        assert base_url == "https://prod.example.com"

    def test_trailing_slashes_normalized(self):
        """Test that trailing slashes are normalized in URLs."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "servers": [{"url": "https://api.example.com/"}],  # With trailing slash
            "paths": {"/test": {"get": {"responses": {"200": {"description": "OK"}}}}},
        }

        handler = OpenAPIHandler(spec)

        # Client URL with trailing slash should match server without
        base_url = handler.determine_base_url("https://api.example.com/")
        assert base_url == "https://api.example.com"

    def test_invalid_server_definitions(self):
        """Test handling of invalid server definitions."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "servers": [{"description": "No URL field"}],  # Missing url field
            "paths": {"/test": {"get": {"responses": {"200": {"description": "OK"}}}}},
        }

        handler = OpenAPIHandler(spec)

        with pytest.raises(ValueError) as exc_info:
            handler.determine_base_url(None)

        assert "Invalid server definitions" in str(exc_info.value)

    def test_empty_server_list(self):
        """Test that empty server list is treated as no servers."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "servers": [],  # Empty list
            "paths": {"/test": {"get": {"responses": {"200": {"description": "OK"}}}}},
        }

        handler = OpenAPIHandler(spec)

        # Should require client URL
        with pytest.raises(ValueError) as exc_info:
            handler.determine_base_url(None)

        assert "No servers defined" in str(exc_info.value)

    def test_client_url_matching_is_case_sensitive(self):
        """Test that URL matching is case-sensitive for the domain."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "servers": [{"url": "https://API.example.com"}],
            "paths": {"/test": {"get": {"responses": {"200": {"description": "OK"}}}}},
        }

        handler = OpenAPIHandler(spec)

        # Different case should not match
        with pytest.raises(ValueError):
            handler.determine_base_url("https://api.example.com")

        # Exact case should match
        base_url = handler.determine_base_url("https://API.example.com")
        assert base_url == "https://API.example.com"


class TestLRUCache:
    """Test LRU caching functionality."""

    def test_schema_caching(self):
        """Test that get_operation_schema results are cached."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "get": {"responses": {"200": {"description": "OK"}}},
                    "post": {"responses": {"201": {"description": "Created"}}},
                }
            },
        }

        handler = OpenAPIHandler(spec)

        # Clear the cache to ensure we start fresh
        handler._get_operation_schema_cached.cache_clear()

        # First call - should hit the actual implementation
        schema1 = handler.get_operation_schema("/test", ["GET"])
        cache_info1 = handler._get_operation_schema_cached.cache_info()
        assert cache_info1.hits == 0
        assert cache_info1.misses == 1

        # Second call with same parameters - should hit cache
        schema2 = handler.get_operation_schema("/test", ["GET"])
        cache_info2 = handler._get_operation_schema_cached.cache_info()
        assert cache_info2.hits == 1
        assert cache_info2.misses == 1

        # Verify they return the same result
        assert schema1 == schema2

        # Different parameters - should miss cache
        handler.get_operation_schema("/test", ["POST"])
        cache_info3 = handler._get_operation_schema_cached.cache_info()
        assert cache_info3.hits == 1
        assert cache_info3.misses == 2

        # Same parameters as first call - should hit cache again
        handler.get_operation_schema("/test", ["GET"])
        cache_info4 = handler._get_operation_schema_cached.cache_info()
        assert cache_info4.hits == 2
        assert cache_info4.misses == 2

    def test_cache_key_includes_methods(self):
        """Test that cache key includes the methods list."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "get": {"responses": {"200": {"description": "OK"}}},
                    "post": {"responses": {"201": {"description": "Created"}}},
                    "put": {"responses": {"200": {"description": "Updated"}}},
                }
            },
        }

        handler = OpenAPIHandler(spec)

        # Different method combinations should have different cache entries
        schema_get = handler.get_operation_schema("/test", ["GET"])
        schema_post = handler.get_operation_schema("/test", ["POST"])
        schema_both = handler.get_operation_schema("/test", ["GET", "POST"])
        schema_all = handler.get_operation_schema("/test", None)

        # Each should have different operations
        assert "get" in schema_get["paths"]["/test"]
        assert "post" not in schema_get["paths"]["/test"]

        assert "post" in schema_post["paths"]["/test"]
        assert "get" not in schema_post["paths"]["/test"]

        assert "get" in schema_both["paths"]["/test"]
        assert "post" in schema_both["paths"]["/test"]
        assert "put" not in schema_both["paths"]["/test"]

        assert "get" in schema_all["paths"]["/test"]
        assert "post" in schema_all["paths"]["/test"]
        assert "put" in schema_all["paths"]["/test"]


class TestPathMatching:
    """Test path matching and sorting functionality."""

    def test_find_matching_paths_exact_match(self):
        """Test exact path matching."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/users": {"get": {"responses": {"200": {"description": "OK"}}}},
                "/users/{id}": {"get": {"responses": {"200": {"description": "OK"}}}},
                "/posts": {"get": {"responses": {"200": {"description": "OK"}}}},
            },
        }

        handler = OpenAPIHandler(spec)

        # Exact match
        matches = handler.find_matching_paths("/users")
        assert len(matches) == 1
        assert matches[0] == ("/users", {})

        # No match
        matches = handler.find_matching_paths("/unknown")
        assert len(matches) == 0

    def test_find_matching_paths_template_match(self):
        """Test template path matching with parameters."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/users/{id}": {"get": {"responses": {"200": {"description": "OK"}}}},
                "/users/{id}/posts/{postId}": {
                    "get": {"responses": {"200": {"description": "OK"}}}
                },
            },
        }

        handler = OpenAPIHandler(spec)

        # Single parameter match
        matches = handler.find_matching_paths("/users/123")
        assert len(matches) == 1
        assert matches[0] == ("/users/{id}", {"id": "123"})

        # Multiple parameter match
        matches = handler.find_matching_paths("/users/123/posts/456")
        assert len(matches) == 1
        assert matches[0] == (
            "/users/{id}/posts/{postId}",
            {"id": "123", "postId": "456"},
        )

    def test_find_matching_paths_prefix_match(self):
        """Test prefix matching for path discovery."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/api": {"get": {"responses": {"200": {"description": "OK"}}}},
                "/api/v1": {"get": {"responses": {"200": {"description": "OK"}}}},
                "/api/v2": {"get": {"responses": {"200": {"description": "OK"}}}},
                "/api/v1/users": {"get": {"responses": {"200": {"description": "OK"}}}},
                "/users": {"get": {"responses": {"200": {"description": "OK"}}}},
            },
        }

        handler = OpenAPIHandler(spec)

        # Prefix match for /api
        matches = handler.find_matching_paths("/api", prefix_match=True)
        paths = [path for path, _ in matches]
        assert "/api" in paths
        assert "/api/v1" in paths
        assert "/api/v2" in paths
        assert "/api/v1/users" in paths
        assert "/users" not in paths

    def test_find_matching_paths_breadth_first_order(self):
        """Test that routes are sorted in breadth-first lexicographical order."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
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

        handler = OpenAPIHandler(spec)

        # Get all routes
        matches = handler.find_matching_paths("/", prefix_match=True)
        paths = [path for path, _ in matches]

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

    def test_find_matching_paths_with_root_path(self):
        """Test sorting handles root path correctly."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/": {"get": {"responses": {"200": {"description": "OK"}}}},
                "/api": {"get": {"responses": {"200": {"description": "OK"}}}},
                "/users": {"get": {"responses": {"200": {"description": "OK"}}}},
                "/api/v1": {"get": {"responses": {"200": {"description": "OK"}}}},
            },
        }

        handler = OpenAPIHandler(spec)

        matches = handler.find_matching_paths("/", prefix_match=True)
        paths = [path for path, _ in matches]

        # Root should come first (depth 0), then depth 1, then depth 2
        expected_order = [
            "/",  # Depth 0
            "/api",  # Depth 1
            "/users",  # Depth 1
            "/api/v1",  # Depth 2
        ]

        assert paths == expected_order

    def test_extract_path_from_url(self):
        """Test extracting OpenAPI path from full URL."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {},
        }

        handler = OpenAPIHandler(spec)

        # Simple case
        path = handler.extract_path_from_url(
            "https://api.example.com/users/123", "https://api.example.com"
        )
        assert path == "/users/123"

        # With base path
        path = handler.extract_path_from_url(
            "https://api.example.com/api/v1/users", "https://api.example.com/api/v1"
        )
        assert path == "/users"

        # Root path
        path = handler.extract_path_from_url(
            "https://api.example.com/", "https://api.example.com"
        )
        assert path == "/"

        # With query parameters (should be preserved)
        path = handler.extract_path_from_url(
            "https://api.example.com/users?filter=active", "https://api.example.com"
        )
        assert path == "/users"
