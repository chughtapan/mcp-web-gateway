"""OpenAPI utilities for schema extraction and path matching.

This module provides utilities for working with OpenAPI specifications,
leveraging existing FastMCP functionality where possible.
"""

from typing import Any

from fastmcp.resources.template import match_uri_template
from fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)


class OpenAPISchemaExtractor:
    """Extracts and manipulates OpenAPI schemas."""

    def __init__(self, openapi_spec: dict[str, Any]):
        """Initialize with an OpenAPI specification.

        Args:
            openapi_spec: Complete OpenAPI specification dictionary
        """
        self._spec = openapi_spec
        self._openapi_version = openapi_spec.get("openapi", "3.0.0")

    def extract_path_schema(
        self, path: str, methods: list[str] | None = None
    ) -> dict[str, Any]:
        """Extract schema for a specific path and optionally specific methods.

        Args:
            path: The path to extract schema for (e.g., "/pets")
            methods: Optional list of HTTP methods to include (e.g., ["GET", "POST"])
                    If None, includes all available methods

        Returns:
            A minimal OpenAPI spec containing only the requested path and methods

        Raises:
            ValueError: If the path is not found in the OpenAPI spec
        """
        # Create a minimal OpenAPI spec
        schema: dict[str, Any] = {
            "openapi": self._openapi_version,
            "paths": {},
        }

        # Get paths from the spec
        original_paths = self._spec.get("paths", {})
        if path not in original_paths:
            raise ValueError(f"Path {path} not found in OpenAPI spec")

        # Get the path item
        original_path_item = original_paths[path]
        if not isinstance(original_path_item, dict):
            raise ValueError(f"Invalid path item for {path}")

        # Extract methods
        path_item = {}
        if methods is None:
            # Include all methods except special keys
            for key, value in original_path_item.items():
                if key.lower() in [
                    "get",
                    "post",
                    "put",
                    "patch",
                    "delete",
                    "options",
                    "head",
                    "trace",
                ]:
                    path_item[key] = value
        else:
            # Include only specified methods
            for method in methods:
                method_lower = method.lower()
                if method_lower in original_path_item:
                    path_item[method_lower] = original_path_item[method_lower]

        schema["paths"][path] = path_item
        return schema

    def extract_all_methods_for_path(self, path: str) -> list[str]:
        """Get all HTTP methods available for a path.

        Args:
            path: The path to check

        Returns:
            List of HTTP methods (uppercase) available for the path

        Raises:
            ValueError: If the path is not found
        """
        original_paths = self._spec.get("paths", {})
        if path not in original_paths:
            raise ValueError(f"Path {path} not found in OpenAPI spec")

        path_item = original_paths[path]
        if not isinstance(path_item, dict):
            return []

        methods = []
        for key in path_item.keys():
            if key.lower() in [
                "get",
                "post",
                "put",
                "patch",
                "delete",
                "options",
                "head",
                "trace",
            ]:
                methods.append(key.upper())

        return methods


class PathMatcher:
    """Utilities for path matching and normalization."""

    @staticmethod
    def normalize_url(url: str) -> str:
        """Normalize URL by removing trailing slash for consistent comparison.

        Args:
            url: URL to normalize

        Returns:
            Normalized URL without trailing slash
        """
        return url.rstrip("/")

    @staticmethod
    def find_matching_paths(
        paths: dict[str, Any], prefix: str, normalize: bool = True
    ) -> list[str]:
        """Find all paths that match a given prefix.

        Args:
            paths: Dictionary of paths (URLs or templates)
            prefix: Prefix to match against
            normalize: Whether to normalize URLs before comparison

        Returns:
            List of matching paths
        """
        if normalize:
            normalized_prefix = PathMatcher.normalize_url(prefix)
        else:
            normalized_prefix = prefix

        matches = []
        for path in paths.keys():
            if normalize:
                normalized_path = PathMatcher.normalize_url(path)
            else:
                normalized_path = path

            if normalized_path.startswith(normalized_prefix):
                matches.append(path)

        return matches

    @staticmethod
    def match_template(url: str, template: str) -> dict[str, str] | None:
        """Check if a URL matches a template pattern.

        This is a wrapper around FastMCP's match_uri_template for consistency.

        Args:
            url: The URL to check
            template: The template pattern (e.g., "/pets/{petId}")

        Returns:
            Dictionary of matched parameters or None if no match
        """
        return match_uri_template(url, template)

    @staticmethod
    def create_route_info(
        url: str, methods: list[str], component_type: str = "resource"
    ) -> dict[str, Any]:
        """Create a standardized route information dictionary.

        Args:
            url: The URL or URL template
            methods: List of HTTP methods available
            component_type: Type of component ("resource" or "template")

        Returns:
            Route information dictionary
        """
        return {
            "url": url,
            "methods": methods,
            "type": component_type,
        }
