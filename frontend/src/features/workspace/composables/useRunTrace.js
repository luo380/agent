import { onUnmounted, ref } from 'vue';

function parseJson(value, fallback = null) {
  if (value == null || value === '') return fallback;
  if (typeof value === 'object') return value;
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

export function useRunTrace(apiJson) {
  const tracePanelVisible = ref(false);
  const runTraceLoading = ref(false);
  const runTraceCurrentId = ref(null);
  const runTraceData = ref(null);
  const runTraceError = ref('');
  const runTraceKind = ref('chat');

  let runTracePollTimer = null;

  function stopRunTracePolling() {
    if (runTracePollTimer) {
      window.clearInterval(runTracePollTimer);
      runTracePollTimer = null;
    }
  }

  function clearRunTraceState() {
    runTraceLoading.value = false;
    runTraceCurrentId.value = null;
    runTraceData.value = null;
    runTraceError.value = '';
    runTraceKind.value = 'chat';
  }

  function isRunTraceMissingError(error) {
    const message = String(error?.message || '');
    return message.includes('No history found')
      || message.includes('No steps found')
      || message.includes('Run not found')
      || message.includes('RAG run not found');
  }

  function setRunTraceKind(kind) {
    runTraceKind.value = kind === 'rag' ? 'rag' : 'chat';
  }

  function getRunTracePath(runId, kind = runTraceKind.value) {
    return kind === 'rag' ? '/rag/run/' + runId : '/runs/run/' + runId;
  }

  function normalizeTraceData(data, kind = 'chat') {
    if (!data) return null;

    if (kind === 'rag') {
      return {
        ...data,
        trace_kind: 'rag',
        input_text: data.question || '',
        output_text: data.answer || '',
        document_scope: parseJson(data.document_scope_json, []),
        strict_mode: Boolean(data.strict_mode),
        top_k: Number(data.top_k) || 0,
      };
    }

    return {
      ...data,
      trace_kind: 'chat',
      input_text: data.input_text || '',
      output_text: data.output_text || '',
    };
  }

  function startRunTracePolling(runId) {
    stopRunTracePolling();
    if (!runId) return;
    runTracePollTimer = window.setInterval(() => {
      loadRunTraceById(runId, { silent: true, allowMissing: true, kind: runTraceKind.value });
    }, 1500);
  }

  async function loadRunTraceById(runId, options = {}) {
    const silent = Boolean(options.silent);
    const allowMissing = Boolean(options.allowMissing);
    const kind = options.kind === 'rag' ? 'rag' : runTraceKind.value;

    if (!runId) {
      clearRunTraceState();
      return null;
    }

    runTraceKind.value = kind;
    runTraceCurrentId.value = runId;
    if (!silent) runTraceLoading.value = true;
    runTraceError.value = '';

    try {
      const result = await apiJson(getRunTracePath(runId, kind));
      runTraceData.value = normalizeTraceData(result?.data || null, kind);
      if (runTraceData.value?.id) {
        runTraceCurrentId.value = runTraceData.value.id;
      }
      if (runTraceData.value?.status && runTraceData.value.status !== 'running') {
        stopRunTracePolling();
      }
      return runTraceData.value;
    } catch (error) {
      if (allowMissing && isRunTraceMissingError(error)) {
        runTraceData.value = null;
        runTraceError.value = '';
        return null;
      }
      runTraceError.value = error?.message || '加载执行轨迹失败';
      return null;
    } finally {
      if (!silent) runTraceLoading.value = false;
    }
  }

  async function loadLatestRunTraceForSession(sessionId, options = {}) {
    const silent = Boolean(options.silent);
    const kind = options.kind === 'rag' ? 'rag' : runTraceKind.value;
    if (!sessionId) {
      clearRunTraceState();
      return null;
    }

    if (kind === 'rag') {
      if (runTraceCurrentId.value) {
        return await loadRunTraceById(runTraceCurrentId.value, { silent, allowMissing: true, kind: 'rag' });
      }
      clearRunTraceState();
      return null;
    }

    if (!silent) runTraceLoading.value = true;
    runTraceError.value = '';

    try {
      const runResult = await apiJson('/runs/session/' + sessionId);
      const latestRun = runResult?.data || null;
      if (!latestRun?.id) {
        clearRunTraceState();
        return null;
      }
      runTraceCurrentId.value = latestRun.id;
      runTraceKind.value = 'chat';
      return await loadRunTraceById(latestRun.id, { silent: true, allowMissing: true, kind: 'chat' });
    } catch (error) {
      if (isRunTraceMissingError(error)) {
        clearRunTraceState();
        return null;
      }
      runTraceError.value = error?.message || '加载执行轨迹失败';
      return null;
    } finally {
      if (!silent) runTraceLoading.value = false;
    }
  }

  async function refreshRunTrace(activeSessionId) {
    if (runTraceCurrentId.value) {
      await loadRunTraceById(runTraceCurrentId.value, { allowMissing: true, kind: runTraceKind.value });
      return;
    }
    if (activeSessionId) {
      await loadLatestRunTraceForSession(activeSessionId, { kind: runTraceKind.value });
    }
  }

  async function toggleRunTracePanel(activeSessionId, options = {}) {
    const nextVisible = !tracePanelVisible.value;
    if (options.kind) {
      setRunTraceKind(options.kind);
    }
    tracePanelVisible.value = nextVisible;

    if (!nextVisible) {
      stopRunTracePolling();
      return;
    }

    await refreshRunTrace(activeSessionId);
  }

  onUnmounted(() => {
    stopRunTracePolling();
  });

  return {
    tracePanelVisible,
    runTraceLoading,
    runTraceCurrentId,
    runTraceData,
    runTraceError,
    runTraceKind,
    setRunTraceKind,
    stopRunTracePolling,
    clearRunTraceState,
    startRunTracePolling,
    loadRunTraceById,
    loadLatestRunTraceForSession,
    refreshRunTrace,
    toggleRunTracePanel,
  };
}
