"""Tests for OpenAPI utilities module."""

import pytest

from mcp_web_gateway.openapi_utils import OpenAPISchemaExtractor, PathMatcher


class TestOpenAPISchemaExtractor:
    """Test OpenAPI schema extraction functionality."""

    @pytest.fixture
    def extractor(self, petstore_openapi_spec):
        """Create an extractor with the petstore spec."""
        return OpenAPISchemaExtractor(petstore_openapi_spec)

    def test_extract_path_schema_all_methods(self, extractor):
        """Test extracting schema for all methods on a path."""
        schema = extractor.extract_path_schema("/pets")

        assert "openapi" in schema
        assert schema["openapi"] == "3.0.0"
        assert "paths" in schema
        assert "/pets" in schema["paths"]

        pets_ops = schema["paths"]["/pets"]
        assert "get" in pets_ops
        assert "post" in pets_ops
        assert pets_ops["get"]["operationId"] == "list_pets"
        assert pets_ops["post"]["operationId"] == "create_pet"

    def test_extract_path_schema_specific_methods(self, extractor):
        """Test extracting schema for specific methods only."""
        schema = extractor.extract_path_schema("/pets", ["GET"])

        pets_ops = schema["paths"]["/pets"]
        assert "get" in pets_ops
        assert "post" not in pets_ops

    def test_extract_path_schema_invalid_path(self, extractor):
        """Test that invalid path raises ValueError."""
        with pytest.raises(ValueError, match="Path /invalid not found"):
            extractor.extract_path_schema("/invalid")

    def test_extract_all_methods_for_path(self, extractor):
        """Test getting all HTTP methods for a path."""
        methods = extractor.extract_all_methods_for_path("/pets")
        assert set(methods) == {"GET", "POST"}

        methods = extractor.extract_all_methods_for_path("/pets/{petId}")
        assert set(methods) == {"GET", "PUT", "DELETE"}

    def test_extract_all_methods_invalid_path(self, extractor):
        """Test that invalid path raises ValueError."""
        with pytest.raises(ValueError, match="Path /invalid not found"):
            extractor.extract_all_methods_for_path("/invalid")


class TestPathMatcher:
    """Test path matching functionality."""

    def test_normalize_url(self):
        """Test URL normalization."""
        assert PathMatcher.normalize_url("http://example.com/") == "http://example.com"
        assert PathMatcher.normalize_url("http://example.com") == "http://example.com"
        assert PathMatcher.normalize_url("/api/pets/") == "/api/pets"
        assert PathMatcher.normalize_url("/api/pets") == "/api/pets"

    def test_find_matching_paths(self):
        """Test finding paths that match a prefix."""
        paths = {
            "/api/users": {},
            "/api/users/{id}": {},
            "/api/posts": {},
            "/users": {},
        }

        matches = PathMatcher.find_matching_paths(paths, "/api/users")
        assert set(matches) == {"/api/users", "/api/users/{id}"}

        matches = PathMatcher.find_matching_paths(paths, "/api")
        assert set(matches) == {"/api/users", "/api/users/{id}", "/api/posts"}

        matches = PathMatcher.find_matching_paths(paths, "/users")
        assert set(matches) == {"/users"}

    def test_find_matching_paths_with_normalization(self):
        """Test that path matching handles trailing slashes."""
        paths = {
            "/api/users": {},
            "/api/users/{id}": {},
        }

        # With trailing slash in prefix
        matches = PathMatcher.find_matching_paths(paths, "/api/users/", normalize=True)
        assert set(matches) == {"/api/users", "/api/users/{id}"}

    def test_match_template(self):
        """Test template matching functionality."""
        # Test successful match
        params = PathMatcher.match_template("/pets/123", "/pets/{petId}")
        assert params == {"petId": "123"}

        # Test no match
        params = PathMatcher.match_template("/users/123", "/pets/{petId}")
        assert params is None

    def test_create_route_info(self):
        """Test route info creation."""
        info = PathMatcher.create_route_info(
            "http://example.com/pets", ["GET", "POST"], "resource"
        )

        assert info == {
            "url": "http://example.com/pets",
            "methods": ["GET", "POST"],
            "type": "resource",
        }

    def test_empty_spec(self):
        """Test extractor with empty OpenAPI spec."""
        empty_spec = {"openapi": "3.0.0", "paths": {}}
        extractor = OpenAPISchemaExtractor(empty_spec)

        with pytest.raises(ValueError, match="Path /test not found"):
            extractor.extract_path_schema("/test")

    def test_extract_methods_case_handling(self):
        """Test that method extraction handles case correctly."""
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/test": {
                    "get": {"operationId": "get_test"},
                    "POST": {"operationId": "post_test"},  # Uppercase
                    "Put": {"operationId": "put_test"},  # Mixed case
                }
            },
        }
        extractor = OpenAPISchemaExtractor(spec)
        methods = extractor.extract_all_methods_for_path("/test")
        assert set(methods) == {"GET", "POST", "PUT"}

    def test_path_matcher_empty_paths(self):
        """Test PathMatcher with empty paths."""
        paths = {}
        matches = PathMatcher.find_matching_paths(paths, "/api")
        assert matches == []

    def test_match_template_complex_patterns(self):
        """Test template matching with complex patterns."""
        # Multiple parameters
        params = PathMatcher.match_template(
            "/users/123/posts/456", "/users/{userId}/posts/{postId}"
        )
        assert params == {"userId": "123", "postId": "456"}

        # Parameter with special characters
        params = PathMatcher.match_template("/users/user@example.com", "/users/{email}")
        assert params == {"email": "user@example.com"}
