<template>
  <div v-if="sessionChecking" class="screen-state">
    <a-spin size="large" />
    <a-typography-paragraph class="screen-copy">正在恢复登录状态...</a-typography-paragraph>
  </div>

  <div v-else-if="currentView === 'workspace'" class="workspace-page">
    <a-layout class="workspace-layout">
      <a-layout-sider :width="448" theme="light" class="workspace-sider">
        <div class="sider-shell">
          <aside class="tool-rail">
            <div class="rail-top">
              <div class="rail-brand">AI</div>
              <button
                v-for="item in toolItems"
                :key="item.key"
                type="button"
                class="rail-item"
                :class="{ 'is-active': item.key === activeToolKey }"
                @click="selectTool(item)"
              >
                <span class="rail-icon">{{ item.short }}</span>
                <span class="rail-label">{{ item.label }}</span>
              </button>
            </div>

            <div class="rail-bottom">
              <a-avatar class="rail-avatar">{{ userInitials }}</a-avatar>
              <a-button type="text" danger class="rail-logout" @click="logout">退出</a-button>
            </div>
          </aside>

          <section class="tool-panel">
            <div class="panel-head">
              <div>
                <div class="panel-overline">{{ activeTool.overline }}</div>
                <a-typography-title :level="4" class="panel-title">
                  {{ activeTool.label }}
                </a-typography-title>
                <a-typography-paragraph class="panel-copy">
                  {{ activeTool.description }}
                </a-typography-paragraph>
              </div>
              <a-tag color="processing">{{ activeTool.status }}</a-tag>
            </div>

            <template v-if="activeToolKey === 'chat'">
              <div class="panel-block">
                <a-button
                  type="primary"
                  block
                  size="large"
                  class="primary-action"
                  :loading="creatingSession"
                  :disabled="!activeAgentId"
                  @click="createNewSession()"
                >
                  新建会话
                </a-button>
              </div>

              <div class="panel-block">
                <div class="block-title">快捷操作</div>
                <div class="shortcut-grid">
                  <button
                    v-for="action in sessionShortcuts"
                    :key="action.label"
                    type="button"
                    class="shortcut-card"
                    @click="handleSessionShortcut(action)"
                  >
                    <span class="shortcut-title">{{ action.label }}</span>
                    <span class="shortcut-copy">{{ action.description }}</span>
                  </button>
                </div>
              </div>

              <div class="panel-block is-fill">
                <div class="block-row">
                  <div class="block-title">会话列表</div>
                  <a-button type="link" size="small" class="inline-action" @click="loadSessions">
                    刷新
                  </a-button>
                </div>

                <div v-if="sessionsLoading" class="section-loading">
                  <a-spin size="small" />
                  <span>正在加载会话...</span>
                </div>

                <div v-else-if="activeAgentId && filteredSessions.length" class="session-list">
                  <button
                    v-for="session in filteredSessions"
                    :key="session.id"
                    type="button"
                    class="session-item"
                    :class="{ 'is-active': session.id === activeSessionId }"
                    @click="activeSessionId = session.id"
                  >
                    <span class="session-title">{{ session.title }}</span>
                    <span class="session-time">{{ formatTime(session.updated_at) }}</span>
                  </button>
                </div>

                <div v-else class="section-empty">
                  <a-empty :image="simpleEmptyImage" description="当前智能体下还没有会话" />
                </div>
              </div>
            </template>

            <template v-else-if="activeToolKey === 'agents'">
              <div class="panel-block">
                <div class="block-row">
                  <div class="block-title">当前智能体</div>
                  <a-button type="link" size="small" class="inline-action" @click="loadAgents">
                    刷新
                  </a-button>
                </div>
                <a-select
                  v-model:value="activeAgentId"
                  class="panel-select"
                  size="large"
                  :options="agentSelectOptions"
                  :loading="workspaceLoading"
                  :disabled="!agents.length"
                  placeholder="选择智能体"
                />
                <div v-if="currentAgent" class="agent-summary">
                  <div class="agent-card-title-row">
                    <span class="agent-card-name">{{ currentAgent.name }}</span>
                    <a-tag color="blue">{{ currentAgent.model }}</a-tag>
                  </div>
                  <div class="agent-card-copy">温度 {{ currentAgent.temperature }}，当前已接入会话工作台。</div>
                </div>
                <a-empty v-else :image="simpleEmptyImage" description="暂无智能体" />
              </div>

              <div class="panel-block">
                <div class="block-title">能力预览</div>
                <div class="tag-grid">
                  <a-tag v-for="tag in agentCapabilityTags" :key="tag" color="processing">{{ tag }}</a-tag>
                </div>
              </div>

              <div class="panel-block">
                <div class="block-title">智能体操作</div>
                <div class="shortcut-grid single-column">
                  <button type="button" class="shortcut-card" @click="createDemoAgent">
                    <span class="shortcut-title">创建示例智能体</span>
                    <span class="shortcut-copy">在没有智能体时，补一个用于联调的标准示例。</span>
                  </button>
                  <button type="button" class="shortcut-card" @click="focusComposer">
                    <span class="shortcut-title">继续当前对话</span>
                    <span class="shortcut-copy">保持右侧主会话区不跳转，直接回到输入区继续协作。</span>
                  </button>
                </div>
              </div>
            </template>

            <template v-else-if="activeToolKey === 'knowledge'">
              <div class="panel-block">
                <div class="block-title">知识入口</div>
                <div class="knowledge-list">
                  <a-card v-for="item in knowledgeCards" :key="item.title" size="small" class="mini-card">
                    <template #title>{{ item.title }}</template>
                    <div class="mini-card-copy">{{ item.copy }}</div>
                  </a-card>
                </div>
              </div>

              <div class="panel-block">
                <div class="block-title">后续接入建议</div>
                <a-list size="small" :data-source="knowledgeTodo">
                  <template #renderItem="{ item }">
                    <a-list-item>{{ item }}</a-list-item>
                  </template>
                </a-list>
              </div>
            </template>

            <template v-else>
              <div class="panel-block">
                <div class="block-title">工具中心</div>
                <div class="tool-status-list">
                  <div v-for="item in toolCenterItems" :key="item.title" class="status-row">
                    <div>
                      <div class="status-title">{{ item.title }}</div>
                      <div class="status-copy">{{ item.copy }}</div>
                    </div>
                    <a-tag :color="item.color">{{ item.status }}</a-tag>
                  </div>
                </div>
              </div>

              <div class="panel-block">
                <div class="block-title">建议动作</div>
                <div class="shortcut-grid single-column">
                  <button
                    type="button"
                    class="shortcut-card"
                    @click="setWorkspaceNotice('工具中心后续可继续接入搜索、浏览器控制、知识检索等能力。', 'info')"
                  >
                    <span class="shortcut-title">查看接入说明</span>
                    <span class="shortcut-copy">保持当前会话布局不变，在二级面板里扩充能力入口。</span>
                  </button>
                </div>
              </div>
            </template>

            <a-card :bordered="false" class="profile-card">
              <div class="profile-row">
                <a-avatar class="profile-avatar">{{ userInitials }}</a-avatar>
                <div class="profile-info">
                  <div class="profile-name">{{ currentUser?.name || '团队成员' }}</div>
                  <div class="profile-email">{{ currentUser?.email || '' }}</div>
                </div>
              </div>
              <a-button danger block @click="logout">退出登录</a-button>
            </a-card>
          </section>
        </div>
      </a-layout-sider>

      <a-layout-content class="workspace-content">
        <header class="workspace-header">
          <div>
            <a-typography-title :level="3" class="workspace-title">
              {{ activeSessionTitle }}
            </a-typography-title>
            <a-typography-paragraph class="workspace-subtitle">
              左侧现在是一级工具导航加二级功能面板，右侧继续保持当前会话区不跳出，便于围绕同一智能体持续协作。
            </a-typography-paragraph>
          </div>

          <div class="header-controls">
            <a-select
              v-model:value="activeAgentId"
              class="agent-select"
              size="large"
              :options="agentSelectOptions"
              :loading="workspaceLoading"
              :disabled="!agents.length"
              placeholder="选择智能体"
            />
            <a-tag v-if="activeAgentModel" color="processing">{{ activeAgentModel }}</a-tag>
          </div>
        </header>

        <a-alert
          v-if="workspaceNotice"
          class="workspace-alert"
          :type="workspaceNoticeType"
          :message="workspaceNotice"
          show-icon
          closable
          @close="workspaceNotice = ''"
        />

        <section class="conversation-stage">
          <div v-if="workspaceLoading" class="screen-state compact-state">
            <a-spin />
            <span>正在加载工作台...</span>
          </div>

          <div v-else-if="!agents.length" class="empty-panel">
            <a-card :bordered="false" class="empty-card">
              <a-empty description="当前账号下还没有智能体" />
              <a-typography-paragraph class="empty-copy">
                先创建一个示例智能体，我们就能继续把注册、登录、会话这条链路完整联调起来。
              </a-typography-paragraph>
              <a-button type="primary" size="large" :loading="creatingAgent" @click="createDemoAgent">
                创建示例智能体
              </a-button>
            </a-card>
          </div>

          <div v-else-if="!activeSessionId" class="empty-panel">
            <a-card :bordered="false" class="empty-card session-welcome-card">
              <div class="welcome-mark">{{ activeAgentShort }}</div>
              <a-typography-title :level="2" class="welcome-title">
                从 {{ activeAgentName }} 开始一段新会话
              </a-typography-title>
              <a-typography-paragraph class="empty-copy">
                这里不是传统 dashboard，而是直接进入对话工作区。你可以先新建会话，或者使用下方快捷提示发起第一条消息。
              </a-typography-paragraph>
              <div class="quick-prompt-list">
                <button
                  v-for="prompt in quickPrompts"
                  :key="prompt"
                  type="button"
                  class="quick-prompt"
                  @click="applyPrompt(prompt)"
                >
                  {{ prompt }}
                </button>
              </div>
              <a-button type="primary" size="large" @click="createNewSession()">新建会话</a-button>
            </a-card>
          </div>

          <div v-else-if="messagesLoading" class="message-loading">
            <a-skeleton active :paragraph="{ rows: 6 }" />
          </div>

          <div v-else-if="messages.length" class="message-list">
            <article
              v-for="message in messages"
              :key="message.id"
              class="message-row"
              :class="'is-' + message.role"
            >
              <div class="message-meta">
                <a-avatar size="small" class="message-avatar">
                  {{ message.role === 'assistant' ? activeAgentShort : userInitials }}
                </a-avatar>
                <div>
                  <div class="message-role">{{ message.role === 'assistant' ? activeAgentName : currentUser?.name || '我' }}</div>
                  <div class="message-time">{{ formatTime(message.created_at) }}</div>
                </div>
              </div>
              <div class="message-bubble">{{ message.content }}</div>
            </article>
          </div>

          <div v-else class="empty-panel">
            <a-card :bordered="false" class="empty-card session-welcome-card">
              <div class="welcome-mark">{{ activeAgentShort }}</div>
              <a-typography-title :level="2" class="welcome-title">
                当前会话还没有消息
              </a-typography-title>
              <a-typography-paragraph class="empty-copy">
                你可以直接输入问题，或者点一个快捷提示，把当前智能体拉进实际工作语境里。
              </a-typography-paragraph>
              <div class="quick-prompt-list">
                <button
                  v-for="prompt in quickPrompts"
                  :key="prompt"
                  type="button"
                  class="quick-prompt"
                  @click="applyPrompt(prompt)"
                >
                  {{ prompt }}
                </button>
              </div>
            </a-card>
          </div>
        </section>

        <footer class="composer-footer">
          <a-card :bordered="false" class="composer-card">
            <a-textarea
              ref="composerRef"
              v-model:value="draftMessage"
              :auto-size="{ minRows: 3, maxRows: 7 }"
              :disabled="!agents.length || sendingMessage"
              :placeholder="composerPlaceholder"
              @keydown="handleComposerKeydown"
            />

            <div class="composer-toolbar">
              <div class="composer-tags">
                <span class="composer-tag">深度思考</span>
                <span class="composer-tag is-active">联网搜索</span>
                <span class="composer-tag">知识库</span>
              </div>

              <a-button
                type="primary"
                size="large"
                :loading="sendingMessage"
                :disabled="!agents.length"
                @click="sendMessage"
              >
                发送消息
              </a-button>
            </div>
          </a-card>
        </footer>
      </a-layout-content>
    </a-layout>
  </div>

  <div v-else class="auth-page">
    <section class="auth-hero">
      <div class="hero-label">Vue 3 / Ant Design Vue</div>
      <a-typography-title :level="1" class="hero-title">
        统一注册、登录与会话入口
      </a-typography-title>
      <a-typography-paragraph class="hero-copy">
        当前认证区和工作台都基于同一套 Ant Design Vue 组件系统实现。登录成功后不进入传统概览页，而是直接进入智能体会话工作台。
      </a-typography-paragraph>

      <div class="hero-grid">
        <a-card v-for="item in heroHighlights" :key="item.key" :bordered="false" class="hero-card">
          <div class="hero-card-index">{{ item.index }}</div>
          <a-typography-title :level="4" class="hero-card-title">{{ item.title }}</a-typography-title>
          <a-typography-paragraph class="hero-card-copy">{{ item.copy }}</a-typography-paragraph>
        </a-card>
      </div>
    </section>

    <section class="auth-panel">
      <a-card :bordered="false" class="auth-card">
        <div class="auth-card-head">
          <div class="panel-label">Authentication</div>
          <a-typography-title :level="2" class="auth-card-title">账号认证</a-typography-title>
          <a-typography-paragraph class="auth-card-copy">
            注册和登录都直接联调后端接口，并保留清晰的校验、提交中、成功和错误反馈。
          </a-typography-paragraph>
        </div>

        <a-tabs v-model:activeKey="activeTab" class="auth-tabs">
          <a-tab-pane key="login" tab="登录">
            <a-form layout="vertical">
              <a-form-item label="邮箱">
                <a-input v-model:value="loginForm.email" size="large" placeholder="you@agentlab.dev" />
              </a-form-item>

              <a-form-item label="密码">
                <a-input-password
                  v-model:value="loginForm.password"
                  size="large"
                  placeholder="请输入登录密码"
                />
              </a-form-item>

              <a-form-item>
                <a-checkbox v-model:checked="loginForm.rememberMe">
                  记住当前登录状态，便于下次直接恢复会话工作台
                </a-checkbox>
              </a-form-item>

              <a-alert
                v-if="loginMessage"
                :type="loginMessageType"
                :message="loginMessage"
                show-icon
                class="feedback-alert"
              />

              <a-button
                type="primary"
                size="large"
                block
                :loading="loginSubmitting"
                @click="submitLogin"
              >
                登录并进入会话页
              </a-button>
            </a-form>
          </a-tab-pane>

          <a-tab-pane key="register" tab="注册">
            <a-form layout="vertical">
              <a-form-item label="名称">
                <a-input
                  v-model:value="registerForm.name"
                  size="large"
                  :maxlength="100"
                  placeholder="例如：产品实验室"
                />
              </a-form-item>

              <a-form-item label="邮箱">
                <a-input v-model:value="registerForm.email" size="large" placeholder="you@agentlab.dev" />
              </a-form-item>

              <a-form-item label="密码">
                <a-input-password
                  v-model:value="registerForm.password"
                  size="large"
                  placeholder="至少 8 位，建议混合大小写和数字"
                />
              </a-form-item>

              <a-form-item label="确认密码">
                <a-input-password
                  v-model:value="registerForm.confirmPassword"
                  size="large"
                  placeholder="再次输入密码"
                />
              </a-form-item>

              <div class="password-meter">
                <a-progress :percent="passwordPercent" :show-info="false" :stroke-color="passwordColor" />
                <span class="password-meter-copy">{{ passwordLabel }}</span>
              </div>

              <a-form-item>
                <a-checkbox v-model:checked="registerForm.agreement">
                  我已知晓这是当前 Agent 项目的测试入口，同意继续进入后续工作台流程
                </a-checkbox>
              </a-form-item>

              <a-alert
                v-if="registerMessage"
                :type="registerMessageType"
                :message="registerMessage"
                show-icon
                class="feedback-alert"
              />

              <a-button
                type="primary"
                size="large"
                block
                :loading="registerSubmitting"
                @click="submitRegister"
              >
                创建账号
              </a-button>
            </a-form>
          </a-tab-pane>
        </a-tabs>
      </a-card>

      <a-card :bordered="false" class="status-card">
        <template #title>当前联调接口</template>
        <ul class="status-list">
          <li><code>POST /api/auth/register</code></li>
          <li><code>POST /api/auth/login</code></li>
          <li><code>GET /api/auth/me</code></li>
          <li><code>GET /api/agents/list_agents</code></li>
          <li><code>GET /api/sessions/list_sessions</code></li>
          <li><code>GET /api/sessions/session/{session_id}</code></li>
          <li><code>POST /api/sessions/session/{session_id}/chat/stream</code></li>
        </ul>
        <pre class="result-panel">{{ activeTab === 'login' ? loginPreview : registerPreview }}</pre>
      </a-card>
    </section>
  </div>
