<template>
  <div class="panel-block is-fill">
    <div class="block-row">
      <div class="block-title">会话列表</div>
      <a-button type="link" size="small" class="inline-action" @click="$emit('refresh')">
        刷新
      </a-button>
    </div>

    <div v-if="loading" class="section-loading">
      <a-spin size="small" />
      <span>正在加载会话...</span>
    </div>

    <div v-else-if="activeAgentId && sessions.length" class="session-list">
      <div
        v-for="session in sessions"
        :key="session.id"
        class="session-item-row"
        :class="{ 'is-active': session.id === activeSessionId }"
      >
        <button
          type="button"
          class="session-item"
          :class="{ 'is-active': session.id === activeSessionId }"
          @click="$emit('select', session.id)"
        >
          <span class="session-title">{{ session.title }}</span>
          <span class="session-time">{{ formatTime(session.updated_at) }}</span>
        </button>
        <a-popconfirm
          title="删除这个会话？"
          description="删除后将无法恢复该会话消息。"
          ok-text="删除"
          cancel-text="取消"
          @confirm="$emit('delete', session.id)"
        >
          <button
            type="button"
            class="session-delete-button"
            :disabled="deletingSessionId === session.id"
            :aria-label="'删除会话 ' + session.title"
            @click.stop
          >
            {{ deletingSessionId === session.id ? '...' : '删' }}
          </button>
        </a-popconfirm>
      </div>
    </div>

    <div v-else class="section-empty">
      <a-empty :image="emptyImage" description="当前智能体下还没有会话" />
    </div>
  </div>
</template>

<script setup>
defineProps({
  loading: { type: Boolean, default: false },
  activeAgentId: { type: [String, Number, null], default: null },
  sessions: { type: Array, default: () => [] },
  activeSessionId: { type: [String, Number, null], default: null },
  deletingSessionId: { type: [String, Number, null], default: null },
  emptyImage: { type: [Object, String], default: null },
  formatTime: { type: Function, required: true },
});

defineEmits(['refresh', 'select', 'delete']);
</script>

<style scoped>
/* ===== Ant Design Vue v4 规范令牌 ===== */
.panel-block {
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

  background:#fff;
  border:1px solid var(--border-light);
  border-radius:var(--radius-lg);
  box-shadow:none;
}
.block-row { display:flex;align-items:center;justify-content:space-between;gap:10px; }
.block-title { font-weight:600;color:var(--text);font-size:14px; }
.inline-action.ant-btn { padding-inline:0; }
.session-list { gap:8px; }
.session-item-row { position:relative; }
.session-item {
  border:0;width:100%;text-align:left;cursor:pointer;
  padding:10px 44px 10px 12px;border-radius:var(--radius);
  background:transparent;transition:background .2s ease;
}
.session-item:hover,
.session-item.is-active {
  background:var(--primary-bg);
}
.session-delete-button {
  position:absolute;top:50%;right:8px;transform:translateY(-50%);
  width:26px;height:26px;border:0;border-radius:var(--radius-sm);
  background:transparent;color:var(--danger);font-size:12px;font-weight:700;cursor:pointer;
  opacity:0;transition:opacity .2s ease,background .2s ease;
}
.session-delete-button:hover:not(:disabled){ background:var(--danger-bg); }
.session-delete-button:disabled{ cursor:not-allowed;color:var(--text-tertiary); }
.session-item-row:hover .session-delete-button,
.session-item-row.is-active .session-delete-button { opacity:1; }
.session-title { display:block;margin-bottom:4px;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:500; }
.session-time { color:var(--text-tertiary); }
.section-empty { padding:12px 0; }
</style>