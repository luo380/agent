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
          await loadRunTraceById(payload.run_id, { allowMissing: true });
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
          await loadRunTraceById(payload.run_id || runTraceCurrentId.value, { allowMissing: true });
        }
        await loadSessions();
        return;
      }
      if (eventName === 'error') {
        stopRunTracePolling();
        if (payload.run_id || runTraceCurrentId.value) {
          await loadRunTraceById(payload.run_id || runTraceCurrentId.value, { silent: true, allowMissing: true });
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

  async function sendMessage() {
    const content = draftMessage.value.trim();
    if (!content) return;
    if (!activeAgentId.value) {
      setWorkspaceNotice('当前没有可用智能体。', 'warning');
      return;
    }
    sendingMessage.value = true;
    setWorkspaceNotice('正在发送消息...', 'info');

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
    };
    const optimisticAssistantId = 'temp-assistant-' + Date.now();
    const optimisticAssistantMessage = {
      id: optimisticAssistantId,
      session_id: targetSessionId,
      role: 'assistant',
      content: '',
      created_at: now,
    };

    appendMessage(optimisticUserMessage);
    appendMessage(optimisticAssistantMessage);
    draftMessage.value = '';

    try {
      const response = await fetch(apiPrefix + '/sessions/session/' + targetSessionId + '/chat/stream', {
        method: 'POST',
        headers: {
          Authorization: 'Bearer ' + currentToken.value,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ content }),
      });
      if (!response.ok) {
        await parseApiResponse(response);
        return;
      }
      await consumeChatStream(response, optimisticAssistantId);
      await loadMessages(targetSessionId);
      setWorkspaceNotice('消息发送成功。', 'success');
    } catch (error) {
      setWorkspaceNotice(error?.message || '发送消息失败', 'error');
      await loadMessages(targetSessionId);
    } finally {
      stopRunTracePolling();
      sendingMessage.value = false;
    }
  }

  return {
    sendMessage,
  };
}