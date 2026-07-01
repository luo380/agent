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
                与 {{ activeAgentName }} 开始一段新会话
              </a-typography-title>
              <a-typography-paragraph class="empty-copy">
                通过同一个输入框切换普通聊天和知识库问答。你可以先新建会话，再决定是否启用知识库模式。
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
              :class="['is-' + message.role, { 'is-rag': message.mode === 'rag' && message.role === 'assistant' }]"
            >
              <div class="message-meta">
                <a-avatar size="small" class="message-avatar">
                  {{ message.role === 'assistant' ? activeAgentShort : userInitials }}
                </a-avatar>
                <div>
                  <div class="message-role">{{ message.role === 'assistant' ? activeAgentName : currentUserName }}</div>
                  <div class="message-time">
                    {{ formatTime(message.created_at) }}
                    <span v-if="message.mode === 'rag'" class="message-mode-pill">知识库问答</span>
                    <span v-else-if="message.role === 'assistant'" class="message-mode-pill is-chat">普通聊天</span>
                  </div>
                </div>
              </div>

              <div class="message-bubble">{{ message.content }}</div>

              <section v-if="message.role === 'assistant' && message.mode === 'rag'" class="rag-response-meta">
                <div class="rag-answer-meta">
                  <span class="rag-meta-pill">strict_mode: {{ message.strict_mode ? 'on' : 'off' }}</span>
                  <span v-if="message.meta?.top_k" class="rag-meta-pill">top_k: {{ message.meta.top_k }}</span>
                  <span v-if="message.run_id" class="rag-meta-pill">run_id: {{ message.run_id }}</span>
                </div>

                <div v-if="message.citations?.length" class="rag-section-card">
                  <div class="rag-section-head">
                    <div class="rag-section-title">引用来源</div>
                    <a-tag color="processing">{{ message.citations.length }} 条</a-tag>
                  </div>
                  <div class="rag-citation-list">
                    <article v-for="citation in message.citations" :key="citation.chunk_id" class="rag-citation-card">
                      <div class="rag-citation-title-row">
                        <strong>{{ citation.document_name }}</strong>
                        <span class="rag-score">score {{ formatScore(citation.score) }}</span>
                      </div>
                      <div class="rag-citation-meta">
                        Chunk #{{ citation.chunk_index }}
                        <span v-if="citation.source_page"> · 第 {{ citation.source_page }} 页</span>
                        <span v-if="citation.source_section"> · {{ citation.source_section }}</span>
                      </div>
                      <div class="rag-citation-copy">{{ citation.content }}</div>
                    </article>
                  </div>
                </div>

                <div v-if="message.retrieved_chunks?.length" class="rag-section-card">
                  <div class="rag-section-head">
                    <div class="rag-section-title">检索结果</div>
                    <a-tag>{{ message.retrieved_chunks.length }} 条</a-tag>
                  </div>
                  <div class="retrieved-chunk-list">
                    <article v-for="chunk in message.retrieved_chunks" :key="chunk.chunk_id" class="retrieved-chunk-card">
                      <div class="retrieved-chunk-head">
                        <strong>{{ chunk.document_name }}</strong>
                        <span class="rag-score">final {{ formatScore(chunk.final_score) }}</span>
                      </div>
                      <div class="retrieved-chunk-meta">
                        Chunk #{{ chunk.chunk_index }}
                        <span v-if="chunk.source_page"> · 第 {{ chunk.source_page }} 页</span>
                        <span v-if="chunk.source_section"> · {{ chunk.source_section }}</span>
                        <span> · vector {{ formatScore(chunk.vector_score) }}</span>
                        <span> · keyword {{ formatScore(chunk.keyword_score) }}</span>
                      </div>
                      <div class="retrieved-chunk-copy">{{ chunk.content }}</div>
                    </article>
                  </div>
                </div>
              </section>
            </article>
          </div>

          <div v-else class="empty-panel">
            <a-card :bordered="false" class="empty-card session-welcome-card">
              <div class="welcome-mark">{{ activeAgentShort }}</div>
              <a-typography-title :level="2" class="welcome-title">
                当前会话还没有消息
              </a-typography-title>
              <a-typography-paragraph class="empty-copy">
                你可以直接输入问题，或者点一个快捷提示，把当前智能体带进实际工作语境里。
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
              <div class="composer-tags composer-mode-tags">
                <button
                  type="button"
                  class="composer-tag mode-chip"
                  :class="{ 'is-active': conversationMode === 'chat' }"
                  @click="handleConversationModeChange('chat')"
                >
                  普通聊天
                </button>
                <button
                  type="button"
                  class="composer-tag mode-chip"
                  :class="{ 'is-active': conversationMode === 'rag' }"
                  @click="handleConversationModeChange('rag')"
                >
                  知识库
                </button>
              </div>

              <a-button
                type="primary"
                size="large"
                :loading="sendingMessage"
                :disabled="!agents.length || (conversationMode === 'rag' && !readyKnowledgeCount)"
                @click="$emit('send-message')"
              >
                发送消息
              </a-button>
            </div>

            <div v-if="conversationMode === 'rag' && !ragConfigCollapsed" class="rag-controls-panel">
              <div class="rag-control-grid">
                <div class="rag-control-card">
                  <div class="rag-control-title">文档范围</div>
                  <a-radio-group
                    :value="ragScopeType"
                    button-style="solid"
                    size="small"
                    @update:value="$emit('update:rag-scope-type', $event)"
                  >
                    <a-radio-button value="all">全部文档</a-radio-button>
                    <a-radio-button value="selected" :disabled="!knowledgeDocumentOptions.length">指定文档</a-radio-button>
                  </a-radio-group>
                  <a-select
                    v-if="ragScopeType === 'selected'"
                    class="rag-doc-select"
                    mode="multiple"
                    :value="ragDocumentIds"
                    :options="knowledgeDocumentOptions"
                    :disabled="!knowledgeDocumentOptions.length"
                    placeholder="选择要参与问答的文档"
                    @update:value="$emit('update:rag-document-ids', $event)"
                  />
                  <div v-if="activeScopedDocuments.length" class="scope-chip-list">
                    <span v-for="item in activeScopedDocuments" :key="item.id" class="scope-chip">{{ item.name }}</span>
                  </div>
                </div>

                <div class="rag-control-card small-card">
                  <div class="rag-control-title">strict_mode</div>
                  <a-switch
                    :checked="ragStrictMode"
                    checked-children="严格"
                    un-checked-children="宽松"
                    @update:checked="$emit('update:rag-strict-mode', $event)"
                  />
                  <div class="rag-control-copy">
                    开启时只按知识库回答；关闭后会优先参考知识库，查不到时也可继续推断。
                  </div>
                </div>

                <div class="rag-control-card small-card">
                  <div class="rag-control-title">top_k</div>
                  <a-input-number
                    :value="ragTopK"
                    :min="1"
                    :max="20"
                    :step="1"
                    class="rag-topk-input"
                    @update:value="$emit('update:rag-top-k', Number($event) || 5)"
                  />
                  <div class="rag-control-copy">
                    控制最终返回给回答链路的知识块数量。
                  </div>
                </div>
              </div>

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
import { computed, nextTick, ref, watch } from 'vue';
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
  conversationMode: { type: String, default: 'chat' },
  ragStrictMode: { type: Boolean, default: true },
  ragTopK: { type: Number, default: 5 },
  ragScopeType: { type: String, default: 'all' },
  ragDocumentIds: { type: Array, default: () => [] },
  knowledgeDocumentOptions: { type: Array, default: () => [] },
  activeScopedDocuments: { type: Array, default: () => [] },
  readyKnowledgeCount: { type: Number, default: 0 },
});

const emit = defineEmits([
  'create-demo-agent',
  'create-new-session',
  'apply-prompt',
  'update:draftMessage',
  'update:conversation-mode',
  'update:rag-strict-mode',
  'update:rag-top-k',
  'update:rag-scope-type',
  'update:rag-document-ids',
  'send-message',
  'retry-run-trace',
]);

const composerRef = ref(null);
const ragConfigCollapsed = ref(false);

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

function handleConversationModeChange(nextMode) {
  if (nextMode === 'chat') {
    ragConfigCollapsed.value = true;
    emit('update:conversation-mode', 'chat');
    return;
  }

  if (props.conversationMode === 'rag') {
    ragConfigCollapsed.value = !ragConfigCollapsed.value;
    return;
  }

  ragConfigCollapsed.value = false;
  emit('update:conversation-mode', 'rag');
}

watch(() => props.conversationMode, (mode) => {
  if (mode !== 'rag') {
    ragConfigCollapsed.value = true;
  }
});

function formatScore(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '--';
  return number.toFixed(3);
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