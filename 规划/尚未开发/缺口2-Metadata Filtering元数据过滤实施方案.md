# 缺口2：Metadata Filtering 元数据过滤 —— 详细实施方案

> 对应文档：《检索与入库技术深化学习规划.md》缺口2
> 预计工作量：2~3 天
> 优先级：【第一周第2步】完成缺口7后立刻做这个

---

## 一、背景与当前痛点

现在的检索只能做到：
```python
# 现在的 hybrid_search 只能按 document_ids 过滤
document_ids: list[int] | None = None  # 仅支持"指定文档ID"
```

但真实用户需求是：
1. **时间过滤**：只搜最近 7 天上传的文档（HR 搜最新版制度）
2. **分类过滤**：只搜"产品手册"类，排除公告/制度（销售人员）
3. **文件类型过滤**：只搜 PDF，不搜 TXT/Markdown
4. **章节层级过滤**：只搜一级/二级标题，不要正文细节（要大纲不要细节）
5. **多标签过滤**：只搜打了"合规"标签的文档

这些需求的本质都是：**先按 metadata 做硬过滤，再做向量相似度软搜索**。

---

## 二、技术选型：3 种过滤方案的取舍

| 方案 | 原理 | 优点 | 缺点 | 推荐度 |
|-----|------|-----|------|--------|
| **A. 后置过滤（先搜再删）** | 先按向量搜出 300 条，再逐条判断 metadata 是否匹配，不匹配的扔掉 | 实现最简单，1 天搞定，FAISS 无侵入 | 如果 300 条里大部分都被过滤了，Recall 会损失 | ⭐⭐⭐⭐⭐ **先实现这个** |
| B. 前置过滤（FAISS IDSelector） | 把所有命中的 chunk_id 提前告诉 FAISS，只在指定 ID 范围内做 ANN | 精度无损失，理论上最快 | 实现复杂，IVF 系列索引支持不好，过滤条件变化时要重新构造 IDSelector 数组 | ⭐⭐ |
| C. 双过滤结合 | 先用 B 方案缩小到候选集合，再用 A 方案精细化过滤 | 兼顾精度和速度 | 代码量最大，维护成本高 | ⭐⭐⭐（等方案 A 遇到瓶颈再升级） |

**结论：** 先上 **方案 A（后置过滤）**，满足 90% 场景，代码改动量最小。真遇到"300条被过滤空了"的极端场景，再升级方案 B。

---

## 三、分步实施方案

### 步骤 1：数据库字段扩展（0.5 天）

#### 1.1 KnowledgeChunks 表加 metadata 字段（JSON）

在 `core/db/models.py` 的 `KnowledgeChunks` 模型中增加：

```python
class KnowledgeChunks(Base, TimestampMixin):
    # ... 原来的字段 ...

    # ========== 【新增】元数据过滤字段 ==========
    # JSON 字段，存储所有可用于过滤的维度
    # 统一 JSON 好处：加新维度不需要改表结构，直接塞 key 就行
    #
    # 示例数据（leaf chunk）：
    # {
    #   "upload_date": "2026-08-01",        # 文档上传日期（从 documents 继承）
    #   "doc_category": "product_manual",   # 文档分类（从 documents 继承）
    #   "file_type": "pdf",                 # 文件类型：pdf/docx/txt/md
    #   "section_level": 3,                 # 分块的标题层级：1=H1, 2=H2, 3=H3, 4=正文无标题
    #   "page_number": 15,                  # 【PDF专属】所在页码（用于UI跳转到源文件定位）
    #   "has_table": true,                  # 是否包含表格内容（过滤"只要表格数据"的场景）
    #   "file_name": "华为Mate60产品手册.pdf"  # 文件名（模糊匹配过滤）
    # }
    metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False, comment="分块元数据，用于检索时的metadata过滤")

    # ========== 【新增】便于 SQL 层快速查询的冗余字段 ==========
    # （JSON 字段做 WHERE 查询慢，冗余几个最常用的维度到普通列上）
    section_level: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, comment="分块所在层级，1=H1,2=H2,3=H3,4=正文")
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="所在页码（仅PDF/Docx有）")
```

#### 1.2 KnowledgeDocuments 表加 doc_category + tags 字段