</template>

<script setup>
import { Empty } from 'ant-design-vue';
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue';

const API_PREFIX = '/api';
const STORAGE_TOKEN_KEY = 'agent_access_token';
const DEFAULT_SESSION_TITLE = '新对话';

const simpleEmptyImage = Empty.PRESENTED_IMAGE_SIMPLE;

const activeTab = ref('login');
const currentView = ref('auth');
const sessionChecking = ref(true);
const workspaceLoading = ref(false);
const sessionsLoading = ref(false);
const messagesLoading = ref(false);
const registerSubmitting = ref(false);
const loginSubmitting = ref(false);
const creatingAgent = ref(false);
const creatingSession = ref(false);
const sendingMessage = ref(false);

const composerRef = ref(null);
const currentToken = ref('');
const currentUser = ref(null);
const activeToolKey = ref('chat');
const activeAgentId = ref(null);
const activeSessionId = ref(null);
const agents = ref([]);
const sessions = ref([]);
const messages = ref([]);
const draftMessage = ref('');
const workspaceNotice = ref('');
const workspaceNoticeType = ref('info');
const registerMessage = ref('');
const registerMessageType = ref('info');
const loginMessage = ref('');
const loginMessageType = ref('info');
const registerPreview = ref('等待注册提交...');
const loginPreview = ref('等待登录提交...');

