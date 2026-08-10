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

<style scoped>
/* ===== Ant Design Vue v4 规范令牌 ===== */
.chat-tool-panel {
  --primary:#1890ff;
  --primary-hover:#40a9ff;
  --primary-bg:#e6f7ff;
  --success:#52c41a;
  --success-bg:#f6ffed;
  --warning:#faad14;
  --warning-bg:#fffbe6;
  --danger:#ff4d4f;
  --danger-bg:#fff1f0;
  --text:rgba(0,0,0,.88);
  --text-secondary:rgba(0,0,0,.65);
  --text-tertiary:rgba(0,0,0,.45);
  --border:#d9d9d9;
  --border-light:#f0f0f0;
  --bg:#f0f2f5;
  --bg-soft:#fafafa;
  --radius-sm:6px;
  --radius:8px;
  --radius-lg:12px;
  --radius-xl:16px;
}
.panel-block {
  background:#fff;
  border:1px solid var(--border-light);
  border-radius:var(--radius-lg);
  box-shadow:none;
}
.primary-action.ant-btn { height:44px;font-weight:600; }
</style>