<template>
  <div v-if="sessionChecking" class="screen-state">
    <a-spin size="large" />
    <a-typography-paragraph class="screen-copy">正在恢复登录状态...</a-typography-paragraph>
  </div>

  <div v-else-if="currentView === 'workspace'" class="workspace-page">
    <a-layout class="workspace-layout">
      <a-layout-sider :width="448" theme="light" class="workspace-sider">
        <WorkspaceSidebar
          :tool-items="toolItems"
          :active-tool-key="activeToolKey"
          :active-tool="activeTool"
          :user-initials="userInitials"
          :user-name="currentUser?.name || '团队成员'"
          :user-email="currentUser?.email || ''"
          :creating-session="creatingSession"
          :active-agent-id="activeAgentId"
          :sessions-loading="sessionsLoading"
          :filtered-sessions="filteredSessions"
          :active-session-id="activeSessionId"
          :deleting-session-id="deletingSessionId"
          :empty-image="simpleEmptyImage"
          :format-time="formatTime"
          :agent-options="agentSelectOptions"
          :workspace-loading="workspaceLoading"
          :has-agents="Boolean(agents.length)"
          :current-agent="currentAgent"
          :capability-tags="agentCapabilityTags"
          :knowledge-documents="knowledgeDocuments"
          :knowledge-documents-loading="knowledgeDocumentsLoading"
          :uploading-document-names="uploadingDocumentNames"
          :deleting-knowledge-document-id="deletingKnowledgeDocumentId"
          :conversation-mode="conversationMode"
          :rag-scope-type="ragScopeType"
          :rag-document-ids="ragDocumentIds"
          :active-scoped-documents="activeScopedDocuments"
          :tool-center-items="toolCenterItems"
          @select-tool="selectTool"
          @logout="logout"
          @create-session="createNewSession()"
          @refresh-sessions="loadSessions"
          @select-session="activeSessionId = $event"
          @delete-session="handleDeleteSession"
          @refresh-agents="loadAgents"
          @select-agent="activeAgentId = $event"
          @create-demo-agent="createDemoAgent"
          @focus-composer="focusComposer"
          @show-integration-guide="setWorkspaceNotice('工具中心后续可继续接入搜索、浏览器控制、知识检索等能力。', 'info')"
          @refresh-knowledge="loadKnowledgeDocuments"
          @upload-knowledge-document="handleUploadKnowledgeDocument"
          @delete-knowledge-document="deleteKnowledgeDocument"
          @add-doc-to-scope="addDocumentToScope"
          @set-conversation-mode="setConversationModeWithTraceGuard"
          @update:rag-scope-type="setRagScopeType"
          @update:rag-document-ids="setRagDocumentIds"
        />
      </a-layout-sider>

      <a-layout-content class="workspace-content">
        <AgentManagementView
          v-if="activeToolKey === 'agents'"
          :workspace-loading="workspaceLoading"
          :workspace-notice="workspaceNotice"
          :workspace-notice-type="workspaceNoticeType"
          :agents="agents"
          :editing-agent="editingAgent"
          :active-agent-id="activeAgentId"
          :creating-agent="creatingAgent"
          :deleting-agent-id="deletingAgentId"
          :saving-agent-config="savingAgentConfig"
          :agent-editor-model-options="agentEditorModelOptions"
          :agent-prompt-templates="agentPromptTemplates"
          :agent-tool-suggestions="agentToolSuggestions"
          :agent-knowledge-mocks="agentKnowledgeMocks"
          :active-agent-name="activeAgentName"
          @close-notice="workspaceNotice = ''"
          @open-create-modal="openAgentCreateModal"
          @create-demo-agent="createDemoAgent"
          @activate-agent="setCurrentAgent"
          @open-editor="openAgentEditor"
          @close-editor="closeAgentEditor"
          @enter-chat="enterAgentConversation"
          @delete-agent="deleteAgent"
          @save-agent-config="saveAgentConfig"
          @refresh-agents="loadAgents"
        />

        <ChatWorkspaceView
          v-else
          ref="chatWorkspaceViewRef"
          :active-session-title="activeSessionTitle"
          :workspace-notice="workspaceNotice"
          :workspace-notice-type="workspaceNoticeType"
          :active-agent-id="activeAgentId"
          :agent-select-options="agentSelectOptions"
          :workspace-loading="workspaceLoading"
          :agents="agents"
          :creating-agent="creatingAgent"
          :active-agent-model="activeAgentModel"
          :active-tool-key="activeToolKey"
          :trace-panel-visible="tracePanelVisible"
          :active-session-id="activeSessionId"
          :run-trace-current-id="runTraceCurrentId"
          :sending-message="sendingMessage"
          :active-agent-short="activeAgentShort"
          :active-agent-name="activeAgentName"
          :quick-prompts="quickPrompts"
          :messages-loading="messagesLoading"
          :messages="visibleMessages"
          :user-initials="userInitials"
          :current-user-name="currentUser?.name || '我'"
          :format-time="formatTime"
          :draft-message="draftMessage"
          :composer-placeholder="displayComposerPlaceholder"
          :run-trace-loading="runTraceLoading"
          :run-trace="runTraceData"
          :run-trace-error="runTraceError"
          :conversation-mode="conversationMode"
          :rag-strict-mode="ragStrictMode"
          :rag-top-k="ragTopK"
          :rag-scope-type="ragScopeType"
          :rag-document-ids="ragDocumentIds"
          :knowledge-document-options="knowledgeDocumentOptions"
          :active-scoped-documents="activeScopedDocuments"
          :ready-knowledge-count="readyKnowledgeDocuments.length"
          :trace-supported="traceSupported"
          @update:active-agent-id="activeAgentId = $event"
          @close-notice="workspaceNotice = ''"
          @toggle-run-trace="handleToggleRunTrace"
          @create-demo-agent="createDemoAgent"
          @create-new-session="createNewSession()"
          @apply-prompt="applyPrompt"
          @update:draft-message="draftMessage = $event"
          @update:conversation-mode="setConversationModeWithTraceGuard"
          @update:rag-strict-mode="ragStrictMode = $event"
          @update:rag-top-k="ragTopK = $event"
          @update:rag-scope-type="setRagScopeType"
          @update:rag-document-ids="setRagDocumentIds"
          @send-message="sendMessage"
          @retry-run-trace="refreshRunTrace"
        />
      </a-layout-content>
    </a-layout>
  </div>

  <AuthScreen
    v-else
    :active-tab="activeTab"
    :register-submitting="registerSubmitting"
    :login-submitting="loginSubmitting"
    :register-message="registerMessage"
    :register-message-type="registerMessageType"
    :login-message="loginMessage"
    :login-message-type="loginMessageType"
    :register-preview="registerPreview"
    :login-preview="loginPreview"
    :register-form="registerForm"
    :login-form="loginForm"
    @update:active-tab="activeTab = $event"
    @submit-login="submitLogin"
    @submit-register="submitRegister"
  />

  <CreateAgentModal
    :open="agentModalOpen"
    :creating-custom-agent="creatingCustomAgent"
    :agent-create-form="agentCreateForm"
    @submit="submitCreateAgent"
    @cancel="handleCancelAgentModal"
  />
