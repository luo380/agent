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

  async function consumeChatStream(response, assistantDraftId) {
    if (!response.body) {
      throw new Error('流式响应不可用');
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let assistantText = '';

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

  async function sendRagMessage(targetSessionId, assistantDraftId, now, content) {
    stopRunTracePolling();

    const response = await fetch(apiPrefix + '/rag/ask', {
      method: 'POST',
      headers: {
        Authorization: 'Bearer ' + currentToken.value,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        question: content,
        top_k: Number(ragTopK.value) || 5,
        strict_mode: Boolean(ragStrictMode.value),
        document_ids: effectiveRagDocumentIds.value,
      }),
    });

    const result = await parseApiResponse(response);
    const payload = result?.data || {};

    replaceSessionOverlayMessage(
      targetSessionId,
      assistantDraftId,
      buildAssistantMessage(
        {
          id: payload.run_id ? 'rag-' + payload.run_id : assistantDraftId,
          session_id: targetSessionId,
          role: 'assistant',
          created_at: now,
        },
        payload.answer || '',
        {
          mode: 'rag',
          run_id: payload.run_id || null,
          strict_mode: Boolean(payload.strict_mode),
          citations: Array.isArray(payload.citations) ? payload.citations : [],
          retrieved_chunks: Array.isArray(payload.retrieved_chunks) ? payload.retrieved_chunks : [],
          meta: {
            top_k: Number(ragTopK.value) || 5,
            document_ids: effectiveRagDocumentIds.value.slice(),
          },
        },
      ),
    );

    if (payload.run_id) {
      tracePanelVisible.value = true;
      await loadRunTraceById(payload.run_id, { allowMissing: true, kind: 'rag' });
    }
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
      citations: [],
      retrieved_chunks: [],
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
        await sendRagMessage(targetSessionId, optimisticAssistantId, now, content);
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
