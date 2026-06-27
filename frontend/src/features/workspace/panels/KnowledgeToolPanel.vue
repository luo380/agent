<template>
  <div class="knowledge-tool-panel">
    <div class="panel-block">
      <div class="block-title">知识入口</div>
      <div class="knowledge-list">
        <a-card v-for="item in knowledgeCards" :key="item.title" size="small" class="mini-card">
          <template #title>{{ item.title }}</template>
          <div class="mini-card-copy">{{ item.copy }}</div>
        </a-card>
      </div>
    </div>

    <div class="panel-block">
      <div class="block-title">后续接入建议</div>
      <a-list size="small" :data-source="knowledgeTodo">
        <template #renderItem="{ item }">
          <a-list-item>{{ item }}</a-list-item>
        </template>
      </a-list>
    </div>
  </div>
</template>

<script setup>
defineProps({
  knowledgeCards: { type: Array, default: () => [] },
  knowledgeTodo: { type: Array, default: () => [] },
});
</script>