</template>

<script setup>
import { Empty } from 'ant-design-vue';
import { computed, onMounted, ref, watch } from 'vue';
import AgentManagementView from './features/agent/components/AgentManagementView.vue';
import AuthScreen from './features/auth/components/AuthScreen.vue';
import ChatWorkspaceView from './features/chat/components/ChatWorkspaceView.vue';
import CreateAgentModal from './features/agent/components/CreateAgentModal.vue';
import WorkspaceSidebar from './features/workspace/sidebar/WorkspaceSidebar.vue';
import {
  API_PREFIX,
  STORAGE_TOKEN_KEY,
  DEFAULT_SESSION_TITLE,
  agentCapabilityTags,
  agentKnowledgeMocks,
  agentPromptTemplates,
  agentToolSuggestions,
  baseAgentModelOptions,
  quickPrompts,
  toolCenterItems,
  toolItems,
} from './shared/config/appContent';
import { useApiClient } from './shared/services/useApiClient';
import { useAuthSession } from './features/auth/composables/useAuthSession';
import { useChatSession } from './features/chat/composables/useChatSession';
import { useKnowledgeBase } from './features/knowledge/composables/useKnowledgeBase';
import { useRunTrace } from './features/workspace/composables/useRunTrace';
import { useWorkspaceData } from './features/workspace/composables/useWorkspaceData';
import { formatTime, getShortName } from './shared/utils/uiHelpers';

const simpleEmptyImage = Empty.PRESENTED_IMAGE_SIMPLE;
const chatWorkspaceViewRef = ref(null);
const workspaceNotice = ref('');
const workspaceNoticeType = ref('info');
const sessionOverlayMessages = ref({});

