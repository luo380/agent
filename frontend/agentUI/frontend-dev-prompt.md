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
9. Before editing any Chinese frontend copy, first verify the target file is readable as normal UTF-8 text and does not already contain mojibake or broken replacement characters.
10. Never write mojibake, garbled Chinese, or replacement-style broken text into frontend source files. If the current file content looks garbled, stop and fix or confirm encoding before making more edits.
11. If a frontend file shows garbled Chinese, do not continue patching that file blindly. First normalize encoding or restore the text to valid UTF-8 Chinese.
12. After any frontend edit touching Chinese copy, re-open the edited lines and confirm the Chinese text still renders as readable Chinese rather than mojibake.
13. Do not automatically restart frontend or backend services unless the user explicitly asks.
14. Do not automatically run build, compile, or dev restart commands unless the user explicitly asks. After code changes, tell the user what they need to restart themselves.
15. In the conversation workspace, the left sidebar and secondary task panel must keep a fixed viewport height and use independent scrolling. They must not expand just because the main conversation area becomes taller.
16. Agent management and agent editing must stay in the same Ant Design Vue visual system as login, register, and workspace pages.
17. When building an agent editor, prefer a two-column builder layout: left for identity and prompt editing, right for model, retrieval, tools, and memory configuration.
18. If some agent capabilities are not connected to backend fields yet, show explicit pending or disabled blocks instead of pretending they are already persisted.
19. Every frontend feature must have its own module boundary. Do not keep unrelated features inside one giant page file.
20. Split by responsibility: page shell, feature panel, dialog, trace panel, session list, and composer should be separate components when they are independent features.
21. Shared stateful logic should move into clearly named composables or service helpers instead of being repeatedly embedded inside a single .vue file.
22. Avoid turning App.vue into a catch-all file. App.vue should coordinate high-level state and routing-level layout, not own every feature implementation detail.
23. Before adding a new frontend feature, first decide its module boundary: component, composable, service, or style module, then implement inside that boundary.
24. Organize frontend files by feature domain whenever possible, for example auth/, workspace/, agent/, chat/, trace/, instead of placing all components flat in one folder.
25. When a feature grows beyond one component, create a dedicated feature directory and colocate its components, composables, and service helpers to keep maintenance clear.

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
6. Confirm edited Chinese copy still displays as readable Chinese, with no mojibake or broken encoding artifacts.

Output requirements:
1. State which Ant Design Vue components and rules are being reused.
2. Implement the code directly instead of only proposing a plan.
3. If custom styles are added, explain that they supplement layout and atmosphere rather than replace Ant Design Vue.
4. After implementation, explain the result, verification method, and next extensible pages.
```
## 中文规则补充

1. 修改任何前端文件前，先确认文件编码是 `UTF-8 without BOM`。
2. 只要文件里出现中文，修改后必须重新打开检查中文是否仍然正常显示。
3. 如果看到 `閫€鍑虹櫥褰?`、`鏂板缓浼氳瘽` 这类文字，说明已经发生乱码，禁止继续在原文件上盲改。
4. 出现乱码时，优先从 Git 恢复干净文件，再重新应用需要的改动。
5. 不要用会经过终端编码转换的方式批量改中文内容，尤其要避免在编码不确定的 PowerShell 文本管道里直接读写中文源码。
6. 优先使用不会破坏编码的改法：`apply_patch`，或显式指定 `UTF-8 without BOM` 的文件写入方式。
7. 改完中文文案后，至少做两次检查：
   - 检查源码里中文是否可读
   - 检查前端构建是否通过
8. 如果文件本身已经乱码，先修编码，再改功能；不要把“修功能”和“修乱码”混在同一次修改里。
9. 以后凡是改前端中文文案，先读这个文件，再开始动代码。
10. 前端每一个功能都必须有自己的模块边界，不要把会话列表、执行轨迹、输入框、弹窗、表单、工具面板等不同功能长期堆在同一个超大文件里。
11. 拆分原则要按职责走：页面壳层、功能面板、弹窗、执行轨迹、会话列表、输入区，能独立演进的就拆成独立组件。
12. 复用或带状态的逻辑要放进命名清晰的 composable 或 service，不要在单个 .vue 文件里不断堆接口调用和状态处理。
13. App.vue 不能继续充当前端杂物间；它应该只负责高层级布局、页面切换和顶层状态协调，不应该承载所有功能实现细节。
14. 每次新增前端功能前，先决定它应该落在哪个模块边界里：组件、composable、service 或样式模块，然后再开始写代码。
15. 前端文件组织也要按功能域划分，优先按 auth/、workspace/、agent/、chat/、trace/ 这类目录归类，不要把所有组件长期平铺在同一个目录。
16. 当某个功能不再只是一个小组件时，要为它建立独立目录，把该功能相关的组件、composable、service 就近放在一起，方便后续维护。