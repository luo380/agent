# Repository Rules

This file defines the default development rules for the whole repository.

## Hard Rules

1. All project text files must be handled as UTF-8.
2. Do not turn Chinese comments, Chinese copy, or Chinese prompt text into mojibake.
3. Do not use unsafe whole-file rewrite methods on files that contain Chinese text.
4. Avoid PowerShell `Set-Content`, `Out-File`, terminal pipeline rewrites, or blind batch replace for Chinese source files.
5. Prefer minimal scoped edits. Do not rewrite unrelated sections.
6. Unless the task explicitly requires it, do not change existing Chinese comments, Chinese UI copy, or prompt text.
7. If a file already looks garbled, stop and restore or confirm encoding before making more edits.
8. Before editing, first identify the exact files and scope of change.
9. After editing Chinese text, reopen the changed lines and confirm the text is still readable.

## Editing Workflow

1. Read the nearest `AGENTS.md` for the area you are changing.
2. Prefer patch-style edits over full-file replacement.
3. Keep backend changes localized to the relevant route, schema, service, or model.
4. Keep frontend changes localized to the relevant feature module or composable.
5. If a safe patch method is unavailable, stop and explain the risk before continuing.

## Area Rules

- Frontend work: also follow `frontend/AGENTS.md`.
- Python backend work under `api/`: also follow `api/AGENTS.md`.
- Python backend work under `core/`: also follow `core/AGENTS.md`.