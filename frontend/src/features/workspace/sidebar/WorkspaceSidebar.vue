<template>
  <div class="sider-shell">
    <ToolRail
      :tool-items="toolItems"
      :active-tool-key="activeToolKey"
      :user-initials="userInitials"
      @select-tool="$emit('select-tool', $event)"
      @logout="$emit('logout')"
    />

    <section class="tool-panel">
      <template v-if="activeToolKey === 'chat'">
        <ChatToolPanel
          :creating-session="creatingSession"
          :active-agent-id="activeAgentId"
          :sessions-loading="sessionsLoading"
          :sessions="filteredSessions"
          :active-session-id="activeSessionId"
          :deleting-session-id="deletingSessionId"
          :empty-image="emptyImage"
          :format-time="formatTime"
          @create-session="$emit('create-session')"
          @refresh-sessions="$emit('refresh-sessions')"
          @select-session="$emit('select-session', $event)"
          @delete-session="$emit('delete-session', $event)"
        />
      </template>

      <template v-else-if="activeToolKey === 'agents'">
        <AgentOverviewPanel
          :active-agent-id="activeAgentId"
          :agent-options="agentOptions"
          :workspace-loading="workspaceLoading"
          :has-agents="hasAgents"
          :current-agent="currentAgent"
          :empty-image="emptyImage"
          :capability-tags="capabilityTags"
          @refresh-agents="$emit('refresh-agents')"
          @select-agent="$emit('select-agent', $event)"
          @create-demo-agent="$emit('create-demo-agent')"
          @focus-composer="$emit('focus-composer')"
        />
      </template>


      <template v-else>
        <ToolsCenterPanel
          :tool-center-items="toolCenterItems"
          @show-integration-guide="$emit('show-integration-guide')"
        />
      </template>
    </section>
  </div>
</template>

<script setup>
import AgentOverviewPanel from '../panels/AgentOverviewPanel.vue';
import ChatToolPanel from '../panels/ChatToolPanel.vue';
import ToolRail from './ToolRail.vue';
import ToolsCenterPanel from '../panels/ToolsCenterPanel.vue';

defineProps({
  toolItems: { type: Array, default: () => [] },
  activeToolKey: { type: String, default: 'chat' },
  activeTool: { type: Object, required: true },
  userInitials: { type: String, default: '我' },
  userName: { type: String, default: '' },
  userEmail: { type: String, default: '' },
  creatingSession: { type: Boolean, default: false },
  activeAgentId: { type: [String, Number, null], default: null },
  sessionsLoading: { type: Boolean, default: false },
  filteredSessions: { type: Array, default: () => [] },
  activeSessionId: { type: [String, Number, null], default: null },
  deletingSessionId: { type: [String, Number, null], default: null },
  emptyImage: { type: [Object, String], default: null },
  formatTime: { type: Function, required: true },
  agentOptions: { type: Array, default: () => [] },
  workspaceLoading: { type: Boolean, default: false },
  hasAgents: { type: Boolean, default: false },
  currentAgent: { type: Object, default: null },
  capabilityTags: { type: Array, default: () => [] },
  knowledgeDocuments: { type: Array, default: () => [] },
  knowledgeDocumentsLoading: { type: Boolean, default: false },
  uploadingDocumentNames: { type: Array, default: () => [] },
  deletingKnowledgeDocumentId: { type: [String, Number, null], default: null },
  conversationMode: { type: String, default: 'chat' },
  ragScopeType: { type: String, default: 'all' },
  ragDocumentIds: { type: Array, default: () => [] },
  activeScopedDocuments: { type: Array, default: () => [] },
  toolCenterItems: { type: Array, default: () => [] },
});

defineEmits([
  'select-tool',
  'logout',
  'create-session',
  'refresh-sessions',
  'select-session',
  'delete-session',
  'refresh-agents',
  'select-agent',
  'create-demo-agent',
  'focus-composer',
  'show-integration-guide',
  'refresh-knowledge',
  'upload-knowledge-document',
  'delete-knowledge-document',
  'add-doc-to-scope',
  'set-conversation-mode',
  'update:rag-scope-type',
  'update:rag-document-ids',
]);
</script>
