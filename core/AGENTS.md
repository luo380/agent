# Core Backend Rules

This file applies to Python backend work inside `core/`.

## Scope

- database models
- database initialization
- services
- shared backend helpers

## Hard Rules

1. Follow `/AGENTS.md` first.
2. Keep edits minimal and local to the affected model, service, or helper.
3. Treat all Python source files as UTF-8 text.
4. Do not rewrite Chinese comments, Chinese prompt text, or Chinese copy unless the task explicitly requires it.
5. Do not use unsafe PowerShell whole-file rewrites for files that contain Chinese text.
6. For model changes, keep persistence compatibility in mind for existing databases.
7. For service-layer prompt changes, distinguish coding rules from runtime business prompts.

## Preferred Change Pattern

1. Identify the exact model, service, or helper.
2. Change only the relevant logic.
3. Recheck any related schema, route, or database compatibility impact.