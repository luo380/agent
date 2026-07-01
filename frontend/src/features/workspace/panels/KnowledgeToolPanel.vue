<template>
  <div class="knowledge-tool-panel">
    <div class="panel-block">
      <div class="block-row">
        <div>
          <div class="block-title">知识库文档</div>
          <div class="panel-copy">当前仅展示当前登录用户自己的文档，可直接参与 RAG 问答。</div>
        </div>
        <a-button size="small" @click="$emit('refresh-knowledge')" :loading="knowledgeDocumentsLoading">刷新</a-button>
      </div>

      <a-upload
        :show-upload-list="false"
        :before-upload="handleBeforeUpload"
        accept=".txt,.pdf,.docx,.xlsx,.xls,.ppt,.pptx"
      >
        <a-button type="primary" class="primary-action" block :loading="Boolean(uploadingDocumentNames.length)">
          上传知识库文档
        </a-button>
      </a-upload>

      <div v-if="uploadingDocumentNames.length" class="uploading-list">
        <div v-for="name in uploadingDocumentNames" :key="name" class="uploading-item">
          <a-spin size="small" />
          <span>{{ name }}</span>
        </div>
      </div>
    </div>

    <div class="panel-block knowledge-panel-fill">
      <div class="block-row">
        <div>
          <div class="block-title">文档列表</div>
          <div class="panel-copy">上传、解析、切块状态都会在这里展示。</div>
        </div>
        <a-tag color="processing">{{ knowledgeDocuments.length }} 份</a-tag>
      </div>

      <div v-if="knowledgeDocumentsLoading" class="section-loading">
        <a-spin size="small" />
        <span>正在加载知识库文档...</span>
      </div>

      <div v-else-if="knowledgeDocuments.length" class="knowledge-document-list">
        <article v-for="doc in knowledgeDocuments" :key="doc.id" class="knowledge-document-card">
          <div class="knowledge-document-head">
            <div>
              <div class="knowledge-document-title">{{ doc.name }}</div>
              <div class="knowledge-document-meta">
                {{ (doc.file_type || 'file').toUpperCase() }}
                <span> · {{ formatTime(doc.updated_at) }}</span>
                <span v-if="doc.chunk_count"> · {{ doc.chunk_count }} chunks</span>
              </div>
            </div>
            <a-tag :color="statusColorMap[doc.status] || 'default'">{{ statusLabelMap[doc.status] || doc.status }}</a-tag>
          </div>

          <div class="knowledge-document-copy">
            <template v-if="doc.status === 'ready'">文档已可用于知识库问答。</template>
            <template v-else-if="doc.error_message">{{ doc.error_message }}</template>
            <template v-else>文档处理中，稍后会自动进入可检索状态。</template>
          </div>

          <div class="knowledge-document-actions">
            <a-button
              v-if="doc.status === 'ready'"
              size="small"
              @click="$emit('add-doc-to-scope', doc.id)"
            >
              加入问答范围
            </a-button>
            <a-button
              size="small"
              danger
              :loading="deletingKnowledgeDocumentId === doc.id"
              @click="$emit('delete-knowledge-document', doc.id)"
            >
              删除
            </a-button>
          </div>
        </article>
      </div>

      <div v-else class="section-empty">
        <a-empty description="还没有知识库文档" />
      </div>
    </div>

    <div class="panel-block">
      <div class="block-title">问答入口</div>
      <div class="knowledge-mode-summary">
        <div class="mode-summary-row">
          <span>当前模式</span>
          <a-tag :color="conversationMode === 'rag' ? 'processing' : 'default'">
            {{ conversationMode === 'rag' ? '知识库问答' : '普通聊天' }}
          </a-tag>
        </div>
        <div class="mode-summary-row">
          <span>文档范围</span>
          <span class="mode-summary-value">
            {{ ragScopeType === 'selected' ? `${activeScopedDocuments.length} 份指定文档` : '全部可用文档' }}
          </span>
        </div>
      </div>
      <div class="panel-copy">
        模式切换统一放在聊天框底部；选择“知识库”后，下方会自动展开范围与参数配置。
      </div>
    </div>
  </div>
</template>

<script setup>

const props = defineProps({
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
  'refresh-knowledge',
  'upload-knowledge-document',
  'delete-knowledge-document',
  'add-doc-to-scope',
  'update:rag-scope-type',
  'update:rag-document-ids',
]);

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

function handleBeforeUpload(file) {
  emit('upload-knowledge-document', file);
  return false;
}
</script>
