<template>
  <div>
    <header class="workspace-header agent-page-header">
      <div>
        <a-typography-title :level="2" class="workspace-title">智能体管理</a-typography-title>
        <a-typography-paragraph class="workspace-subtitle">
          在这里集中管理你的智能体，可以创建、设为当前，或者直接进入对应会话工作台。
        </a-typography-paragraph>
      </div>

      <a-button type="primary" size="large" @click="$emit('open-create-modal')">
        创建智能体
      </a-button>
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

    <section class="agent-manage-stage">
      <div v-if="workspaceLoading" class="screen-state compact-state">
        <a-spin />
        <span>正在加载智能体...</span>
      </div>

      <div v-else-if="!agents.length" class="empty-panel">
        <a-card :bordered="false" class="empty-card">
          <a-empty description="当前账号下还没有智能体" />
          <a-typography-paragraph class="empty-copy">
            可以先创建一个智能体，再把它设为当前智能体并进入会话工作台。
          </a-typography-paragraph>
          <div class="agent-empty-actions">
            <a-button type="primary" size="large" @click="$emit('open-create-modal')">创建智能体</a-button>
            <a-button size="large" :loading="creatingAgent" @click="$emit('create-demo-agent')">创建示例智能体</a-button>
          </div>
        </a-card>
      </div>

      <div v-else-if="editingAgent">
        <AgentEditorPanel
          :agent="editingAgent"
          :agents="agents"
          :active-agent-id="activeAgentId"
          :saving="savingAgentConfig"
          :model-options="agentEditorModelOptions"
          :prompt-templates="agentPromptTemplates"
          :tool-suggestions="agentToolSuggestions"
          :knowledge-mocks="agentKnowledgeMocks"
          @activate="$emit('activate-agent', $event)"
          @back="$emit('close-editor')"
          @chat="$emit('enter-chat', $event)"
          @delete="$emit('delete-agent', $event)"
          @save="$emit('save-agent-config', $event)"
          @switch-agent="$emit('open-editor', $event)"
        />
      </div>

      <div v-else class="agent-manage-page">
        <div class="agent-manage-head">
          <div>
            <a-typography-title :level="4" class="agent-manage-title">我的智能体</a-typography-title>
            <a-typography-paragraph class="agent-manage-copy">
              共 {{ agents.length }} 个智能体，当前激活 {{ activeAgentName }}。
            </a-typography-paragraph>
          </div>
          <a-button type="link" @click="$emit('refresh-agents')">刷新列表</a-button>
        </div>

        <div class="agent-card-grid">
          <a-card
            v-for="agent in agents"
            :key="agent.id"
            :bordered="false"
            class="agent-manage-card"
            :class="{ 'is-current': agent.id === activeAgentId }"
          >
            <div class="agent-manage-card-top">
              <a-avatar class="agent-manage-avatar">{{ getShortName(agent.name, 'AI') }}</a-avatar>
              <a-tag v-if="agent.id === activeAgentId" color="success">当前</a-tag>
            </div>

            <a-typography-title :level="5" class="agent-manage-card-title">
              {{ agent.name }}
            </a-typography-title>
            <a-typography-paragraph class="agent-manage-card-copy">
              {{ summarizeAgentPrompt(agent.system_prompt) }}
            </a-typography-paragraph>

            <div class="agent-manage-meta">
              <a-tag color="processing">{{ agent.model }}</a-tag>
              <span>温度 {{ agent.temperature }}</span>
            </div>

            <div class="agent-manage-actions">
              <a-button
                :type="agent.id === activeAgentId ? 'primary' : 'default'"
                @click="$emit('activate-agent', agent.id)"
              >
                {{ agent.id === activeAgentId ? '当前智能体' : '设为当前' }}
              </a-button>
              <a-button @click="$emit('open-editor', agent.id)">编辑配置</a-button>
              <a-button @click="$emit('enter-chat', agent.id)">进入会话</a-button>
              <a-popconfirm
                title="删除这个智能体？"
                description="删除后将无法恢复该智能体及其关联上下文。"
                ok-text="删除"
                cancel-text="取消"
                @confirm="$emit('delete-agent', agent.id)"
              >
                <a-button danger :loading="deletingAgentId === agent.id">删除</a-button>
              </a-popconfirm>
            </div>
          </a-card>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import AgentEditorPanel from './AgentEditorPanel.vue';
import { getShortName, summarizeAgentPrompt } from '../../../shared/utils/uiHelpers';

defineProps({
  workspaceLoading: { type: Boolean, default: false },
  workspaceNotice: { type: String, default: '' },
  workspaceNoticeType: { type: String, default: 'info' },
  agents: { type: Array, default: () => [] },
  editingAgent: { type: Object, default: null },
  activeAgentId: { type: [Number, String], default: null },
  creatingAgent: { type: Boolean, default: false },
  deletingAgentId: { type: [Number, String], default: null },
  savingAgentConfig: { type: Boolean, default: false },
  agentEditorModelOptions: { type: Array, default: () => [] },
  agentPromptTemplates: { type: Array, default: () => [] },
  agentToolSuggestions: { type: Array, default: () => [] },
  agentKnowledgeMocks: { type: Array, default: () => [] },
  activeAgentName: { type: String, default: '智能体' },
});

defineEmits([
  'close-notice',
  'open-create-modal',
  'create-demo-agent',
  'activate-agent',
  'open-editor',
  'close-editor',
  'enter-chat',
  'delete-agent',
  'save-agent-config',
  'refresh-agents',
]);
</script>