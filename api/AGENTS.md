# API Backend Rules

This file applies to Python backend work inside `api/`.

## Scope

- FastAPI routes
- request and response schemas
- backend API behavior

## Hard Rules

1. Follow `/AGENTS.md` first.
2. Keep edits minimal and close to the affected route, schema, or integration point.
3. When changing an API contract, update the related schema together with the route.
4. Do not rewrite Chinese comments or Chinese response copy unless the task explicitly requires it.
5. Treat all Python source files as UTF-8 text.
6. Do not use unsafe PowerShell whole-file rewrites for Python files that contain Chinese text.
7. If a response field is added, confirm persistence, schema output, and route return shape stay aligned.
8. If a database field is added, consider compatibility for existing tables instead of assuming a fresh database.

## Preferred Change Pattern

1. Locate the exact route or schema.
2. Modify the smallest relevant code path.
3. Verify related model or persistence behavior if the API output depends on it.