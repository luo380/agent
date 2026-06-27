<template>
  <section class="conversation-stage">
    <div class="conversation-layout" :class="{ 'is-trace-visible': traceVisible }">
      <div class="conversation-main">
        <div class="conversation-scroll">
          <div v-if="workspaceLoading" class="screen-state compact-state">
            <a-spin />
            <span>正在加载工作区...</span>
          </div>

          <div v-else-if="!agents.length" class="empty-panel">
            <a-card :bordered="false" class="empty-card">
              <a-empty description="当前账号下还没有智能体" />
              <a-typography-paragraph class="empty-copy">
                先创建一个示例智能体，我们就能继续把注册、登录、会话这条链路完整联调起来。
              </a-typography-paragraph>
              <a-button type="primary" size="large" :loading="creatingAgent" @click="$emit('create-demo-agent')">
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
                  @click="$emit('apply-prompt', prompt)"
                >
                  {{ prompt }}
                </button>
              </div>
              <a-button type="primary" size="large" @click="$emit('create-new-session')">新建会话</a-button>
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
                  <div class="message-role">{{ message.role === 'assistant' ? activeAgentName : currentUserName }}</div>
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
                  @click="$emit('apply-prompt', prompt)"
                >
                  {{ prompt }}
                </button>
              </div>
            </a-card>
          </div>
        </div>

        <footer class="composer-footer">
          <a-card :bordered="false" class="composer-card">
            <a-textarea
              ref="composerRef"
              v-model:value="composerModel"
              rows="3"
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
                @click="$emit('send-message')"
              >
                发送消息
              </a-button>
            </div>
          </a-card>
        </footer>
      </div>

      <RunTracePanel
        v-if="traceVisible"
        :loading="runTraceLoading"
        :trace="runTrace"
        :error="runTraceError"
        @refresh="$emit('retry-run-trace')"
      />
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue';
import RunTracePanel from '../../workspace/trace/RunTracePanel.vue';

const props = defineProps({
  workspaceLoading: { type: Boolean, default: false },
  agents: { type: Array, default: () => [] },
  creatingAgent: { type: Boolean, default: false },
  activeSessionId: { type: [String, Number, null], default: null },
  activeAgentShort: { type: String, default: 'AI' },
  activeAgentName: { type: String, default: '智能体' },
  quickPrompts: { type: Array, default: () => [] },
  messagesLoading: { type: Boolean, default: false },
  messages: { type: Array, default: () => [] },
  userInitials: { type: String, default: '我' },
  currentUserName: { type: String, default: '我' },
  formatTime: { type: Function, required: true },
  draftMessage: { type: String, default: '' },
  sendingMessage: { type: Boolean, default: false },
  composerPlaceholder: { type: String, default: '' },
  traceVisible: { type: Boolean, default: false },
  runTraceLoading: { type: Boolean, default: false },
  runTrace: { type: Object, default: null },
  runTraceError: { type: String, default: '' },
});

const emit = defineEmits([
  'create-demo-agent',
  'create-new-session',
  'apply-prompt',
  'update:draftMessage',
  'send-message',
  'retry-run-trace',
]);

const composerRef = ref(null);

const composerModel = computed({
  get: () => props.draftMessage,
  set: (value) => emit('update:draftMessage', value),
});

function handleComposerKeydown(event) {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
    event.preventDefault();
    emit('send-message');
  }
}

function focusComposer() {
  nextTick(() => {
    const instance = composerRef.value;
    const textarea = instance?.resizableTextArea?.textArea || instance?.$el?.querySelector?.('textarea');
    textarea?.focus?.();
  });
}

defineExpose({
  focusComposer,
});
</script>
