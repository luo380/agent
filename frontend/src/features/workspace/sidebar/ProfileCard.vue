<template>
  <a-card :bordered="false" class="profile-card">
    <div class="profile-row">
      <a-avatar class="profile-avatar">{{ userInitials }}</a-avatar>
      <div class="profile-info">
        <div class="profile-name">{{ userName || '团队成员' }}</div>
        <div class="profile-email">{{ userEmail || '' }}</div>
      </div>
    </div>
    <a-button danger block @click="$emit('logout')">退出登录</a-button>
  </a-card>
</template>

<script setup>
defineProps({
  userInitials: { type: String, default: '我' },
  userName: { type: String, default: '' },
  userEmail: { type: String, default: '' },
});

defineEmits(['logout']);
</script>