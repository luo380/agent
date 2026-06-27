<template>
  <a-modal
    :open="open"
    title="创建智能体"
    ok-text="创建"
    cancel-text="取消"
    :confirm-loading="creatingCustomAgent"
    @ok="$emit('submit')"
    @cancel="$emit('cancel')"
  >
    <a-form layout="vertical">
      <a-form-item label="智能体名称">
        <a-input v-model:value="agentCreateForm.name" placeholder="例如：扫地机器人客服" />
      </a-form-item>
      <a-form-item label="系统提示词">
        <a-textarea
          v-model:value="agentCreateForm.system_prompt"
          :auto-size="{ minRows: 4, maxRows: 8 }"
          placeholder="描述这个智能体的职责、语气和回答边界。"
        />
      </a-form-item>
      <a-form-item label="模型">
        <a-input v-model:value="agentCreateForm.model" placeholder="qwen/qwen3-1.7b" />
      </a-form-item>
      <a-form-item label="温度">
        <a-slider v-model:value="agentCreateForm.temperature" :min="0" :max="1" :step="0.1" />
      </a-form-item>
    </a-form>
  </a-modal>
</template>

<script setup>
defineProps({
  open: { type: Boolean, default: false },
  creatingCustomAgent: { type: Boolean, default: false },
  agentCreateForm: { type: Object, required: true },
});

defineEmits(['submit', 'cancel']);
</script>