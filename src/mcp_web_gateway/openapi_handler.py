"""Unified OpenAPI handler for all specification operations.

This module consolidates all OpenAPI-related functionality into a single class,
providing a clean interface for path iteration, schema extraction, and routing.
"""

import re
from functools import lru_cache
from typing import Any, Iterator, Sequence
from urllib.parse import urljoin, urlparse

from fastmcp.utilities.logging import get_logger
from fastmcp.utilities.openapi import HttpMethod

logger = get_logger(__name__)

# Map lowercase string methods to HttpMethod literals
METHOD_MAP: dict[str, HttpMethod] = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "delete": "DELETE",
    "patch": "PATCH",
    "options": "OPTIONS",
    "head": "HEAD",
    "trace": "TRACE",
}


class OpenAPIHandler:
    """Unified handler for all OpenAPI specification operations."""

    def __init__(self, openapi_spec: dict[str, Any]):
        """Initialize with an OpenAPI specification.

        Args:
            openapi_spec: Complete OpenAPI specification dictionary
        """
        self.spec = openapi_spec
        self.paths = openapi_spec.get("paths", {})
        self.components = openapi_spec.get("components", {})
        self.servers = openapi_spec.get("servers", [])
        self.openapi_version = openapi_spec.get("openapi", "3.0.0")

    def determine_base_url(self, client_base_url: str | None = None) -> str:
        """Determine and validate the base URL to use.

        Args:
            client_base_url: Optional base URL from the client

        Returns:
            The validated base URL

        Raises:
            ValueError: If client URL doesn't match any server when servers are defined
        """
        # If no servers defined in spec, require client base_url
        if not self.servers:
            if not client_base_url:
                raise ValueError(
                    "No servers defined in OpenAPI spec and client has no base_url. "
                    "Either define servers in the spec or provide a client with base_url."
                )
            return client_base_url.rstrip("/")

        # Extract server URLs
        server_urls: list[str] = []
        for server in self.servers:
            if isinstance(server, dict) and "url" in server:
                url = server["url"]
                if isinstance(url, str):
                    server_urls.append(url.rstrip("/"))

        if not server_urls:
            raise ValueError("Invalid server definitions in OpenAPI spec")

        # Case 1: Client has base_url - validate against servers
        if client_base_url:
            normalized_client_url = client_base_url.rstrip("/")
            if normalized_client_url not in server_urls:
                raise ValueError(
                    f"Client base_url '{client_base_url}' does not match any OpenAPI server. "
                    f"Available servers: {', '.join(server_urls)}"
                )
            return normalized_client_url

        # Case 2: No client base_url, single server
        if len(server_urls) == 1:
            return server_urls[0]

        # Case 3: No client base_url, multiple servers
        logger.warning(
            f"Multiple servers defined in OpenAPI spec but no client base_url specified. "
            f"Using first server: {server_urls[0]}. Available servers: {', '.join(server_urls)}"
        )
        return server_urls[0]

    def _validate_path(self, path: str) -> dict[str, Any]:
        """Validate and return path item from OpenAPI spec.

        Args:
            path: The path to validate

        Returns:
            The path item dictionary

        Raises:
            ValueError: If path not found or invalid
        """
        if path not in self.paths:
            raise ValueError(f"Path {path} not found in OpenAPI spec")

        path_item = self.paths[path]
        if not isinstance(path_item, dict):
            raise ValueError(f"Invalid path item for {path}")

        return path_item

    def get_path_info(self, path: str) -> tuple[list[HttpMethod], set[str]]:
        """Get methods and tags for a specific path.

        Args:
            path: The path to get info for

        Returns:
            Tuple of (methods, tags) for the path
        """
        try:
            path_item = self._validate_path(path)
        except ValueError:
            return [], set()

        methods: list[HttpMethod] = []
        all_tags = set()

        # Extract methods and collect tags
        for method, operation in path_item.items():
            http_method = METHOD_MAP.get(method.lower())
            if http_method:
                methods.append(http_method)

                # Collect tags from this operation
                if isinstance(operation, dict):
                    tags = operation.get("tags", [])
                    if isinstance(tags, list):
                        all_tags.update(tags)

        return methods, all_tags

    def iter_paths(self) -> Iterator[str]:
        """Iterate over all paths in the specification.

        Yields:
            Path strings that have HTTP methods
        """
        for path, path_item in self.paths.items():
            if not isinstance(path_item, dict):
                continue

            # Check if this path has any HTTP methods
            has_methods = False
            for method in path_item.keys():
                if METHOD_MAP.get(method.lower()):
                    has_methods = True
                    break

            if has_methods:
                yield path

    def get_operation_schema(
        self, path: str, methods: Sequence[str] | None = None
    ) -> dict[str, Any]:
        """Get minimal OpenAPI schema for specific path and methods.

        Args:
            path: The path to extract schema for
            methods: Optional list of HTTP methods to include (all if None)

        Returns:
            Minimal OpenAPI spec containing only requested path/methods

        Raises:
            ValueError: If path not found in spec
        """
        # Convert methods to a cacheable tuple
        cache_key = (path, tuple(sorted(methods)) if methods else None)
        return self._get_operation_schema_cached(cache_key)

    @lru_cache(maxsize=128)
    def _get_operation_schema_cached(
        self, cache_key: tuple[str, tuple[HttpMethod, ...] | None]
    ) -> dict[str, Any]:
        """Cache for get_operation_schema.

        Args:
            cache_key: Tuple of (path, sorted_methods_tuple)

        Returns:
            Minimal OpenAPI spec containing only requested path/methods

        Raises:
            ValueError: If path not found in spec
        """
        path, methods_tuple = cache_key
        methods = list(methods_tuple) if methods_tuple else None

        path_item = self._validate_path(path)

        # Build minimal schema
        schema = {"openapi": self.openapi_version, "paths": {path: {}}}

        # Add requested methods or all methods
        if methods:
            for method in methods:
                method_lower = method.lower()
                if method_lower in path_item:
                    schema["paths"][path][method_lower] = path_item[method_lower]
        else:
            # Copy all HTTP methods
            for key, value in path_item.items():
                if METHOD_MAP.get(key.lower()):
                    schema["paths"][path][key] = value

        return schema

    def build_full_uri(self, base_url: str, path: str) -> str:
        """Build full URI from base URL and path.

        Args:
            base_url: Base URL (e.g., "https://api.example.com")
            path: Path (e.g., "/users")

        Returns:
            Full URI (e.g., "https://api.example.com/users")
        """
        # Ensure base_url ends with / for proper urljoin
        base = base_url.rstrip("/") + "/"
        # Remove leading / from path since urljoin will handle it
        path_clean = path.lstrip("/")
        return urljoin(base, path_clean)

    def extract_path_from_url(self, url: str, base_url: str) -> str:
        """Extract the OpenAPI path from a full URL.

        Args:
            url: Full URL to extract path from
            base_url: Base URL to remove from the path

        Returns:
            OpenAPI path (e.g., "/pets" or "/pets/123")
        """
        parsed = urlparse(url)
        path = parsed.path

        # Remove base path if present (e.g., /api/pets -> /pets)
        base_parsed = urlparse(base_url)
        if base_parsed.path and path.startswith(base_parsed.path):
            path = path[len(base_parsed.path) :]
            if not path.startswith("/"):
                path = "/" + path

        return path

    def find_matching_paths(
        self, path: str, prefix_match: bool = False
    ) -> list[tuple[str, dict[str, str]]]:
        """Find OpenAPI paths that match the given path.

        Args:
            path: The path to match (e.g., "/pets/123" or "/pets")
            prefix_match: If True, find all paths starting with the given prefix.
                         If False, find exact match (including template matching).

        Returns:
            List of tuples (openapi_path, path_params) where:
            - openapi_path is the OpenAPI spec path (e.g., "/pets/{petId}")
            - path_params are extracted parameters (e.g., {"petId": "123"})
            Empty dict for non-template paths.
        """
        matches: list[tuple[str, dict[str, str]]] = []
        normalized_path = path.rstrip("/")

        if prefix_match:
            # Find all paths that start with the given prefix
            for spec_path in self.paths:
                normalized_spec_path = spec_path.rstrip("/")
                if normalized_spec_path.startswith(normalized_path):
                    matches.append((spec_path, {}))
        else:
            # First try exact match
            if path in self.paths:
                return [(path, {})]

            # Try template matching
            for spec_path in self.paths:
                if not ("{" in spec_path and "}" in spec_path):
                    continue

                # Convert OpenAPI path to regex pattern
                pattern = spec_path
                param_names = []

                # Extract parameter names and build pattern
                for match in re.finditer(r"\{(\w+)\}", spec_path):
                    param_name = match.group(1)
                    param_names.append(param_name)
                    pattern = pattern.replace(
                        f"{{{param_name}}}", "(?P<" + param_name + ">[^/]+)"
                    )

                # Add anchors
                pattern = "^" + pattern + "$"

                # Try to match
                regex_match = re.match(pattern, path)
                if regex_match:
                    path_params = regex_match.groupdict()
                    return [(spec_path, path_params)]

        # Sort by depth for prefix matches (breadth-first)
        if matches:
            matches.sort(key=lambda x: (x[0].count("/"), x[0]))

        return matches
