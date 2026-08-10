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
                  <span class="rag-meta-pill">本条回答：{{ formatStrictMode(message.strict_mode) }}</span>
                  <span v-if="message.meta?.top_k" class="rag-meta-pill">top_k: {{ message.meta.top_k }}</span>
                  <span v-if="message.run_id" class="rag-meta-pill">run_id: {{ message.run_id }}</span>
                </div>

                <div v-if="message.citations?.length" class="rag-section-card">
                  <div class="rag-section-head">
                    <div class="rag-section-heading">
                      <div class="rag-section-title">参考资料</div>
                      <div class="rag-section-description">以下资料参与了本次回答生成，优先展示更相关的片段。</div>
                    </div>
                    <a-tag color="processing">{{ message.citations.length }} 条</a-tag>
                  </div>
                  <div class="rag-citation-list">
                    <article
                      v-for="(citation, citationIndex) in message.citations"
                      :key="getRecordKey(citation, 'citation', citationIndex)"
                      class="rag-citation-card"
                    >
                      <div class="rag-citation-title-row">
                        <div class="rag-citation-main">
                          <strong>{{ getDisplayText(citation.document_name, '未命名文档') }}</strong>
                          <div class="rag-citation-summary">
                            {{ formatCitationLocation(citation) }}
                            <span v-if="hasScore(citation.score)"> · 相关度 {{ formatScore(citation.score) }}</span>
                          </div>
                        </div>
                        <span class="rag-score" v-if="hasScore(citation.score)">Top Match</span>
                      </div>
                      <div
                        v-if="hasSourcePage(citation.source_page) || hasMeaningfulText(citation.source_section)"
                        class="rag-citation-tags"
                      >
                        <a-tag v-if="hasSourcePage(citation.source_page)" color="blue">{{ formatSourcePage(citation.source_page) }}</a-tag>
                        <a-tag v-if="hasMeaningfulText(citation.source_section)">{{ getDisplayText(citation.source_section) }}</a-tag>
                      </div>
                      <div class="rag-citation-meta">
                        <span>{{ formatChunkLabel(citation.chunk_index) }}</span>
                        <span v-if="citation.chunk_id != null"> · 片段 ID {{ citation.chunk_id }}</span>
                      </div>
                      <div class="rag-citation-copy">
                        <div>{{ getDisplayText(citation.content, '暂无引用内容') }}</div>
                      </div>
                    </article>
                  </div>
                </div>

                <a-collapse v-if="message.retrieved_chunks?.length" ghost class="rag-debug-collapse">
                  <a-collapse-panel key="retrieved-chunks">
                    <template #header>
                      <div class="rag-section-title">检索过程（调试）</div>
                    </template>
                    <template #extra>
                      <a-tag>{{ message.retrieved_chunks.length }} 条</a-tag>
                    </template>
                    <div class="rag-debug-note">这里展示的是召回并重排后的候选片段，用于排查命中效果，不等同于答案中的直接引用。</div>
                    <div class="retrieved-chunk-list">
                      <article
                        v-for="(chunk, chunkIndex) in message.retrieved_chunks"
                        :key="getRecordKey(chunk, 'chunk', chunkIndex)"
                        class="retrieved-chunk-card"
                      >
                        <div class="retrieved-chunk-head">
                          <strong>{{ getDisplayText(chunk.document_name, '未命名文档') }}</strong>
                          <span class="rag-score">final {{ formatScore(chunk.final_score) }}</span>
                        </div>
                        <div class="retrieved-chunk-meta">
                          <span>{{ formatChunkLabel(chunk.chunk_index) }}</span>
                          <span> · 页码 {{ formatSourcePage(chunk.source_page) }}</span>
                          <span> · 章节 {{ getDisplayText(chunk.source_section, '未标注章节') }}</span>
                          <span> · vector {{ formatScore(chunk.vector_score) }}</span>
                          <span> · keyword {{ formatScore(chunk.keyword_score) }}</span>
                        </div>
                        <div class="retrieved-chunk-copy">{{ getDisplayText(chunk.content, '暂无检索内容') }}</div>
                      </article>
                    </div>
                  </a-collapse-panel>
                </a-collapse>
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
                <a-segmented
                  class="composer-mode-segmented"
                  :value="conversationMode"
                  :options="modeOptions"
                  @change="handleConversationModeChange"
                />
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
                  <div class="rag-control-status">当前发送设置：{{ formatStrictMode(ragStrictMode) }}</div>
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

