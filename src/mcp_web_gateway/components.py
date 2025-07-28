"""Web resource component implementations.

These components extend the base OpenAPI components to support the web gateway
approach where resources represent API endpoints but don't execute them directly.
"""

import json
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


class WebResource(BaseOpenAPIResource):
    """Resource that represents a web API endpoint and returns its OpenAPI schema."""

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
    ):
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
        # Store all routes for this URL
        self._routes = [route]

    async def read(self) -> str | bytes:
        """Return OpenAPI schema for all methods available at this URL."""
        schema = self._build_openapi_schema(self._routes[0].path)
        return json.dumps(schema, indent=2)

    def _build_operation_schema(self, route: HTTPRoute) -> dict[str, Any]:
        """Build OpenAPI operation schema for a single route."""
        operation: dict[str, Any] = {
            "operationId": route.operation_id,
            "summary": route.summary,
            "description": route.description,
            "tags": list(route.tags) if route.tags else [],
        }

        # Add parameters
        if route.parameters:
            operation["parameters"] = [p.model_dump() for p in route.parameters]

        # Add request body
        if route.request_body:
            operation["requestBody"] = route.request_body.model_dump()

        # Add responses
        if route.responses:
            operation["responses"] = {
                str(code): resp.model_dump() for code, resp in route.responses.items()
            }

        return operation

    def _build_openapi_schema(self, resource_path: str) -> dict[str, Any]:
        """Build the complete OpenAPI schema for this resource."""
        schema: dict[str, Any] = {"openapi": "3.0.0", "paths": {resource_path: {}}}

        # Build operations for each method
        path_item: dict[str, Any] = schema["paths"][resource_path]
        for route in self._routes:
            operation = self._build_operation_schema(route)
            path_item[route.method.lower()] = operation

        return schema

    def add_route(self, route: HTTPRoute) -> None:
        """Add a new route to this resource."""
        # Check if this method already exists
        existing_methods = {r.method for r in self._routes}
        if route.method not in existing_methods:
            self._routes.append(route)
            # Update tags if the new route has tags
            if route.tags:
                self.tags.update(route.tags)


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
        # Store all routes for this URL template
        self._routes = [route]

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

        # Create a web resource with the first route
        resource = WebResource(
            client=self._client,
            route=self._routes[0],
            director=self._director,
            uri=uri,
            name=f"{self.name}-{'-'.join(uri_parts)}",
            description=self.description or f"Resource for {self._routes[0].path}",
            mime_type="application/json",
            tags=set(self._routes[0].tags or []),
            timeout=self._timeout,
        )

        # Add remaining routes if any
        for route in self._routes[1:]:
            resource.add_route(route)

        return resource

    def add_route(self, route: HTTPRoute) -> None:
        """Add a new route to this template."""
        # Check if this method already exists
        existing_methods = {r.method for r in self._routes}
        if route.method not in existing_methods:
            self._routes.append(route)
            # Update tags if the new route has tags
            if route.tags:
                self.tags.update(route.tags)


__all__ = [
    "WebResource",
    "WebResourceTemplate",
]
