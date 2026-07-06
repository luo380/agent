export function useChatSession(options) {
  const {
    apiPrefix,
    defaultSessionTitle,
    currentToken,
    activeAgentId,
    activeSessionId,
    draftMessage,
    messages,
    sendingMessage,
    conversationMode,
    ragStrictMode,
    ragTopK,
    effectiveRagDocumentIds,
    createNewSession,
    loadMessages,
    loadSessions,
    setWorkspaceNotice,
    stopRunTracePolling,
    startRunTracePolling,
    loadRunTraceById,
    runTraceCurrentId,
    tracePanelVisible,
    parseApiResponse,
    appendSessionOverlayMessage = () => {},
    replaceSessionOverlayMessage = () => {},
    clearSessionOverlayMessages = () => {},
  } = options;

  function appendMessage(message) {
    messages.value = [...messages.value, message];
  }

  function updateMessageContent(messageId, content) {
    messages.value = messages.value.map((item) => item.id === messageId ? { ...item, content } : item);
  }

  function replaceMessage(messageId, nextMessage) {
    messages.value = messages.value.map((item) => item.id === messageId ? nextMessage : item);
  }

  function buildAssistantMessage(baseMessage, content, extra = {}) {
    return {
      ...baseMessage,
      content,
      ...extra,
    };
  }

  async function consumeSseStream(response, onEvent) {
    if (!response.body) {
      throw new Error('流式响应不可用');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    const processBlock = async (block) => {
      if (!block.trim()) return;
      const lines = block.split('\n');
      let eventName = 'message';
      const dataLines = [];

      for (const line of lines) {
        if (line.startsWith('event:')) eventName = line.slice(6).trim();
        if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
      }

      const payloadText = dataLines.join('\n');
      let payload = {};
      if (payloadText) {
        try {
          payload = JSON.parse(payloadText);
        } catch (error) {
          console.warn('SSE 数据解析失败:', payloadText, error);
          return;
        }
      }

      await onEvent(eventName, payload);
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });
      buffer += chunk.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
      const blocks = buffer.split('\n\n');
      buffer = blocks.pop() || '';
      for (const block of blocks) await processBlock(block);
    }

    if (buffer.trim()) await processBlock(buffer.trim());
  }

  function buildRagAssistantExtra(payload) {
    return {
      mode: 'rag',
      run_id: payload.run_id || null,
      strict_mode: Boolean(payload.strict_mode),
      citations: Array.isArray(payload.citations) ? payload.citations : [],
      retrieved_chunks: Array.isArray(payload.retrieved_chunks) ? payload.retrieved_chunks : [],
      meta: {
        top_k: Number(ragTopK.value) || 5,
        document_ids: effectiveRagDocumentIds.value.slice(),
      },
    };
  }

  function normalizeComparableText(value) {
    return String(value || '')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function hydrateLatestRagAssistantMessage(payload, createdAt) {
    const targetAnswer = normalizeComparableText(payload.answer);
    const createdTime = Date.parse(createdAt || '');
    let fallbackIndex = -1;

    for (let index = messages.value.length - 1; index >= 0; index -= 1) {
      const message = messages.value[index];
      if (!message || message.role !== 'assistant') continue;
      if (message.mode && message.mode !== 'rag') continue;

      const messageTime = Date.parse(message.created_at || '');
      const closeToCurrent = !Number.isFinite(createdTime)
        || !Number.isFinite(messageTime)
        || Math.abs(messageTime - createdTime) <= 120000;

      if (!closeToCurrent) continue;
      if (fallbackIndex === -1) fallbackIndex = index;

      if (!targetAnswer) continue;
      if (normalizeComparableText(message.content) === targetAnswer) {
        fallbackIndex = index;
        break;
      }
    }

    if (fallbackIndex === -1) return false;

    const nextMessages = messages.value.slice();
    const targetMessage = nextMessages[fallbackIndex];
    nextMessages[fallbackIndex] = buildAssistantMessage(
      targetMessage,
      payload.answer || targetMessage.content || '',
      buildRagAssistantExtra(payload),
    );
    messages.value = nextMessages;
    return true;
  }

  async function consumeChatStream(response, assistantDraftId) {
    let assistantText = '';

    await consumeSseStream(response, async (eventName, payload) => {
      if (eventName === 'start') {
        if (payload.run_id) {
          tracePanelVisible.value = true;
          await loadRunTraceById(payload.run_id, { allowMissing: true, kind: 'chat' });
          startRunTracePolling(payload.run_id);
        }
        return;
      }
      if (eventName === 'delta') {
        assistantText += payload.content || '';
        updateMessageContent(assistantDraftId, assistantText);
        return;
      }
      if (eventName === 'done') {
        if (payload.message) replaceMessage(assistantDraftId, payload.message);
        stopRunTracePolling();
        if (payload.run_id || runTraceCurrentId.value) {
          await loadRunTraceById(payload.run_id || runTraceCurrentId.value, { allowMissing: true, kind: 'chat' });
        }
        return;
      }
      if (eventName === 'error') {
        stopRunTracePolling();
        if (payload.run_id || runTraceCurrentId.value) {
          await loadRunTraceById(payload.run_id || runTraceCurrentId.value, { silent: true, allowMissing: true, kind: 'chat' });
        }
        throw new Error(payload.message || '流式会话返回错误');
      }
    });
  }

  async function consumeRagStream(response, targetSessionId, assistantDraftMessage) {
    let assistantText = '';
    let currentRunId = null;
    let finalPayload = null;
    let hasReceivedDelta = false;
    let draftAssistantMessage = { ...assistantDraftMessage };

    const syncDraftAssistantMessage = (content, extra = {}) => {
      draftAssistantMessage = buildAssistantMessage(draftAssistantMessage, content, extra);
      replaceSessionOverlayMessage(
        targetSessionId,
        assistantDraftMessage.id,
        draftAssistantMessage,
      );
    };

    await consumeSseStream(response, async (eventName, payload) => {
      if (eventName === 'start') {
        currentRunId = payload.run_id || currentRunId;
        if (currentRunId) {
          tracePanelVisible.value = true;
          await loadRunTraceById(currentRunId, { allowMissing: true, kind: 'rag-langchain' });
          startRunTracePolling(currentRunId);
        }
        syncDraftAssistantMessage('正在检索知识库...', {
          run_id: currentRunId,
          strict_mode: Boolean(payload.strict_mode),
        });
        return;
      }

      if (eventName === 'context_ready') {
        const retrievedChunkCount = Number(payload.retrieved_chunk_count) || 0;
        const contextStatusText = retrievedChunkCount > 0
          ? `已检索到 ${retrievedChunkCount} 条相关内容，正在生成回答...`
          : '未检索到相关内容，正在整理回答...';

        if (!hasReceivedDelta) {
          syncDraftAssistantMessage(contextStatusText, {
            run_id: currentRunId,
            strict_mode: draftAssistantMessage.strict_mode,
          });
        }

        setWorkspaceNotice(contextStatusText, 'info');
        if (currentRunId) {
          await loadRunTraceById(currentRunId, { silent: true, allowMissing: true, kind: 'rag-langchain' });
        }
        return;
      }

      if (eventName === 'delta') {
        hasReceivedDelta = true;
        assistantText += payload.content || '';
        syncDraftAssistantMessage(assistantText, {
          run_id: currentRunId,
          strict_mode: draftAssistantMessage.strict_mode,
        });
        return;
      }

      if (eventName === 'done') {
        finalPayload = {
          ...payload,
          run_id: payload.run_id || currentRunId,
        };
        currentRunId = finalPayload.run_id || currentRunId;
        syncDraftAssistantMessage(
          finalPayload.answer || assistantText || draftAssistantMessage.content || '',
          buildRagAssistantExtra(finalPayload),
        );
        stopRunTracePolling();
        if (currentRunId) {
          await loadRunTraceById(currentRunId, { allowMissing: true, kind: 'rag-langchain' });
        }
        return;
      }

      if (eventName === 'error') {
        stopRunTracePolling();
        if (payload.run_id || currentRunId || runTraceCurrentId.value) {
          await loadRunTraceById(
            payload.run_id || currentRunId || runTraceCurrentId.value,
            { silent: true, allowMissing: true, kind: 'rag-langchain' },
          );
        }
        throw new Error(payload.message || '知识库流式问答返回错误');
      }
    });

    return finalPayload;
  }

  async function sendRagMessage(targetSessionId, assistantDraftMessage, now, content) {
    stopRunTracePolling();

    const response = await fetch(apiPrefix + '/rag-langchain/ask/stream', {
      method: 'POST',
      headers: {
        Authorization: 'Bearer ' + currentToken.value,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        session_id: targetSessionId,
        question: content,
        top_k: Number(ragTopK.value) || 5,
        strict_mode: Boolean(ragStrictMode.value),
        document_ids: effectiveRagDocumentIds.value,
      }),
    });

    if (!response.ok) {
      await parseApiResponse(response);
      return;
    }

    const payload = await consumeRagStream(response, targetSessionId, assistantDraftMessage);

    await loadMessages(targetSessionId);
    if (payload) {
      hydrateLatestRagAssistantMessage(payload, now);
    }
    clearSessionOverlayMessages(targetSessionId);
  }

  async function sendMessage() {

    const content = draftMessage.value.trim();
    if (!content) return;
    if (!activeAgentId.value) {
      setWorkspaceNotice('当前没有可用智能体。', 'warning');
      return;
    }

    const isRagMode = conversationMode.value === 'rag';
    sendingMessage.value = true;
    setWorkspaceNotice(isRagMode ? '正在检索知识库并生成回答...' : '正在发送消息...', 'info');

    let targetSessionId = activeSessionId.value;
    if (!targetSessionId) {
      const createdSession = await createNewSession(defaultSessionTitle);
      if (!createdSession?.id) {
        sendingMessage.value = false;
        return;
      }
      targetSessionId = createdSession.id;
    }

    const now = new Date().toISOString();
    const optimisticUserMessage = {
      id: 'temp-user-' + Date.now(),
      session_id: targetSessionId,
      role: 'user',
      content,
      created_at: now,
      mode: isRagMode ? 'rag' : 'chat',
    };
    const optimisticAssistantId = 'temp-assistant-' + Date.now();
    const optimisticAssistantMessage = {
      id: optimisticAssistantId,
      session_id: targetSessionId,
      role: 'assistant',
      content: '',
      created_at: now,
      mode: isRagMode ? 'rag' : 'chat',
      strict_mode: isRagMode ? Boolean(ragStrictMode.value) : undefined,
      citations: [],
      retrieved_chunks: [],
      meta: isRagMode
        ? {
            top_k: Number(ragTopK.value) || 5,
            document_ids: effectiveRagDocumentIds.value.slice(),
          }
        : undefined,
    };

    if (isRagMode) {
      appendSessionOverlayMessage(targetSessionId, optimisticUserMessage);
      appendSessionOverlayMessage(targetSessionId, optimisticAssistantMessage);
    } else {
      appendMessage(optimisticUserMessage);
      appendMessage(optimisticAssistantMessage);
    }
    draftMessage.value = '';

    try {
      if (isRagMode) {
        await sendRagMessage(targetSessionId, optimisticAssistantMessage, now, content);
      } else {
        const response = await fetch(apiPrefix + '/sessions/session/' + targetSessionId + '/chat/stream', {
          method: 'POST',
          headers: {
            Authorization: 'Bearer ' + currentToken.value,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ content, mode: 'chat' }),
        });
        if (!response.ok) {
          await parseApiResponse(response);
          return;
        }
        await consumeChatStream(response, optimisticAssistantId);
        await loadMessages(targetSessionId);
      }

      await loadSessions();
      setWorkspaceNotice(isRagMode ? '知识库问答已完成。' : '消息发送成功。', 'success');
    } catch (error) {
      setWorkspaceNotice(error?.message || '发送消息失败', 'error');
      if (isRagMode) {
        replaceSessionOverlayMessage(
          targetSessionId,
          optimisticAssistantId,
          buildAssistantMessage(
            {
              id: optimisticAssistantId,
              session_id: targetSessionId,
              role: 'assistant',
              created_at: now,
            },
            '知识库问答失败：' + (error?.message || '请稍后重试'),
            {
              mode: 'rag',
              is_error: true,
              citations: [],
              retrieved_chunks: [],
            },
          ),
        );
      } else {
        await loadMessages(targetSessionId);
      }
    } finally {
      stopRunTracePolling();
      sendingMessage.value = false;
    }
  }

  return {
    sendMessage,
  };
}
