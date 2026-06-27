<template>
  <section class="agent-editor-page">
    <div class="agent-editor-topbar">
      <div class="agent-editor-identity">
        <a-button class="agent-editor-back" @click="$emit('back')">返回列表</a-button>
        <a-avatar class="agent-editor-avatar">{{ avatarText }}</a-avatar>
        <div class="agent-editor-heading">
          <div class="agent-editor-eyebrow">Agent Builder</div>
          <h2 class="agent-editor-title">{{ form.name || '未命名智能体' }}</h2>
          <p class="agent-editor-subtitle">
            按照 Ant Design Vue 工作台样式集中编辑当前智能体的 Prompt、模型与扩展能力。
          </p>
        </div>
      </div>

      <div class="agent-editor-toolbar">
        <a-select
          :value="agent?.id"
          class="agent-editor-current-select"
          size="large"
          :options="agentOptions"
          @update:value="handleAgentChange"
        />
        <a-button @click="$emit('activate', agent?.id)" :disabled="!agent?.id || agent?.id === activeAgentId">
          {{ agent?.id === activeAgentId ? '当前会话已使用' : '设为当前' }}
        </a-button>
        <a-button @click="$emit('chat', agent?.id)" :disabled="!agent?.id">进入会话</a-button>
        <a-popconfirm
          title="删除这个智能体？"
          description="删除后会同时移除该智能体关联的会话记录，且无法恢复。"
          ok-text="删除"
          cancel-text="取消"
          @confirm="$emit('delete', agent?.id)"
        >
          <a-button danger :disabled="!agent?.id">删除智能体</a-button>
        </a-popconfirm>
        <a-button type="primary" :loading="saving" @click="submit">保存修改</a-button>
      </div>
    </div>

    <a-alert
      class="agent-editor-stage"
      type="info"
      show-icon
      message="当前已接通保存：名称、系统提示词、模型、温度。知识库、工具、记忆区域已按同一编辑流预留，待后端字段接入后可直接继续扩展。"
    />

    <div class="agent-editor-shell">
      <div class="agent-editor-main">
        <a-card :bordered="false" class="agent-editor-card">
          <template #title>
            <div class="agent-editor-card-head">
              <span>基础信息</span>
              <a-tag color="processing">已接通</a-tag>
            </div>
          </template>

          <a-form layout="vertical" class="agent-editor-form">
            <a-form-item label="智能体名称">
              <a-input v-model:value="form.name" size="large" maxlength="160" placeholder="例如：扫地机器人客服" />
            </a-form-item>

            <a-form-item label="欢迎语">
              <a-textarea
                v-model:value="form.welcome_message"
                :rows="4"
                placeholder="用于新建会话时的开场欢迎语，例如：你好，我可以帮你处理售前咨询、使用指导和售后问题。"
              />
            </a-form-item>

            <a-form-item label="系统提示词">
              <a-textarea
                v-model:value="form.system_prompt"
                :rows="11"
                class="agent-prompt-input"
                placeholder="写清楚角色、目标、边界、回复风格、工具调用规则和输出格式。"
              />
            </a-form-item>
          </a-form>
        </a-card>

        <a-card :bordered="false" class="agent-editor-card">
          <template #title>
            <div class="agent-editor-card-head">
              <span>提示词模板</span>
              <a-tag color="default">快捷套用</a-tag>
            </div>
          </template>

          <div class="agent-template-toolbar">
            <span class="agent-editor-section-heading">常用模板</span>
            <a-button size="small" @click="resetPrompt">恢复当前配置</a-button>
          </div>

          <div class="agent-template-grid">
            <button
              v-for="template in promptTemplates"
              :key="template.key"
              type="button"
              class="agent-template-card"
              @click="applyTemplate(template.content)"
            >
              <strong>{{ template.title }}</strong>
              <span>{{ template.description }}</span>
            </button>
          </div>
        </a-card>
      </div>

      <div class="agent-editor-side">
        <a-card :bordered="false" class="agent-editor-card">
          <template #title>
            <div class="agent-editor-card-head">
              <span>模型与生成</span>
              <a-tag color="processing">已接通</a-tag>
            </div>
          </template>

          <a-form layout="vertical" class="agent-config-form">
            <a-form-item label="对话模型">
              <a-select
                v-model:value="form.model"
                size="large"
                :options="modelOptions"
                placeholder="选择对话模型"
              />
            </a-form-item>

            <a-form-item label="温度">
              <div class="agent-temperature-row">
                <a-slider v-model:value="form.temperature" :min="0" :max="1" :step="0.1" />
                <a-input-number v-model:value="form.temperature" :min="0" :max="1" :step="0.1" />
              </div>
            </a-form-item>
          </a-form>
        </a-card>

        <a-card :bordered="false" class="agent-editor-card">
          <template #title>
            <div class="agent-editor-card-head">
              <span>知识检索</span>
              <a-tag color="gold">待接后端</a-tag>
            </div>
          </template>

          <div class="agent-config-split">
            <div class="agent-memory-row">
              <span>默认启用 RAG</span>
              <a-switch v-model:checked="draft.ragEnabled" />
            </div>
            <div class="agent-config-triple">
              <a-form layout="vertical">
                <a-form-item label="召回条数">
                  <a-input-number v-model:value="draft.retrievalCount" :min="1" :max="20" :disabled="!draft.ragEnabled" />
                </a-form-item>
              </a-form>
              <a-form layout="vertical">
                <a-form-item label="Dense">
                  <a-input-number v-model:value="draft.denseTopK" :min="1" :max="50" :disabled="!draft.ragEnabled" />
                </a-form-item>
              </a-form>
              <a-form layout="vertical">
                <a-form-item label="BM25">
                  <a-input-number v-model:value="draft.bm25TopK" :min="1" :max="50" :disabled="!draft.ragEnabled" />
                </a-form-item>
              </a-form>
            </div>
            <div class="agent-config-triple">
              <a-form layout="vertical">
                <a-form-item label="RRF K">
                  <a-input-number v-model:value="draft.rrfK" :min="1" :max="200" :disabled="!draft.ragEnabled" />
                </a-form-item>
              </a-form>
              <div class="agent-memory-row">
                <span>Rerank</span>
                <a-switch v-model:checked="draft.rerankEnabled" :disabled="!draft.ragEnabled" />
              </div>
            </div>
          </div>
        </a-card>

        <a-card :bordered="false" class="agent-editor-card">
          <template #title>
            <div class="agent-editor-card-head">
              <span>工具绑定</span>
              <a-tag color="gold">待接后端</a-tag>
            </div>
          </template>

          <div class="agent-pill-list">
            <a-tag v-for="item in toolSuggestions" :key="item" color="blue">{{ item }}</a-tag>
          </div>
          <p class="agent-resource-hint">当前先展示能力位。后端补齐工具字段后，可直接在这里做绑定和开关。</p>
        </a-card>

        <a-card :bordered="false" class="agent-editor-card">
          <template #title>
            <div class="agent-editor-card-head">
              <span>知识库</span>
              <a-tag color="gold">待接后端</a-tag>
            </div>
          </template>

          <div class="agent-resource-list">
            <div v-for="item in knowledgeMocks" :key="item.name" class="agent-resource-item">
              <div>
                <strong>{{ item.name }}</strong>
                <p>{{ item.copy }}</p>
              </div>
              <a-tag>{{ item.state }}</a-tag>
            </div>
          </div>
        </a-card>

        <a-card :bordered="false" class="agent-editor-card">
          <template #title>
            <div class="agent-editor-card-head">
              <span>记忆策略</span>
              <a-tag color="gold">待接后端</a-tag>
            </div>
          </template>

          <div class="agent-config-split">
            <div class="agent-memory-row">
              <span>会话记忆</span>
              <a-switch v-model:checked="draft.memoryEnabled" />
            </div>
            <a-form layout="vertical">
              <a-form-item label="记忆消息上限">
                <a-input-number
                  v-model:value="draft.memoryLimit"
                  :min="1"
                  :max="100"
                  :disabled="!draft.memoryEnabled"
                />
              </a-form-item>
            </a-form>
          </div>
        </a-card>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, reactive, watch } from 'vue';