const toolItems = [
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
    status: '待接入',
    description: '二级面板预留知识入口，后续可直接挂接检索与数据源。',
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

const heroHighlights = [
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
    copy: '加载中、接口报错、注册成功、流式回复中都在页面内明确反馈，便于联调和排查。',
  },
];

const sessionShortcuts = [
  {
    label: '发起新会话',
    description: '为当前智能体快速开一个新的上下文窗口。',
    action: 'new-session',
  },
  {
    label: '聚焦输入区',
    description: '回到右侧主会话输入框，继续当前任务。',
    action: 'focus-composer',
  },
];

const agentCapabilityTags = ['会话编排', '知识问答', '流程协同', '工具调用'];
const knowledgeCards = [
  { title: '知识分组', copy: '后续可在这里按业务线、项目、角色拆分知识来源。' },
  { title: '检索状态', copy: '二级区可以直接展示命中情况、索引更新时间和召回策略。' },
];
const knowledgeTodo = [
  '接入知识库列表与详情弹层',
  '补充检索开关与引用来源状态',
  '把知识命中结果映射到主会话区回复中',
];
const toolCenterItems = [
  { title: '浏览器能力', copy: '适合后续挂接网页浏览、抓取和页面操作。', status: '预留', color: 'gold' },
  { title: '联网搜索', copy: '可扩展为搜索源选择、实时查询和结果缓存。', status: '规划中', color: 'blue' },
  { title: '插件入口', copy: '适合接入自定义工具、插件卡片和可用性状态。', status: '待接入', color: 'default' },
];
const quickPrompts = [
  '先介绍一下你能帮我完成哪些工作。',
  '帮我梳理当前智能体项目的注册到会话链路。',
  '给我一个适合首页欢迎语的智能体开场白。',
];

