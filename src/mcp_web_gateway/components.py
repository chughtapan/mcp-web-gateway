"""Web resource component implementations.

These components extend the base OpenAPI components to support the web gateway
approach where resources represent API endpoints but don't execute them directly.
"""

import json
from typing import Any

from fastmcp.experimental.utilities.openapi import HTTPRoute
from fastmcp.resources import Resource, ResourceTemplate
from fastmcp.server import Context
from pydantic.networks import AnyUrl


class WebResource(Resource):
    """Resource that represents a web API endpoint and returns its OpenAPI schema."""

    def __init__(
        self,
        route: HTTPRoute,
        uri: str,
        name: str,
        description: str,
        mime_type: str = "application/json",
        tags: set[str] = set(),
        meta: dict[str, Any] | None = None,
    ):
        # Initialize base class
        super().__init__(
            uri=AnyUrl(uri),
            name=name,
            description=description,
            mime_type=mime_type,
            tags=tags,
            meta=meta,
        )
        # Store all routes for this URL
        self._routes = [route]

    async def read(self) -> str | bytes:
        """Return OpenAPI schema for all methods available at this URL."""
        return json.dumps(self.meta, indent=2)

    def add_route(self, route: HTTPRoute, method_schema: dict[str, Any]) -> None:
        """Add a new route to this resource with its pre-extracted method schema.

        Args:
            route: The HTTPRoute to add
            method_schema: Pre-extracted OpenAPI schema for this method
        """
        # Check if this method already exists
        existing_methods = {r.method for r in self._routes}
        if route.method not in existing_methods:
            self._routes.append(route)
            # Update tags if the new route has tags
            if route.tags:
                self.tags.update(route.tags)
            # Update the schema to include the new method
            path = self._routes[0].path
            if self.meta and path in self.meta.get("paths", {}):
                self.meta["paths"][path][route.method.lower()] = method_schema


class WebResourceTemplate(ResourceTemplate):
    """Resource template that creates web resources."""

    def __init__(
        self,
        route: HTTPRoute,
        uri_template: str,
        name: str,
        description: str,
        parameters: dict[str, Any],
        tags: set[str] = set(),
        meta: dict[str, Any] | None = None,
    ):
        super().__init__(
            uri_template=uri_template,
            name=name,
            description=description,
            parameters=parameters,
            tags=tags,
            meta=meta,
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

        # Create a web resource with the first route and same schema
        resource = WebResource(
            route=self._routes[0],
            uri=str(uri),  # Convert AnyUrl to string
            name=f"{self.name}-{'-'.join(uri_parts)}",
            description=self.description or f"Resource for {self._routes[0].path}",
            mime_type="application/json",
            tags=set(self._routes[0].tags or []),
            meta=self.meta.copy() if self.meta else {},
        )

        # Add remaining routes if any
        for route in self._routes[1:]:
            # Extract method schema from our meta
            path = route.path
            method = route.method.lower()
            method_schema = (
                self.meta.get("paths", {}).get(path, {}).get(method, {})
                if self.meta
                else {}
            )
            resource.add_route(route, method_schema)

        return resource

    def add_route(self, route: HTTPRoute, method_schema: dict[str, Any]) -> None:
        """Add a new route to this template with its pre-extracted method schema.

        Args:
            route: The HTTPRoute to add
            method_schema: Pre-extracted OpenAPI schema for this method
        """
        # Check if this method already exists
        existing_methods = {r.method for r in self._routes}
        if route.method not in existing_methods:
            self._routes.append(route)
            # Update tags if the new route has tags
            if route.tags:
                self.tags.update(route.tags)
            # Update the schema to include the new method
            path = self._routes[0].path
            if self.meta and path in self.meta.get("paths", {}):
                self.meta["paths"][path][route.method.lower()] = method_schema


__all__ = [
    "WebResource",
    "WebResourceTemplate",
]