const props = defineProps({
  agent: {
    type: Object,
    default: null,
  },
  agents: {
    type: Array,
    default: () => [],
  },
  activeAgentId: {
    type: Number,
    default: null,
  },
  saving: {
    type: Boolean,
    default: false,
  },
  modelOptions: {
    type: Array,
    default: () => [],
  },
  promptTemplates: {
    type: Array,
    default: () => [],
  },
  toolSuggestions: {
    type: Array,
    default: () => [],
  },
  knowledgeMocks: {
    type: Array,
    default: () => [],
  },
});

const emit = defineEmits(['activate', 'back', 'chat', 'delete', 'save', 'switch-agent']);

const form = reactive({
  name: '',
  welcome_message: '',
  system_prompt: '',
  model: 'qwen/qwen3-1.7b',
  temperature: 0.2,
});

const draft = reactive({
  ragEnabled: true,
  retrievalCount: 4,
  denseTopK: 12,
  bm25TopK: 12,
  rrfK: 60,
  rerankEnabled: true,
  memoryEnabled: false,
  memoryLimit: 12,
});

const agentOptions = computed(() =>
  props.agents.map((item) => ({
    label: item.name,
    value: item.id,
  })),
);

const avatarText = computed(() => {
  const text = String(form.name || props.agent?.name || 'AI').trim();
  return text.slice(0, 2).toUpperCase();
});