const registerForm = reactive({
  name: '',
  email: '',
  password: '',
  confirmPassword: '',
  agreement: false,
});

const loginForm = reactive({
  email: '',
  password: '',
  rememberMe: true,
});

const passwordScore = computed(() => {
  let score = 0;
  if (registerForm.password.length >= 8) score += 1;
  if (/[A-Z]/.test(registerForm.password) && /[a-z]/.test(registerForm.password)) score += 1;
  if (/d/.test(registerForm.password)) score += 1;
  if (/[^A-Za-z0-9]/.test(registerForm.password)) score += 1;
  return score;
});

const passwordPercent = computed(() => [0, 25, 50, 75, 100][passwordScore.value]);
const passwordColor = computed(() => ['#d9d9d9', '#ff7875', '#faad14', '#52c41a', '#1677ff'][passwordScore.value]);
const passwordLabel = computed(() => [
  '密码强度：等待输入',
  '密码强度：偏弱，建议增加长度',
  '密码强度：一般，建议混合大小写和数字',
  '密码强度：良好，可以继续',
  '密码强度：很强，适合继续使用',
][passwordScore.value]);

const currentAgent = computed(() => agents.value.find((item) => item.id === activeAgentId.value) || null);
const activeTool = computed(() => toolItems.find((item) => item.key === activeToolKey.value) || toolItems[0]);
const agentSelectOptions = computed(() => agents.value.map((item) => ({ label: item.name, value: item.id })));
const filteredSessions = computed(() => {
  if (!activeAgentId.value) return [];
  return sessions.value.filter((item) => item.agent_id === activeAgentId.value);
});
const activeAgentName = computed(() => currentAgent.value?.name || '智能体');
const activeAgentModel = computed(() => currentAgent.value?.model || '');
const activeAgentShort = computed(() => getShortName(activeAgentName.value, 'AI'));
const userInitials = computed(() => getShortName(currentUser.value?.name, '我'));
const activeSessionTitle = computed(() => {
  const session = filteredSessions.value.find((item) => item.id === activeSessionId.value);
  if (session) return session.title;
  return activeAgentName.value + ' 会话工作台';
});
const composerPlaceholder = computed(() => '给 ' + activeAgentName.value + ' 发送消息，Ctrl+Enter 发送');