function setWorkspaceNotice(message, type = 'info') {
  workspaceNotice.value = message;
  workspaceNoticeType.value = type;
}

function getSessionOverlayKey(sessionId) {
  return sessionId == null ? '' : String(sessionId);
}

function appendSessionOverlayMessage(sessionId, message) {
  const key = getSessionOverlayKey(sessionId);
  if (!key) return;
  const existing = sessionOverlayMessages.value[key] || [];
  sessionOverlayMessages.value = {
    ...sessionOverlayMessages.value,
    [key]: [...existing, message],
  };
}

function replaceSessionOverlayMessage(sessionId, messageId, nextMessage) {
  const key = getSessionOverlayKey(sessionId);
  if (!key) return;
  const existing = sessionOverlayMessages.value[key] || [];
  sessionOverlayMessages.value = {
    ...sessionOverlayMessages.value,
    [key]: existing.map((item) => item.id === messageId ? nextMessage : item),
  };
}

function clearSessionOverlayMessages(sessionId) {
  const key = getSessionOverlayKey(sessionId);
  if (!key || !sessionOverlayMessages.value[key]) return;
  const nextStore = { ...sessionOverlayMessages.value };
  delete nextStore[key];
  sessionOverlayMessages.value = nextStore;
}

function resetSessionOverlayMessages() {
  sessionOverlayMessages.value = {};
}

let currentTokenRef = null;
let workspaceEnterWorkspace = async () => {};

const { parseApiResponse, apiJson, fetchCurrentUser } = useApiClient(() => currentTokenRef?.value || '', API_PREFIX);

const {
  activeTab,
  currentView,
  sessionChecking,
  registerSubmitting,
  loginSubmitting,
  registerMessage,
  registerMessageType,
  loginMessage,
  loginMessageType,
  registerPreview,
  loginPreview,
  currentToken,
  currentUser,
  registerForm,
  loginForm,
  setLoginMessage,
  clearStoredSession,
  restoreSession,
  submitRegister,
  submitLogin,
} = useAuthSession({
  storageTokenKey: STORAGE_TOKEN_KEY,
  apiJson,
  fetchCurrentUser,
  enterWorkspace: () => workspaceEnterWorkspace(),
});

currentTokenRef = currentToken;

const {
  tracePanelVisible,
  runTraceLoading,
  runTraceCurrentId,
  runTraceData,
  runTraceError,
  stopRunTracePolling,
  clearRunTraceState,
  startRunTracePolling,
  loadRunTraceById,
  loadLatestRunTraceForSession,
  refreshRunTrace,
  toggleRunTracePanel,
} = useRunTrace(apiJson);

const {
  workspaceLoading,
  sessionsLoading,
  messagesLoading,
  creatingAgent,
  creatingSession,
  sendingMessage,
  deletingSessionId,
  deletingAgentId,
  savingAgentConfig,
  editingAgentId,
  agentModalOpen,
  creatingCustomAgent,
  activeToolKey,
  activeAgentId,
  activeSessionId,
  agents,
  sessions,
  messages,
  draftMessage,
  agentCreateForm,
  currentAgent,
  editingAgent,
  agentSelectOptions,
  agentEditorModelOptions,
  filteredSessions,
  activeAgentName,
  activeAgentModel,
  activeAgentShort,
  userInitials,
  activeSessionTitle,
  composerPlaceholder,
  resetWorkspaceState,
  selectTool,
  applyPrompt: setDraftFromPrompt,
  openAgentCreateModal,
  resetAgentCreateForm,
  openAgentEditor,
  closeAgentEditor,
  setCurrentAgent,
  loadAgents,
  loadSessions,
  loadMessages,
  createDemoAgent,
  deleteAgent,
  createNewSession,
  deleteSession,
  submitCreateAgent,
  saveAgentConfig,
  enterAgentConversation,
  enterWorkspace: enterWorkspaceView,
} = useWorkspaceData({
  apiJson,
  setWorkspaceNotice,
  getShortName,
  formatTime,
  currentUser,
  baseAgentModelOptions,
  defaultSessionTitle: DEFAULT_SESSION_TITLE,
  stopRunTracePolling,
  clearRunTraceState,
  tracePanelVisible,
  loadLatestRunTraceForSession,
});

