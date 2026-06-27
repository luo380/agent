<template>
  <div class="chat-tool-panel">
    <div class="panel-block">
      <a-button
        type="primary"
        block
        size="large"
        class="primary-action"
        :loading="creatingSession"
        :disabled="!activeAgentId"
        @click="$emit('create-session')"
      >
        新建会话
      </a-button>
    </div>

    <SessionListPanel
      :loading="sessionsLoading"
      :active-agent-id="activeAgentId"
      :sessions="sessions"
      :active-session-id="activeSessionId"
      :deleting-session-id="deletingSessionId"
      :empty-image="emptyImage"
      :format-time="formatTime"
      @refresh="$emit('refresh-sessions')"
      @select="$emit('select-session', $event)"
      @delete="$emit('delete-session', $event)"
    />
  </div>
</template>

<script setup>
import SessionListPanel from './SessionListPanel.vue';

defineProps({
  creatingSession: { type: Boolean, default: false },
  activeAgentId: { type: [String, Number, null], default: null },
  sessionsLoading: { type: Boolean, default: false },
  sessions: { type: Array, default: () => [] },
  activeSessionId: { type: [String, Number, null], default: null },
  deletingSessionId: { type: [String, Number, null], default: null },
  emptyImage: { type: [Object, String], default: null },
  formatTime: { type: Function, required: true },
});

defineEmits(['create-session', 'refresh-sessions', 'select-session', 'delete-session']);
</script>