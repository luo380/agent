<template>
  <div>
    <header class="workspace-header">
      <div>
        <a-typography-title :level="3" class="workspace-title">
          {{ activeSessionTitle }}
        </a-typography-title>
        <a-typography-paragraph class="workspace-subtitle">
          左侧负责工具导航与上下文入口，右侧保持会话工作区，便于围绕当前智能体持续协作。
        </a-typography-paragraph>
      </div>

      <div class="header-controls">
        <a-select
          v-model:value="agentIdProxy"
          class="agent-select"
          size="large"
          :options="agentSelectOptions"
          :loading="workspaceLoading"
          :disabled="!agents.length"
          placeholder="选择智能体"
        />
        <a-tag v-if="activeAgentModel" color="processing">{{ activeAgentModel }}</a-tag>
        <a-button
          v-if="activeToolKey === 'chat'"
          class="trace-toggle-button"
          :disabled="!activeSessionId && !runTraceCurrentId && !sendingMessage"
          @click="$emit('toggle-run-trace', activeSessionId)"
        >
          {{ tracePanelVisible ? '隐藏轨迹' : '执行轨迹' }}
        </a-button>
      </div>
    </header>

    <a-alert
      v-if="workspaceNotice"
      class="workspace-alert"
      :type="workspaceNoticeType"
      :message="workspaceNotice"
      show-icon
      closable
      @close="$emit('close-notice')"
    />

    <ConversationWorkspace
      ref="conversationWorkspaceRef"
      :workspace-loading="workspaceLoading"
      :agents="agents"
      :creating-agent="creatingAgent"
      :active-session-id="activeSessionId"
      :active-agent-short="activeAgentShort"
      :active-agent-name="activeAgentName"
      :quick-prompts="quickPrompts"
      :messages-loading="messagesLoading"
      :messages="messages"
      :user-initials="userInitials"
      :current-user-name="currentUserName"
      :format-time="formatTime"
      :draft-message="draftMessage"
      :sending-message="sendingMessage"
      :composer-placeholder="composerPlaceholder"
      :trace-visible="tracePanelVisible"
      :run-trace-loading="runTraceLoading"
      :run-trace="runTrace"
      :run-trace-error="runTraceError"
      @create-demo-agent="$emit('create-demo-agent')"
      @create-new-session="$emit('create-new-session')"
      @apply-prompt="$emit('apply-prompt', $event)"
      @update:draft-message="$emit('update:draftMessage', $event)"
      @send-message="$emit('send-message')"
      @retry-run-trace="$emit('retry-run-trace', activeSessionId)"
    />
  </div>
</template>

<script setup>
import { computed, ref } from 'vue';
import ConversationWorkspace from './ConversationWorkspace.vue';

const props = defineProps({
  activeSessionTitle: { type: String, default: '' },
  workspaceNotice: { type: String, default: '' },
  workspaceNoticeType: { type: String, default: 'info' },
  activeAgentId: { type: [Number, String], default: null },
  agentSelectOptions: { type: Array, default: () => [] },
  workspaceLoading: { type: Boolean, default: false },
  agents: { type: Array, default: () => [] },
  creatingAgent: { type: Boolean, default: false },
  activeAgentModel: { type: String, default: '' },
  activeToolKey: { type: String, default: 'chat' },
  tracePanelVisible: { type: Boolean, default: false },
  activeSessionId: { type: [Number, String], default: null },
  runTraceCurrentId: { type: [Number, String], default: null },
  sendingMessage: { type: Boolean, default: false },
  activeAgentShort: { type: String, default: 'AI' },
  activeAgentName: { type: String, default: '智能体' },
  quickPrompts: { type: Array, default: () => [] },
  messagesLoading: { type: Boolean, default: false },
  messages: { type: Array, default: () => [] },
  userInitials: { type: String, default: '我' },
  currentUserName: { type: String, default: '我' },
  formatTime: { type: Function, required: true },
  draftMessage: { type: String, default: '' },
  composerPlaceholder: { type: String, default: '' },
  runTraceLoading: { type: Boolean, default: false },
  runTrace: { type: Object, default: null },
  runTraceError: { type: String, default: '' },
});

const emit = defineEmits([
  'update:activeAgentId',
  'close-notice',
  'toggle-run-trace',
  'create-demo-agent',
  'create-new-session',
  'apply-prompt',
  'update:draftMessage',
  'send-message',
  'retry-run-trace',
]);

const conversationWorkspaceRef = ref(null);

const agentIdProxy = computed({
  get: () => props.activeAgentId,
  set: (value) => emit('update:activeAgentId', value),
});

function focusComposer() {
  conversationWorkspaceRef.value?.focusComposer?.();
}

defineExpose({
  focusComposer,
});
</script>