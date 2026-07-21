  RAG + 知识库完善：你接下来要补的新技术

这份内容只讨论一件事：
先把你当前项目里的 RAG 和知识库做扎实，不考虑 Agent。

结合你现在的代码基础：
- 已有文档上传、解析、切块、embedding、检索、rerank、RAG 回答
- 已有普通 RAG 和 LangChain Native RAG 两条链路
- 已有 run / step trace，方便继续做效果排查

所以你现在不是从 0 学 RAG，而是进入“RAG 工程化深化阶段”。


一、你现在最需要补的新技术，不是 Agent，而是这 8 类

1. 文档解析增强
你现在已经支持：
txt / md / pdf / docx / xlsx / xls / pptx

但下一步要补的是：
- PDF 复杂版面解析
- 表格抽取
- 扫描件 OCR
- 标题层级提取
- 图片内文字提取
- 重复页眉页脚清洗

建议学习关键词：
OCR
layout parsing
table extraction
unstructured document parsing

对你项目的作用：
知识库效果上限，首先取决于文档是不是被“正确读懂”。


2. 更高级的 Chunking
你现在已经有：
- 基于 page / section 的 chunking
- chunk_size / overlap

下一步建议补：
- 语义分块
- 标题感知分块
- 表格单独分块
- parent-child chunk
- small-to-big retrieval
- 按文件类型使用不同 chunk 策略

建议学习关键词：
semantic chunking
hierarchical chunking
parent document retriever
context-preserving chunking

对你项目的作用：
chunk 切得好不好，会直接决定召回质量和引用可信度。


3. Hybrid Retrieval
你现在已经有：
- embedding 检索
- keyword overlap
- phrase overlap
- 手写 rerank

下一步建议系统化补齐：
- BM25
- hybrid search
- metadata filter
- document-level boost
- title/section boost
- query rewrite

建议学习关键词：
BM25
hybrid retrieval
metadata filtering
query expansion
query rewrite

对你项目的作用：
让“检索命中”更稳定，不只依赖向量相似度。


4. 真正的 Rerank
你现在的 rerank 更像规则融合，已经比纯向量好了。

下一步建议学习：
- cross-encoder reranker
- bge-reranker
- jina reranker
- rerank score fusion

建议学习关键词：
cross-encoder reranking
reranker model
score fusion

对你项目的作用：
把“看起来相关”的 chunk，进一步筛成“真正适合回答问题”的 chunk。


5. 向量存储与索引
你现在更偏“自己把 embedding 存库，再手动算相似度”。

这对学习很有帮助，但下一步最好补：
- FAISS
- pgvector
- Milvus
- Chroma
- ANN 检索
- 索引构建与更新

建议学习关键词：
vector database
FAISS
pgvector
approximate nearest neighbor
ANN index

对你项目的作用：
数据量一上来，检索速度和可扩展性会成为问题。


6. RAG 评测
这是你后面非常值得补的一块。

建议学习：
- Recall@K
- MRR
- NDCG
- answer faithfulness
- context precision
- citation correctness
- 人工评测集设计

建议学习关键词：
RAG evaluation
Recall@K
MRR
NDCG
faithfulness
groundedness

对你项目的作用：
不是“感觉效果变好了”，而是你能证明它变好了。


7. Prompt 与回答约束
你现在已经有 strict_mode 和 citation fallback。

下一步建议补：
- grounded answer prompt
- refusal strategy
- citation formatting policy
- no-answer strategy
- prompt versioning

建议学习关键词：
grounded generation
prompt versioning
answer guardrails
citation grounding

对你项目的作用：
让模型少编、少飘、少“看起来对其实不可靠”。


8. 知识库工程化能力
这部分最容易被忽略，但很重要。

建议学习：
- 异步任务队列
- 重试机制
- 大文件处理
- 去重与增量更新
- 文档状态机
- 失败恢复
- 重新切块 / 重新 embedding

建议学习关键词：
background jobs
retry strategy
incremental indexing
deduplication
document pipeline

对你项目的作用：
让知识库从“能导入一次”升级成“能长期维护”。