const {
  conversationMode,
  ragScopeType,
  ragDocumentIds,
  ragStrictMode,
  ragTopK,
  knowledgeDocuments,
  knowledgeDocumentsLoading,
  uploadingDocumentNames,
  deletingKnowledgeDocumentId,
  readyKnowledgeDocuments,
  knowledgeDocumentOptions,
  activeScopedDocuments,
  effectiveRagDocumentIds,
  resetKnowledgeState,
  setConversationMode,
  setRagScopeType,
  setRagDocumentIds,
  addDocumentToScope,
  loadKnowledgeDocuments,
  uploadKnowledgeDocument,
  deleteKnowledgeDocument,
} = useKnowledgeBase({
  apiPrefix: API_PREFIX,
  currentToken,
  parseApiResponse,
  apiJson,
  setWorkspaceNotice,
});

workspaceEnterWorkspace = async () => {
  await enterWorkspaceView(currentView);
  try {
    await loadKnowledgeDocuments();
  } catch (error) {
    setWorkspaceNotice(error?.message || '加载知识库失败', 'warning');
  }
};

const activeTool = computed(() => toolItems.find((item) => item.key === activeToolKey.value) || toolItems[0]);

const visibleMessages = computed(() => {
  const serverMessages = Array.isArray(messages.value) ? messages.value : [];
  const key = getSessionOverlayKey(activeSessionId.value);
  const overlayMessages = key ? (sessionOverlayMessages.value[key] || []) : [];

  return [...serverMessages, ...overlayMessages].sort((left, right) => {
    const leftTime = Date.parse(left?.created_at || '');
    const rightTime = Date.parse(right?.created_at || '');
    if (Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime !== rightTime) {
      return leftTime - rightTime;
    }
    return String(left?.id || '').localeCompare(String(right?.id || ''));
  });
});

const displayComposerPlaceholder = computed(() => (
  conversationMode.value === 'rag'
    ? '向知识库提问，可限定文档范围并控制 strict mode / top_k。Ctrl+Enter 发送'
    : composerPlaceholder.value
));

const traceSupported = computed(() => conversationMode.value === 'chat');

const { sendMessage } = useChatSession({
  apiPrefix: API_PREFIX,
  defaultSessionTitle: DEFAULT_SESSION_TITLE,
  currentToken,
  activeAgentId,
  activeSessionId,
  draftMessage,
  messages,
  sendingMessage,
  conversationMode,
  ragStrictMode,
  ragTopK,
  effectiveRagDocumentIds,
  createNewSession,
  loadMessages,
  loadSessions,
  setWorkspaceNotice,
  stopRunTracePolling,
  startRunTracePolling,
  loadRunTraceById,
  runTraceCurrentId,
  tracePanelVisible,
  parseApiResponse,
  appendSessionOverlayMessage,
  replaceSessionOverlayMessage,
});

function setConversationModeWithTraceGuard(mode) {
  setConversationMode(mode);
  if (mode === 'rag') {
    tracePanelVisible.value = false;
    stopRunTracePolling();
    clearRunTraceState();
  }
}

async function handleToggleRunTrace(sessionId) {
  if (!traceSupported.value) {
    tracePanelVisible.value = false;
    stopRunTracePolling();
    clearRunTraceState();
    setWorkspaceNotice('当前后端还没有提供 RAG trace 查询接口，知识库问答暂不支持查看轨迹。', 'info');
    return;
  }
  await toggleRunTracePanel(sessionId);
}

async function handleUploadKnowledgeDocument(file) {
  try {
    await uploadKnowledgeDocument(file);
  } catch {
    return false;
  }
  return false;
}

async function handleDeleteSession(sessionId) {
  clearSessionOverlayMessages(sessionId);
  await deleteSession(sessionId);
}

function logout() {
  currentToken.value = '';
  currentUser.value = null;
  currentView.value = 'auth';
  workspaceNotice.value = '';
  clearStoredSession();
  resetWorkspaceState();
  resetKnowledgeState();
  resetSessionOverlayMessages();
  activeTab.value = 'login';
  loginForm.password = '';
  setLoginMessage('你已退出登录。', 'info');
}

function focusComposer() {
  chatWorkspaceViewRef.value?.focusComposer?.();
}

function applyPrompt(prompt) {
  setDraftFromPrompt(prompt);
  focusComposer();
}

function handleCancelAgentModal() {
  agentModalOpen.value = false;
  resetAgentCreateForm();
}

watch(conversationMode, (mode) => {
  if (mode === 'rag') {
    tracePanelVisible.value = false;
    stopRunTracePolling();
    clearRunTraceState();
  }
});

onMounted(() => {
  restoreSession();
});
</script>
