# Query Rewrite与关系理解升级任务规划

## 一、任务背景

当前项目已经完成了一部分“口语化显式问法增强”能力，能够在一些典型中文口语问法中抽取焦点词，并在 recall 与 rerank 阶段利用这些信号提升命中率。

但如果要继续向更接近市面产品的检索理解能力升级，还需要从“只做焦点词增强”继续演进到：

- 更强的 query rewrite
- 更复杂的关系理解
- 更自然语言化的检索改写能力

这意味着后续优化重点不再只是“从原句里多抽几个词”，而是要把用户问题先理解成结构，再把结构转成更适合检索系统使用的多个 query form。

---

## 二、本阶段总目标

把当前检索链路从：

`原始 query -> focus term -> recall / rerank`

升级为：

`原始 query -> query understanding -> query rewrite -> hybrid recall -> rerank`

本阶段的核心目标有三项：

1. 让系统更稳定地理解“谁和谁是什么关系”
2. 让系统能把自然语言问法改写成更像 FAQ / 标准问法 / 文档标题的检索问法
3. 让 recall、phrase match、rerank 共同利用 rewrite 结果，而不是只靠原始问题

---

## 三、本阶段要解决的核心问题

### 1. 现有 query understanding 还偏“词项级”

当前系统已经能抽取部分焦点词，但还不够稳定地区分：

- 哪些词是实体
- 哪些词是关系
- 哪些词只是口语填充
- 哪些词是中介平台或桥接关系

例如：

`我家里有小爱同学，不知道可以控扫地机器人吗`

当前更容易抽到：

- `小爱同学`
- `扫地机器人`

但还没有真正稳定形成：

- `小爱同学 -> 控制 -> 扫地机器人`

### 2. 现有 recall form 还不够“标准问法化”

现在的 recall form 主要还是：

- 原始 query
- 锚点后的 focused tail
- focus term

这对一些显式问法已经有效，但对更自然、更自由的中文表达仍然不够。

例如同一个问题，更适合命中文档的标准写法可能是：

- `小爱同学控制扫地机器人`
- `扫地机器人是否支持小爱同学控制`

### 3. recall 与 rerank 还没有真正共享“关系级 rewrite”

如果 rewrite 只停留在分析层，或者只在单一阶段生效，那么收益会比较有限。

后续应让以下几层共同利用 rewrite：

- coarse recall
- phrase overlap
- rerank
- direct grounded answer

---

## 四、本阶段设计目标

本阶段希望补齐一条更完整的检索理解链路：

### 1. Query Understanding

把自然语言问题分析为统一结构，包括：

- `question_type`
- `relation`
- `entities`
- `bridge`
- `focus_terms`

### 2. Query Rewrite

基于上面的结构，生成多条 rewrite form，包括：

- 原始 query
- 标准关系问法
- 倒装关系问法
- 中介平台问法
- 实体短语
- focus term 兜底问法

### 3. Recall / Phrase / Rerank 共用 Rewrite

让 rewrite 不只参与 recall，还参与：

- phrase overlap score
- rerank score
- grounded answer evidence match

### 4. 保持可控性

这一轮仍然以规则增强为主，不直接引入额外模型，保证：

- 改造范围可控
- 易于调试
- 易于回归测试
- 便于后续继续升级到 LLM rewrite 或轻量模型 rewrite

---

## 五、实施范围

本阶段优先修改以下文件：

- `core/service/rag_grounding.py`
- `core/service/retrieval.py`
- `test/test_retrieval.py`

本阶段暂时不修改：

- `core/service/vector_index.py`
- FAISS 索引逻辑
- embedding 模型
- 数据库 schema
- API 路由
- chunking 策略

原因是这一轮属于 query understanding 与 retrieval rewrite 升级，不属于底层索引或数据结构升级。

---

## 六、分阶段任务规划

### 阶段 1：现状梳理与回归基线确认

目标：

- 先把现有口语化增强能力的边界看清楚
- 明确哪些能力已经有，哪些能力还缺
- 建立后续改造的测试基线

