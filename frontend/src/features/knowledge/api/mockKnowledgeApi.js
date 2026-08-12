// ============================================================
// 知识库 Mock 接口层
// 后端未就绪时，页面通过这一层异步获取 / 提交数据，
// 形态与真实接口一致（异步、带网络延迟、返回 { data }）。
// 后端就绪后，只需把下方 listDocuments / createDocument /
// uploadDocument / deleteDocument 换成对真实 /api/knowledge/* 的
// fetch 调用即可，页面与 useKnowledgeBase 无需改动。
// ============================================================

// 内存数据（即原来的 12 篇种子文档）
let _store = [
  {
    id: 1, title: '用户访谈与研究方法', category: 'product', author: '张明',
    updatedAt: '2025-08-05', views: 248, status: 'ready', statusText: '可检索', statusColor: 'success',
    typeIcon: '📄', iconBg: '#E8F1FF', iconColor: '#2B6FFF',
    excerpt: '本文档梳理了用户访谈的完整方法论：从访谈前的目标设定与提纲撰写，到访谈中的提问技巧与记录规范。',
    wordCount: '3,820', isFavorite: true,
    aiSummary: '本文档梳理了用户访谈的完整方法论：从访谈前的目标设定与提纲撰写，到访谈中的提问技巧与记录规范。重点介绍了半结构化访谈、情境访谈、影子跟访三种方式的适用场景，并提供了可直接复用的访谈提纲模板。',
    toc: [
      { text: '一、访谈前的准备' }, { text: '1.1 明确研究问题', sub: true },
      { text: '1.2 撰写访谈提纲', sub: true }, { text: '二、访谈中的提问技巧' },
      { text: '三、访谈后的整理' },
    ],
    relatedDocs: [{ id: 2, title: '用户画像模板 v2' }, { id: 3, title: '访谈提纲模板' }],
    content: `
      <h2>一、访谈前的准备</h2>
      <p>访谈不是闲聊，每一次访谈都应当带着明确的研究目标。在开始访谈前，研究员需要完成三件事：明确研究问题、筛选受访者、撰写访谈提纲。</p>
      <blockquote>💡 关键原则：访谈提纲是"脚手架"而非"剧本"，要为追问和发散预留空间。</blockquote>
      <h3>1.1 明确研究问题</h3>
      <p>研究问题应当具体、可回答、可验证。避免"用户喜欢我们的产品吗"这类模糊问题，改为"用户在使用搜索功能时遇到哪些阻碍"。</p>
      <ul>
        <li>核心问题：本次访谈要回答的最关键 1-2 个问题</li>
        <li>子问题：拆解核心问题后形成的 3-5 个具体问题</li>
        <li>验证假设：列出预期假设，便于访谈后对比验证</li>
      </ul>
      <h3>1.2 撰写访谈提纲</h3>
      <p>提纲建议按"破冰 → 主题深入 → 收尾"三段式组织，每段 3-5 个问题，总时长控制在 45-60 分钟。</p>
      <table>
        <thead><tr><th>阶段</th><th>时长</th><th>目标</th><th>典型问题</th></tr></thead>
        <tbody>
          <tr><td>破冰</td><td>5-10 min</td><td>建立信任</td><td>能否聊聊您目前的工作职责？</td></tr>
          <tr><td>主题深入</td><td>30-40 min</td><td>挖掘行为与动机</td><td>上次遇到这个问题时您是怎么处理的？</td></tr>
          <tr><td>收尾</td><td>5-10 min</td><td>补充与感谢</td><td>还有什么想分享但没问到的吗？</td></tr>
        </tbody>
      </table>
      <h2>二、访谈中的提问技巧</h2>
      <p>提问是访谈的核心技能。好的问题应当是<code>开放式</code>、<code>中性</code>、<code>具体</code>的，避免引导性问题和判断性问题。</p>
      <ol>
        <li>用"能否聊聊…"代替"你是否喜欢…"</li>
        <li>用"上次具体是怎么做的"代替"你通常怎么做"</li>
        <li>遇到模糊回答时，用"能举个例子吗"追问</li>
        <li>保持沉默 3-5 秒，往往能引出更深入的回答</li>
      </ol>
      <h2>三、访谈后的整理</h2>
      <p>访谈结束后 24 小时内完成整理是最佳实践。建议按照"原始记录 → 关键行为 → 痛点洞察 → 机会点"四层结构梳理。</p>
    `,
    comments: [
      { author: '王芳', avatarBg: 'linear-gradient(135deg,#5B8CFF,#2B6FFF)', time: '2 小时前', text: '关于"沉默 3-5 秒"这一点，新手研究员往往不敢停顿，但实际效果非常好，建议在培训里强化这点。', likes: 3 },
      { author: '陈晨', avatarBg: 'linear-gradient(135deg,#00B85C,#5BD887)', time: '昨天', text: '提纲表格很实用，能不能单独抽出来做成可复制的模板？', likes: 5 },
    ],
  },
  {
    id: 2, title: 'Q3 产品需求评审纪要', category: 'product', author: '王芳',
    updatedAt: '2025-08-04', views: 156, status: 'ready', statusText: '可检索', statusColor: 'success',
    typeIcon: '📊', iconBg: '#DBFAE0', iconColor: '#00B85C',
    excerpt: '本次评审覆盖 8 个需求项，其中 5 项通过、2 项待补充资料、1 项暂缓。包含优先级排序与排期安排。',
    wordCount: '2,150', isFavorite: true,
    aiSummary: 'Q3 产品需求评审覆盖 8 个需求项：5 项通过进入开发排期，2 项需补充技术可行性评估，1 项因优先级较低暂缓至 Q4。重点讨论了搜索重构和数据导出两个核心需求的技术方案。',
    toc: [{ text: '一、评审概况' }, { text: '二、逐项评审结果' }, { text: '三、决议与排期' }],
    relatedDocs: [{ id: 4, title: '需求文档 PRD 模板 v3' }],
    content: '<h2>一、评审概况</h2><p>2025年8月4日14:00-16:30，产品中心Q3需求评审会议...</p>',
    comments: [],
  },
  {
    id: 3, title: '用户访谈实录与洞察 - Q3', category: 'product', author: '陈晨',
    updatedAt: '2025-07-22', views: 89, status: 'ready', statusText: '可检索', statusColor: 'success',
    typeIcon: '🔬', iconBg: '#EFE9FF', iconColor: '#7C5CFC',
    excerpt: '本季度共完成用户访谈 12 场，覆盖 3 类核心用户画像。通过对访谈记录的整理，提炼出 8 个关键痛点与 5 个机会点。',
    wordCount: '5,600', isFavorite: false,
    aiSummary: 'Q3 用户访谈共 12 场，覆盖 3 类核心用户画像。提炼出 8 个关键痛点（搜索效率低、协作流程不透明等）和 5 个机会点（智能推荐、模板化工作流等）。',
    toc: [{ text: '一、访谈概况' }, { text: '二、关键发现' }, { text: '三、痛点汇总' }, { text: '四、机会点' }],
    relatedDocs: [{ id: 1, title: '用户访谈与研究方法' }],
    content: '<h2>一、访谈概况</h2><p>本季度共完成12场用户访谈...</p>',
    comments: [],
  },
  {
    id: 4, title: '需求文档 PRD 模板 v3', category: 'product', author: '张明',
    updatedAt: '2025-07-15', views: 312, status: 'ready', statusText: '可检索', statusColor: 'success',
    typeIcon: '🎯', iconBg: '#FFF4D6', iconColor: '#E6A23C',
    excerpt: '标准 PRD 模板，包含背景、目标、用户场景、功能方案、交互流程、数据埋点、排期等完整模块，支持一键创建。',
    wordCount: '4,200', isFavorite: true,
    aiSummary: 'PRD 模板 v3 更新了数据埋点和排期模块，新增了竞品对比分析章节，适用于 B 端和 C 端产品需求文档编写。',
    toc: [{ text: '一、文档说明' }, { text: '二、背景与目标' }, { text: '三、用户场景' }, { text: '四、功能方案' }, { text: '五、排期计划' }],
    relatedDocs: [],
    content: '<h2>一、文档说明</h2><p>本模板为产品需求文档(PRD)标准格式...</p>',
    comments: [],
  },
  {
    id: 5, title: '微服务架构改造方案', category: 'tech', author: '刘洋',
    updatedAt: '2025-07-10', views: 178, status: 'ready', statusText: '可检索', statusColor: 'success',
    typeIcon: '⚙️', iconBg: '#E0F2FF', iconColor: '#0EA5E9',
    excerpt: '对比微服务、单体、Serverless 三种架构的适用场景，含成本、维护、扩展性维度的评分矩阵。',
    wordCount: '6,800', isFavorite: false,
    aiSummary: '架构改造方案详细对比了三种架构模式，最终推荐渐进式微服务拆分策略，预计分 4 个阶段完成迁移。',
    toc: [{ text: '一、现状分析' }, { text: '二、方案对比' }, { text: '三、推荐方案' }, { text: '四、实施路线图' }],
    relatedDocs: [],
    content: '<h2>一、现状分析</h2><p>当前系统采用单体架构...</p>',
    comments: [],
  },
  {
    id: 6, title: 'API 接口设计规范 v2', category: 'tech', author: '刘洋',
    updatedAt: '2025-07-08', views: 245, status: 'ready', statusText: '可检索', statusColor: 'success',
    typeIcon: '📋', iconBg: '#FFE6E3', iconColor: '#F5483B',
    excerpt: 'RESTful API 设计规范，涵盖命名约定、版本管理、错误码体系、认证鉴权、限流熔断等最佳实践。',
    wordCount: '3,400', isFavorite: false,
    toc: [{ text: '一、命名规范' }, { text: '二、版本管理' }, { text: '三、错误处理' }, { text: '四、安全规范' }],
    relatedDocs: [],
    content: '',
    comments: [],
  },
  {
    id: 7, title: '运营周报标准格式', category: 'ops', author: '赵雪',
    updatedAt: '2025-07-05', views: 134, status: 'ready', statusText: '可检索', statusColor: 'success',
    typeIcon: '📈', iconBg: '#FFF4D6', iconColor: '#E6A23C',
    excerpt: '统一运营周报格式：进展、数据指标、风险、下周计划，支持数据图表自动嵌入。',
    wordCount: '1,800', isFavorite: false,
    toc: [{ text: '一、基本信息' }, { text: '二、核心指标' }, { text: '三、重点工作' }, { text: '四、风险与问题' }],
    relatedDocs: [],
    content: '',
    comments: [],
  },
  {
    id: 8, title: 'SOP 操作手册编写规范', category: 'ops', author: '赵雪',
    updatedAt: '2025-06-28', views: 98, status: 'ready', statusText: '可检索', statusColor: 'success',
    typeIcon: '📚', iconBg: '#E8F1FF', iconColor: '#2B6FFF',
    excerpt: '标准化操作手册的编写规范，含步骤化结构、图文混排、视频嵌入、版本管理等要求。',
    wordCount: '2,900', isFavorite: true,
    toc: [{ text: '一、编写原则' }, { text: '二、结构要求' }, { text: '三、格式规范' }, { text: '四、审核发布流程' }],
    relatedDocs: [],
    content: '',
    comments: [],
  },
  {
    id: 9, title: '客户反馈原始记录 - Q3', category: 'customer', author: '孙磊',
    updatedAt: '2025-06-20', views: 67, status: 'ready', statusText: '可检索', statusColor: 'success',
    typeIcon: '📎', iconBg: '#FFE6E3', iconColor: '#F5483B',
    excerpt: 'Q3 客户反馈汇总，包含 NPS 调研结果、主要投诉类别、改进建议优先级排序。',
    wordCount: '4,500', isFavorite: false,
    toc: [{ text: '一、NPS 调研' }, { text: '二、投诉分析' }, { text: '三、改进建议' }],
    relatedDocs: [],
    content: '',
    comments: [],
  },
  {
    id: 10, title: '用户画像模板 v2', category: 'product', author: '张明',
    updatedAt: '2025-06-15', views: 201, status: 'ready', statusText: '可检索', statusColor: 'success',
    typeIcon: '👤', iconBg: '#EFE9FF', iconColor: '#7C5CFC',
    excerpt: '标准化用户画像模板，包含人口统计特征、行为数据、痛点与需求、使用场景等维度。',
    wordCount: '2,200', isFavorite: false,
    toc: [{ text: '一、基础信息' }, { text: '二、行为特征' }, { text: '三、痛点与需求' }, { text: '四、使用场景' }],
    relatedDocs: [{ id: 1, title: '用户访谈与研究方法' }],
    content: '',
    comments: [],
  },
  {
    id: 11, title: '技术栈选型指南', category: 'tech', author: '刘洋',
    updatedAt: '2025-06-10', views: 167, status: 'parsing', statusText: '解析中', statusColor: 'warning',
    typeIcon: '🔧', iconBg: '#F0F1F3', iconColor: '#6B7280',
    excerpt: '前端框架、后端语言、数据库、缓存、消息队列等技术选型的决策树和评分表。',
    wordCount: '-', isFavorite: false,
    toc: [], relatedDocs: [], content: '',
    comments: [],
  },
  {
    id: 12, title: '新员工入职指南 2025版', category: 'ops', author: '赵雪',
    updatedAt: '2025-06-01', views: 320, status: 'ready', statusText: '可检索', statusColor: 'success',
    typeIcon: '📖', iconBg: '#DBFAE0', iconColor: '#00B85C',
    excerpt: '新员工入职全流程指南，包含入职准备、环境配置、工具介绍、文化融入等内容。',
    wordCount: '5,100', isFavorite: true,
    toc: [{ text: '一、入职第一天' }, { text: '二、环境配置' }, { text: '三、常用工具' }, { text: '四、团队文化' }],
    relatedDocs: [],
    content: '',
    comments: [],
  },
];

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function nextId() {
  const max = _store.reduce((m, d) => (d.id > m ? d.id : m), 0);
  return max + 1;
}

