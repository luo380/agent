<template>
  <div class="knowledge-workspace-view">
    <header class="knowledge-workspace-head">
      <div>
        <a-typography-title :level="3" class="workspace-title">
          知识库
        </a-typography-title>
        <a-typography-paragraph class="workspace-subtitle">
          左列集中管理文件，右列查看文档详情与问答范围，让上传、筛选和 RAG 使用连在一起。
        </a-typography-paragraph>
      </div>

      <div class="knowledge-workspace-summary">
        <a-tag color="processing">{{ knowledgeDocuments.length }} 份文档</a-tag>
        <a-tag color="success">{{ readyDocumentCount }} 份可检索</a-tag>
        <a-tag :color="conversationMode === 'rag' ? 'processing' : 'default'">
          {{ conversationMode === 'rag' ? '知识库问答' : '普通聊天' }}
        </a-tag>
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

    <div class="knowledge-workspace-grid">
      <aside class="knowledge-library-panel">
        <div class="knowledge-library-head">
          <div>
            <div class="block-title">文件列表</div>
            <div class="panel-copy">按状态查看当前账号下的知识库文档。</div>
          </div>
          <a-button size="small" @click="$emit('refresh-knowledge')" :loading="knowledgeDocumentsLoading">刷新</a-button>
        </div>

        <a-upload
          :show-upload-list="false"
          :before-upload="handleBeforeUpload"
          accept=".txt,.pdf,.docx,.xlsx,.xls,.ppt,.pptx"
        >
          <a-button type="primary" block class="primary-action" :loading="Boolean(uploadingDocumentNames.length)">
            上传知识库文档
          </a-button>
        </a-upload>

        <div v-if="uploadingDocumentNames.length" class="uploading-list">
          <div v-for="name in uploadingDocumentNames" :key="name" class="uploading-item">
            <a-spin size="small" />
            <span>{{ name }}</span>
          </div>
        </div>

        <div class="knowledge-library-scroll">
          <div v-if="knowledgeDocumentsLoading" class="section-loading">
            <a-spin size="small" />
            <span>正在加载知识库文档...</span>
          </div>

          <div v-else-if="knowledgeDocuments.length" class="knowledge-library-list">
            <button
              v-for="doc in knowledgeDocuments"
              :key="doc.id"
              type="button"
              class="knowledge-library-item"
              :class="{ 'is-active': selectedDocument?.id === doc.id }"
              @click="selectDocument(doc.id)"
            >
              <div class="knowledge-library-item-head">
                <strong>{{ doc.name }}</strong>
                <a-tag :color="statusColorMap[doc.status] || 'default'">{{ statusLabelMap[doc.status] || doc.status }}</a-tag>
              </div>
              <div class="knowledge-library-item-meta">
                <span>{{ (doc.file_type || 'file').toUpperCase() }}</span>
                <span>· {{ formatTime(doc.updated_at) }}</span>
                <span v-if="doc.chunk_count">· {{ doc.chunk_count }} chunks</span>
              </div>
              <div class="knowledge-library-item-flags">
                <span v-if="isScopedDocument(doc.id)" class="scope-chip">已加入问答范围</span>
              </div>
            </button>
          </div>

          <div v-else class="section-empty">
            <a-empty description="还没有知识库文档" />
          </div>
        </div>
      </aside>

      <section class="knowledge-detail-stage">
        <template v-if="selectedDocument">
          <div class="knowledge-detail-stack">
            <div class="knowledge-detail-card">
              <div class="knowledge-detail-head">
                <div>
                  <div class="panel-overline">Document</div>
                  <a-typography-title :level="4" class="knowledge-detail-title">
                    {{ selectedDocument.name }}
                  </a-typography-title>
                </div>
                <a-tag :color="statusColorMap[selectedDocument.status] || 'default'">
                  {{ statusLabelMap[selectedDocument.status] || selectedDocument.status }}
                </a-tag>
              </div>

              <div class="knowledge-detail-metrics">
                <div class="knowledge-metric-card">
                  <span class="knowledge-metric-label">文件类型</span>
                  <strong>{{ (selectedDocument.file_type || 'file').toUpperCase() }}</strong>
                </div>
                <div class="knowledge-metric-card">
                  <span class="knowledge-metric-label">更新时间</span>
                  <strong>{{ formatTime(selectedDocument.updated_at) }}</strong>
                </div>
                <div class="knowledge-metric-card">
                  <span class="knowledge-metric-label">知识块</span>
                  <strong>{{ selectedDocument.chunk_count || 0 }}</strong>
                </div>
              </div>

              <div class="knowledge-detail-copy">
                <template v-if="selectedDocument.status === 'ready'">
                  文档已经完成解析，可以直接纳入问答范围。你可以只用这份文档，也可以把它加入当前的指定范围。
                </template>
                <template v-else-if="selectedDocument.error_message">
                  {{ selectedDocument.error_message }}
                </template>
                <template v-else>
                  文档还在处理中，完成后会自动进入可检索状态。
                </template>
              </div>

              <div class="knowledge-detail-actions">
                <a-button
                  v-if="selectedDocument.status === 'ready' && !isScopedDocument(selectedDocument.id)"
                  @click="$emit('add-doc-to-scope', selectedDocument.id)"
                >
                  加入问答范围
                </a-button>
                <a-button
                  v-else-if="selectedDocument.status === 'ready'"
                  @click="removeFromScope(selectedDocument.id)"
                >
                  移出问答范围
                </a-button>
                <a-button
                  type="primary"
                  :disabled="selectedDocument.status !== 'ready'"
                  @click="focusDocumentForAsk(selectedDocument.id)"
                >
                  仅用这份文档问答
                </a-button>
                <a-button
                  danger
                  :loading="deletingKnowledgeDocumentId === selectedDocument.id"
                  @click="$emit('delete-knowledge-document', selectedDocument.id)"
                >
                  删除文档
                </a-button>
              </div>
            </div>

            <div class="knowledge-detail-card">
              <div class="knowledge-detail-head is-secondary">
                <div>
                  <div class="panel-overline">RAG Scope</div>
                  <a-typography-title :level="4" class="knowledge-detail-title">
                    当前问答范围
                  </a-typography-title>
                </div>
                <a-tag :color="ragScopeType === 'selected' ? 'processing' : 'default'">
                  {{ ragScopeType === 'selected' ? `指定 ${activeScopedDocuments.length} 份文档` : '全部可用文档' }}
                </a-tag>
              </div>

              <div class="knowledge-scope-copy">
                这里决定聊天区在知识库模式下检索哪些文档。设置完成后，切回“会话工作台”直接提问即可。
              </div>

              <div class="knowledge-scope-actions">
                <a-button type="primary" @click="useAllDocumentsForAsk">使用全部文档问答</a-button>
                <a-button @click="focusDocumentForAsk(selectedDocument.id)" :disabled="selectedDocument.status !== 'ready'">
                  仅用当前文档问答
                </a-button>
                <a-button v-if="ragScopeType === 'selected'" @click="clearScopedDocuments">清空指定范围</a-button>
              </div>

              <div v-if="activeScopedDocuments.length" class="scope-chip-list">
                <span v-for="doc in activeScopedDocuments" :key="doc.id" class="scope-chip">{{ doc.name }}</span>
              </div>
              <div v-else class="knowledge-scope-empty">
                当前没有单独指定文档，问答时会默认使用全部可检索文档。
              </div>
            </div>
          </div>
        </template>

        <div v-else class="knowledge-detail-empty">
          <a-empty description="先上传一份文档开始构建知识库" />
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue';

