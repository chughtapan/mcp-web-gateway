"""Web resource component implementations.

These components extend the base OpenAPI components to support the web gateway
approach where resources represent API endpoints but don't execute them directly.
"""

from typing import Any

import httpx
from fastmcp.experimental.server.openapi.components import (
    OpenAPIResource as BaseOpenAPIResource,
)
from fastmcp.experimental.server.openapi.components import (
    OpenAPIResourceTemplate as BaseOpenAPIResourceTemplate,
)
from fastmcp.experimental.utilities.openapi import HTTPRoute
from fastmcp.experimental.utilities.openapi.director import RequestDirector
from fastmcp.server import Context
from mcp.types import Annotations


class WebResource(BaseOpenAPIResource):
    """Resource that represents a web API endpoint but doesn't execute it directly."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        route: HTTPRoute,
        director: RequestDirector,
        uri: str,
        name: str,
        description: str,
        mime_type: str = "application/json",
        tags: set[str] = set(),
        timeout: float | None = None,
        annotations: Annotations | dict[str, Any] | None = None,
    ):
        # Convert string URI to AnyUrl for parent class
        super().__init__(
            client=client,
            route=route,
            director=director,
            uri=uri,
            name=name,
            description=description,
            mime_type=mime_type,
            tags=tags,
            timeout=timeout,
        )
        # Store annotations on the resource
        if isinstance(annotations, dict):
            annotations = Annotations(**annotations)

        if annotations:
            self.annotations = annotations

    async def read(self) -> str | bytes:
        """Reading a web resource is not supported - use the appropriate REST tool instead."""
        raise NotImplementedError(
            f"This resource represents a {self._route.method} endpoint at {self._route.path}. "
            f"To execute the request, use the {self._route.method} tool with this resource's URI."
        )


class WebResourceTemplate(BaseOpenAPIResourceTemplate):
    """Resource template that creates web resources."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        route: HTTPRoute,
        director: RequestDirector,
        uri_template: str,
        name: str,
        description: str,
        parameters: dict[str, Any],
        tags: set[str] = set(),
        timeout: float | None = None,
        annotations: Annotations | dict[str, Any] | None = None,
    ):
        super().__init__(
            client=client,
            route=route,
            director=director,
            uri_template=uri_template,
            name=name,
            description=description,
            parameters=parameters,
            tags=tags,
            timeout=timeout,
        )
        # Store annotations on the template
        if isinstance(annotations, dict):
            annotations = Annotations(**annotations)

        if annotations:
            self.annotations = annotations

    async def create_resource(
        self,
        uri: str,
        params: dict[str, Any],
        context: Context | None = None,
    ) -> WebResource:
        """Create a web resource with the given parameters."""
        # Generate a descriptive name for this resource instance
        uri_parts = []
        for key, value in params.items():
            uri_parts.append(f"{key}={value}")

        # Create and return a web resource
        return WebResource(
            client=self._client,
            route=self._route,
            director=self._director,
            uri=uri,
            name=f"{self.name}-{'-'.join(uri_parts)}",
            description=self.description or f"Resource for {self._route.path}",
            mime_type="application/json",
            tags=set(self._route.tags or []),
            timeout=self._timeout,
            annotations=self.annotations,  # Pass through the annotations
        )


__all__ = [
    "WebResource",
    "WebResourceTemplate",
]
