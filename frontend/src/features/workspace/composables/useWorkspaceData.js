import { computed, reactive, ref, watch } from 'vue';

export function useWorkspaceData(options) {
  const {
    apiJson,
    setWorkspaceNotice,
    getShortName,
    currentUser,
    baseAgentModelOptions,
    defaultSessionTitle,
    stopRunTracePolling,
    clearRunTraceState,
    tracePanelVisible,
    loadLatestRunTraceForSession,
  } = options;

  const workspaceLoading = ref(false);
  const sessionsLoading = ref(false);
  const messagesLoading = ref(false);
  const creatingAgent = ref(false);
  const creatingSession = ref(false);
  const sendingMessage = ref(false);
  const deletingSessionId = ref(null);
  const deletingAgentId = ref(null);
  const savingAgentConfig = ref(false);
  const editingAgentId = ref(null);
  const agentModalOpen = ref(false);
  const creatingCustomAgent = ref(false);
  const activeToolKey = ref('chat');
  const activeAgentId = ref(null);
  const activeSessionId = ref(null);
  const agents = ref([]);
  const sessions = ref([]);
  const messages = ref([]);
  const draftMessage = ref('');

  const agentCreateForm = reactive({
    name: '',
    system_prompt: '',
    model: 'qwen/qwen3-1.7b',
    temperature: 0.2,
  });

  const currentAgent = computed(() => agents.value.find((item) => item.id === activeAgentId.value) || null);
  const editingAgent = computed(() => agents.value.find((item) => item.id === editingAgentId.value) || null);
  const agentSelectOptions = computed(() => agents.value.map((item) => ({ label: item.name, value: item.id })));
  const agentEditorModelOptions = computed(() => {
    const options = [...baseAgentModelOptions];
    const seen = new Set(options.map((item) => item.value));
    for (const agent of agents.value) {
      if (agent.model && !seen.has(agent.model)) {
        options.push({ label: agent.model, value: agent.model });
        seen.add(agent.model);
      }
    }
    return options;
  });
  const filteredSessions = computed(() => {
    if (!activeAgentId.value) return [];
    return sessions.value.filter((item) => item.agent_id === activeAgentId.value);
  });
  const activeAgentName = computed(() => currentAgent.value?.name || '智能体');
  const activeAgentModel = computed(() => currentAgent.value?.model || '');
  const activeAgentShort = computed(() => getShortName(activeAgentName.value, 'AI'));
  const userInitials = computed(() => getShortName(currentUser.value?.name, '我'));
  const activeSessionTitle = computed(() => {
    const session = filteredSessions.value.find((item) => item.id === activeSessionId.value);
    if (session) return session.title;
    return activeAgentName.value + ' 会话工作台';
  });
  const composerPlaceholder = computed(() => '给 ' + activeAgentName.value + ' 发送消息，Ctrl+Enter 发送');

  function resetWorkspaceState() {
    stopRunTracePolling();
    tracePanelVisible.value = false;
    clearRunTraceState();
    activeAgentId.value = null;
    activeSessionId.value = null;
    editingAgentId.value = null;
    agents.value = [];
    sessions.value = [];
    messages.value = [];
    draftMessage.value = '';
  }

  function selectTool(item) {
    activeToolKey.value = item.key;
    if (item.key !== 'agents') {
      editingAgentId.value = null;
    }
  }

  function applyPrompt(prompt) {
    draftMessage.value = prompt;
  }

  function openAgentCreateModal() {
    editingAgentId.value = null;
    agentModalOpen.value = true;
  }

  function resetAgentCreateForm() {
    agentCreateForm.name = '';
    agentCreateForm.system_prompt = '';
    agentCreateForm.model = 'qwen/qwen3-1.7b';
    agentCreateForm.temperature = 0.2;
  }

  function openAgentEditor(agentId) {
    if (!agentId) return;
    editingAgentId.value = agentId;
  }

  function closeAgentEditor() {
    editingAgentId.value = null;
  }

  function setCurrentAgent(agentId) {
    activeAgentId.value = agentId;
    setWorkspaceNotice('已切换当前智能体。', 'success');
  }

  function syncActiveSessionSelection() {
    const list = filteredSessions.value;
    if (!list.length) {
      activeSessionId.value = null;
      messages.value = [];
      return;
    }
    if (!list.some((item) => item.id === activeSessionId.value)) {
      activeSessionId.value = list[0].id;
    }
  }

  async function loadAgents() {
    const result = await apiJson('/agents/list_agents');
    agents.value = Array.isArray(result?.data) ? result.data : [];
    if (!agents.value.length) {
      activeAgentId.value = null;
      editingAgentId.value = null;
      return;
    }
    if (!agents.value.some((item) => item.id === activeAgentId.value)) {
      activeAgentId.value = agents.value[0].id;
    }
    if (editingAgentId.value && !agents.value.some((item) => item.id === editingAgentId.value)) {
      editingAgentId.value = null;
    }
  }

  async function loadSessions() {
    sessionsLoading.value = true;
    try {
      const result = await apiJson('/sessions/list_sessions');
      sessions.value = Array.isArray(result?.data) ? result.data : [];
      syncActiveSessionSelection();
    } finally {
      sessionsLoading.value = false;
    }
  }

  async function loadMessages(sessionId) {
    if (!sessionId) {
      messages.value = [];
      return;
    }
    messagesLoading.value = true;
    try {
      const result = await apiJson('/sessions/session/' + sessionId);
      messages.value = Array.isArray(result?.data) ? result.data : [];
    } finally {
      messagesLoading.value = false;
    }
  }

  async function createDemoAgent() {
    creatingAgent.value = true;
    setWorkspaceNotice('正在创建示例智能体...', 'info');
    try {
      await apiJson('/agents/create_agent', {
        method: 'POST',
        body: JSON.stringify({
          name: '扫地机器人客服',
          system_prompt: '你是一个面向扫地机器人售前、售后与维护场景的智能客服，回答需要简洁、准确、友好。',
          model: 'qwen/qwen3-1.7b',
          temperature: 0.2,
        }),
      });
      await loadAgents();
      await loadSessions();
      setWorkspaceNotice('示例智能体已创建，可以开始新会话了。', 'success');
    } catch (error) {
      setWorkspaceNotice(error?.message || '创建示例智能体失败', 'error');
    } finally {
      creatingAgent.value = false;
    }
  }

  async function deleteAgent(agentId) {
    if (!agentId) return;
    deletingAgentId.value = agentId;
    const deletingCurrent = activeAgentId.value === agentId;

    try {
      await apiJson('/agents/agent/' + agentId, {
        method: 'POST',
      });

      agents.value = agents.value.filter((item) => item.id !== agentId);

      if (editingAgentId.value === agentId) {
        editingAgentId.value = null;
      }

      if (deletingCurrent) {
        activeAgentId.value = null;
        activeSessionId.value = null;
        messages.value = [];
      }

      await loadAgents();
      await loadSessions();
      if (activeSessionId.value) {
        await loadMessages(activeSessionId.value);
      }
      setWorkspaceNotice('智能体已删除。', 'success');
    } catch (error) {
      setWorkspaceNotice(error?.message || '删除智能体失败', 'error');
    } finally {
      deletingAgentId.value = null;
    }
  }

  async function createNewSession(title = defaultSessionTitle) {
    if (!activeAgentId.value) {
      setWorkspaceNotice('请先选择一个智能体。', 'warning');
      return null;
    }
    creatingSession.value = true;
    try {
      const result = await apiJson('/sessions/create_session', {
        method: 'POST',
        body: JSON.stringify({ title, agent_id: activeAgentId.value }),
      });
      const createdSession = result?.data || null;
      await loadSessions();
      if (createdSession?.id) {
        activeSessionId.value = createdSession.id;
        messages.value = [];
      }
      setWorkspaceNotice('已创建新会话。', 'success');
      return createdSession;
    } catch (error) {
      setWorkspaceNotice(error?.message || '创建会话失败', 'error');
      return null;
    } finally {
      creatingSession.value = false;
    }
  }

  async function deleteSession(sessionId) {
    if (!sessionId) return;
    deletingSessionId.value = sessionId;
    const deletingActive = activeSessionId.value === sessionId;
    const currentList = filteredSessions.value.slice();
    const currentIndex = currentList.findIndex((item) => item.id === sessionId);
    const fallbackSession = currentList[currentIndex + 1] || currentList[currentIndex - 1] || null;

    try {
      await apiJson('/sessions/session/' + sessionId, {
        method: 'DELETE',
      });

      sessions.value = sessions.value.filter((item) => item.id !== sessionId);

      if (deletingActive) {
        activeSessionId.value = fallbackSession?.id || null;
        if (!fallbackSession) {
          messages.value = [];
        }
      }

      setWorkspaceNotice('会话已删除。', 'success');
      await loadSessions();
    } catch (error) {
      setWorkspaceNotice(error?.message || '删除会话失败', 'error');
    } finally {
      deletingSessionId.value = null;
    }
  }

  async function submitCreateAgent() {
    if (!agentCreateForm.name.trim()) {
      setWorkspaceNotice('请输入智能体名称。', 'warning');
      return;
    }

    creatingCustomAgent.value = true;
    try {
      const result = await apiJson('/agents/create_agent', {
        method: 'POST',
        body: JSON.stringify({
          name: agentCreateForm.name.trim(),
          system_prompt: agentCreateForm.system_prompt.trim(),
          model: agentCreateForm.model.trim() || 'qwen/qwen3-1.7b',
          temperature: Number(agentCreateForm.temperature) || 0.2,
        }),
      });

      const createdAgent = result?.data || null;
      await loadAgents();
      if (createdAgent?.id) {
        activeAgentId.value = createdAgent.id;
        editingAgentId.value = createdAgent.id;
      }
      agentModalOpen.value = false;
      resetAgentCreateForm();
      setWorkspaceNotice('智能体创建成功。', 'success');
    } catch (error) {
      setWorkspaceNotice(error?.message || '创建智能体失败', 'error');
    } finally {
      creatingCustomAgent.value = false;
    }
  }

  async function saveAgentConfig(payload) {
    const targetAgentId = editingAgentId.value;
    if (!targetAgentId) return;
    if (!payload?.name?.trim()) {
      setWorkspaceNotice('请输入智能体名称。', 'warning');
      return;
    }

    savingAgentConfig.value = true;
    try {
      const result = await apiJson('/agents/agent/' + targetAgentId, {
        method: 'PUT',
        body: JSON.stringify({
          name: payload.name.trim(),
          system_prompt: payload.system_prompt?.trim?.() || '',
          model: payload.model?.trim?.() || 'qwen/qwen3-1.7b',
          temperature: Number(payload.temperature) || 0.2,
        }),
      });

      const updatedAgent = result?.data || null;
      if (updatedAgent?.id) {
        agents.value = agents.value.map((item) => item.id === updatedAgent.id ? updatedAgent : item);
      }
      await loadAgents();
      setWorkspaceNotice('智能体配置已保存。', 'success');
    } catch (error) {
      setWorkspaceNotice(error?.message || '保存智能体配置失败', 'error');
    } finally {
      savingAgentConfig.value = false;
    }
  }

  async function enterAgentConversation(agentId) {
    activeAgentId.value = agentId;
    activeToolKey.value = 'chat';
    await loadSessions();
    if (activeSessionId.value) {
      await loadMessages(activeSessionId.value);
    } else {
      messages.value = [];
    }
    setWorkspaceNotice('已进入该智能体的会话工作台。', 'success');
  }

  async function enterWorkspace(currentView) {
    currentView.value = 'workspace';
    workspaceLoading.value = true;
    try {
      await loadAgents();
      await loadSessions();
      if (activeSessionId.value) {
        await loadMessages(activeSessionId.value);
      } else {
        messages.value = [];
      }
    } finally {
      workspaceLoading.value = false;
    }
  }

  watch(activeAgentId, () => {
    syncActiveSessionSelection();
  });

  watch(activeSessionId, async (sessionId, previousId) => {
    stopRunTracePolling();
    clearRunTraceState();

    if (sessionId && sessionId !== previousId) {
      await loadMessages(sessionId);
      if (tracePanelVisible.value) {
        await loadLatestRunTraceForSession(sessionId, { silent: true });
      }
    }
    if (!sessionId) {
      messages.value = [];
      tracePanelVisible.value = false;
      clearRunTraceState();
    }
  });

  return {
    workspaceLoading,
    sessionsLoading,
    messagesLoading,
    creatingAgent,
    creatingSession,
    sendingMessage,
    deletingSessionId,
    deletingAgentId,
    savingAgentConfig,
    editingAgentId,
    agentModalOpen,
    creatingCustomAgent,
    activeToolKey,
    activeAgentId,
    activeSessionId,
    agents,
    sessions,
    messages,
    draftMessage,
    agentCreateForm,
    currentAgent,
    editingAgent,
    agentSelectOptions,
    agentEditorModelOptions,
    filteredSessions,
    activeAgentName,
    activeAgentModel,
    activeAgentShort,
    userInitials,
    activeSessionTitle,
    composerPlaceholder,
    resetWorkspaceState,
    selectTool,
    applyPrompt,
    openAgentCreateModal,
    resetAgentCreateForm,
    openAgentEditor,
    closeAgentEditor,
    setCurrentAgent,
    loadAgents,
    loadSessions,
    loadMessages,
    createDemoAgent,
    deleteAgent,
    createNewSession,
    deleteSession,
    submitCreateAgent,
    saveAgentConfig,
    enterAgentConversation,
    enterWorkspace,
  };
}
