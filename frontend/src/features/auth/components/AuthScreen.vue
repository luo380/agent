<template>
  <div class="auth-page">
    <section class="auth-hero">
      <div class="hero-label">Vue 3 / Ant Design Vue</div>
      <a-typography-title :level="1" class="hero-title">
        统一注册、登录与会话入口
      </a-typography-title>
      <a-typography-paragraph class="hero-copy">
        当前认证区和工作台都基于同一套 Ant Design Vue 组件系统实现。登录成功后不进入传统概览页，而是直接进入智能体会话工作台。
      </a-typography-paragraph>

      <div class="hero-grid">
        <a-card v-for="item in heroHighlights" :key="item.key" :bordered="false" class="hero-card">
          <div class="hero-card-index">{{ item.index }}</div>
          <a-typography-title :level="4" class="hero-card-title">{{ item.title }}</a-typography-title>
          <a-typography-paragraph class="hero-card-copy">{{ item.copy }}</a-typography-paragraph>
        </a-card>
      </div>
    </section>

    <section class="auth-panel">
      <a-card :bordered="false" class="auth-card">
        <div class="auth-card-head">
          <div class="panel-label">Authentication</div>
          <a-typography-title :level="2" class="auth-card-title">账号认证</a-typography-title>
          <a-typography-paragraph class="auth-card-copy">
            注册和登录都直接联调后端接口，并保留清晰的校验、提交中、成功和错误反馈。
          </a-typography-paragraph>
        </div>

        <a-tabs v-model:activeKey="tabKey" class="auth-tabs">
          <a-tab-pane key="login" tab="登录">
            <a-form layout="vertical">
              <a-form-item label="邮箱">
                <a-input v-model:value="loginForm.email" size="large" placeholder="you@agentlab.dev" />
              </a-form-item>

              <a-form-item label="密码">
                <a-input-password
                  v-model:value="loginForm.password"
                  size="large"
                  placeholder="请输入登录密码"
                />
              </a-form-item>

              <a-form-item>
                <a-checkbox v-model:checked="loginForm.rememberMe">
                  记住当前登录状态，便于下次直接恢复会话工作台
                </a-checkbox>
              </a-form-item>

              <a-alert
                v-if="loginMessage"
                :type="loginMessageType"
                :message="loginMessage"
                show-icon
                class="feedback-alert"
              />

              <a-button
                type="primary"
                size="large"
                block
                :loading="loginSubmitting"
                @click="$emit('submit-login')"
              >
                登录并进入会话页
              </a-button>
            </a-form>
          </a-tab-pane>

          <a-tab-pane key="register" tab="注册">
            <a-form layout="vertical">
              <a-form-item label="名称">
                <a-input
                  v-model:value="registerForm.name"
                  size="large"
                  :maxlength="100"
                  placeholder="例如：产品实验室"
                />
              </a-form-item>

              <a-form-item label="邮箱">
                <a-input v-model:value="registerForm.email" size="large" placeholder="you@agentlab.dev" />
              </a-form-item>

              <a-form-item label="密码">
                <a-input-password
                  v-model:value="registerForm.password"
                  size="large"
                  placeholder="至少 8 位，建议混合大小写和数字"
                />
              </a-form-item>

              <a-form-item label="确认密码">
                <a-input-password
                  v-model:value="registerForm.confirmPassword"
                  size="large"
                  placeholder="再次输入密码"
                />
              </a-form-item>

              <div class="password-meter">
                <a-progress :percent="passwordPercent" :show-info="false" :stroke-color="passwordColor" />
                <span class="password-meter-copy">{{ passwordLabel }}</span>
              </div>

              <a-form-item>
                <a-checkbox v-model:checked="registerForm.agreement">
                  我已知晓这是当前 Agent 项目的测试入口，同意继续进入后续工作台流程
                </a-checkbox>
              </a-form-item>

              <a-alert
                v-if="registerMessage"
                :type="registerMessageType"
                :message="registerMessage"
                show-icon
                class="feedback-alert"
              />

              <a-button
                type="primary"
                size="large"
                block
                :loading="registerSubmitting"
                @click="$emit('submit-register')"
              >
                创建账号
              </a-button>
            </a-form>
          </a-tab-pane>
        </a-tabs>
      </a-card>

      <a-card :bordered="false" class="status-card">
        <template #title>当前联调接口</template>
        <ul class="status-list">
          <li><code>POST /api/auth/register</code></li>
          <li><code>POST /api/auth/login</code></li>
          <li><code>GET /api/auth/me</code></li>
          <li><code>GET /api/agents/list_agents</code></li>
          <li><code>GET /api/sessions/list_sessions</code></li>
          <li><code>GET /api/sessions/session/{session_id}</code></li>
          <li><code>POST /api/sessions/session/{session_id}/chat/stream</code></li>
        </ul>
        <pre class="result-panel">{{ activeTab === 'login' ? loginPreview : registerPreview }}</pre>
      </a-card>
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue';
import { heroHighlights } from '../../../shared/config/appContent';

const props = defineProps({
  activeTab: { type: String, required: true },
  registerSubmitting: { type: Boolean, default: false },
  loginSubmitting: { type: Boolean, default: false },
  registerMessage: { type: String, default: '' },
  registerMessageType: { type: String, default: 'info' },
  loginMessage: { type: String, default: '' },
  loginMessageType: { type: String, default: 'info' },
  registerPreview: { type: String, default: '' },
  loginPreview: { type: String, default: '' },
  registerForm: { type: Object, required: true },
  loginForm: { type: Object, required: true },
});

const emit = defineEmits(['update:activeTab', 'submit-login', 'submit-register']);

const tabKey = computed({
  get: () => props.activeTab,
  set: (value) => emit('update:activeTab', value),
});

const passwordScore = computed(() => {
  let score = 0;
  if (props.registerForm.password.length >= 8) score += 1;
  if (/[A-Z]/.test(props.registerForm.password) && /[a-z]/.test(props.registerForm.password)) score += 1;
  if (/\d/.test(props.registerForm.password)) score += 1;
  if (/[^A-Za-z0-9]/.test(props.registerForm.password)) score += 1;
  return score;
});

const passwordPercent = computed(() => [0, 25, 50, 75, 100][passwordScore.value]);
const passwordColor = computed(() => ['#d9d9d9', '#ff7875', '#faad14', '#52c41a', '#1677ff'][passwordScore.value]);
const passwordLabel = computed(() => [
  '密码强度：等待输入',
  '密码强度：偏弱，建议增加长度',
  '密码强度：一般，建议混合大小写和数字',
  '密码强度：良好，可以继续',
  '密码强度：很强，适合继续使用',
][passwordScore.value]);
</script>