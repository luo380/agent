# agentUI Frontend Spec

## Purpose

This project uses Vue for frontend implementation and Ant Design Vue as the primary UI component standard. Every new frontend task should read this file first, then build within the same component system, page structure, and interaction rules.

## Default Stack

- Framework: Vue 3
- Build tool: Vite
- UI library: Ant Design Vue
- Styling approach: Ant Design components first, then project-level layout and page styling

## Core Principles

1. Trust first
   Interfaces should feel reliable, structured, and calm.
2. One primary action
   Each page should expose one dominant action and keep secondary actions visually quieter.
3. State is visible
   Loading, empty, success, error, and disabled states must always be explicit.
4. Extend from the design system
   Prefer Ant Design Vue components and patterns before introducing custom UI.
5. Human plus agent collaboration
   Copy should reflect an intelligent-workbench product, not a generic admin shell.

## Encoding Rules

- All frontend source and config files must use UTF-8 without BOM.
- This includes `package.json`, `vite.config.js`, `.vue`, `.js`, `.css`, `.md`, and related frontend files.
- Do not save frontend files as UTF-8 with BOM.
- If Vite reports `Unexpected token`, `invalid JSON`, or PostCSS config load errors, check file encoding first.

## Ant Design Rules

- Prefer Ant Design Vue components such as `a-form`, `a-input`, `a-input-password`, `a-button`, `a-card`, `a-alert`, `a-table`, and `a-modal`.
- Keep visual customization focused on layout, spacing, page atmosphere, and information hierarchy rather than replacing core component affordances.
- Use Ant Design feedback components for errors, success states, notices, and async progress whenever possible.
- Form pages should use standard Ant Design label, input, validation, and button patterns.

## Layout Rules

- Desktop pages should prefer a strong split layout or a clearly staged vertical flow.
- Mobile should collapse cleanly into a readable single-column structure.
- Keep content widths intentional; avoid full-width stretched forms.
- When a page mixes explanation and action, use one context area and one action area.

## Typography And Copy

- Use concise operational copy.
- Form labels must remain visible and explicit.
- Use Chinese copy for user-facing Chinese pages.
- Headlines should be compact and confident.

## Vue Rules

- Use Vue single-file components for feature pages.
- Each frontend feature must have a clear module boundary instead of being merged into one oversized page file.
- Prefer splitting independent areas such as session list, conversation workspace, trace panel, modal forms, and tool panels into separate components.
- Prefer `ref`, `reactive`, and `computed` for local state.
- Move reusable or stateful business logic into clearly named composables or service helpers.
- Keep templates readable and aligned to page sections.
- Keep API calls and validation logic inside the Vue component or a clearly named composable.
- Prefer feature-oriented directory structure such as auth/, workspace/, agent/, chat/, and trace/ when modules start to grow.
- When one feature contains multiple components and helpers, colocate them inside a dedicated feature folder rather than scattering them randomly.

## Delivery Checklist

Before finishing any frontend task:

1. Confirm the page uses Vue.
2. Confirm Ant Design Vue is the primary UI system.
3. Confirm loading, success, and error states exist.
4. Confirm desktop and mobile both work.
5. Confirm custom styling complements rather than fights Ant Design.
6. Confirm the page can extend into the next product step.
7. Confirm edited frontend files are saved as UTF-8 without BOM.

## 中文模块化规则

- 前端每一个功能都要有明确的模块边界，不能长期堆在同一个超大页面文件中。
- 会话列表、执行轨迹、输入框、弹窗、表单、工具面板这类可独立演进的区域，默认拆成独立组件。
- 可复用逻辑或带状态逻辑，优先放入命名清晰的 composable 或 service。
- App.vue 只负责高层布局和顶层协调，不负责承载所有功能细节。
- 开始写前端功能前，先确定它属于组件、composable、service 还是样式模块。
- 前端目录组织也要按功能域归类，优先使用 auth/、workspace/、agent/、chat/、trace/ 这类目录结构。
- 如果一个功能包含多个组件和辅助逻辑，就为它建立独立文件夹，把相关组件、composable、service 就近放在一起，不要四处分散。