```python
class KnowledgeDocuments(Base, TimestampMixin):
    # ... 原来的字段 ...

    # ========== 【新增】文档分类和标签 ==========
    # 枚举：product_manual（产品手册）/ regulation（制度规范）/ notice（公告通知）/ report（报告）/ other（其他）
    doc_category: Mapped[str] = mapped_column(String(50), default="other", nullable=False, index=True, comment="文档分类")
    # 多标签：["合规", "财务", "2024版", "必读"]
    # 用 JSON 数组存，UI 可加标签云
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False, comment="文档自定义标签，用于过滤和检索增强")
```

#### 1.3 写 Alembic 迁移脚本

```bash
# 生成迁移脚本（会自动检测字段变化）
alembic revision --autogenerate -m "add metadata_filter_fields"

# 执行迁移
alembic upgrade head
```

---

### 步骤 2：分块时自动填充 metadata（0.5 天）

在 `core/service/hierarchical_chunking.py` 的分块流程中，把 metadata 一路传进去：

```python
# 在 chunk_document() 函数签名里新增 metadata 参数
def chunk_document(
    self,
    document_id: int,
    raw_text: str,
    file_type: str,                # 【新增】
    file_name: str,                # 【新增】
    upload_date: str,              # 【新增】
    doc_category: str = "other",   # 【新增】
    use_semantic_chunking: bool = False,
) -> tuple[list[str], list[str], list[dict]]:
    # ... 省略 ...
    
    # 把全局 document 的 metadata 传给递归分块函数
    document_level_meta = {
        "upload_date": upload_date,
        "doc_category": doc_category,
        "file_type": file_type,
        "file_name": file_name,
    }
    
    # 在 build_hierarchical_chunks 的递归过程中，每个 leaf chunk 生成时
    # 除了 chunk 自己的 section_level / page_number / has_table
    # 还要把 document_level_meta 合并进去
```

每个 leaf chunk 的 `metadata_dict` 组装逻辑（伪代码）：

```python
def _make_leaf_chunk_metadata(self, document_level_meta, chunk_node):
    """组装单个 leaf chunk 的 metadata JSON"""
    chunk_meta = {
        **document_level_meta,                            # 文档级的公共字段
        "section_level": chunk_node.section_level,         # 该chunk的标题层级
        "page_number": getattr(chunk_node, "page_number", None),  # PDF解析时带的页码
        "has_table": chunk_node.text.count("|") > 5,       # 简单判断：含|超过5个=大概率有表格
        "heading_path": chunk_node.heading_path,           # 标题路径："H1产品介绍/H2参数/H3屏幕尺寸"
    }
    return chunk_meta
```

写入数据库时（`knowledge_service.py:512-550` 左右），把 metadata 一并写入：

```python
chunk = KnowledgeChunks(
    document_id=doc.id,
    chunk_index=i,
    content=content,
    heading_path=title_path,
    section_level=section_level,   # 【新增】冗余列
    page_number=page_number,       # 【新增】冗余列
    metadata=metadata_dict,        # 【新增】JSON 全量字段
    role=role_flag,
)
```

---

### 步骤 3：检索接口加 metadata_filter 参数（1 天）

#### 3.1 `vector_index.py` 和 `retrieval.py` 增加过滤逻辑

**关键设计**：`SearchResultChunk` 里已经有 `document_id` 字段了，但缺少 `metadata`，所以第一步先在 SearchResultChunk 里加 metadata 字段：

```python
@dataclass
class SearchResultChunk:
    chunk_id: int
    document_id: int
    score: float
    content: str
    heading_path: str | None = None
    # 【新增】检索结果带完整 metadata，上层调用方和过滤函数都能用
    metadata: dict | None = None
```

然后在 `retrieval.py:433 hybrid_search()` 函数签名加参数：