function getShortName(value, fallback) {
  const text = String(value || '').trim();
  if (!text) return fallback;
  return text.slice(0, 2).toUpperCase();
}

function formatTime(value) {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function setWorkspaceNotice(message, type = 'info') {
  workspaceNotice.value = message;
  workspaceNoticeType.value = type;
}

function setRegisterMessage(message, type = 'info') {
  registerMessage.value = message;
  registerMessageType.value = type;
}

function setLoginMessage(message, type = 'info') {
  loginMessage.value = message;
  loginMessageType.value = type;
}

function clearStoredSession() {
  localStorage.removeItem(STORAGE_TOKEN_KEY);
}

function resetWorkspaceState() {
  activeAgentId.value = null;
  activeSessionId.value = null;
  agents.value = [];
  sessions.value = [];
  messages.value = [];
  draftMessage.value = '';
}

function logout() {
  currentToken.value = '';
  currentUser.value = null;
  currentView.value = 'auth';
  workspaceNotice.value = '';
  clearStoredSession();
  resetWorkspaceState();
  activeTab.value = 'login';
  loginForm.password = '';
  setLoginMessage('你已退出登录。', 'info');
}

function applyPrompt(prompt) {
  draftMessage.value = prompt;
  focusComposer();
}

function selectTool(item) {
  activeToolKey.value = item.key;
}

function handleSessionShortcut(action) {
  if (action.action === 'new-session') {
    createNewSession();
    return;
  }
  if (action.action === 'focus-composer') {
    focusComposer();
  }
}

function focusComposer() {
  nextTick(() => {
    const instance = composerRef.value;
    const textarea = instance?.resizableTextArea?.textArea || instance?.$el?.querySelector?.('textarea');
    textarea?.focus?.();
  });
}

function syncActiveSessionSelection() {
  const list = filteredSessions.value;
  if (!list.length) {
    activeSessionId.value = null;
    messages.value = [];
    return;
  }
  if (!list.some((item) => item.id === activeSessionId.value)) {
    activeSessionId.value = list[0].id;
  }
}

async function parseApiResponse(response) {
  const rawText = await response.text();
  let data = null;
  if (rawText) {
    try {
      data = JSON.parse(rawText);
    } catch {
      throw new Error('接口返回了非 JSON 内容：' + rawText.slice(0, 120));
    }
  }
  if (!response.ok) {
    throw new Error(data?.detail || data?.message || ('请求失败：' + response.status + ' ' + response.statusText));
  }
  return data;
}

async function apiJson(path, options = {}) {
  const headers = {
    ...(currentToken.value ? { Authorization: 'Bearer ' + currentToken.value } : {}),
    ...(options.body ? { 'Content-Type': 'application/json' } : {}),
    ...(options.headers || {}),
  };
  const response = await fetch(API_PREFIX + path, { ...options, headers });
  return parseApiResponse(response);
}

async function fetchCurrentUser(token) {
  const response = await fetch(API_PREFIX + '/auth/me', {
    headers: { Authorization: 'Bearer ' + token },
  });
  return parseApiResponse(response);
}

async function loadAgents() {
  const result = await apiJson('/agents/list_agents');
  agents.value = Array.isArray(result?.data) ? result.data : [];
  if (!agents.value.length) {
    activeAgentId.value = null;
    return;
  }
  if (!agents.value.some((item) => item.id === activeAgentId.value)) {
    activeAgentId.value = agents.value[0].id;
  }
}

async function loadSessions() {
  sessionsLoading.value = true;
  try {
    const result = await apiJson('/sessions/list_sessions');
    sessions.value = Array.isArray(result?.data) ? result.data : [];
    syncActiveSessionSelection();
  } finally {
    sessionsLoading.value = false;
  }
}

async function loadMessages(sessionId) {
  if (!sessionId) {
    messages.value = [];
    return;
  }
  messagesLoading.value = true;
  try {
    const result = await apiJson('/sessions/session/' + sessionId);
    messages.value = Array.isArray(result?.data) ? result.data : [];
  } finally {
    messagesLoading.value = false;
  }
}

async function createDemoAgent() {
  creatingAgent.value = true;
  setWorkspaceNotice('正在创建示例智能体...', 'info');
  try {
    await apiJson('/agents/create_agent', {
      method: 'POST',
      body: JSON.stringify({
        name: '扫地机器人客服',
        system_prompt: '你是一个面向扫地机器人售前、售后与维护场景的智能客服，回答需要简洁、准确、友好。',
        model: 'qwen/qwen3-1.7b',
        temperature: 0.2,
      }),
    });
    await loadAgents();
    await loadSessions();
    setWorkspaceNotice('示例智能体已创建，可以开始新会话了。', 'success');
  } catch (error) {
    setWorkspaceNotice(error?.message || '创建示例智能体失败', 'error');
  } finally {
    creatingAgent.value = false;
  }
}

async function createNewSession(title = DEFAULT_SESSION_TITLE) {
  if (!activeAgentId.value) {
    setWorkspaceNotice('请先选择一个智能体。', 'warning');
    return null;
  }
  creatingSession.value = true;
  try {
    const result = await apiJson('/sessions/create_session', {
      method: 'POST',
      body: JSON.stringify({ title, agent_id: activeAgentId.value }),
    });
    const createdSession = result?.data || null;
    await loadSessions();
    if (createdSession?.id) {
      activeSessionId.value = createdSession.id;
      messages.value = [];
    }
    setWorkspaceNotice('已创建新会话。', 'success');
    return createdSession;
  } catch (error) {
    setWorkspaceNotice(error?.message || '创建会话失败', 'error');
    return null;
  } finally {
    creatingSession.value = false;
  }
}

function appendMessage(message) {
  messages.value = [...messages.value, message];
}

function updateMessageContent(messageId, content) {
  messages.value = messages.value.map((item) => item.id === messageId ? { ...item, content } : item);
}

function replaceMessage(messageId, nextMessage) {
  messages.value = messages.value.map((item) => item.id === messageId ? nextMessage : item);
}

async function consumeChatStream(response, assistantDraftId) {
  if (!response.body) {
    throw new Error('流式响应不可用');
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  let assistantText = '';

  const processBlock = async (block) => {
    if (!block.trim()) return;
    const lines = block.split('\n');
    let eventName = 'message';
    const dataLines = [];
    for (const line of lines) {
      if (line.startsWith('event:')) eventName = line.slice(6).trim();
      if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
    }
    const payloadText = dataLines.join('\n');
    let payload = {};
    if (payloadText) {
      try {
        payload = JSON.parse(payloadText);
      } catch (e) {
        console.warn('SSE 数据解析失败:', payloadText, e);
        return;
      }
    }
    if (eventName === 'delta') {
      assistantText += payload.content || '';
      updateMessageContent(assistantDraftId, assistantText);
      return;
    }
    if (eventName === 'done') {
      if (payload.message) replaceMessage(assistantDraftId, payload.message);
      await loadSessions();
      return;
    }
    if (eventName === 'error') throw new Error(payload.message || '流式会话返回错误');
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    const chunk = decoder.decode(value, { stream: true });
    // 统一换行符：\r\n -> \n，孤立 \r -> \n，避免残留 \r 污染 JSON 解析
    buffer += chunk.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    const blocks = buffer.split('\n\n');
    buffer = blocks.pop() || '';
    for (const block of blocks) await processBlock(block);
  }
  if (buffer.trim()) await processBlock(buffer.trim());
}

async function sendMessage() {
  const content = draftMessage.value.trim();
  if (!content) return;
  if (!activeAgentId.value) {
    setWorkspaceNotice('当前没有可用智能体。', 'warning');
    return;
  }
  sendingMessage.value = true;
  setWorkspaceNotice('正在发送消息...', 'info');

  let targetSessionId = activeSessionId.value;
  if (!targetSessionId) {
    const createdSession = await createNewSession(DEFAULT_SESSION_TITLE);
    if (!createdSession?.id) {
      sendingMessage.value = false;
      return;
    }
    targetSessionId = createdSession.id;
  }

  const now = new Date().toISOString();
  const optimisticUserMessage = {
    id: 'temp-user-' + Date.now(),
    session_id: targetSessionId,
    role: 'user',
    content,
    created_at: now,
  };
  const optimisticAssistantId = 'temp-assistant-' + Date.now();
  const optimisticAssistantMessage = {
    id: optimisticAssistantId,
    session_id: targetSessionId,
    role: 'assistant',
    content: '',
    created_at: now,
  };

  appendMessage(optimisticUserMessage);
  appendMessage(optimisticAssistantMessage);
  draftMessage.value = '';

  try {
    const response = await fetch(API_PREFIX + '/sessions/session/' + targetSessionId + '/chat/stream', {
      method: 'POST',
      headers: {
        Authorization: 'Bearer ' + currentToken.value,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ content }),
    });
    if (!response.ok) {
      await parseApiResponse(response);
      return;
    }
    await consumeChatStream(response, optimisticAssistantId);
    await loadMessages(targetSessionId);
    setWorkspaceNotice('消息发送成功。', 'success');
  } catch (error) {
    setWorkspaceNotice(error?.message || '发送消息失败', 'error');
    await loadMessages(targetSessionId);
  } finally {
    sendingMessage.value = false;
  }
}

function handleComposerKeydown(event) {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
    event.preventDefault();
    sendMessage();
  }
}