function todayStr() {
  return new Date().toISOString().split('T')[0];
}

// GET /api/knowledge/list
export async function listDocuments() {
  await delay(350);
  return { data: _store.map((d) => ({ ...d })), total: _store.length };
}

// POST /api/knowledge  (新建空白/模板文档)
export async function createDocument(payload = {}) {
  await delay(400);
  const doc = {
    id: nextId(),
    title: payload.title || '未命名文档',
    category: payload.category || 'product',
    author: payload.author || '李明',
    updatedAt: todayStr(),
    views: 0,
    status: 'ready',
    statusText: '可检索',
    statusColor: 'success',
    typeIcon: '📄',
    iconBg: '#E8F1FF',
    iconColor: '#2B6FFF',
    excerpt: (payload.content || '').substring(0, 80) || '（暂无摘要）',
    wordCount: String((payload.content || '').length),
    isFavorite: false,
    aiSummary: '',
    toc: [],
    relatedDocs: [],
    content: payload.content || '',
    comments: [],
    isUploaded: false,
  };
  _store.unshift(doc);
  return { data: { ...doc } };
}

// POST /api/knowledge/upload  (上传文件)
export async function uploadDocument(file, payload = {}) {
  await delay(700);
  const ext = (String(file?.name || '').split('.').pop() || 'FILE').toUpperCase();
  const iconMap = { PDF: '📕', DOC: '📝', DOCX: '📝', XLS: '📊', XLSX: '📊', PPT: '📑', PPTX: '📑', MD: '📄', DEFAULT: '📄' };
  const bgMap = { PDF: '#FFE6E3', DOC: '#DBFAE0', XLS: '#FFF4D6', PPT: '#EFE6FF', MD: '#E8F1FF', IMG: '#E0F2FF', DEFAULT: '#E8F1FF' };
  const colorMap = { PDF: '#F5483B', DOC: '#00B85C', XLS: '#E6A23C', PPT: '#7C5CFC', MD: '#2B6FFF', IMG: '#0EA5E9', DEFAULT: '#2B6FFF' };
  const isImg = ['PNG', 'JPG', 'JPEG', 'GIF'].includes(ext);
  const typeIcon = iconMap[ext] || iconMap.DEFAULT;
  const iconBg = isImg ? bgMap.IMG : (bgMap[ext] || bgMap.DEFAULT);
  const iconColor = isImg ? colorMap.IMG : (colorMap[ext] || colorMap.DEFAULT);
  const doc = {
    id: nextId(),
    title: file?.name || '未命名文件',
    category: payload.category || 'product',
    author: payload.author || '李明',
    updatedAt: todayStr(),
    views: 0,
    status: 'ready',
    statusText: '可检索',
    statusColor: 'success',
    typeIcon,
    iconBg,
    iconColor,
    excerpt: '由文件「' + (file?.name || '') + '」上传生成，已自动解析为可检索文档。',
    wordCount: '-',
    isFavorite: false,
    aiSummary: '该文档由本地文件上传自动生成，内容解析完成后可在此查看 AI 摘要与目录。',
    toc: [],
    relatedDocs: [],
    content: '<p>该文档由本地文件上传生成，内容为原始文件解析结果，可在详情页查看。</p>',
    comments: [],
    isUploaded: true,
  };
  _store.unshift(doc);
  return { data: { ...doc } };
}

// DELETE /api/knowledge/:id
export async function deleteDocument(id) {
  await delay(300);
  _store = _store.filter((d) => d.id !== id);
  return { data: { id } };
}