watch(
  () => props.agent,
  (agent) => {
    form.name = agent?.name || '';
    form.welcome_message = agent?.welcome_message || '';
    form.system_prompt = agent?.system_prompt || '';
    form.model = agent?.model || 'qwen/qwen3-1.7b';
    form.temperature = Number(agent?.temperature ?? 0.2);
  },
  { immediate: true },
);

function handleAgentChange(value) {
  emit('switch-agent', value);
}

function applyTemplate(content) {
  form.system_prompt = content;
}

function resetPrompt() {
  form.system_prompt = props.agent?.system_prompt || '';
}

function submit() {
  emit('save', {
    name: form.name.trim(),
    welcome_message: form.welcome_message.trim(),
    system_prompt: form.system_prompt.trim(),
    model: form.model.trim() || 'qwen/qwen3-1.7b',
    temperature: Number(form.temperature) || 0.2,
  });
}
</script>

<style scoped>
.agent-editor-page {
  display: grid;
  gap: 18px;
  align-content: start;
}

.agent-editor-topbar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}

.agent-editor-identity {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  min-width: 0;
}

.agent-editor-back.ant-btn {
  margin-top: 6px;
}

.agent-editor-avatar.ant-avatar {
  width: 52px;
  height: 52px;
  background: linear-gradient(135deg, #111827 0%, #1f3c88 100%);
  font-weight: 700;
}

.agent-editor-heading {
  min-width: 0;
}

.agent-editor-eyebrow {
  margin-bottom: 6px;
  color: #1677ff;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.agent-editor-title {
  margin: 0 0 8px;
  font-size: 28px;
  line-height: 1.1;
}

.agent-editor-subtitle {
  margin: 0;
  color: #667085;
  line-height: 1.7;
}

.agent-editor-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.agent-editor-current-select {
  min-width: 240px;
}

.agent-editor-stage {
  margin-bottom: 0;
}

.agent-editor-shell {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(320px, 0.9fr);
  gap: 18px;
  align-items: start;
}

.agent-editor-main,
.agent-editor-side {
  display: grid;
  gap: 18px;
  align-content: start;
}

.agent-editor-card.ant-card {
  border-radius: 24px;
  box-shadow: 0 18px 48px rgba(15, 23, 42, 0.08);
}

.agent-editor-card :deep(.ant-card-body) {
  display: grid;
  gap: 18px;
}

.agent-editor-card-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.agent-editor-form,
.agent-config-form,
.agent-config-split {
  display: grid;
  gap: 8px;
}

.agent-prompt-input {
  min-height: 280px;
}

.agent-template-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.agent-editor-section-heading {
  font-size: 13px;
  font-weight: 600;
  color: #344054;
}

.agent-template-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}

.agent-template-card {
  border: 0;
  text-align: left;
  cursor: pointer;
  padding: 16px;
  border-radius: 18px;
  background: linear-gradient(180deg, #fff 0%, #f7faff 100%);
  box-shadow: inset 0 0 0 1px rgba(15, 23, 42, 0.06);
  display: grid;
  gap: 8px;
  transition: transform 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
}

.agent-template-card:hover {
  background: rgba(22, 119, 255, 0.08);
  box-shadow: inset 0 0 0 1px rgba(22, 119, 255, 0.2);
  transform: translateY(-1px);
}

.agent-template-card strong {
  color: #101828;
}

.agent-template-card span,
.agent-resource-item p,
.agent-resource-hint {
  color: #667085;
  font-size: 12px;
  line-height: 1.7;
}

.agent-temperature-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 110px;
  gap: 12px;
  align-items: center;
}

.agent-config-triple {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.agent-pill-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.agent-resource-list {
  display: grid;
  gap: 12px;
}

.agent-resource-item {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  padding: 14px;
  border-radius: 16px;
  background: #f8fafc;
}

.agent-resource-item strong {
  display: block;
  margin-bottom: 6px;
}

.agent-resource-item p {
  margin: 0;
}

.agent-memory-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

@media (max-width: 1180px) {
  .agent-editor-shell {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .agent-editor-topbar {
    flex-direction: column;
  }

  .agent-editor-toolbar {
    width: 100%;
    justify-content: flex-start;
  }

  .agent-editor-current-select {
    width: 100%;
  }
}

@media (max-width: 640px) {
  .agent-editor-identity {
    flex-wrap: wrap;
  }

  .agent-config-triple,
  .agent-temperature-row {
    grid-template-columns: 1fr;
  }
}
</style>
