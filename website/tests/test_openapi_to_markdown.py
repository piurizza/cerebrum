from __future__ import annotations

from typing import Any

from openapi_to_markdown import render

SCHEMA: dict[str, Any] = {
    "info": {"title": "Cerebrum", "version": "0.1.0"},
    "paths": {
        "/api/search": {
            "get": {
                "summary": "Search",
                "parameters": [
                    {
                        "name": "q",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string", "default": ""},
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Successful Response",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {"$ref": "#/components/schemas/NoteMeta"},
                                }
                            }
                        },
                    }
                },
            }
        },
        "/api/notes/{path}": {
            "put": {
                "summary": "Put Note",
                "description": "Create or replace a note.",
                "parameters": [
                    {"name": "path", "in": "path", "required": True, "schema": {}}
                ],
                "requestBody": {
                    "content": {"text/markdown": {"schema": {"type": "string"}}}
                },
                "responses": {"200": {"description": "OK"}},
            },
            "get": {
                "summary": "Get Note Endpoint",
                "responses": {"200": {"description": "OK"}},
            },
        },
    },
    "components": {
        "schemas": {
            "NoteMeta": {
                "properties": {
                    "path": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "updated": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                },
                "required": ["path", "tags"],
            }
        }
    },
}


def test_lists_each_route_under_its_area() -> None:
    page = render(SCHEMA)
    assert "## Notes" in page
    assert "## Search" in page
    assert "### `GET /api/search`" in page
    assert page.index("### `GET /api/notes/{path}`") < page.index(
        "### `PUT /api/notes/{path}`"
    )


def test_lists_parameters_bodies_and_responses() -> None:
    page = render(SCHEMA)
    assert "| `q` | query | no | string |" in page
    assert "| `path` | path | yes | any |" in page
    assert "Request body: `text/markdown` (string)" in page
    assert "Returns: array of [`NoteMeta`](#notemeta)" in page


def test_uses_cleaned_summaries_not_developer_docstrings() -> None:
    page = render(SCHEMA)
    assert "Create or replace a note." not in page
    assert "\nPut note\n" in page
    assert "\nGet note\n" in page


def test_introduces_known_areas() -> None:
    page = render(SCHEMA)
    assert "## Notes\n\nRead, create, update, move and delete notes" in page


def test_lists_schemas_with_required_fields() -> None:
    page = render(SCHEMA)
    assert "### NoteMeta" in page
    assert "| `tags` | array of string | yes |" in page
    assert "| `updated` | string or null | no |" in page


def test_output_is_stable() -> None:
    assert render(SCHEMA) == render(SCHEMA)
