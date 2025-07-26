"""Shared test fixtures and utilities for MCP Web Gateway tests."""

from typing import Any

import httpx
import pytest


@pytest.fixture
def petstore_openapi_spec():
    """Pet Store OpenAPI specification for testing."""
    return {
        "openapi": "3.0.0",
        "info": {
            "title": "Petstore API",
            "version": "1.0.0",
            "description": "A simple pet store API",
        },
        "servers": [{"url": "https://petstore.example.com/api"}],
        "paths": {
            "/pets": {
                "get": {
                    "operationId": "list_pets",
                    "summary": "List all pets",
                    "parameters": [
                        {
                            "name": "limit",
                            "in": "query",
                            "description": "How many items to return",
                            "required": False,
                            "schema": {"type": "integer", "default": 10},
                        },
                        {
                            "name": "status",
                            "in": "query",
                            "description": "Filter by status",
                            "required": False,
                            "schema": {
                                "type": "string",
                                "enum": ["available", "pending", "sold"],
                            },
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "List of pets",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "id": {"type": "integer"},
                                                "name": {"type": "string"},
                                                "species": {"type": "string"},
                                                "status": {"type": "string"},
                                            },
                                        },
                                    }
                                }
                            },
                        }
                    },
                },
                "post": {
                    "operationId": "create_pet",
                    "summary": "Create a new pet",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["name", "species"],
                                    "properties": {
                                        "name": {"type": "string"},
                                        "species": {"type": "string"},
                                        "breed": {"type": "string"},
                                        "age": {"type": "integer"},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "201": {
                            "description": "Pet created",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "integer"},
                                            "name": {"type": "string"},
                                            "species": {"type": "string"},
                                        },
                                    }
                                }
                            },
                        }
                    },
                },
            },
            "/pets/{petId}": {
                "get": {
                    "operationId": "get_pet",
                    "summary": "Get a pet by ID",
                    "parameters": [
                        {
                            "name": "petId",
                            "in": "path",
                            "required": True,
                            "description": "The ID of the pet",
                            "schema": {"type": "integer"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Pet details",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "integer"},
                                            "name": {"type": "string"},
                                            "species": {"type": "string"},
                                            "breed": {"type": "string"},
                                            "age": {"type": "integer"},
                                            "status": {"type": "string"},
                                        },
                                    }
                                }
                            },
                        }
                    },
                },
                "put": {
                    "operationId": "update_pet",
                    "summary": "Update a pet",
                    "parameters": [
                        {
                            "name": "petId",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer"},
                        }
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "species": {"type": "string"},
                                        "breed": {"type": "string"},
                                        "age": {"type": "integer"},
                                        "status": {"type": "string"},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "Pet updated"}},
                },
                "delete": {
                    "operationId": "delete_pet",
                    "summary": "Delete a pet",
                    "parameters": [
                        {
                            "name": "petId",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer"},
                        }
                    ],
                    "responses": {"204": {"description": "Pet deleted"}},
                },
            },
        },
    }


class MockHTTPClient(httpx.AsyncClient):
    """Mock HTTP client that simulates API responses."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pets = {
            1: {
                "id": 1,
                "name": "Fluffy",
                "species": "cat",
                "breed": "Persian",
                "age": 3,
                "status": "available",
            },
            2: {
                "id": 2,
                "name": "Buddy",
                "species": "dog",
                "breed": "Golden Retriever",
                "age": 5,
                "status": "available",
            },
            3: {
                "id": 3,
                "name": "Tweety",
                "species": "bird",
                "breed": "Canary",
                "age": 1,
                "status": "sold",
            },
        }
        self.next_id = 4

    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Simulate API responses."""
        # Parse the URL
        path = url.replace("https://petstore.example.com/api", "")

        if method == "GET" and path == "/pets":
            # List pets
            pets = list(self.pets.values())
            params = kwargs.get("params", {})
            if "status" in params:
                pets = [p for p in pets if p["status"] == params["status"]]
            if "limit" in params:
                pets = pets[: params["limit"]]

            return self._create_response(200, pets)

        elif method == "POST" and path == "/pets":
            # Create pet
            data = kwargs.get("json", {})
            pet = {
                "id": self.next_id,
                "name": data.get("name", "Unknown"),
                "species": data.get("species", "Unknown"),
                "breed": data.get("breed", "Mixed"),
                "age": data.get("age", 0),
                "status": "available",
            }
            self.pets[self.next_id] = pet
            self.next_id += 1
            return self._create_response(201, pet)

        elif method == "GET" and path.startswith("/pets/"):
            # Get specific pet
            pet_id = int(path.split("/")[-1])
            if pet_id in self.pets:
                return self._create_response(200, self.pets[pet_id])
            else:
                return self._create_response(404, {"error": "Pet not found"})

        elif method == "PUT" and path.startswith("/pets/"):
            # Update pet
            pet_id = int(path.split("/")[-1])
            if pet_id in self.pets:
                data = kwargs.get("json", {})
                self.pets[pet_id].update(data)
                return self._create_response(200, self.pets[pet_id])
            else:
                return self._create_response(404, {"error": "Pet not found"})

        elif method == "DELETE" and path.startswith("/pets/"):
            # Delete pet
            pet_id = int(path.split("/")[-1])
            if pet_id in self.pets:
                del self.pets[pet_id]
                return self._create_response(204, "")
            else:
                return self._create_response(404, {"error": "Pet not found"})

        return self._create_response(404, {"error": "Not found"})

    def _create_response(self, status_code: int, data: Any) -> httpx.Response:
        """Create a mock response."""
        import json as json_module

        # Create proper response content
        if isinstance(data, (dict, list)):
            content = json_module.dumps(data).encode()
            headers = {"content-type": "application/json"}
        elif data == "":
            content = b""
            headers = {}
        else:
            content = str(data).encode()
            headers = {"content-type": "text/plain"}

        # Create a mock request for the response
        request = httpx.Request("GET", "https://mock.example.com")

        response = httpx.Response(
            status_code=status_code,
            headers=headers,
            content=content,
            request=request,
        )
        return response


@pytest.fixture
def mock_http_client():
    """Create a mock HTTP client instance."""
    return MockHTTPClient(base_url="https://petstore.example.com/api")