```python
def hybrid_search(
    db: Session,
    user_id: int,
    query_text: str,
    *,
    top_k: int = 5,
    # ========== 【新增】元数据过滤参数 ==========
    # A. 粗粒度：直接指定文档ID（原来就有的功能）
    document_ids: list[int] | None = None,
    
    # B. 细粒度：通用 metadata 过滤字典（推荐用这个，扩展性最好）
    #    语法规则（简单够用版，复杂场景交给专业向量库）：
    #    {
    #      # === 值匹配（等于）===
    #      "doc_category": "product_manual",
    #      "file_type": "pdf",
    #      "section_level": 2,
    #
    #      # === 列表匹配（包含任意一个就算命中，IN 语义）===
    #      "doc_category__in": ["product_manual", "regulation"],
    #
    #      # === 范围匹配（仅支持日期和数字）===
    #      "upload_date__gte": "2026-08-01",   # >= 8月1日
    #      "upload_date__lte": "2026-08-31",   # <= 8月31日
    #      "page_number__gte": 10,
    #      "page_number__lte": 50,
    #
    #      # === 标签匹配（数组包含任意一个）===
    #      "_tags__any": ["合规", "财务"],     # 在 documents.tags 里命中任意一个
    #
    #      # === 章节层级过滤（层级 <= 指定值）===
    #      "section_level__lte": 2,            # 只要 H1 + H2，不要 H3/正文
    #    }
    metadata_filter: dict | None = None,
    
    # C. 快捷参数（把最常用的几个单独抽出来，调用方不用写字典）
    upload_date_from: str | None = None,   # 快捷：upload_date__gte
    upload_date_to: str | None = None,     # 快捷：upload_date__lte
    doc_category_in: list[str] | None = None,  # 快捷：doc_category__in
    file_type_in: list[str] | None = None,     # 快捷：file_type__in
    section_level_lte: int | None = None,      # 快捷：section_level__lte
) -> list[SearchResultChunk]:
    pass
```

#### 3.2 后置过滤实现（核心函数）

在检索 pipeline 的合适位置（**粗排之后，rerank 之前**）插入过滤：

```python
def _apply_metadata_filter(
    chunks: list[SearchResultChunk],
    metadata_filter: dict | None,
    *,
    # 快捷参数合并器：把快捷参数合并到 metadata_filter 里
    upload_date_from: str | None = None,
    upload_date_to: str | None = None,
    doc_category_in: list[str] | None = None,
    file_type_in: list[str] | None = None,
    section_level_lte: int | None = None,
    document_tags_map: dict[int, list[str]] | None = None,  # document_id -> tags 映射
) -> list[SearchResultChunk]:
    """
    后置 metadata 过滤（先向量搜出 300 条，再逐条判断是否保留）

    Args:
        chunks: 向量搜索返回的候选集（建议 200~300 条，留足被过滤掉的余量）
        metadata_filter: 通用过滤字典（上面注释里的 __in/__gte/__lte 语法）
        upload_date_from 等：快捷参数（如果都传，会先合并到 metadata_filter）
        document_tags_map: 文档 tags 映射（tags 在 documents 表，不在 chunks 表）

    Returns:
        过滤后的 chunks 列表（顺序保持不变，因为已经按相似度排好序了）
    """
    if not chunks:
        return chunks

    # --- Step 1: 快捷参数 → 合并进 metadata_filter（统一一套判断逻辑）---
    merged_filter = dict(metadata_filter or {})
    if upload_date_from:
        merged_filter["upload_date__gte"] = upload_date_from
    if upload_date_to:
        merged_filter["upload_date__lte"] = upload_date_to
    if doc_category_in:
        merged_filter["doc_category__in"] = doc_category_in
    if file_type_in:
        merged_filter["file_type__in"] = file_type_in
    if section_level_lte is not None:
        merged_filter["section_level__lte"] = section_level_lte

    # 空过滤：直接返回
    if not merged_filter and not document_tags_map:
        return chunks

    # --- Step 2: 拆分 tags 过滤（特殊处理，因为 tags 在 documents 上）---
    tags_any = None
    if "_tags__any" in merged_filter:
        tags_any = set(merged_filter.pop("_tags__any"))

    # --- Step 3: 逐条判断，保留全部命中的 chunk ---
    kept = []
    for chunk in chunks:
        chunk_meta = chunk.metadata or {}

        # tags 过滤（单独判断）
        if tags_any is not None:
            doc_tags = document_tags_map.get(chunk.document_id) or []
            if not tags_any.intersection(doc_tags):
                continue  # 没命中任何一个 tag，跳过

        # 其他字段：逐条判断 merged_filter 里的所有条件
        all_pass = True
        for key, expected in merged_filter.items():
            # key 可能是 "upload_date" / "upload_date__gte" / "doc_category__in"
            field, _, op = key.partition("__")
            op = op or "eq"  # 默认 = 等值匹配

            actual = chunk_meta.get(field)
            if actual is None:
                # 字段不存在直接不通过（除非有特殊逻辑需要默认通过，看业务）
                all_pass = False
                break

            # 根据 operator 做比较
            if op == "eq" and actual != expected:
                all_pass = False
                break
            elif op == "in" and actual not in expected:
                all_pass = False
                break
            elif op == "gte" and actual < expected:
                all_pass = False
                break
            elif op == "lte" and actual > expected:
                all_pass = False
                break
            elif op == "contains" and expected not in str(actual):
                all_pass = False
                break

        if all_pass:
            kept.append(chunk)

    return kept
```

