<template>
  <aside class="tool-rail">
    <div class="rail-top">
      <div class="rail-brand">AI</div>
      <button
        v-for="item in toolItems"
        :key="item.key"
        type="button"
        class="rail-item"
        :class="{ 'is-active': item.key === activeToolKey }"
        @click="$emit('select-tool', item)"
      >
        <span class="rail-icon">{{ item.short }}</span>
        <span class="rail-label">{{ item.label }}</span>
      </button>
    </div>

    <div class="rail-bottom">
      <a-avatar class="rail-avatar">{{ userInitials }}</a-avatar>
      <a-button type="text" danger class="rail-logout" @click="$emit('logout')">退出登录</a-button>
    </div>
  </aside>
</template>

<script setup>
defineProps({
  toolItems: { type: Array, default: () => [] },
  activeToolKey: { type: String, default: 'chat' },
  userInitials: { type: String, default: '我' },
});

defineEmits(['select-tool', 'logout']);
</script>