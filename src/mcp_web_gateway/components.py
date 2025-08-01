"""Web resource component implementations.

These components extend the base Resource/ResourceTemplate to provide
OpenAPI schema on read() operations.
"""

import json
from typing import TYPE_CHECKING, Any

from fastmcp.resources import Resource, ResourceTemplate
from fastmcp.server import Context
from fastmcp.utilities.openapi import HttpMethod
from pydantic.networks import AnyUrl

if TYPE_CHECKING:
    from .openapi_handler import OpenAPIHandler


class HttpComponentBase:
    """Base class for HTTP components with shared properties."""

    def __init__(
        self, path: str, methods: list[HttpMethod], openapi_handler: "OpenAPIHandler"
    ):
        """Initialize base web component.

        Args:
            path: OpenAPI path (e.g., "/users")
            methods: List of HTTP methods available
            openapi_handler: Handler for OpenAPI operations
        """
        self._path = path
        self._methods = methods
        self._openapi_handler = openapi_handler

    @property
    def path(self) -> str:
        """Get the OpenAPI path for this component."""
        return self._path

    @property
    def methods(self) -> list[HttpMethod]:
        """Get the HTTP methods for this component."""
        return self._methods


class HttpResource(Resource, HttpComponentBase):
    """Resource that represents an HTTP API endpoint and returns its OpenAPI schema."""

    def __init__(
        self,
        uri: str,
        path: str,
        methods: list[HttpMethod],
        name: str,
        description: str,
        tags: set[str],
        openapi_handler: "OpenAPIHandler",
    ):
        """Initialize a web resource.

        Args:
            uri: Full URI for this resource (e.g., "https://api.example.com/users")
            path: OpenAPI path (e.g., "/users")
            methods: List of HTTP methods available
            name: Resource name
            description: Resource description
            tags: Set of tags
            openapi_handler: Handler for OpenAPI operations
        """
        # Initialize Resource
        Resource.__init__(
            self,
            uri=AnyUrl(uri),
            name=name,
            description=description,
            mime_type="application/json",
            tags=tags,
        )
        # Initialize HttpComponentBase
        HttpComponentBase.__init__(self, path, methods, openapi_handler)

    async def read(self) -> str:
        """Return OpenAPI schema for all methods available at this URL."""
        schema = self._openapi_handler.get_operation_schema(self._path, self._methods)
        return json.dumps(schema, indent=2)


class HttpResourceTemplate(ResourceTemplate, HttpComponentBase):
    """Resource template for HTTP paths with parameters."""

    def __init__(
        self,
        uri_template: str,
        path: str,
        methods: list[HttpMethod],
        name: str,
        description: str,
        parameters: dict[str, Any],
        tags: set[str],
        openapi_handler: "OpenAPIHandler",
    ):
        """Initialize a web resource template.

        Args:
            uri_template: URI template with {param} placeholders
            path: OpenAPI path template (e.g., "/users/{id}")
            methods: List of HTTP methods available
            name: Template name
            description: Template description
            parameters: JSON Schema for path parameters
            tags: Set of tags
            openapi_handler: Handler for OpenAPI operations
        """
        # Initialize ResourceTemplate
        ResourceTemplate.__init__(
            self,
            uri_template=uri_template,
            name=name,
            description=description,
            parameters=parameters,
            tags=tags,
        )
        # Initialize HttpComponentBase
        HttpComponentBase.__init__(self, path, methods, openapi_handler)

    async def read(self, arguments: dict[str, Any] | None = None) -> str:
        """Return OpenAPI schema for all methods available at this template URL."""
        schema = self._openapi_handler.get_operation_schema(self._path, self._methods)
        return json.dumps(schema, indent=2)

    async def create_resource(
        self,
        uri: str,
        params: dict[str, Any],
        context: Context | None = None,
    ) -> HttpResource:
        """Create an HTTP resource instance from this template.

        Args:
            uri: Concrete URI with parameters filled in
            params: Parameter values used to create the URI
            context: Optional context

        Returns:
            HttpResource instance
        """
        # Generate a descriptive name
        param_parts = [f"{k}={v}" for k, v in params.items()]

        resource = HttpResource(
            uri=str(uri),
            path=self._path,  # Keep template path for schema extraction
            methods=self._methods,
            name=f"{self.name}-{'-'.join(param_parts)}",
            description=f"Resource instance of {self._path}",
            tags=self.tags.copy(),
            openapi_handler=self._openapi_handler,
        )

        return resource


__all__ = ["HttpResource", "HttpResourceTemplate"]
