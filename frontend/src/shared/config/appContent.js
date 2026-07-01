export const API_PREFIX = '/api';
export const STORAGE_TOKEN_KEY = 'agent_access_token';
export const DEFAULT_SESSION_TITLE = '新对话';

export const toolItems = [
  {
    key: 'chat',
    label: '会话工作台',
    short: '会',
    overline: 'Conversation',
    status: '已接通',
    description: '围绕当前智能体管理会话、快捷动作和上下文入口。',
  },
  {
    key: 'agents',
    label: '智能体管理',
    short: '智',
    overline: 'Agents',
    status: '可扩展',
    description: '在不离开当前会话页的前提下，切换和查看当前智能体。',
  },
  {
    key: 'knowledge',
    label: '知识库',
    short: '知',
    overline: 'Knowledge',
    status: '已接通',
    description: '上传当前用户自己的知识文档，并把它们直接带入同一个聊天输入框。',
  },
  {
    key: 'tools',
    label: '工具中心',
    short: '工',
    overline: 'Tools',
    status: '待接入',
    description: '统一承接浏览器、搜索、插件等工具能力，不打断主会话流。',
  },
];

export const heroHighlights = [
  {
    key: 'system',
    index: '01',
    title: '统一组件体系',
    copy: '登录、注册、工作台都优先复用 Ant Design Vue 组件，避免认证区和工作区像两套产品。',
  },
  {
    key: 'flow',
    index: '02',
    title: '登录直达会话页',
    copy: '认证成功后直接进入会话工作台，左侧是工具栏和会话列表，中间是当前智能体协作区。',
  },
  {
    key: 'feedback',
    index: '03',
    title: '状态清晰可见',
    copy: '加载中、接口报错、注册成功、流式回复中都会在页面内明确反馈，便于联调和排查。',
  },
];

export const agentCapabilityTags = ['会话编排', '知识问答', '流程协同', '工具调用'];

export const knowledgeCards = [
  { title: '知识范围', copy: '当前默认只展示当前用户自己的文档，并支持在聊天前限定检索范围。' },
  { title: '答案出处', copy: 'RAG 返回的 citations 与 retrieved chunks 会直接映射到主会话区。' },
];

export const knowledgeTodo = [
  '补充文档详情抽屉与分块预览',
  '接入后端 RAG trace 查询接口',
  '支持文档标签、项目维度和批量操作',
];

export const toolCenterItems = [
  { title: '浏览器能力', copy: '适合后续挂接网页浏览、抓取和页面操作。', status: '预留', color: 'gold' },
  { title: '联网搜索', copy: '可扩展为搜索源选择、实时查询和结果缓存。', status: '规划中', color: 'blue' },
  { title: '插件入口', copy: '适合接入自定义工具、插件卡片和可用性状态。', status: '待接入', color: 'default' },
];

export const quickPrompts = [
  '先介绍一下你能帮我完成哪些工作。',
  '帮我梳理当前智能体项目的注册到会话链路。',
  '给我一个适合首页欢迎语的智能体开场白。',
];

export const agentPromptTemplates = [
  {
    key: 'customer-service',
    title: '客服接待',
    description: '适合售前咨询、工单分流和常见问题解答。',
    content: '你是一名专业客服智能体，先快速理解用户诉求，再给出清晰、准确、礼貌的分步回答。遇到不确定的信息时要明确说明，并主动给出下一步建议。',
  },
  {
    key: 'delivery-manager',
    title: '交付推进',
    description: '适合项目跟进、里程碑同步和风险提醒。',
    content: '你是一名项目交付智能体，需要围绕目标、时间节点、风险和下一步动作组织回答。优先输出结论、阻塞点和建议动作，并保持表达简洁。',
  },
  {
    key: 'product-expert',
    title: '产品专家',
    description: '适合功能说明、方案对比和使用引导。',
    content: '你是一名产品方案顾问，回答时先确认用户场景，再结合产品能力给出解释、对比和推荐方案。内容要结构化，必要时补充使用注意事项。',
  },
];

export const agentToolSuggestions = ['联网搜索', '网页解析', 'HTTP 调用', '表单填写', '知识检索'];

export const agentKnowledgeMocks = [
  { name: '产品资料库', copy: '挂载产品说明、FAQ、定价和更新说明。', state: '待接入' },
  { name: '交付文档库', copy: '挂载实施手册、项目 SOP 和巡检文档。', state: '待接入' },
];

export const baseAgentModelOptions = [
  { label: 'Qwen 3 1.7B', value: 'qwen/qwen3-1.7b' },
  { label: 'Qwen Plus', value: 'qwen-plus' },
  { label: 'DeepSeek Chat', value: 'deepseek-chat' },
];
