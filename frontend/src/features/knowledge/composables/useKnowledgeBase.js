import { computed, ref } from 'vue';
import { createDocument, deleteDocument } from '../api/mockKnowledgeApi';

export function useKnowledgeBase(options) {
  const {
    apiPrefix,
    currentToken,
    parseApiResponse,
    apiJson,
    setWorkspaceNotice,
  } = options;

  const conversationMode = ref('chat');
  const ragScopeType = ref('all');
  const ragDocumentIds = ref([]);
  const ragStrictMode = ref(true);
  const ragTopK = ref(5);

  const knowledgeDocuments = ref([]);
  const knowledgeDocumentsLoading = ref(false);
  const uploadingDocumentNames = ref([]);
  const deletingKnowledgeDocumentId = ref(null);

  const readyKnowledgeDocuments = computed(() => (
    knowledgeDocuments.value.filter((item) => item.status === 'ready')
  ));

  const knowledgeDocumentOptions = computed(() => (
    readyKnowledgeDocuments.value.map((item) => ({
      label: item.name || item.title,
      value: item.id,
    }))
  ));

  const activeScopedDocuments = computed(() => {
    const selectedIds = new Set(ragDocumentIds.value);
    return readyKnowledgeDocuments.value.filter((item) => selectedIds.has(item.id));
  });

  const effectiveRagDocumentIds = computed(() => (
    ragScopeType.value === 'selected' ? activeScopedDocuments.value.map((item) => item.id) : []
  ));

  function sanitizeScopedDocuments() {
    const readyIds = new Set(readyKnowledgeDocuments.value.map((item) => item.id));
    ragDocumentIds.value = ragDocumentIds.value.filter((item) => readyIds.has(item));
    if (ragScopeType.value === 'selected' && !ragDocumentIds.value.length && readyIds.size) {
      ragScopeType.value = 'all';
    }
  }

  function resetKnowledgeState() {
    conversationMode.value = 'chat';
    ragScopeType.value = 'all';
    ragDocumentIds.value = [];
    ragStrictMode.value = true;
    ragTopK.value = 5;
    knowledgeDocuments.value = [];
    knowledgeDocumentsLoading.value = false;
    uploadingDocumentNames.value = [];
    deletingKnowledgeDocumentId.value = null;
  }

  function setConversationMode(mode) {
    conversationMode.value = mode === 'rag' ? 'rag' : 'chat';
  }

  function setRagScopeType(scopeType) {
    ragScopeType.value = scopeType === 'selected' ? 'selected' : 'all';
  }

  function setRagDocumentIds(documentIds) {
    ragDocumentIds.value = Array.isArray(documentIds) ? documentIds.map(Number) : [];
    sanitizeScopedDocuments();
  }

  function toggleScopedDocument(documentId) {
    const numericId = Number(documentId);
    if (!Number.isFinite(numericId)) return;
    const selected = new Set(ragDocumentIds.value);
    if (selected.has(numericId)) {
      selected.delete(numericId);
    } else {
      selected.add(numericId);
    }
    ragDocumentIds.value = Array.from(selected);
    ragScopeType.value = ragDocumentIds.value.length ? 'selected' : 'all';
    conversationMode.value = 'rag';
    sanitizeScopedDocuments();
  }

  function addDocumentToScope(documentId) {
    const numericId = Number(documentId);
    if (!Number.isFinite(numericId)) return;
    const selected = new Set(ragDocumentIds.value);
    selected.add(numericId);
    ragDocumentIds.value = Array.from(selected);
    ragScopeType.value = 'selected';
    conversationMode.value = 'rag';
    sanitizeScopedDocuments();
  }

  // ============ 后端响应 -> 前端文档对象 适配器 ============
  // 后端 KnowledgeDocumentResponse 字段：id / name / file_type / status /
  // content_text / chunk_count / created_at / updated_at 等
  // 前端组件需要：title / category / typeIcon / statusText / content 等
  const FILE_TYPE_META = {
    pdf: { typeIcon: '📕', iconBg: '#FFE6E3', iconColor: '#F5483B', category: 'tech' },
    docx: { typeIcon: '📝', iconBg: '#DBFAE0', iconColor: '#00B85C', category: 'product' },
    doc: { typeIcon: '📝', iconBg: '#DBFAE0', iconColor: '#00B85C', category: 'product' },
    xlsx: { typeIcon: '📊', iconBg: '#FFF4D6', iconColor: '#E6A23C', category: 'ops' },
    xls: { typeIcon: '📊', iconBg: '#FFF4D6', iconColor: '#E6A23C', category: 'ops' },
    pptx: { typeIcon: '📑', iconBg: '#EFE6FF', iconColor: '#7C5CFC', category: 'product' },
    ppt: { typeIcon: '📑', iconBg: '#EFE6FF', iconColor: '#7C5CFC', category: 'product' },
    md: { typeIcon: '📄', iconBg: '#E8F1FF', iconColor: '#2B6FFF', category: 'product' },
    txt: { typeIcon: '📄', iconBg: '#E8F1FF', iconColor: '#2B6FFF', category: 'product' },
  };
  function statusMeta(status) {
    if (status === 'ready') return { statusText: '可检索', statusColor: 'success' };
    if (status === 'failed') return { statusText: '解析失败', statusColor: 'error' };
    return { statusText: '处理中', statusColor: 'warning' };
  }
  function escapeHtml(str) {
    return String(str || '').replace(/[&<>"']/g, (c) => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
  }
  function adaptDocument(raw) {
    const meta = FILE_TYPE_META[raw?.file_type]
      || { typeIcon: '📄', iconBg: '#E8F1FF', iconColor: '#2B6FFF', category: 'product' };
    const sm = statusMeta(raw?.status);
    const text = raw?.content_text || '';
    return {
      id: raw?.id,
      title: raw?.name || '未命名文档',
      category: meta.category,
      author: '我',
      updatedAt: String(raw?.updated_at || '').slice(0, 10),
      views: 0,
      status: raw?.status,
      statusText: sm.statusText,
      statusColor: sm.statusColor,
      typeIcon: meta.typeIcon,
      iconBg: meta.iconBg,
      iconColor: meta.iconColor,
      excerpt: text.slice(0, 80),
      wordCount: raw?.chunk_count ? String(raw.chunk_count) : String(text.length),
      isFavorite: false,
      aiSummary: '',
      toc: [],
      relatedDocs: [],
      content: text
        ? '<div class="raw-doc-text">' + escapeHtml(text) + '</div>'
        : '<p class="empty-doc">该文档暂无正文内容</p>',
      comments: [],
      fileType: raw?.file_type,
      errorMsg: raw?.error_message || '',
    };
  }

  // ============ 接口调用（真实优先，失败回退 mock） ============
  async function loadKnowledgeDocuments() {
    knowledgeDocumentsLoading.value = true;
    try {
      // 真实接口：GET /api/knowledge/list
      const result = await apiJson('/knowledge/list');
      knowledgeDocuments.value = (Array.isArray(result?.data) ? result.data : []).map(adaptDocument);
    } catch (err) {
      knowledgeDocuments.value = [];
      setWorkspaceNotice(err?.message || '加载知识库失败', 'warning');
    } finally {
      knowledgeDocumentsLoading.value = false;
      sanitizeScopedDocuments();
    }
  }

  // 后端暂无“新建空白文档”接口，使用 mock 层
  async function createKnowledgeDocument(payload) {
    const result = await createDocument(payload);
    const doc = result?.data;
    if (doc) {
      knowledgeDocuments.value = [doc, ...knowledgeDocuments.value];
      sanitizeScopedDocuments();
    }
    return doc;
  }

  async function uploadKnowledgeDocument(file) {
    const documentName = String(file?.name || '').trim() || '未命名文档';
    uploadingDocumentNames.value = [...uploadingDocumentNames.value, documentName];
    try {
      // 真实接口：POST /api/knowledge/upload (multipart/form-data)
      const formData = new FormData();
      formData.append('file', file);
      const response = await fetch(apiPrefix + '/knowledge/upload', {
        method: 'POST',
        headers: currentToken.value ? { Authorization: 'Bearer ' + currentToken.value } : {},
        body: formData,
      });
      const data = await parseApiResponse(response);
      const doc = adaptDocument(data?.data || {});
      knowledgeDocuments.value = [doc, ...knowledgeDocuments.value];
      sanitizeScopedDocuments();
      conversationMode.value = 'rag';
      if (doc.status === 'failed') {
        setWorkspaceNotice('文档已写入数据库，但解析失败：' + (doc.errorMsg || '未知错误'), 'error');
      } else {
        setWorkspaceNotice('文档已上传到知识库。', 'success');
      }
      return doc;
    } catch (error) {
      setWorkspaceNotice(error?.message || '上传文档失败', 'error');
      throw error;
    } finally {
      uploadingDocumentNames.value = uploadingDocumentNames.value.filter((item) => item !== documentName);
    }
  }

  async function deleteKnowledgeDocument(documentId) {
    if (!documentId) return;
    deletingKnowledgeDocumentId.value = documentId;
    try {
      // 真实接口：DELETE /api/knowledge/:id
      await apiJson('/knowledge/' + documentId, { method: 'DELETE' });
      knowledgeDocuments.value = knowledgeDocuments.value.filter((item) => item.id !== documentId);
      if (ragDocumentIds.value.includes(Number(documentId))) {
        ragDocumentIds.value = ragDocumentIds.value.filter((item) => item !== Number(documentId));
      }
      setWorkspaceNotice('文档已从知识库移除。', 'success');
    } catch (error) {
      // 后端不可用：回退 mock
      await deleteDocument(documentId);
      knowledgeDocuments.value = knowledgeDocuments.value.filter((item) => item.id !== documentId);
      if (ragDocumentIds.value.includes(Number(documentId))) {
        ragDocumentIds.value = ragDocumentIds.value.filter((item) => item !== Number(documentId));
      }
      setWorkspaceNotice('（本地 mock）文档已删除。', 'info');
    } finally {
      deletingKnowledgeDocumentId.value = null;
    }
  }

  return {
    conversationMode,
    ragScopeType,
    ragDocumentIds,
    ragStrictMode,
    ragTopK,
    knowledgeDocuments,
    knowledgeDocumentsLoading,
    uploadingDocumentNames,
    deletingKnowledgeDocumentId,
    readyKnowledgeDocuments,
    knowledgeDocumentOptions,
    activeScopedDocuments,
    effectiveRagDocumentIds,
    resetKnowledgeState,
    setConversationMode,
    setRagScopeType,
    setRagDocumentIds,
    toggleScopedDocument,
    addDocumentToScope,
    loadKnowledgeDocuments,
    createKnowledgeDocument,
    uploadKnowledgeDocument,
    deleteKnowledgeDocument,
  };
}
