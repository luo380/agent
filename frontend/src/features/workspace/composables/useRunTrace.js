import { onUnmounted, ref } from 'vue';

export function useRunTrace(apiJson) {
  const tracePanelVisible = ref(false);
  const runTraceLoading = ref(false);
  const runTraceCurrentId = ref(null);
  const runTraceData = ref(null);
  const runTraceError = ref('');

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
  }

  function isRunTraceMissingError(error) {
    const message = String(error?.message || '');
    return message.includes('No history found')
      || message.includes('No steps found')
      || message.includes('Run not found');
  }

  function startRunTracePolling(runId) {
    stopRunTracePolling();
    if (!runId) return;
    runTracePollTimer = window.setInterval(() => {
      loadRunTraceById(runId, { silent: true, allowMissing: true });
    }, 1500);
  }

  async function loadRunTraceById(runId, options = {}) {
    const silent = Boolean(options.silent);
    const allowMissing = Boolean(options.allowMissing);

    if (!runId) {
      clearRunTraceState();
      return null;
    }

    runTraceCurrentId.value = runId;
    if (!silent) runTraceLoading.value = true;
    runTraceError.value = '';

    try {
      const result = await apiJson('/runs/run/' + runId);
      runTraceData.value = result?.data || null;
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
    if (!sessionId) {
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
      return await loadRunTraceById(latestRun.id, { silent: true, allowMissing: true });
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
      await loadRunTraceById(runTraceCurrentId.value, { allowMissing: true });
      return;
    }
    if (activeSessionId) {
      await loadLatestRunTraceForSession(activeSessionId);
    }
  }

  async function toggleRunTracePanel(activeSessionId) {
    const nextVisible = !tracePanelVisible.value;
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
    stopRunTracePolling,
    clearRunTraceState,
    startRunTracePolling,
    loadRunTraceById,
    loadLatestRunTraceForSession,
    refreshRunTrace,
    toggleRunTracePanel,
  };
}