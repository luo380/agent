<template>
  <div class="agent-overview-panel">
    <div class="panel-block">
      <div class="block-row">
        <div class="block-title">当前智能体</div>
        <a-button type="link" size="small" class="inline-action" @click="$emit('refresh-agents')">
          刷新
        </a-button>
      </div>
      <a-select
        :value="activeAgentId"
        class="panel-select"
        size="large"
        :options="agentOptions"
        :loading="workspaceLoading"
        :disabled="!hasAgents"
        placeholder="选择智能体"
        @update:value="$emit('select-agent', $event)"
      />
      <div v-if="currentAgent" class="agent-summary">
        <div class="agent-card-title-row">
          <span class="agent-card-name">{{ currentAgent.name }}</span>
          <a-tag color="blue">{{ currentAgent.model }}</a-tag>
        </div>
        <div class="agent-card-copy">温度 {{ currentAgent.temperature }}，当前已接入会话工作台。</div>
      </div>
      <a-empty v-else :image="emptyImage" description="暂无智能体" />
    </div>

    <div class="panel-block">
      <div class="block-title">能力预览</div>
      <div class="tag-grid">
        <a-tag v-for="tag in capabilityTags" :key="tag" color="processing">{{ tag }}</a-tag>
      </div>
    </div>

    <div class="panel-block">
      <div class="block-title">智能体操作</div>
      <div class="shortcut-grid single-column">
        <button type="button" class="shortcut-card" @click="$emit('create-demo-agent')">
          <span class="shortcut-title">创建示例智能体</span>
          <span class="shortcut-copy">当你还没有配置智能体时，可以先生成一个联调用的标准示例。</span>
        </button>
        <button type="button" class="shortcut-card" @click="$emit('focus-composer')">
          <span class="shortcut-title">继续当前对话</span>
          <span class="shortcut-copy">保持右侧主会话区不跳转，直接回到输入区继续协作。</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  activeAgentId: { type: [String, Number, null], default: null },
  agentOptions: { type: Array, default: () => [] },
  workspaceLoading: { type: Boolean, default: false },
  hasAgents: { type: Boolean, default: false },
  currentAgent: { type: Object, default: null },
  emptyImage: { type: [Object, String], default: null },
  capabilityTags: { type: Array, default: () => [] },
});

defineEmits([
  'refresh-agents',
  'select-agent',
  'create-demo-agent',
  'focus-composer',
]);
</script>