const modeOptions = [
  { label: '普通聊天', value: 'chat' },
  { label: '知识库', value: 'rag' },
];

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
  ragConfigCollapsed.value = nextMode !== 'rag';
  emit('update:conversation-mode', nextMode);
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

function formatStrictMode(value) {
  if (value === true || value === 1) return '严格模式';
  if (value === false || value === 0) return '宽松模式';
  return '模式未知';
}

function getDisplayText(value, fallback = '--') {
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed || fallback;
  }
  if (value == null) return fallback;
  return String(value);
}

function hasMeaningfulText(value) {
  if (typeof value === 'string') return value.trim().length > 0;
  return value != null && String(value).trim().length > 0;
}

function hasSourcePage(value) {
  return Number.isFinite(Number(value));
}

function hasScore(value) {
  return Number.isFinite(Number(value));
}

function formatSourcePage(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '未标注';
  return '第 ' + number + ' 页';
}

function formatCitationLocation(citation) {
  const parts = [];
  if (hasSourcePage(citation?.source_page)) {
    parts.push(formatSourcePage(citation.source_page));
  }
  if (hasMeaningfulText(citation?.source_section)) {
    parts.push(getDisplayText(citation.source_section));
  }
  return parts.join(' · ') || '未标注位置';
}

function formatChunkLabel(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 'Chunk 未知';
  return 'Chunk #' + number;
}