具体任务：

1. 梳理当前已有能力
   - `extract_question_focus_terms(...)`
   - `build_recall_query_forms(...)`
   - `phrase_overlap_score(...)`
   - `rerank_chunks(...)`
2. 总结当前缺口
   - 缺少关系级结构化理解
   - 缺少标准问法 rewrite
   - 缺少 recall / rerank 共享 rewrite
3. 补一组基线测试样例
   - 口语 yes/no 问法
   - 控制关系问法
   - 连接关系问法
   - 中介平台问法
   - 更自然长句问法

阶段产出：

- 当前能力与缺口说明
- 一组后续回归测试基线

---

### 阶段 2：升级 Query Understanding

目标：

- 从“抽几个焦点词”升级到“理解问题结构”

具体任务：

1. 新增统一结构
   - 增加 `QueryRewritePlan`
2. 增加关系识别能力
   - 识别 `支持 / 兼容 / 控制 / 连接 / 使用`
   - 统一 canonical relation
3. 增加实体抽取能力
   - 从现有 focus term 基础上进一步清洗
   - 过滤泛词
4. 增加 bridge 抽取能力
   - 识别“通过 X 控制 Y”里的 `X`
5. 增加总分析入口
   - `analyze_query_rewrite_plan(...)`

重点样例：

- `我家里有小爱同学，不知道可以控扫地机器人吗`
- `扫地机器人能不能通过米家让小爱同学控制`
- `这个设备能不能连接 HomeKit`

阶段产出：

- 结构化 query understanding 能力

验收标准：

- 能稳定得到 `question_type + relation + entities + bridge`

---

### 阶段 3：升级 Query Rewrite

目标：

- 让系统把自然语言问法转成更像知识库标准问题的检索问法

具体任务：

1. 新增 rewrite 主函数
   - `build_question_rewrite_forms(...)`
2. 按层生成 rewrite
   - 原始 query
   - 结构化标准问法
   - 倒装关系问法
   - bridge 问法
   - 实体短语
   - focus term 兜底
3. 增加 rewrite 质量控制
   - 归一化
   - 去重
   - 长度限制
   - 泛词过滤
   - 规则上限控制

典型目标输出：

对于：

`我家里有小爱同学，不知道可以控扫地机器人吗`

希望得到类似：

- `小爱同学控制扫地机器人`
- `小爱同学能否控制扫地机器人`
- `扫地机器人是否支持小爱同学控制`
- `扫地机器人支持小爱同学语音控制`

阶段产出：

- 更自然、更标准的 recall rewrite forms

验收标准：

- 能稳定生成 2 到 5 条高质量 rewrite
- 不产生明显重复和明显错误改写

---

### 阶段 4：把 Rewrite 接入 Recall

目标：

- 让 recall 层真正利用 rewrite，而不是只保留在分析层

具体任务：

1. 改造 `build_recall_query_forms(...)`
   - 保留原始 query
   - 保留 focused tail
   - 接入 `build_question_rewrite_forms(...)`
   - 补 focus term
   - 最后补长 token
2. 控制 recall form 数量
   - 既要增强召回，又要避免噪音过大
3. 保持旧逻辑兼容
   - 避免已经修好的场景回归

阶段产出：

- 新版 recall query forms 生成逻辑

验收标准：

- 口语问法与标准问法都能更稳定命中同一类正确 chunk

---

### 阶段 5：把 Rewrite 接入 Phrase Match 与 Rerank

目标：

- 不只是 recall 命中，还要让排序真正体现“关系正确性”

具体任务：

1. 改造 `_phrase_query_forms(...)`
   - 不再只做尾部截断
   - 复用 recall rewrite 结果
2. 改造 `phrase_overlap_score(...)`
   - 对所有 query forms 计算并取 max
3. 保持现有 rerank 框架不变
   - 继续保留 `vector + keyword + phrase + evidence`
