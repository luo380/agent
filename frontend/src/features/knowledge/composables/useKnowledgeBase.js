import { computed, ref } from 'vue';

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
      label: item.name,
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

  async function loadKnowledgeDocuments() {
    knowledgeDocumentsLoading.value = true;
    try {
      const result = await apiJson('/knowledge/list');
      knowledgeDocuments.value = Array.isArray(result?.data) ? result.data : [];
      sanitizeScopedDocuments();
    } finally {
      knowledgeDocumentsLoading.value = false;
    }
  }

  async function uploadKnowledgeDocument(file) {
    const documentName = String(file?.name || '').trim() || '未命名文档';
    uploadingDocumentNames.value = [...uploadingDocumentNames.value, documentName];

    try {
      const formData = new FormData();
      formData.append('file', file);

      const response = await fetch(apiPrefix + '/knowledge/upload', {
        method: 'POST',
        headers: currentToken.value ? { Authorization: 'Bearer ' + currentToken.value } : {},
        body: formData,
      });

      await parseApiResponse(response);
      await loadKnowledgeDocuments();
      conversationMode.value = 'rag';
      setWorkspaceNotice('文档已上传到知识库。', 'success');
    } catch (error) {
      setWorkspaceNotice(error?.message || '文档上传失败', 'error');
      throw error;
    } finally {
      uploadingDocumentNames.value = uploadingDocumentNames.value.filter((item) => item !== documentName);
    }
  }

  async function deleteKnowledgeDocument(documentId) {
    if (!documentId) return;
    deletingKnowledgeDocumentId.value = documentId;
    try {
      await apiJson('/knowledge/' + documentId, {
        method: 'DELETE',
      });
      if (ragDocumentIds.value.includes(Number(documentId))) {
        ragDocumentIds.value = ragDocumentIds.value.filter((item) => item !== Number(documentId));
      }
      await loadKnowledgeDocuments();
      setWorkspaceNotice('文档已从知识库移除。', 'success');
    } catch (error) {
      setWorkspaceNotice(error?.message || '删除文档失败', 'error');
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
    uploadKnowledgeDocument,
    deleteKnowledgeDocument,
  };
}
