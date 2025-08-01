"""Simple example of using MCP Web Gateway with FastAPI."""

from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from mcp_web_gateway import McpWebGateway


# Define our data models
class TodoItem(BaseModel):
    title: str
    completed: bool = False


class TodoItemResponse(BaseModel):
    id: int
    title: str
    completed: bool


class TodoItemUpdate(BaseModel):
    title: str | None = None
    completed: bool | None = None


# Create FastAPI app
app = FastAPI(title="Todo API", version="1.0.0", description="A simple todo list API")

# In-memory storage
todos: Dict[int, Dict[str, Any]] = {}
next_id: int = 1


@app.get("/", response_class=PlainTextResponse)
@app.get("/llms.txt", response_class=PlainTextResponse)
async def get_llms_txt() -> str:
    """Return API documentation for LLMs."""
    return """# Todo API

Base URL: http://localhost:8000

## Available Endpoints:

### List all todos
GET /todos
Returns: Array of todo objects

### Create a new todo
POST /todos
Body: {"title": "string", "completed": boolean}
Returns: Created todo object with id

### Get a specific todo
GET /todos/{todo_id}
Returns: Todo object

### Update a todo (full replacement)
PUT /todos/{todo_id}
Body: {"title": "string", "completed": boolean}
Returns: Updated todo object

### Partially update a todo
PATCH /todos/{todo_id}
Body: Any subset of todo fields to update
Returns: Updated todo object

### Delete a todo
DELETE /todos/{todo_id}
Returns: 204 No Content

## Example Usage:

# Create a todo
curl -X POST http://localhost:8000/todos \\
  -H "Content-Type: application/json" \\
  -d '{"title": "Buy milk", "completed": false}'

# List todos
curl http://localhost:8000/todos

# Update todo status
curl -X PATCH http://localhost:8000/todos/1 \\
  -H "Content-Type: application/json" \\
  -d '{"completed": true}'
"""


@app.get("/todos")
async def list_todos() -> list[TodoItemResponse]:
    """List all todos."""
    return [TodoItemResponse(**todo) for todo in todos.values()]


@app.post("/todos", status_code=201)
async def create_todo(todo: TodoItem) -> TodoItemResponse:
    """Create a new todo item."""
    global next_id
    todo_dict = todo.dict()
    todo_dict["id"] = next_id
    todos[next_id] = todo_dict
    next_id += 1
    return TodoItemResponse(**todo_dict)


@app.get("/todos/{todo_id}")
async def get_todo(todo_id: int) -> TodoItemResponse:
    """Get a specific todo by ID."""
    if todo_id not in todos:
        raise HTTPException(status_code=404, detail="Todo not found")
    return TodoItemResponse(**todos[todo_id])


@app.put("/todos/{todo_id}")
async def update_todo(todo_id: int, todo: TodoItem) -> TodoItemResponse:
    """Update an existing todo."""
    if todo_id not in todos:
        raise HTTPException(status_code=404, detail="Todo not found")
    todo_dict = todo.dict()
    todo_dict["id"] = todo_id
    todos[todo_id] = todo_dict
    return TodoItemResponse(**todo_dict)


@app.patch("/todos/{todo_id}")
async def patch_todo(todo_id: int, updates: TodoItemUpdate) -> TodoItemResponse:
    """Partially update a todo."""
    if todo_id not in todos:
        raise HTTPException(status_code=404, detail="Todo not found")

    # Only update fields that were provided
    update_data = updates.dict(exclude_unset=True)
    for key, value in update_data.items():
        todos[todo_id][key] = value

    return TodoItemResponse(**todos[todo_id])


@app.delete("/todos/{todo_id}", status_code=204)
async def delete_todo(todo_id: int) -> None:
    """Delete a todo."""
    if todo_id not in todos:
        raise HTTPException(status_code=404, detail="Todo not found")
    del todos[todo_id]


# Create MCP Web Gateway from FastAPI app
mcp = McpWebGateway.from_fastapi(app)
