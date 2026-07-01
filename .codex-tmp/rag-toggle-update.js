const fs = require('fs');

const convo = 'E:/02agent/frontend/src/features/chat/components/ConversationWorkspace.vue';
let s = fs.readFileSync(convo, 'utf8');
s = s.replace("import { computed, nextTick, ref } from 'vue';", "import { computed, nextTick, ref, watch } from 'vue';");
s = s.replace('const composerRef = ref(null);', 'const composerRef = ref(null);\nconst ragConfigCollapsed = ref(false);');
s = s.replace(
  'function formatScore(value) {',
  "watch(() => props.conversationMode, (mode) => {\n  if (mode === 'rag') {\n    ragConfigCollapsed.value = false;\n  }\n});\n\nfunction formatScore(value) {"
);
const panelStart = s.indexOf("            <div v-if=\"conversationMode === 'rag'\" class=\"rag-controls-panel\">");
const panelEnd = s.indexOf('          </a-card>', panelStart);
if (panelStart === -1 || panelEnd === -1) throw new Error('rag panel markers not found');
const newPanel = `            <div v-if="conversationMode === 'rag'" class="rag-controls-panel">
              <div class="rag-controls-head">
                <div>
                  <div class="rag-control-title">知识库配置</div>
                  <div class="rag-controls-copy">点击右侧按钮可收起或展开文档范围、strict_mode 和 top_k。</div>
                </div>
                <a-button size="small" @click="ragConfigCollapsed = !ragConfigCollapsed">
                  {{ ragConfigCollapsed ? '展开配置' : '收起配置' }}
                </a-button>
              </div>

              <div v-if="!ragConfigCollapsed" class="rag-control-grid">
                <div class="rag-control-card">
                  <div class="rag-control-title">文档范围</div>
                  <a-radio-group
                    :value="ragScopeType"
                    button-style="solid"
                    size="small"
                    @update:value="$emit('update:rag-scope-type', $event)"
                  >
                    <a-radio-button value="all">全部文档</a-radio-button>
                    <a-radio-button value="selected" :disabled="!knowledgeDocumentOptions.length">指定文档</a-radio-button>
                  </a-radio-group>
                  <a-select
                    v-if="ragScopeType === 'selected'"
                    class="rag-doc-select"
                    mode="multiple"
                    :value="ragDocumentIds"
                    :options="knowledgeDocumentOptions"
                    :disabled="!knowledgeDocumentOptions.length"
                    placeholder="选择要参与问答的文档"
                    @update:value="$emit('update:rag-document-ids', $event)"
                  />
                  <div v-if="activeScopedDocuments.length" class="scope-chip-list">
                    <span v-for="item in activeScopedDocuments" :key="item.id" class="scope-chip">{{ item.name }}</span>
                  </div>
                </div>

                <div class="rag-control-card small-card">
                  <div class="rag-control-title">strict_mode</div>
                  <a-switch
                    :checked="ragStrictMode"
                    checked-children="严格"
                    un-checked-children="宽松"
                    @update:checked="$emit('update:rag-strict-mode', $event)"
                  />
                  <div class="rag-control-copy">
                    严格模式下，无相关知识时不会自由发挥。
                  </div>
                </div>

                <div class="rag-control-card small-card">
                  <div class="rag-control-title">top_k</div>
                  <a-input-number
                    :value="ragTopK"
                    :min="1"
                    :max="20"
                    :step="1"
                    class="rag-topk-input"
                    @update:value="$emit('update:rag-top-k', Number($event) || 5)"
                  />
                  <div class="rag-control-copy">
                    控制最终返回给回答链路的知识块数量。
                  </div>
                </div>
              </div>

              <div v-else class="rag-controls-collapsed">
                已隐藏知识库配置。点击“展开配置”继续设置文档范围、strict_mode 和 top_k。
              </div>
            </div>`;
s = s.slice(0, panelStart) + newPanel + s.slice(panelEnd);
fs.writeFileSync(convo, s, 'utf8');

const styles = 'E:/02agent/frontend/src/styles.css';
let css = fs.readFileSync(styles, 'utf8');
css = css.replace(
  '.rag-controls-panel {\n  display: grid;\n  gap: 12px;\n  margin-bottom: 12px;\n}',
  '.rag-controls-panel {\n  display: grid;\n  gap: 12px;\n  margin-bottom: 12px;\n}\n.rag-controls-head {\n  display: flex;\n  justify-content: space-between;\n  align-items: flex-start;\n  gap: 12px;\n}\n.rag-controls-copy {\n  margin-top: 4px;\n  color: var(--text-soft);\n  font-size: 12px;\n  line-height: 1.6;\n}\n.rag-controls-collapsed {\n  padding: 14px 16px;\n  border-radius: 16px;\n  background: rgba(22, 119, 255, 0.05);\n  color: var(--text-soft);\n  border: 1px dashed rgba(22, 119, 255, 0.18);\n  font-size: 13px;\n  line-height: 1.7;\n}'
);
fs.writeFileSync(styles, css, 'utf8');