---

### 步骤 4：API 层暴露过滤能力（0.5 天）

在 `api/routes/rag_langchain_native.py` 的问答接口里，把过滤参数透传下去：

```python
@router.post("/knowledge/chat-with-documents", summary="【RAG原生】知识问答")
async def chat_with_documents(
    req: schemas.ChatWithKnowledgeRequest,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_active_user),
):
    # ... 前面的代码不变 ...

    # ========== 【新增】解析请求里的过滤参数 ==========
    metadata_filter = req.metadata_filter  # 请求体 schema 里要先加这个字段
    upload_date_from = req.upload_date_from
    upload_date_to = req.upload_date_to
    doc_category_in = req.doc_category_in
    file_type_in = req.file_type_in
    section_level_lte = req.section_level_lte

    # 调用检索时传进去
    chunks = retrieval.hybrid_search(
        db,
        current_user.id,
        query,
        top_k=5,
        document_ids=req.document_ids,
        # 以下 6 个是新增
        metadata_filter=metadata_filter,
        upload_date_from=upload_date_from,
        upload_date_to=upload_date_to,
        doc_category_in=doc_category_in,
        file_type_in=file_type_in,
        section_level_lte=section_level_lte,
    )
    # ... 后面不变 ...
```

对应的 `schemas.py` 请求体也要加字段：

```python
class ChatWithKnowledgeRequest(BaseModel):
    # ... 原来的 query / document_ids / session_id / ...
    metadata_filter: dict | None = Field(None, description="通用元数据过滤字典，如 {\"doc_category\": \"product_manual\"}")
    upload_date_from: str | None = Field(None, description="文档上传起始日期（含），格式 YYYY-MM-DD")
    upload_date_to: str | None = Field(None, description="文档上传截止日期（含），格式 YYYY-MM-DD")
    doc_category_in: list[str] | None = Field(None, description="文档分类列表，命中任意一个即可")
    file_type_in: list[str] | None = Field(None, description="文件类型列表：pdf/docx/txt/md")
    section_level_lte: int | None = Field(None, description="章节层级上限，2 表示只要 H1+H2")
```

---

## 四、集成测试验证清单

| 测试场景 | 输入 | 期望输出 |
|---------|------|---------|
| 等值匹配 | `metadata_filter={"file_type": "pdf"}` | 返回的所有 chunk.metadata.file_type 都是 "pdf" |
| 日期范围 | `upload_date_from="2026-08-01"`, `upload_date_to="2026-08-15"` | chunk 上传日期都在 8月1日~15日之间 |
| 多值 IN | `doc_category_in=["product_manual", "regulation"]` | chunk 的分类都属于这两个 |
| 层级上限 | `section_level_lte=2` | chunk.section_level <= 2（没有 H3 或正文） |
| 组合过滤 | 日期范围 + PDF + 分类=手册 | 三个条件同时满足 |
| 全被过滤 | 用户只有 10 份 2025 年的文档，却搜 `upload_date_from=2027` | 返回空列表，但不报错 |
| 旧数据兼容 | 老 chunk.metadata 是空 dict `{}` | 会被所有过滤条件过滤掉（正常，因为没有信息），重建索引后正常 |

---

## 五、关键注意点

1. **向后兼容**：旧的 chunk.metadata 是默认空 dict，所以过滤时会被"判不通过"。建议做个一次性数据迁移脚本，把历史 documents 的字段回填到 chunks.metadata。
2. **候选集大小**：原来 `candidate_top_n=30`，开启 metadata 过滤后建议改成 200~300 打底，否则"30条被过滤剩2条"会严重影响 Recall。
3. **tags 的位置**：tags 在 documents 表（一个文档打几个标签），不在 chunks 表，所以过滤时需要先批量查 `{document_id: tags}` 的映射，不要循环每条 chunk 单独查数据库（N+1 问题）。
4. **分页/数量保证**：用户传 `top_k=10` 但过滤后只剩 3 条，这是正常的，不要为了"凑够10条"把被过滤掉的塞回去，要在 UI 上明确告诉用户"符合条件的只有 3 条"。