function validateRegisterForm() {
  if (!registerForm.name.trim()) return '请输入名称';
  if (!registerForm.email.trim()) return '请输入邮箱';
  if (registerForm.password.length < 8) return '密码至少需要 8 位';
  if (registerForm.password !== registerForm.confirmPassword) return '两次输入的密码不一致';
  if (!registerForm.agreement) return '请先确认当前测试协议';
  return '';
}

function validateLoginForm() {
  if (!loginForm.email.trim()) return '请输入登录邮箱';
  if (loginForm.password.length < 8) return '请输入正确的登录密码';
  return '';
}

async function enterWorkspace() {
  currentView.value = 'workspace';
  workspaceLoading.value = true;
  try {
    await loadAgents();
    await loadSessions();
    if (activeSessionId.value) {
      await loadMessages(activeSessionId.value);
    } else {
      messages.value = [];
    }
  } finally {
    workspaceLoading.value = false;
  }
}

async function restoreSession() {
  const storedToken = localStorage.getItem(STORAGE_TOKEN_KEY);
  if (!storedToken) {
    sessionChecking.value = false;
    return;
  }
  try {
    const user = await fetchCurrentUser(storedToken);
    currentToken.value = storedToken;
    currentUser.value = user;
    await enterWorkspace();
  } catch {
    clearStoredSession();
    currentToken.value = '';
    currentUser.value = null;
    currentView.value = 'auth';
    activeTab.value = 'login';
    setLoginMessage('登录状态已失效，请重新登录。', 'warning');
  } finally {
    sessionChecking.value = false;
  }
}