二、按优先级，你最该先学什么

第一优先级：马上提升效果
1. 高级 Chunking
2. Hybrid Retrieval
3. 更强的 Rerank
4. 回答约束和引用可信度

第二优先级：让系统更像正式项目
1. 向量索引 / 向量库
2. 文档解析增强
3. 异步导入与失败恢复

第三优先级：让项目具备可验证性
1. RAG 评测
2. Prompt version 管理
3. 检索参数对比实验


三、最适合你当前代码的学习顺序

第 1 阶段：把现有链路吃透
重点读这些文件：
- core/service/document_parser.py
- core/service/chunking.py
- core/service/retrieval.py
- core/service/rag.py
- api/routes/knowledge.py
- api/routes/rag.py

你要能回答：
- 文档在哪一步变成统一文本？
- chunk 在哪一步生成？
- embedding 在哪一步写入数据库？
- 检索和 rerank 的边界在哪里？
- strict_mode 真正约束了什么？


第 2 阶段：补检索质量
建议学习内容：
- BM25 原理
- hybrid retrieval
- query rewrite
- metadata filter
- rerank model

目标结果：
让“问得稍微绕一点也能命中”。


第 3 阶段：补文档理解能力
建议学习内容：
- OCR 基础
- PDF / 表格解析
- 标题层级提取
- 表格 chunking

目标结果：
让知识库不只会处理“干净文本”，也能处理真实办公文档。


第 4 阶段：补评测
建议学习内容：
- 构建 20 到 50 条固定测试问题
- 标注期望命中文档
- 记录 top_k 命中情况
- 评估回答是否忠于上下文

目标结果：
以后每次改 chunking、改 rerank、改 prompt，都能看出是不是变好。


四、你现在最值得掌握的技术名词

这一批技术词，最适合出现在你的学习和求职表达里：
- document parsing
- semantic chunking
- hierarchical chunking
- hybrid retrieval
- BM25
- reranking
- vector database
- metadata filtering
- grounded generation
- citation grounding
- RAG evaluation
- Recall@K
- faithfulness
- prompt versioning


五、结合你项目，推荐你下一步的实际落点

先做这 5 个方向，收益最大：

1. 给不同文档类型配置不同 chunk 策略
比如：
- pdf 偏小块
- docx 按标题块
- xlsx 按 sheet 或表格块

2. 在现有 retrieval 上加入真正的 BM25 或混合检索
让召回不再主要依赖 embedding。

3. 给引用做“更强约束”
至少做到：
- 回答里每条结论尽量能对应 chunk
- 没命中时明确说不知道

4. 给知识库导入流程补失败恢复
比如：
- 解析失败
- embedding 失败
- 某些 chunk 失败

5. 建一个最小 RAG 评测集
哪怕先只有 20 个问题，也非常值钱。


六、建议你按 4 周学习和落地

第 1 周：检索理解
目标：
看懂你现有 retrieval + rerank

学习重点：
- embedding retrieval
- BM25
- hybrid retrieval
- rerank


第 2 周：chunking 升级
目标：
把 chunk 从“能切”升级到“更适合召回”

学习重点：
- semantic chunking
- title-aware chunking
- parent-child chunk


第 3 周：知识库工程化
目标：
提升导入稳定性和可维护性

学习重点：
- 状态机
- 重试
- 增量更新
- 去重


第 4 周：评测闭环
目标：
建立一套自己的 RAG 评测方式

学习重点：
- Recall@K
- MRR
- faithfulness
- citation correctness


七、你现在不急着学什么

现在先不用把精力放到这些方向：
- Agent orchestration
- LangGraph
- function calling
- 多工具决策
- 长期记忆 Agent

原因很简单：
你当前项目最强的主线是知识库问答，不是 Agent。
先把 RAG 做深，面试和项目质量都会更扎实。


八、一句话结论

你接下来最该补的新技术，不是“怎么让模型更像 Agent”，而是：
怎么让知识库被更准确地解析、切块、检索、重排、引用和评测。

把这条线做深，你的项目会从“有 RAG 功能”升级成“有 RAG 工程能力”。