4. 重点增强关系正确性的区分
   - 实体对但关系错，分数不能过高
   - 实体和关系都对，分数应更明显领先

阶段产出：

- 基于 rewrite 的 phrase match 与 rerank 能力

验收标准：

- “支持小爱同学语音控制”的 chunk 要稳定排在“普通操作说明”前面

---

### 阶段 6：增强 Grounded Answer 的关系表达

目标：

- 让 yes/no 类直答不再只回答实体，而是回答关系

具体任务：

1. 新增关系短语拼接能力
   - `build_relation_focus_text(...)`
2. 改造 `evidence_match_score(...)`
   - 关系短语整体命中时提高置信度
3. 改造 `build_direct_grounded_answer(...)`
   - 优先使用关系短语生成 yes/no 答案

示例目标：

从：

- `支持小爱同学。`

升级到：

- `支持小爱同学控制扫地机器人。`

阶段产出：

- 更自然的 grounded direct answer

验收标准：

- yes/no 回答更自然，更符合真实问句语义

---

### 阶段 7：补齐测试与回归保护

目标：

- 为后续迭代建立稳定保护网

具体任务：

1. 增加结构化理解测试
2. 增加 rewrite 生成测试
3. 增加 recall form 测试
4. 增加 phrase overlap 测试
5. 增加 rerank 排序测试
6. 增加 grounded answer 测试

建议补充的测试名称：

- `test_analyze_query_rewrite_plan_extracts_relation_and_entities`
- `test_build_question_rewrite_forms_generates_standard_relation_queries`
- `test_build_recall_query_forms_adds_relation_rewrite_for_colloquial_control_question`
- `test_phrase_overlap_score_uses_relation_rewrite_for_natural_language_question`
- `test_rerank_chunks_prefers_relation_aware_rewrite_hit`
- `test_build_direct_grounded_answer_uses_relation_phrase_for_yes_no_answers`

阶段产出：

- 覆盖 query understanding 与 rewrite 的回归测试集

验收标准：

- 新能力通过测试
- 旧场景不退化

---

## 七、建议开发顺序

推荐按下面顺序推进：

1. 先做 `rag_grounding.py` 的结构化分析
2. 再做 `build_question_rewrite_forms(...)`
3. 再把 rewrite 接入 `retrieval.py`
4. 再调整 phrase / rerank / direct answer
5. 最后补测试并做回归验证

这样做的好处是：

- 风险最小
- 调试路径清晰
- 每一阶段都能单独验证收益

---

## 八、本阶段完成标志

这一轮完成后，项目的检索理解层应从：

- `原始 query + focus term`

升级为：

- `原始 query + 结构化理解 + 多条标准 rewrite + 关系驱动 recall / rerank`

具体表现应包括：

1. 更能理解中文自然问法中的实体和关系
2. 更能生成接近知识库标准表达的 query rewrite
3. 更能把“关系正确”的 chunk 排到前面
4. yes/no 回答更自然，不再只答实体名

---

## 九、后续可继续升级的方向

本阶段完成后，下一步还可以继续演进到：

### 1. 更复杂的多层关系理解

例如：

- `X 通过 Y 控制 Z`
- `Z 的哪个功能支持 X`
- `在什么条件下支持 X`

### 2. 长句压缩与主干抽取

适合处理更绕、更长、更自由的自然语言表达。

### 3. 轻量模型或 LLM Query Rewrite

在规则版稳定后，可继续探索：

- 小模型 query rewrite
- LLM 先改写再检索
- query classification + rewrite routing

### 4. 基于行为数据的 rewrite 优化

如果后续有点击、停留、命中反馈，可以进一步做：

- 高价值 rewrite 提权
- 低质量 rewrite 降权
- 热门问法自动沉淀成规则

---

## 十、一句话总结

这一阶段的核心不是“再多抽几个词”，而是：

`把用户自然语言问题先理解成关系结构，再把结构改写成更适合检索的标准问法，并让 recall 与 rerank 共同利用这些 rewrite。`