async function submitRegister() {
  const errorMessage = validateRegisterForm();
  if (errorMessage) {
    setRegisterMessage(errorMessage, 'error');
    return;
  }
  registerSubmitting.value = true;
  setRegisterMessage('正在创建账号，请稍候...', 'info');
  registerPreview.value = 'Submitting register request...';
  try {
    const result = await apiJson('/auth/register', {
      method: 'POST',
      body: JSON.stringify({
        name: registerForm.name.trim(),
        email: registerForm.email.trim(),
        password: registerForm.password,
      }),
    });
    registerPreview.value = JSON.stringify(result, null, 2);
    setRegisterMessage('注册成功，现在可以直接切换到登录继续。', 'success');
    loginForm.email = registerForm.email.trim();
    registerForm.name = '';
    registerForm.email = '';
    registerForm.password = '';
    registerForm.confirmPassword = '';
    registerForm.agreement = false;
    activeTab.value = 'login';
  } catch (error) {
    const m = error?.message || '注册失败，请检查后端接口状态';
    registerPreview.value = JSON.stringify({ error: m }, null, 2);
    setRegisterMessage(m, 'error');
  } finally {
    registerSubmitting.value = false;
  }
}

async function submitLogin() {
  const errorMessage = validateLoginForm();
  if (errorMessage) {
    setLoginMessage(errorMessage, 'error');
    return;
  }
  loginSubmitting.value = true;
  setLoginMessage('正在登录，请稍候...', 'info');
  loginPreview.value = 'Submitting login request...';
  try {
    const result = await apiJson('/auth/login', {
      method: 'POST',
      body: JSON.stringify({
        email: loginForm.email.trim(),
        password: loginForm.password,
      }),
    });
    const loginData = result?.data || {};
    currentToken.value = loginData.access_token || '';
    currentUser.value = loginData.user || null;
    loginPreview.value = JSON.stringify(result, null, 2);
    if (loginForm.rememberMe && currentToken.value) {
      localStorage.setItem(STORAGE_TOKEN_KEY, currentToken.value);
    } else {
      clearStoredSession();
    }
    setLoginMessage('登录成功，正在进入会话工作台...', 'success');
    loginForm.password = '';
    await enterWorkspace();
  } catch (error) {
    const m = error?.message || '登录失败，请检查后端接口状态';
    loginPreview.value = JSON.stringify({ error: m }, null, 2);
    setLoginMessage(m, 'error');
  } finally {
    loginSubmitting.value = false;
  }
}

watch(activeAgentId, () => {
  syncActiveSessionSelection();
});

watch(activeSessionId, async (sessionId, previousId) => {
  if (sessionId && sessionId !== previousId) {
    await loadMessages(sessionId);
  }
  if (!sessionId) {
    messages.value = [];
  }
});

onMounted(() => {
  restoreSession();
});
</script>