<template>
  <div class="mockup-surface">
    <div class="mockup-switcher">
      <div><strong>知识库 UI</strong><span>按设计稿查看完整页面模块</span></div>
      <div class="mockup-tabs">
        <button v-for="item in views" :key="item.key" :class="{ active: item.key === activeView }" @click="activeView = item.key">{{ item.label }}</button>
      </div>
    </div>
    <iframe class="mockup-frame" :srcdoc="srcdoc" title="知识库 UI mockup" />
  </div>
</template>

<script setup>
import { computed, ref } from 'vue';
import createReadHtml from '../mockups/01-create-and-read.html?raw';
import collaborationHtml from '../mockups/02-collaboration.html?raw';
import personalHtml from '../mockups/03-personal-center.html?raw';

const activeView = ref('read');
const views = [
  { key: 'read', label: '文档阅读', html: createReadHtml, pageIndex: 0 },
  { key: 'edit', label: '文档编辑', html: createReadHtml, pageIndex: 1 },
  { key: 'create', label: '新建与上传', html: createReadHtml, pageIndex: 2 },
  { key: 'members', label: '成员权限', html: collaborationHtml, pageIndex: 0 },
  { key: 'assistant', label: 'AI 助手', html: collaborationHtml, pageIndex: 1 },
  { key: 'search', label: '全局搜索', html: personalHtml, pageIndex: 0 },
  { key: 'favorites', label: '我的收藏', html: personalHtml, pageIndex: 1 },
  { key: 'shared', label: '与我共享', html: personalHtml, pageIndex: 2 },
  { key: 'trash', label: '回收站', html: personalHtml, pageIndex: 3 },
];

const srcdoc = computed(() => {
  const current = views.find((item) => item.key === activeView.value) || views[0];
  const injection = `<style>body{padding:0!important;background:#f5f6f8!important}.doc-head,.page-banner{display:none!important}.page{display:none!important;margin:0!important;max-width:none!important;border-radius:0!important;box-shadow:none!important}.page:nth-of-type(${current.pageIndex + 1}){display:block!important}</style>`;
  return current.html.replace('</head>', `${injection}</head>`);
});
</script>

<style scoped>
.mockup-surface { position: fixed; inset: 0; z-index: 200; display: flex; flex-direction: column; background: #f5f6f8; }
.mockup-switcher { display: flex; align-items: center; justify-content: space-between; gap: 18px; min-height: 58px; padding: 10px 18px; border-bottom: 1px solid #e5e7eb; background: #fff; }
.mockup-switcher strong, .mockup-switcher span { display: block; }.mockup-switcher span { margin-top: 2px; color: #9ca3af; font-size: 12px; }
.mockup-tabs { display: flex; gap: 4px; overflow-x: auto; }.mockup-tabs button { flex: 0 0 auto; padding: 7px 12px; border: 0; border-radius: 6px; background: transparent; color: #6b7280; cursor: pointer; }.mockup-tabs button.active { background: #e8f1ff; color: #2b6fff; font-weight: 600; }
.mockup-frame { width: 100%; flex: 1; border: 0; background: #f5f6f8; }
@media (max-width: 760px) { .mockup-switcher { align-items: flex-start; flex-direction: column; }.mockup-tabs { width: 100%; } }
</style>