const props = defineProps({
  workspaceNotice: { type: String, default: '' },
  workspaceNoticeType: { type: String, default: 'info' },
  knowledgeDocuments: { type: Array, default: () => [] },
  knowledgeDocumentsLoading: { type: Boolean, default: false },
  uploadingDocumentNames: { type: Array, default: () => [] },
  deletingKnowledgeDocumentId: { type: [String, Number, null], default: null },
  conversationMode: { type: String, default: 'chat' },
  ragScopeType: { type: String, default: 'all' },
  ragDocumentIds: { type: Array, default: () => [] },
  activeScopedDocuments: { type: Array, default: () => [] },
  formatTime: { type: Function, required: true },
});

const emit = defineEmits([
  'close-notice',
  'refresh-knowledge',
  'upload-knowledge-document',
  'delete-knowledge-document',
  'add-doc-to-scope',
  'update:conversation-mode',
  'update:rag-scope-type',
  'update:rag-document-ids',
]);

const selectedDocumentId = ref(null);

const statusLabelMap = {
  uploaded: '已上传',
  parsing: '解析中',
  chunking: '切块中',
  ready: '可检索',
  failed: '处理失败',
};

const statusColorMap = {
  uploaded: 'default',
  parsing: 'processing',
  chunking: 'gold',
  ready: 'success',
  failed: 'error',
};

const readyDocumentCount = computed(() => (
  props.knowledgeDocuments.filter((item) => item.status === 'ready').length
));

const selectedDocument = computed(() => (
  props.knowledgeDocuments.find((item) => item.id === selectedDocumentId.value) || null
));

watch(
  () => props.knowledgeDocuments,
  (documents) => {
    if (!documents.length) {
      selectedDocumentId.value = null;
      return;
    }

    const hasCurrent = documents.some((item) => item.id === selectedDocumentId.value);
    if (!hasCurrent) {
      selectedDocumentId.value = documents[0].id;
    }
  },
  { immediate: true },
);

function handleBeforeUpload(file) {
  emit('upload-knowledge-document', file);
  return false;
}

function selectDocument(documentId) {
  selectedDocumentId.value = documentId;
}

function isScopedDocument(documentId) {
  const numericId = Number(documentId);
  return props.activeScopedDocuments.some((item) => Number(item.id) === numericId);
}

function focusDocumentForAsk(documentId) {
  emit('update:rag-document-ids', [Number(documentId)]);
  emit('update:rag-scope-type', 'selected');
  emit('update:conversation-mode', 'rag');
}

function useAllDocumentsForAsk() {
  emit('update:rag-document-ids', []);
  emit('update:rag-scope-type', 'all');
  emit('update:conversation-mode', 'rag');
}

function clearScopedDocuments() {
  emit('update:rag-document-ids', []);
  emit('update:rag-scope-type', 'all');
}

function removeFromScope(documentId) {
  const numericId = Number(documentId);
  const nextIds = props.ragDocumentIds
    .map((item) => Number(item))
    .filter((item) => item !== numericId);

  emit('update:rag-document-ids', nextIds);
  emit('update:rag-scope-type', nextIds.length ? 'selected' : 'all');
}
</script>