# agentUI Frontend Prompt

Use this prompt before every frontend task in this project:

```text
Before starting any frontend work, read `/frontend/agentUI/agentui-spec.md` completely and follow it strictly.

Hard rules:
1. The frontend stack for this project is Vue 3.
2. The UI system for this project is Ant Design Vue.
3. Prefer Ant Design Vue components first for forms, inputs, password inputs, buttons, cards, tabs, alerts, modals, drawers, tables, empty states, and loading states.
4. Do not create a separate base UI system that fights Ant Design Vue unless the user explicitly asks for an exception.
5. Custom CSS should mainly support layout, spacing, hierarchy, and product atmosphere. It should not replace the core interaction patterns of Ant Design Vue.
6. All frontend source and config files must be saved as UTF-8 without BOM.
7. This includes `package.json`, `vite.config.js`, `.vue`, `.js`, `.css`, `.md`, and related frontend files.
8. If Vite shows `Unexpected token`, `invalid JSON`, or PostCSS config load errors, check file encoding first.

9. Do not automatically restart frontend or backend services unless the user explicitly asks.
10. Do not automatically run build, compile, or dev restart commands unless the user explicitly asks. After code changes, tell the user what they need to restart themselves.
11. In the conversation workspace, the left sidebar and secondary task panel must keep a fixed viewport height and use independent scrolling. They must not expand just because the main conversation area becomes taller.
12. Agent management and agent editing must stay in the same Ant Design Vue visual system as login, register, and workspace pages.
13. When building an agent editor, prefer a two-column builder layout: left for identity and prompt editing, right for model, retrieval, tools, and memory configuration.
14. If some agent capabilities are not connected to backend fields yet, show explicit pending or disabled blocks instead of pretending they are already persisted.

Page rules:
1. Login, register, and workspace pages must stay in one consistent Ant Design Vue visual system.
2. After login succeeds, the default landing page is the conversation workspace, not a traditional dashboard.
3. The default workspace layout is: left toolbar + session list + main conversation area.
4. Loading, empty, error, success, and disabled states must be visible.
5. Copy should match an agent workspace product, not a generic admin template.
6. Desktop and mobile must both work. Mobile may collapse into a single-column or staged layout.

Pre-delivery checks:
1. Confirm edited frontend files are UTF-8 without BOM.
2. Confirm key files such as `package.json`, `vite.config.js`, `.vue`, `.js`, and `.css` do not contain a BOM.
3. Confirm Ant Design Vue is actually used as the main component system.
4. Confirm successful login lands on the conversation workspace.
5. Confirm register, login, session loading, and message sending all show visible feedback.

Output requirements:
1. State which Ant Design Vue components and rules are being reused.
2. Implement the code directly instead of only proposing a plan.
3. If custom styles are added, explain that they supplement layout and atmosphere rather than replace Ant Design Vue.
4. After implementation, explain the result, verification method, and next extensible pages.
```