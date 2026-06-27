<template>
  <div class="tools-center-panel">
    <div class="panel-block">
      <div class="block-title">工具中心</div>
      <div class="tool-status-list">
        <div v-for="item in toolCenterItems" :key="item.title" class="status-row">
          <div>
            <div class="status-title">{{ item.title }}</div>
            <div class="status-copy">{{ item.copy }}</div>
          </div>
          <a-tag :color="item.color">{{ item.status }}</a-tag>
        </div>
      </div>
    </div>

    <div class="panel-block">
      <div class="block-title">建议动作</div>
      <div class="shortcut-grid single-column">
        <button
          type="button"
          class="shortcut-card"
          @click="$emit('show-integration-guide')"
        >
          <span class="shortcut-title">查看接入说明</span>
          <span class="shortcut-copy">保持当前会话布局不变，在二级面板里扩充能力入口。</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  toolCenterItems: { type: Array, default: () => [] },
});

defineEmits(['show-integration-guide']);
</script>