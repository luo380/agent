# Frontend Rules

This file applies to frontend work under `frontend/`.

## Stack

- Vue 3
- Vite
- Ant Design Vue

## Hard Rules

1. Follow `/AGENTS.md` first.
2. All frontend source and config files must use UTF-8 without BOM.
3. Never write mojibake or garbled Chinese into frontend source files.
4. If a frontend file already looks garbled, stop and fix or restore it before making feature edits.
5. Do not use unsafe whole-file PowerShell rewrites on files that contain Chinese text.
6. Prefer Ant Design Vue components as the main UI system.
7. Keep custom CSS focused on layout, spacing, hierarchy, and page atmosphere.
8. Do not turn `App.vue` into a catch-all file.
9. Split features by module boundary: component, composable, service, or style module.
10. Do not automatically restart frontend or backend services unless explicitly asked.
11. Do not automatically run build or restart commands unless explicitly asked.

## Structure Rules

1. Prefer feature-oriented folders such as `auth/`, `workspace/`, `agent/`, `chat/`, and `trace/`.
2. Independent UI areas should be separate components.
3. Shared stateful logic should move into clearly named composables or service helpers.

## Extra UI Spec

For agent workspace UI details, also read `frontend/agentUI/agentui-spec.md`.