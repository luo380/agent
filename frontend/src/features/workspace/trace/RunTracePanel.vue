<template>
  <aside class="run-trace-panel">
    <div class="run-trace-head">
      <div>
        <div class="panel-overline">Execution Trace</div>
        <a-typography-title :level="5" class="panel-title">执行轨迹</a-typography-title>
      </div>

      <a-button size="small" :loading="loading" @click="$emit('refresh')">
        刷新
      </a-button>
    </div>

    <div v-if="loading && !trace" class="run-trace-loading">
      <a-spin />
      <span>正在加载执行轨迹...</span>
    </div>

    <div v-else-if="error" class="trace-block trace-error-block">
      <div class="trace-block-title">执行轨迹加载失败</div>
      <div class="trace-copy">{{ error }}</div>
    </div>

    <div v-else-if="trace" class="run-trace-scroll">
      <section class="trace-block trace-summary">
        <div class="trace-summary-row">
          <span class="trace-label">执行状态</span>
          <a-tag :color="getStatusColor(trace.status)">{{ getStatusLabel(trace.status) }}</a-tag>
        </div>
        <div class="trace-summary-row">
          <span class="trace-label">Run ID</span>
          <code class="trace-code">{{ trace.id }}</code>
        </div>
        <div class="trace-summary-row">
          <span class="trace-label">开始时间</span>
          <span>{{ formatTraceTime(trace.started_at) }}</span>
        </div>
        <div v-if="trace.finished_at" class="trace-summary-row">
          <span class="trace-label">完成时间</span>
          <span>{{ formatTraceTime(trace.finished_at) }}</span>
        </div>
      </section>

      <section v-if="trace.input_text" class="trace-block">
        <div class="trace-block-title">用户输入</div>
        <div class="trace-copy">{{ trace.input_text }}</div>
      </section>

      <section v-if="trace.output_text" class="trace-block">
        <div class="trace-block-title">模型输出</div>
        <div class="trace-copy">{{ trace.output_text }}</div>
      </section>

      <section v-if="trace.error_message" class="trace-block trace-error-block">
        <div class="trace-block-title">错误信息</div>
        <div class="trace-copy">{{ trace.error_message }}</div>
      </section>

      <section v-if="Array.isArray(trace.steps) && trace.steps.length" class="trace-block">
        <div class="trace-block-title">执行步骤</div>
        <div class="trace-step-list">
          <article
            v-for="step in trace.steps"
            :key="step.id"
            class="trace-step-card"
            :class="getStepClass(step.status)"
          >
            <div class="trace-step-line"></div>

            <div class="trace-step-head">
              <div>
                <div class="trace-step-name">{{ step.step_name }}</div>
                <div class="trace-step-type">{{ step.step_type }}</div>
              </div>
              <div class="trace-step-time">{{ formatTraceTime(step.finished_at || step.started_at) }}</div>
            </div>

            <a-tag :color="getStatusColor(step.status)">{{ getStatusLabel(step.status) }}</a-tag>

            <pre v-if="formatPayload(step.input_payload)" class="trace-payload">{{ formatPayload(step.input_payload) }}</pre>
            <pre v-if="formatPayload(step.output_payload)" class="trace-payload is-output">{{ formatPayload(step.output_payload) }}</pre>
            <div v-if="step.error_message" class="trace-copy">{{ step.error_message }}</div>
          </article>
        </div>
      </section>
    </div>

    <div v-else class="run-trace-loading">
      <a-empty description="当前会话还没有执行轨迹" />
    </div>
  </aside>
</template>

<script setup>
defineProps({
  loading: { type: Boolean, default: false },
  trace: { type: Object, default: null },
  error: { type: String, default: '' },
});

defineEmits(['refresh']);

function formatTraceTime(value) {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(date);
}

function getStatusLabel(status) {
  if (status === 'running') return '执行中';
  if (status === 'completed') return '已完成';
  if (status === 'failed') return '失败';
  return status || '--';
}

function getStatusColor(status) {
  if (status === 'running') return 'processing';
  if (status === 'completed') return 'success';
  if (status === 'failed') return 'error';
  return 'default';
}

function getStepClass(status) {
  if (status === 'running') return 'is-running';
  if (status === 'completed') return 'is-success';
  if (status === 'failed') return 'is-failed';
  return '';
}

function formatPayload(payload) {
  const text = String(payload || '').trim();
  if (!text) return '';
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}
</script>