function getRecordKey(record, fallbackPrefix, index) {
  return record?.chunk_id ?? record?.id ?? fallbackPrefix + '-' + index;
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

<style scoped>
/* ===== Ant Design Vue v4 规范令牌（向子组件透传） ===== */
.conversation-stage {
  --primary:#1890ff;
  --primary-hover:#40a9ff;
  --primary-bg:#e6f7ff;
  --success:#52c41a;
  --success-bg:#f6ffed;
  --warning:#faad14;
  --warning-bg:#fffbe6;
  --danger:#ff4d4f;
  --danger-bg:#fff1f0;
  --purple:#722ed1;
  --purple-bg:#f9f0ff;
  --text:rgba(0,0,0,.88);
  --text-secondary:rgba(0,0,0,.65);
  --text-tertiary:rgba(0,0,0,.45);
  --border:#d9d9d9;
  --border-light:#f0f0f0;
  --bg:#f0f2f5;
  --bg-soft:#fafafa;
  --card:#fff;
  --radius-sm:6px;
  --radius:8px;
  --radius-lg:12px;
  --radius-xl:16px;
}

/* 欢迎 / 空状态大图标 */
.welcome-mark {
  display:flex;align-items:center;justify-content:center;
  background:var(--primary);
  color:#fff;
  border-radius:var(--radius-lg);
  font-weight:600;
  box-shadow:0 6px 16px rgba(24,144,255,.25);
}
.welcome-title.ant-typography { color:var(--text); }

/* 快捷提示词 → antd 标签按钮 */
.quick-prompt-list { justify-content:center; }
.quick-prompt {
  border:1px solid var(--border);
  border-radius:var(--radius);
  background:#fff;
  color:var(--text-secondary);
  font-size:13px;
  font-weight:500;
  box-shadow:none;
}
.quick-prompt:hover {
  background:var(--primary-bg);
  color:var(--primary);
  border-color:var(--primary);
  transform:none;
}

/* 消息流 */
.message-list { padding:6px 0 24px; }
.message-meta { gap:10px; }
.message-role { color:var(--text);font-weight:600;font-size:13px; }
.message-time { color:var(--text-tertiary); }
.message-avatar.ant-avatar { background:var(--primary); }

.message-bubble {
  max-width:min(780px,100%);
  padding:14px 18px;
  border-radius:var(--radius-lg);
  background:#fff;
  border:1px solid var(--border-light);
  box-shadow:none;
  color:var(--text);
  font-size:14px;
  line-height:1.75;
  white-space:pre-wrap;
}
.message-row.is-user .message-bubble {
  background:var(--primary);
  border-color:var(--primary);
  color:#fff;
}
.message-row.is-rag .message-bubble {
  background:var(--primary-bg);
  border-color:#91d5ff;
  color:var(--text);
}

/* 模式 / 标签 pill */
.message-mode-pill,
.rag-meta-pill,
.scope-chip {
  display:inline-flex;align-items:center;
  border-radius:var(--radius-sm);
  padding:2px 8px;
  background:var(--primary-bg);
  color:var(--primary);
  font-size:12px;font-weight:600;
  border:1px solid #91d5ff;
}
.message-mode-pill.is-chat {
  background:var(--bg-soft);color:var(--text-secondary);border-color:var(--border-light);
}

/* RAG 引用卡片 */
.rag-response-meta { gap:12px; }
.rag-section-card,
.rag-citation-card,
.retrieved-chunk-card {
  background:#fff;
  border:1px solid var(--border-light);
  border-radius:var(--radius);
  padding:14px 16px;
}
.rag-section-head { display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:10px; }
.rag-section-heading { display:grid;gap:2px; }
.rag-section-title { font-weight:600;font-size:14px;color:var(--text); }
.rag-section-description { color:var(--text-tertiary);font-size:12px; }
.rag-citation-title-row { display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:8px; }
.rag-citation-main strong { color:var(--text);font-size:14px; }
.rag-citation-summary { color:var(--text-tertiary);font-size:12px;margin-top:2px; }
.rag-score {
  display:inline-flex;align-items:center;
  padding:2px 8px;border-radius:var(--radius-sm);
  background:var(--primary-bg);color:var(--primary);
  font-size:11px;font-weight:600;white-space:nowrap;
}
.rag-citation-tags { display:flex;flex-wrap:wrap;gap:6px;margin-bottom:6px; }
.rag-citation-meta { color:var(--text-tertiary);font-size:12px;margin-bottom:6px; }
.rag-citation-copy { color:var(--text-secondary);font-size:13px;line-height:1.7;background:var(--bg-soft);border-radius:var(--radius-sm);padding:10px 12px; }
.retrieved-chunk-head { display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:6px; }
.retrieved-chunk-head strong { color:var(--text); }
.retrieved-chunk-meta { color:var(--text-tertiary);font-size:12px;margin-bottom:6px; }
.retrieved-chunk-copy { color:var(--text-secondary);font-size:13px;line-height:1.7; }
.rag-debug-collapse { background:#fff;border:1px solid var(--border-light);border-radius:var(--radius);margin-top:10px; }

/* 输入区卡片 */
.composer-footer { padding-top:14px; }
.composer-card {
  width:100%;margin:0;
  background:#fff;
  border:1px solid var(--border-light);
  border-radius:var(--radius-lg);
  box-shadow:0 1px 4px rgba(0,0,0,.04);
}
.composer-card .ant-card-body { padding:14px 18px;background:transparent; }
.composer-card .ant-input {
  border:0;box-shadow:none;resize:none;
  background:transparent;color:var(--text);
  font-size:15px;line-height:1.75;
}
.composer-card textarea.ant-input { min-height:88px !important;max-height:88px !important;overflow-y:auto; }

/* 模式切换段控 → antd segmented */
.composer-mode-tags { align-items:center; }
.composer-mode-segmented { background:var(--bg-soft); }

/* 发送工具栏 */
.composer-toolbar {
  display:flex;align-items:center;justify-content:space-between;gap:16px;
  margin-top:12px;padding-top:12px;
  border-top:1px solid var(--border-light);
}

/* RAG 控制面板 */
.rag-controls-panel { gap:12px;margin-bottom:12px; }
.rag-control-grid { gap:12px; }
.rag-control-card {
  background:#fff;border:1px solid var(--border-light);
  border-radius:var(--radius-lg);padding:14px 16px;
  display:grid;gap:10px;align-content:start;
}
.rag-control-title { font-weight:600;font-size:13px;color:var(--text); }
.rag-control-status { color:var(--text-secondary);font-size:12px; }
.rag-control-copy { color:var(--text-tertiary);font-size:12px;line-height:1.6; }
.rag-doc-select, .rag-topk-input { width:100%; }

/* 执行轨迹面板 */
.run-trace-panel {
  padding:18px;border-radius:var(--radius-lg);
  background:#fff;border:1px solid var(--border-light);
  box-shadow:0 1px 4px rgba(0,0,0,.04);
}

/* 空状态卡片统一为白底 */
.empty-card.ant-card {
  background:#fff;
  border-radius:var(--radius-lg);
}
</style>
