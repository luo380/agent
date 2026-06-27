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