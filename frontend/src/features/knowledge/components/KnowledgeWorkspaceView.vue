<template>
  <div class="kb-app">
    <!-- 顶部导航栏 -->
    <header class="kb-topnav">
      <div class="kb-logo">
        <span class="kb-logo-mark">K</span>
        <span class="kb-logo-text">知识中枢</span>
      </div>
      <nav class="kb-nav-tabs">
        <button
          v-for="tab in topTabs"
          :key="tab.key"
          :class="['kb-nav-tab', { active: activeTopTab === tab.key }]"
          @click="activeTopTab = tab.key"
        >{{ tab.label }}</button>
      </nav>
      <div class="kb-topnav-right">
        <div class="kb-search-box" @click="currentPage = 'search'">
          <span>🔍</span>
          <span>搜索文档、知识库、成员…</span>
          <span class="kbd">⌘K</span>
        </div>
        <button class="kb-upload-btn" @click="openUpload">
          <span>📤</span> 上传
        </button>
        <button class="kb-icon-btn">?</button>
        <div class="kb-avatar">{{ userInitial }}</div>
      </div>
    </header>

    <div class="kb-body">
      <!-- 左侧边栏 -->
      <aside class="kb-sidebar">
        <!-- 我的空间 -->
        <div class="sb-section">
          <div class="sb-title">我的空间</div>
          <div :class="['sb-item', { active: currentPage === 'home' }]" @click="navigateTo('home')">
            <span class="ico">📁</span><span>团队知识库</span><span class="count">{{ docCount }}</span>
          </div>
        </div>

        <!-- 空间导航 -->
        <div class="sb-section">
          <div class="sb-title">空间导航</div>
          <div
            v-for="cat in categories"
            :key="cat.key"
            :class="['sb-item', { active: currentCategory === cat.key && ['home','detail'].includes(currentPage) }]"
            @click="selectCategory(cat.key)"
          >
            <span class="ico">{{ cat.icon }}</span><span>{{ cat.name }}</span>
            <span v-if="cat.count" class="count">{{ cat.count }}</span>
          </div>
        </div>

        <!-- 快捷入口 -->
        <div class="sb-section">
          <div class="sb-title">快捷入口</div>
          <div :class="['sb-item', { active: currentPage === 'recent' }]" @click="navigateTo('recent')">
            <span class="ico">🕒</span><span>最近更新</span>
          </div>
          <div :class="['sb-item', { active: currentPage === 'favorites' }]" @click="navigateTo('favorites')">
            <span class="ico">⭐</span><span>我的收藏</span><span class="count">{{ favorites.length }}</span>
          </div>
          <div :class="['sb-item', { active: currentPage === 'shared' }]" @click="navigateTo('shared')">
            <span class="ico">🔗</span><span>与我共享</span><span class="count">{{ sharedDocs.length }}</span>
          </div>
        </div>

        <!-- 空间设置 -->
        <div class="sb-section">
          <div class="sb-title">空间设置</div>
          <div :class="['sb-item', { active: currentPage === 'members' }]" @click="navigateTo('members')">
            <span class="ico">🔐</span><span>成员与权限</span>
          </div>
          <div :class="['sb-item', { active: currentPage === 'trash' }]" @click="navigateTo('trash')">
            <span class="ico">🗑️</span><span>回收站</span><span class="count">{{ trashDocs.length }}</span>
          </div>
        </div>

        <!-- 存储用量 -->
        <div class="usage-card">
          <div class="usage-label">本周知识库用量</div>
          <div class="usage-num">{{ stats.storageUsed }} / {{ storageLimit }}</div>
          <div class="usage-bar"><div class="usage-fill" :style="{ width: storagePercent + '%' }"></div></div>
        </div>
      </aside>

      <!-- 主内容区 -->
      <main class="kb-main">
        <!-- ========== 首页/文档列表 ========== -->
        <div v-if="currentPage === 'home'" class="kb-page">
          <div class="kb-breadcrumb">
            <a @click="navigateTo('home')">团队知识库</a>
            <span v-if="currentCategory" class="sep">/</span>
            <a v-if="currentCategory" @click="selectCategory(currentCategory)">{{ categoryName }}</a>
          </div>

          <div class="page-header-row">
            <div>
              <h2>{{ currentCategory ? categoryName : '全部文档' }}</h2>
              <p class="page-desc">{{ categoryDesc }}</p>
            </div>
            <div class="header-actions">
              <a-button type="primary" @click="showCreateModal = true">
                <template #icon>➕</template> 新建文档
              </a-button>
            </div>
          </div>

          <!-- 统计卡片 -->
          <div class="stat-row">
            <div class="stat-card" v-for="s in statCards" :key="s.label">
              <div class="sicon" :style="{ background: s.bg, color: s.color }">{{ s.icon }}</div>
              <div class="sinfo">
                <div class="slabel">{{ s.label }}</div>
                <div class="snum">{{ s.value }}</div>
                <div class="ssub" :class="{ up: s.up }">{{ s.sub }}</div>
              </div>
            </div>
          </div>

          <!-- 筛选和搜索 -->
          <div class="filter-bar">
            <input class="filter-search" v-model="docSearchKey" placeholder="🔍 搜索文档标题..." />
            <button
              v-for="f in filterChips"
              :key="f"
              :class="['filter-chip', { active: activeFilter === f }]"
              @click="activeFilter = f"
            >{{ f }}</button>
            <div class="filter-right">
              <a-select v-model="sortBy" size="small" style="width:120px">
                <a-select-option value="recent">最近更新</a-select-option>
                <a-select-option value="name">按名称</a-select-option>
                <a-select-option value="size">按大小</a-select-option>
              </a-select>
            </div>
          </div>

          <!-- 文档列表 -->
          <div class="doc-list">
            <div
              v-for="doc in filteredDocList"
              :key="doc.id"
              class="doc-card"
              @click="openDocument(doc)"
            >
              <div class="doc-card-icon" :style="{ background: doc.iconBg, color: doc.iconColor }">{{ doc.typeIcon }}</div>
              <div class="doc-card-info">
                <div class="doc-card-title">{{ doc.title }}</div>
                <div class="doc-card-desc">{{ doc.excerpt }}</div>
                <div class="doc-card-meta">
                  <span>📁 {{ doc.category }}</span>
                  <span class="dot">·</span>
                  <span>👤 {{ doc.author }}</span>
                  <span class="dot">·</span>
                  <span>🕒 {{ doc.updatedAt }}</span>
                  <span class="dot">·</span>
                  <span>👁️ {{ doc.views }} 次阅读</span>
                </div>
              </div>
              <div class="doc-card-right">
                <span :class="['tag', `tag-${doc.statusColor}`]">{{ doc.statusText }}</span>
                <div class="doc-card-actions">
                  <button class="action-dot" @click.stop="toggleDocMenu(doc.id)">···</button>
                </div>
              </div>
            </div>
          </div>

          <div v-if="!filteredDocList.length" class="empty-state">
            <a-empty description="暂无匹配的文档" />
          </div>
        </div>

        <!-- ========== 文档详情页 ========== -->
        <div v-else-if="currentPage === 'detail'" class="kb-page kb-detail-page">
          <div class="kb-breadcrumb">
            <a @click="navigateTo('home')">团队知识库</a><span class="sep">/</span>
            <a @click="selectCategory(currentDetailDoc?.category)">{{ categoryMap[currentDetailDoc?.category] || '分类' }}</a><span class="sep">/</span>
            <span>{{ currentDetailDoc?.title }}</span>
          </div>

          <div class="doc-header">
            <div class="doc-title-row">
              <h1>{{ currentDetailDoc?.title }}</h1>
              <div class="doc-actions">
                <button class="btn btn-ghost" :class="{ favorited: currentDetailDoc?.isFavorite }" @click="toggleFavorite(currentDetailDoc)">
                  ⭐ {{ currentDetailDoc?.isFavorite ? '已收藏' : '收藏' }}
                </button>
                <button class="btn btn-outline">🔗 分享</button>
                <button class="btn btn-outline">···</button>
                <button class="btn btn-primary" @click="editDocument(currentDetailDoc)">✏️ 编辑</button>
              </div>
            </div>
            <div class="doc-meta">
              <span :class="['tag', `tag-${currentDetailDoc?.statusColor}`]">● {{ currentDetailDoc?.statusText }}</span>
              <span class="meta-item">👤 {{ currentDetailDoc?.author }}</span>
              <span class="dot"></span>
              <span class="meta-item">🕒 {{ currentDetailDoc?.updatedAt }} 更新</span>
              <span class="dot"></span>
              <span class="meta-item">📝 {{ currentDetailDoc?.wordCount || '3,820' }} 字</span>
              <span class="dot"></span>
              <span class="meta-item">👁️ {{ currentDetailDoc?.views }} 次阅读</span>
              <span class="dot"></span>
              <span class="meta-item">💬 {{ currentDetailDoc?.comments?.length || 6 }} 条评论</span>
            </div>
          </div>

          <!-- AI摘要 -->
          <div class="ai-summary-box">
            <div class="ai-head">✨ AI 摘要 · 自动生成</div>
            <p>{{ currentDetailDoc?.aiSummary }}</p>
            <div class="ai-actions">
              <span class="ai-chip">📌 关注要点</span>
              <span class="ai-chip">💬 追问 AI</span>
              <span class="ai-chip">📋 复制摘要</span>
            </div>
          </div>

          <div class="doc-body">
            <div class="doc-content">
              <div v-html="currentDetailDoc?.content"></div>
            </div>

            <div class="doc-toc">
              <div class="toc-title">📑 本页目录</div>
              <ul class="toc-list">
                <li
                  v-for="(toc, idx) in currentDetailDoc?.toc"
                  :key="idx"
                  :class="[toc.sub ? 'sub' : '', { active: activeTocIdx === idx }]"
                  @click="scrollToToc(idx)"
                >{{ toc.text }}</li>
              </ul>
              <div style="margin-top:20px;padding-top:16px;border-top:1px solid var(--border-light)">
                <div class="toc-title">📎 关联文档</div>
                <ul class="toc-list">
                  <li v-for="(rel, i) in currentDetailDoc?.relatedDocs" :key="'r'+i" @click="openDocumentById(rel.id)">{{ rel.title }}</li>
                </ul>
              </div>
            </div>
          </div>

          <!-- 评论 -->
          <div class="comments">
            <div class="comments-header">💬 讨论 ({{ currentDetailDoc?.comments?.length || 0 }})</div>
            <div class="comment-input-wrap">
              <textarea class="comment-input" v-model="newComment" placeholder="💡 在此发表你的看法…" rows="2"></textarea>
              <a-button type="primary" size="small" @click="submitComment" :disabled="!newComment.trim()">发表评论</a-button>
            </div>
            <div class="comment-list">
              <div v-for="(c, idx) in currentDetailDoc?.comments" :key="idx" class="comment">
                <div class="avatar" :style="{ background: c.avatarBg }">{{ c.author.charAt(0) }}</div>
                <div class="comment-body">
                  <div><span class="comment-author">{{ c.author }}</span><span class="comment-time">{{ c.time }}</span></div>
                  <div class="comment-text">{{ c.text }}</div>
                  <div class="comment-actions"><span @click="likeComment(idx)">👍 {{ c.likes || 0 }}</span><span>回复</span></div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- ========== 新建文档 ========== -->
        <div v-else-if="currentPage === 'create'" class="kb-page kb-create-page">
          <div class="new-content-wrap">
            <div class="new-header">
              <h1>✨ 创建新内容</h1>
              <p>选择一种方式，快速开始你的知识沉淀</p>
            </div>
            <div class="new-tabs">
              <button
                v-for="t in createTabs"
                :key="t.key"
                :class="['new-tab', { active: createActiveTab === t.key }]"
                @click="createActiveTab = t.key"
              >{{ t.label }}</button>
            </div>

            <!-- 从模板创建 -->
            <div v-if="createActiveTab === 'template'">
              <div class="divider-label">选择模板 · {{ currentCategory ? categoryName : '全部' }}</div>
              <div class="template-grid">
                <div v-for="tpl in templates" :key="tpl.name" class="template-card" @click="createFromTemplate(tpl)">
                  <div class="icon" :style="{ background: tpl.bg, color: tpl.color }">{{ tpl.icon }}</div>
                  <div class="name">{{ tpl.name }}</div>
                  <div class="desc">{{ tpl.desc }}</div>
                </div>
              </div>
            </div>

            <!-- 空白文档 -->
            <div v-else-if="createActiveTab === 'blank'">
              <div class="blank-editor">
                <input class="blank-title" v-model="newDocTitle" placeholder="请输入文档标题…" />
                <textarea class="blank-content" v-model="newDocContent" placeholder="开始撰写内容…" rows="16"></textarea>
                <div class="blank-actions">
                  <a-button @click="navigateTo('home')">取消</a-button>
                  <a-button type="primary" @click="createBlankDoc">创建文档</a-button>
                </div>
              </div>
            </div>

            <!-- 上传文件 -->
            <div v-else-if="createActiveTab === 'upload'">
              <div class="divider-label">或者 · 上传已有文件</div>
              <div class="upload-zone" @click="triggerUpload" @dragover.prevent @drop.prevent="handleDrop">
                <div class="uicon">☁️</div>
                <h3>拖拽文件到此处，或点击选择</h3>
                <p>支持批量上传，单文件最大 100MB，自动解析为可检索文档</p>
                <a-button type="primary">📤 选择文件</a-button>
                <div class="formats">
                  <span v-for="f in uploadFormats" :key="f" class="fmt">{{ f }}</span>
                </div>
              </div>
              <input ref="fileInput" type="file" multiple style="display:none" @change="handleFileSelect" />
              <div v-if="uploadList.length" class="upload-list">
                <div v-for="(file, idx) in uploadList" :key="idx" class="upload-item">
                  <div class="file-icon" :style="{ background: file.color }">{{ file.ext }}</div>
                  <div class="file-info">
                    <div class="file-name">{{ file.name }}</div>
                    <div class="file-meta">{{ file.size }} · {{ file.status }}</div>
                    <div v-if="file.progress < 100" class="progress-bar"><div class="fill" :style="{ width: file.progress + '%' }"></div></div>
                    <a v-if="file.inLibrary" class="lib-link" @click="navigateTo('home')">✓ 已加入文档库 · 查看</a>
                  </div>
                  <span :class="['tag', `tag-${file.tagType}`]">{{ file.tagText }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- ========== 全局搜索 ========== -->
        <div v-else-if="currentPage === 'search'" class="kb-page kb-search-page">
          <div class="big-search">
            <span class="sicon">🔍</span>
            <input v-model="searchQuery" placeholder="输入关键词搜索文档…" @keyup.enter="doSearch" />
            <span v-if="searchQuery" class="clear" @click="searchQuery = ''">✕</span>
            <button class="search-btn" @click="doSearch">搜索</button>
          </div>
          <div v-if="hasSearched" class="search-result-info">
            找到约 <strong>{{ searchResults.length }}</strong> 条结果 · 耗时 0.23 秒
          </div>
          <div v-if="hasSearched" class="result-tabs">
            <button
              v-for="tab in resultTabs"
              :key="tab.key"
              :class="['result-tab', { active: searchResultTab === tab.key }]"
              @click="searchResultTab = tab.key"
            >{{ tab.label }}<span v-if="tab.count" class="num">{{ tab.count }}</span></button>
          </div>
          <div v-if="hasSearched && searchResults.length" class="result-list">
            <div v-for="r in searchResults" :key="r.id" class="result-item" @click="openDocument(r.doc)">
              <div class="ricon" :style="{ background: r.iconBg, color: r.iconColor }">{{ r.typeIcon }}</div>
              <div class="rbody">
                <div class="rtitle" v-html="highlightText(r.title)"></div>
                <div class="rexcerpt" v-html="highlightText(r.excerpt)"></div>
                <div class="rmeta">
                  <span>📁 {{ r.category }}</span><span class="dot">·</span>
                  <span>👤 {{ r.author }}</span><span class="dot">·</span>
                  <span>🕒 {{ r.date }}</span>
                </div>
              </div>
            </div>
          </div>
          <div v-else-if="hasSearched && !searchResults.length" class="empty-state">
            <a-empty description="没有找到匹配的结果" />
          </div>
          <div v-else class="search-welcome">
            <div class="sw-icon">🔍</div>
            <h3>在知识库中搜索</h3>
            <p>支持搜索文档标题、正文内容、评论等，输入关键词即可开始</p>
          </div>
        </div>

        <!-- ========== 我的收藏 ========== -->
        <div v-else-if="currentPage === 'favorites'" class="kb-page">
          <div class="page-title-row">
            <div>
              <h2>⭐ 我的收藏</h2>
              <p class="sub">你收藏了 <strong>{{ favorites.length }}</strong> 篇文档 · 按收藏时间排序</p>
            </div>
            <div class="right">
              <button :class="['view-toggle', { active: favViewMode === 'grid' }]" @click="favViewMode = 'grid'">卡片视图</button>
              <button :class="['view-toggle', { active: favViewMode === 'list' }]" @click="favViewMode = 'list'">列表视图</button>
            </div>
          </div>
          <div v-if="favViewMode === 'grid'" class="fav-grid">
            <div v-for="doc in favorites" :key="doc.id" class="fav-card" @click="openDocument(doc)">
              <div class="fstar">⭐</div>
              <div class="ficon" :style="{ background: doc.iconBg, color: doc.iconColor }">{{ doc.typeIcon }}</div>
              <div class="ftitle">{{ doc.title }}</div>
              <div class="fdesc">{{ doc.excerpt }}</div>
              <div class="fmeta">
                <span>📁 {{ doc.category }}</span><span class="dot">·</span>
                <span>👤 {{ doc.author }}</span><span class="dot">·</span>
                <span>⭐ {{ doc.favoritedAt }}</span>
              </div>
            </div>
          </div>
          <div v-else class="doc-list">
            <div v-for="doc in favorites" :key="doc.id" class="doc-card" @click="openDocument(doc)">
              <div class="doc-card-icon" :style="{ background: doc.iconBg, color: doc.iconColor }">{{ doc.typeIcon }}</div>
              <div class="doc-card-info">
                <div class="doc-card-title">{{ doc.title }}</div>
                <div class="doc-card-desc">{{ doc.excerpt }}</div>
                <div class="doc-card-meta">
                  <span>📁 {{ doc.category }}</span><span class="dot">·</span><span>👤 {{ doc.author }}</span><span class="dot">·</span><span>⭐ {{ doc.favoritedAt }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- ========== 与我共享 ========== -->
        <div v-else-if="currentPage === 'shared'" class="kb-page">
          <div class="page-title-row">
            <div>
              <h2>🔗 与我共享</h2>
              <p class="sub">别人直接分享或通过链接分享给你的文档 · 共 <strong>{{ sharedDocs.length }}</strong> 篇</p>
            </div>
            <div class="right">
              <button :class="['filter-chip', { active: shareFilter === 'all' }]" @click="shareFilter = 'all'">全部</button>
              <button :class="['filter-chip', { active: shareFilter === 'editable' }]" @click="shareFilter = 'editable'">可编辑 ({{ sharedDocs.filter(d => d.editable).length }})</button>
              <button :class="['filter-chip', { active: shareFilter === 'readonly' }]" @click="shareFilter = 'readonly'">只读 ({{ sharedDocs.filter(d => !d.editable).length }})</button>
            </div>
          </div>
          <div class="share-list">
            <div v-for="doc in filteredSharedDocs" :key="doc.id" class="share-item">
              <div class="sicon" :style="{ background: doc.iconBg, color: doc.iconColor }">{{ doc.typeIcon }}</div>
              <div class="sinfo">
                <div class="stitle">{{ doc.title }}</div>
                <div class="smeta">
                  <span class="from-user"><div class="avatar-sm" :style="{ background: doc.sharedByAvatar }">{{ doc.sharedBy.charAt(0) }}</div>{{ doc.sharedBy }}</span>
                  <span class="dot">·</span>
                  <span>{{ doc.sharedTime }}</span>
                  <span class="dot">·</span>
                  <span>📁 {{ doc.category }}</span>
                  <span class="dot">·</span>
                  <span :class="['tag', doc.editable ? 'tag-success' : 'tag-default']">{{ doc.editable ? '✏️ 可编辑' : '👁️ 只读' }}</span>
                </div>
              </div>
              <div class="sactions">
                <a-button size="small" @click="openSharedDoc(doc)">打开</a-button>
                <button class="btn btn-ghost">···</button>
              </div>
            </div>
          </div>
        </div>

        <!-- ========== 回收站 ========== -->
        <div v-else-if="currentPage === 'trash'" class="kb-page">
          <div class="page-title-row">
            <div>
              <h2>🗑️ 回收站</h2>
              <p class="sub">已删除的文档 · 可在 30 天内恢复</p>
            </div>
            <div class="right">
              <a-button size="small" danger>🗑️ 清空回收站</a-button>
            </div>
          </div>
          <div class="recycle-banner">
            <span class="ricon">⚠️</span>
            <span class="rtext">回收站中的文档将在 <strong>30 天后自动彻底删除</strong>。彻底删除后无法恢复。</span>
          </div>
          <div class="recycle-list">
            <div v-for="doc in trashDocs" :key="doc.id" class="recycle-item">
              <div class="ricon">📄</div>
              <div class="rinfo">
                <div class="rname">{{ doc.title }}</div>
                <div class="rmeta">
                  <span>📁 原位置：{{ doc.originalPath }}</span>
                  <span class="dot">·</span>
                  <span>🗑️ {{ doc.deletedBy }} 删除</span>
                  <span class="dot">·</span>
                  <span>🕒 {{ doc.deletedAt }}</span>
                  <span class="dot">·</span>
                  <span class="countdown" :class="{ danger: doc.daysLeft <= 5 }">⏰ {{ doc.daysLeft }} 天后自动删除</span>
                </div>
              </div>
              <div class="ractions">
                <a-button size="small" @click="restoreDoc(doc)">↩️ 恢复</a-button>
                <a-button size="small" danger>彻底删除</a-button>
              </div>
            </div>
          </div>
          <div v-if="!trashDocs.length" class="empty-state">
            <a-empty description="回收站是空的" />
          </div>
        </div>

        <!-- ========== 成员与权限 ========== -->
        <div v-else-if="currentPage === 'members'" class="kb-page">
          <div class="page-title-row">
            <div>
              <h2>成员与权限</h2>
              <p class="sub">管理团队成员、角色权限及邀请记录</p>
            </div>
            <div class="right">
              <a-button @click="showInviteModal = true" type="primary">➕ 邀请成员</a-button>
            </div>
          </div>

          <div class="stat-row">
            <div class="stat-card" v-for="m in memberStats" :key="m.label">
              <div class="sicon" :style="{ background: m.bg, color: m.color }">{{ m.icon }}</div>
              <div class="sinfo">
                <div class="slabel">{{ m.label }}</div>
                <div class="snum">{{ m.value }}</div>
                <div class="ssub">{{ m.sub }}</div>
              </div>
            </div>
          </div>

          <div class="section-card">
            <div class="tab-bar">
              <button v-for="t in memberTabs" :key="t.key" :class="['tab-item', { active: memberTab === t.key }]" @click="memberTab = t.key">
                {{ t.label }}<span v-if="t.count" class="num">{{ t.count }}</span>
              </button>
            </div>

            <!-- 成员列表 -->
            <div v-if="memberTab === 'list'" class="member-table-wrap">
              <table class="data-table">
                <thead>
                  <tr>
                    <th><div class="checkbox" :class="{ checked: allSelected }" @click="toggleSelectAll"></div></th>
                    <th>成员</th>
                    <th>角色</th>
                    <th>部门</th>
                    <th>加入时间</th>
                    <th>最后活跃</th>
                    <th>状态</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="m in members" :key="m.id">
                    <td><div class="checkbox" :class="{ checked: selectedMembers.includes(m.id) }" @click="toggleMemberSelect(m.id)"></div></td>
                    <td>
                      <div class="member-cell">
                        <div class="avatar" :style="{ background: m.avatarBg }">{{ m.name.charAt(0) }}</div>
                        <div class="info">
                          <div class="name">{{ m.name }} <span v-if="m.isMe" class="tag tag-primary" style="font-size:10px;padding:1px 6px">我</span></div>
                          <div class="email">{{ m.email }}</div>
                        </div>
                      </div>
                    </td>
                    <td><span :class="['role-badge', `role-${m.roleType}`]">{{ m.roleLabel }}</span></td>
                    <td>{{ m.dept }}</td>
                    <td>{{ m.joinedAt }}</td>
                    <td>{{ m.lastActive }}</td>
                    <td><span :class="['tag', m.online ? 'tag-success' : 'tag-default']">{{ m.online ? '● 在线' : '离线' }}</span></td>
                    <td><span class="action-icon">···</span></td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- 角色权限矩阵 -->
            <div v-else-if="memberTab === 'roles'" class="perm-matrix">
              <div class="perm-row head">
                <div>权限项</div>
                <div class="perm-cell">超级管理员</div>
                <div class="perm-cell">管理员</div>
                <div class="perm-cell">编辑者</div>
                <div class="perm-cell">只读</div>
              </div>
              <div v-for="perm in permissions" :key="perm.name" class="perm-row">
                <div>{{ perm.name }}</div>
                <div class="perm-cell"><span :class="perm.admin ? 'perm-yes' : 'perm-no'">{{ perm.admin ? '✓' : '✕' }}</span></div>
                <div class="perm-cell"><span :class="perm.manager ? 'perm-yes' : 'perm-no'">{{ perm.manager ? '✓' : '✕' }}</span></div>
                <div class="perm-cell"><span :class="perm.editor === true ? 'perm-yes' : perm.editor === false ? 'perm-no' : 'perm-partial'">{{ formatPerm(perm.editor) }}</span></div>
                <div class="perm-cell"><span :class="perm.viewer ? 'perm-yes' : 'perm-no'">{{ perm.viewer ? '✓' : '✕' }}</span></div>
              </div>
            </div>
          </div>

          <!-- 邀请弹窗 -->
          <a-modal v-model:open="showInviteModal" title="邀请成员" ok-text="发送邀请" cancel-text="取消">
            <a-form layout="vertical">
              <a-form-item label="邮箱地址">
                <a-input placeholder="请输入被邀请人的邮箱地址" />
              </a-form-item>
              <a-form-item label="角色">
                <a-select default-value="editor" style="width:100%">
                  <a-select-option value="admin">管理员</a-select-option>
                  <a-select-option value="editor">编辑者</a-select-option>
                  <a-select-option value="viewer">只读</a-select-option>
                </a-select>
              </a-form-item>
            </a-form>
          </a-modal>
        </div>

        <!-- ========== 最近更新 ========== -->
        <div v-else-if="currentPage === 'recent'" class="kb-page">
          <div class="page-title-row">
            <div>
              <h2>🕒 最近更新</h2>
              <p class="sub">最近修改过的文档，按时间倒序排列</p>
            </div>
          </div>
          <div class="doc-list">
            <div v-for="doc in recentDocs" :key="doc.id" class="doc-card" @click="openDocument(doc)">
              <div class="doc-card-icon" :style="{ background: doc.iconBg, color: doc.iconColor }">{{ doc.typeIcon }}</div>
              <div class="doc-card-info">
                <div class="doc-card-title">{{ doc.title }}</div>
                <div class="doc-card-meta">
                  <span>📁 {{ doc.category }}</span><span class="dot">·</span><span>👤 {{ doc.author }}</span><span class="dot">·</span><span>🕒 {{ doc.updatedAt }}</span>
                </div>
              </div>
              <span :class="['tag', `tag-${doc.statusColor}`]">{{ doc.statusText }}</span>
            </div>
          </div>
        </div>

        <!-- ========== AI 助手 ========== -->
        <div v-else-if="currentPage === 'assistant'" class="kb-page kb-assistant-page">
          <div class="chat-layout">
            <div class="chat-sidebar">
              <button class="chat-new-btn" @click="clearChatMessages">✨ 新建对话</button>
              <div class="chat-history-group">
                <div class="chat-history-label">今天</div>
                <div
                  v-for="(h, i) in chatHistoryToday"
                  :key="'t'+i"
                  :class="['chat-history-item', { active: activeChatId === h.id }]"
                  @click="activeChatId = h.id"
                >{{ h.question }}<div class="time">{{ h.time }}</div></div>
              </div>
              <div class="chat-history-group">
                <div class="chat-history-label">昨天</div>
                <div
                  v-for="(h, i) in chatHistoryYesterday"
                  :key="'y'+i"
                  :class="['chat-history-item', { active: activeChatId === h.id }]"
                  @click="activeChatId = h.id"
                >{{ h.question }}<div class="time">{{ h.time }}</div></div>
              </div>
            </div>

            <div class="chat-main">
              <div class="chat-topbar">
                <div class="title">✨ AI 智能助手 <span class="ai-badge">基于知识库</span></div>
              </div>
              <div class="chat-messages">
                <div v-if="!chatMessages.length" class="chat-welcome">
                  <div class="wicon">✨</div>
                  <h2>你好，我是知识库助手</h2>
                  <p>我可以基于团队知识库回答问题、总结文档、生成提纲。试试这些：</p>
                  <div class="quick-questions">
                    <div v-for="(q, i) in quickQuestions" :key="i" class="quick-q" @click="askQuick(q.q)">
                      <div class="qicon">{{ q.icon }}</div>
                      <div class="qtext">{{ q.q }}</div>
                      <div class="qhint">{{ q.hint }}</div>
                    </div>
                  </div>
                </div>
                <template v-else>
                  <div v-for="(msg, i) in chatMessages" :key="i" :class="['msg', msg.role === 'user' ? 'msg-user' : 'msg-ai']">
                    <div class="avatar" :style="{ background: msg.role === 'user' ? 'linear-gradient(135deg,#FF7A59,#FFB088)' : 'linear-gradient(135deg,#7C5CFC,#A78BFA)' }">{{ msg.role === 'user' ? userInitial : '✨' }}</div>
                    <div class="bubble" v-html="msg.content"></div>
                  </div>
                </template>
              </div>
              <div class="chat-input-bar">
                <div class="chat-input">
                  <textarea class="textarea" v-model="chatInput" rows="1" @keydown.enter.exact.prevent="sendChatMessage" placeholder="输入问题，按 Enter 发送… 可使用 @ 引用文档、# 引用知识库"></textarea>
                  <div class="send-btn" @click="sendChatMessage">↑</div>
                </div>
                <div class="chat-input-hint">
                  <span class="h">@ 文档</span>
                  <span class="h"># 知识库</span>
                  <span class="shortcut">Enter 发送 · Shift+Enter 换行</span>
                </div>
              </div>
            </div>

            <div class="chat-right">
              <div class="kb-scope">
                <div class="title">🎯 知识库范围</div>
                <div v-for="sc in scopeItems" :key="sc.label" class="scope-item">
                  <span :class="sc.checked ? 'check' : ''">{{ sc.checked ? '✓' : '○' }}</span> {{ sc.label }}
                </div>
              </div>
              <div class="ref-panel-title">📚 本次对话引用</div>
              <div v-for="(ref, i) in chatRefs" :key="i" class="ref-item" @click="openDocumentById(ref.id)">
                <div class="rt">{{ ref.title }}</div>
                <div class="rm">{{ ref.meta }}</div>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref, computed, watch } from 'vue';

// ==================== Props / Emits ====================
const props = defineProps({
  workspaceNotice: { type: String, default: '' },
  workspaceNoticeType: { type: String, default: 'info' },
  knowledgeDocuments: { type: Array, default: () => [] },
  knowledgeDocumentsLoading: { type: Boolean, default: false },
  uploadingDocumentNames: { type: Array, default: () => [] },
  deletingKnowledgeDocumentId: { type: [String, Number, null], default: null },
  conversationMode: { type: String, default: 'chat' },
  ragScopeType: { type: String, default: 'all' },
  ragDocumentIds: { type: Array, default: () => [] },
  activeScopedDocuments: { type: Array, default: () => [] },
  formatTime: { type: Function, default: (d) => d || '-' },
});

defineEmits([
  'close-notice', 'refresh-knowledge', 'upload-knowledge-document', 'create-document',
  'delete-knowledge-document', 'add-doc-to-scope',
  'update:conversation-mode', 'update:rag-scope-type', 'update:rag-document-ids',
]);

// ==================== 基础状态 ====================
const userInitial = ref('李');
const activeTopTab = ref('knowledge');
const topTabs = [
  { key: 'workspace', label: '工作台' },
  { key: 'knowledge', label: '知识库' },
  { key: 'assistant', label: '智能助手' },
];

// ==================== 页面导航 ====================
const currentPage = ref('home');
const currentCategory = ref('');
const activeTocIdx = ref(0);

function navigateTo(page) {
  currentPage.value = page;
}
function selectCategory(key) {
  currentCategory.value = key;
  currentPage.value = 'home';
}

// ==================== Mock 数据：分类 ====================
const categories = reactive([
  { key: '', name: '全部文档', icon: '📄', count: 128 },
  { key: 'product', name: '产品设计', icon: '🎨', count: 24 },
  { key: 'tech', name: '技术研发', icon: '⚙️', count: 36 },
  { key: 'ops', name: '运营手册', icon: '📊', count: 18 },
  { key: 'customer', name: '客户资料', icon: '👥', count: 12 },
]);

const categoryMap = { product: '产品设计', tech: '技术研发', ops: '运营手册', customer: '客户资料' };
const categoryName = computed(() => categoryMap[currentCategory.value] || '');
const categoryDesc = computed(() => {
  const descs = {
    '': '浏览和管理所有知识库文档',
    product: '产品设计相关的需求文档、用户研究、设计规范等',
    tech: '技术研发相关的架构设计、API文档、技术方案等',
    ops: '运营手册、周报模板、数据分析规范等',
    customer: '客户资料、反馈记录、调研报告等',
  };
  return descs[currentCategory.value] || '';
});

// ==================== Mock 数据：文档列表 ====================
const mockDocuments = reactive([]);

// 文档列表由接口层（useKnowledgeBase -> mockKnowledgeApi）经 props 流入
watch(
  () => props.knowledgeDocuments,
  (val) => {
    if (Array.isArray(val)) {
      mockDocuments.splice(0, mockDocuments.length, ...val.map((d) => ({ ...d })));
    }
  },
  { immediate: true }
);
const docCount = computed(() => mockDocuments.length);

// ==================== 统计 ====================
const stats = reactive({
  // totalDocs 已改为响应式 docCount（见下方 computed）
  readyDocs: mockDocuments.filter(d => d.status === 'ready').length,
  storageUsed: '3.2 GB',
});
const storageLimit = '5 GB';
const storagePercent = 65;

const statCards = computed(() => [
  { icon: '📄', label: '总文档数', value: mockDocuments.length, sub: `${mockDocuments.filter(d => d.status === 'ready').length} 份可检索`, bg: '#E8F1FF', color: '#2B6FFF', up: true },
  { icon: '👥', label: '贡献成员', value: '6', sub: '本月活跃 5 人', bg: '#DBFAE0', color: '#00B85C' },
  { icon: '👁️', label: '总阅读量', value: '2,214', sub: '↑ 12% 较上周', bg: '#EFE9FF', color: '#7C5CFC', up: true },
  { icon: '💬', label: '评论数', value: '38', sub: '本周新增 8 条', bg: '#FFF4D6', color: '#E6A23C' },
]);

// ==================== 筛选和搜索 ====================
const docSearchKey = ref('');
const activeFilter = ref('全部');
const filterChips = ['全部', '可检索', '解析中', '已收藏'];
const sortBy = ref('recent');

const filteredDocList = computed(() => {
  let list = [...mockDocuments];
  if (currentCategory.value) list = list.filter(d => d.category === currentCategory.value);
  if (docSearchKey.value) list = list.filter(d => d.title.includes(docSearchKey.value));
  if (activeFilter.value === '可检索') list = list.filter(d => d.status === 'ready');
  else if (activeFilter.value === '解析中') list = list.filter(d => d.status === 'parsing');
  else if (activeFilter.value === '已收藏') list = list.filter(d => d.isFavorite);
  return list;
});

// ==================== 文档详情 ====================
const currentDetailDoc = ref(null);

function openDocument(doc) {
  currentDetailDoc.value = doc;
  currentPage.value = 'detail';
}
function openDocumentById(id) {
  const doc = mockDocuments.find(d => d.id === id);
  if (doc) openDocument(doc);
}
function openSharedDoc(sharedDoc) {
  const doc = mockDocuments.find(d => d.id === sharedDoc.docId);
  if (doc) openDocument(doc);
}

function toggleFavorite(doc) {
  if (doc) doc.isFavorite = !doc.isFavorite;
}

function editDocument(doc) {
  newDocTitle.value = doc?.title || '';
  newDocContent.value = doc?.content || '';
  currentPage.value = 'create';
  createActiveTab.value = 'blank';
}

function scrollToToc(idx) {
  activeTocIdx.value = idx;
}

// ==================== 评论 ====================
const newComment = ref('');
function submitComment() {
  if (!newComment.value.trim() || !currentDetailDoc.value) return;
  currentDetailDoc.value.comments.push({
    author: '李明', avatarBg: 'linear-gradient(135deg,#FF7A59,#FFB088)',
    time: '刚刚', text: newComment.value, likes: 0,
  });
  newComment.value = '';
}
function likeComment(idx) {
  if (currentDetailDoc.value?.comments[idx]) {
    currentDetailDoc.value.comments[idx].likes = (currentDetailDoc.value.comments[idx].likes || 0) + 1;
  }
}

// ==================== 新建文档 ====================
const showCreateModal = ref(false);
const createActiveTab = ref('template');
function openUpload() {
  createActiveTab.value = 'upload';
  navigateTo('create');
}
const createTabs = [
  { key: 'template', label: '📝 从模板创建' },
  { key: 'blank', label: '📄 空白文档' },
  { key: 'upload', label: '📤 上传文件' },
];
const templates = [
  { name: '空白文档', desc: '从零开始撰写，适合自由格式的记录', icon: '📄', bg: '#E8F1FF', color: '#2B6FFF' },
  { name: '会议纪要', desc: '议题、决议、待办三段式结构，自动归档', icon: '📋', bg: '#DBFAE0', color: '#00B85C' },
  { name: '需求文档 PRD', desc: '背景、目标、方案、排期完整框架', icon: '🎯', bg: '#FFF4D6', color: '#E6A23C' },
  { name: '用户研究报告', desc: '访谈记录、洞察、机会点结构化模板', icon: '🔬', bg: '#EFE9FF', color: '#7C5CFC' },
  { name: '周报 / 月报', desc: '进展、风险、下周计划，支持数据图表', icon: '📈', bg: '#FFE6E3', color: '#F5483B' },
  { name: 'SOP 操作手册', desc: '步骤化操作流程，支持图文与视频嵌入', icon: '📚', bg: '#E0F2FF', color: '#0EA5E9' },
];

const newDocTitle = ref('');
const newDocContent = ref('');

function createFromTemplate(tpl) {
  newDocTitle.value = tpl.name + ' - ' + new Date().toLocaleDateString();
  newDocContent.value = `# ${newDocTitle.value}\n\n请在此处填写内容...`;
  createActiveTab.value = 'blank';
}

function createBlankDoc() {
  emit('create-document', {
    title: newDocTitle.value || '未命名文档',
    category: currentCategory.value || 'product',
    content: newDocContent.value,
  });
  navigateTo('home');
  newDocTitle.value = '';
  newDocContent.value = '';
}

// ==================== 上传 ====================
const fileInput = ref(null);
const uploadFormats = ['PDF', 'Word', 'Excel', 'PPT', 'Markdown', '图片'];
const uploadList = reactive([]);

function triggerUpload() { fileInput.value?.click(); }
function handleDrop(e) {
  const files = e.dataTransfer.files;
  for (const f of files) addUploadItem(f);
}
function handleFileSelect(e) {
  const files = e.target.files;
  for (const f of files) addUploadItem(f);
}
function addUploadItem(file) {
  const ext = file.name.split('.').pop()?.toUpperCase() || 'FILE';
  const colors = { PDF: '#F5483B', DOC: '#00B85C', XLS: '#E6A23C', PPT: '#7C5CFC', MD: '#2B6FFF' };
  const item = reactive({
    name: file.name, ext, size: formatFileSize(file.size),
    progress: 0, status: '上传中…',
    tagText: '上传中', tagType: 'warning',
    color: colors[ext] || '#6B7280',
  });
  uploadList.push(item);
  // 模拟上传进度
  let p = 0;
  const timer = setInterval(() => {
    p += Math.random() * 25;
    if (p >= 100) {
      p = 100;
      clearInterval(timer);
      item.progress = 100;
      item.status = '已完成';
      item.tagText = '● 可检索';
      item.tagType = 'success';
      addUploadedDocToLibrary(file, item);
    } else {
      item.progress = Math.round(p);
    }
  }, 300);
}
function addUploadedDocToLibrary(file, item) {
  // 通过接口层上传：App.vue -> useKnowledgeBase.uploadKnowledgeDocument -> mockKnowledgeApi
  emit('upload-knowledge-document', file);
  item.inLibrary = true;
}
function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1048576).toFixed(1) + ' MB';
}

// ==================== 搜索 ====================
const searchQuery = ref('');
const hasSearched = ref(false);
const searchResults = ref([]);
const searchResultTab = ref('all');

const resultTabs = computed(() => {
  const total = searchResults.value.length;
  return [
    { key: 'all', label: '全部', count: total },
    { key: 'doc', label: '文档', count: searchResults.value.filter(r => r.type === 'doc').length },
    { key: 'sheet', label: '表格', count: searchResults.value.filter(r => r.type === 'sheet').length },
  ];
});

function doSearch() {
  if (!searchQuery.value.trim()) return;
  hasSearched.value = true;
  const q = searchQuery.value.toLowerCase();
  searchResults.value = mockDocuments
    .filter(d => d.title.toLowerCase().includes(q) || d.excerpt.toLowerCase().includes(q))
    .map(d => ({
      id: 'sr-' + d.id, doc: d, title: d.title, excerpt: d.excerpt,
      category: categoryMap[d.category] || '', author: d.author, date: d.updatedAt,
      typeIcon: d.typeIcon, iconBg: d.iconBg, iconColor: d.iconColor, type: 'doc',
    }));
  // 模拟额外搜索结果
  if (q.includes('访谈')) {
    searchResults.value.push({
      id: 'sr-cmt', title: `评论 · 在「${mockDocuments[0].title}」中`,
      excerpt: `关于"${q}"这一点，新手研究员往往不敢停顿，但实际效果非常好。建议在${q}培训里强化这点。`,
      category: '', author: '王芳', date: '2 小时前', typeIcon: '💬', iconBg: '#F9FAFB', iconColor: '#6B7280', type: 'comment',
    });
  }
}

function highlightText(text) {
  if (!searchQuery.value) return text;
  const q = searchQuery.value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return text.replace(new RegExp(`(${q})`, 'gi'), '<span class="highlight">$1</span>');
}

// ==================== 收藏 ====================
const favViewMode = ref('grid');
const favorites = computed(() => mockDocuments.filter(d => d.isFavorite));

// ==================== 与我共享 ====================
const shareFilter = ref('all');
const sharedDocs = reactive([
  { id: 'sh1', title: 'Q3 产品需求评审纪要', docId: 2, sharedBy: '王芳', sharedByAvatar: 'linear-gradient(135deg,#00B85C,#5BD887)', sharedTime: '2 小时前分享', category: '产品设计', editable: true, typeIcon: '📊', iconBg: '#DBFAE0', iconColor: '#00B85C' },
  { id: 'sh2', title: '用户行为数据汇总.xlsx', docId: null, sharedBy: '陈晨', sharedByAvatar: 'linear-gradient(135deg,#FF7A59,#FFB088)', sharedTime: '昨天分享', category: '产品设计', editable: false, typeIcon: '📊', iconBg: '#DBFAE0', iconColor: '#00B85C' },
  { id: 'sh3', title: '微服务架构改造方案', docId: 5, sharedBy: '刘洋', sharedByAvatar: 'linear-gradient(135deg,#7C5CFC,#A78BFA)', sharedTime: '5 天前分享', category: '技术研发', editable: true, typeIcon: '⚙️', iconBg: '#E0F2FF', iconColor: '#0EA5E9' },
  { id: 'sh4', title: '8 月运营月报', docId: null, sharedBy: '赵雪', sharedByAvatar: 'linear-gradient(135deg,#E6A23C,#F0C060)', sharedTime: '1 周前分享', category: '运营手册', editable: false, typeIcon: '📈', iconBg: '#FFF4D6', iconColor: '#E6A23C' },
  { id: 'sh5', title: '客户反馈原始记录 - 8月', docId: 9, sharedBy: '孙磊', sharedByAvatar: 'linear-gradient(135deg,#0EA5E9,#67C3F3)', sharedTime: '2 周前分享', category: '客户资料', editable: false, typeIcon: '📎', iconBg: '#FFE6E3', iconColor: '#F5483B' },
]);
const filteredSharedDocs = computed(() => {
  if (shareFilter.value === 'editable') return sharedDocs.filter(d => d.editable);
  if (shareFilter.value === 'readonly') return sharedDocs.filter(d => !d.editable);
  return sharedDocs;
});

// ==================== 回收站 ====================
const trashDocs = reactive([
  { id: 't1', title: '旧版用户研究方法对比（废弃稿）', originalPath: '产品设计 / 用户研究', deletedBy: '张明', deletedAt: '2 天前', daysLeft: 28 },
  { id: 't2', title: 'Q1 运营数据周报（已归档）', originalPath: '运营手册 / 周报', deletedBy: '赵雪', deletedAt: '5 天前', daysLeft: 25 },
  { id: 't3', title: '客户反馈录音 - 20250615.mp3', originalPath: '客户资料', deletedBy: '孙磊', deletedAt: '1 周前', daysLeft: 23 },
  { id: 't4', title: '技术栈选型讨论稿（初版）', originalPath: '技术研发 / 架构设计', deletedBy: '刘洋', deletedAt: '2 周前', daysLeft: 16 },
  { id: 't5', title: 'PRD 模板 v1（已被 v3 替代）', originalPath: '产品设计 / 模板库', deletedBy: '张明', deletedAt: '3 周前', daysLeft: 9 },
]);
function restoreDoc(doc) {
  const idx = trashDocs.indexOf(doc);
  if (idx > -1) trashDocs.splice(idx, 1);
}

// ==================== 成员管理 ====================
const memberTab = ref('list');
const memberTabs = [
  { key: 'list', label: '成员列表', count: 6 },
  { key: 'roles', label: '角色与权限', count: 4 },
  { key: 'invites', label: '邀请记录', count: 3 },
  { key: 'logs', label: '操作日志' },
];
const showInviteModal = ref(false);

const memberStats = computed(() => [
  { icon: '👥', label: '总成员数', value: 6, sub: '↑ 1 本月新增', bg: '#E8F1FF', color: '#2B6FFF' },
  { icon: '🔑', label: '管理员', value: 2, sub: '含 1 名超级管理员', bg: '#DBFAE0', color: '#00B85C' },
  { icon: '✏️', label: '编辑者', value: 3, sub: '可创建和编辑文档', bg: '#FFF4D6', color: '#E6A23C' },
  { icon: '⏳', label: '待处理邀请', value: 2, sub: '1 封已过期需重发', bg: '#FFE6E3', color: '#F5483B' },
]);

const members = reactive([
  { id: 1, name: '张明', email: 'zhangming@company.com', roleType: 'admin', roleLabel: '🔑 超级管理员', dept: '产品中心', joinedAt: '2024-03-12', lastActive: '刚刚', online: true, isMe: true, avatarBg: 'linear-gradient(135deg,#2B6FFF,#5B8CFF)' },
  { id: 2, name: '王芳', email: 'wangfang@company.com', roleType: 'admin', roleLabel: '🔑 管理员', dept: '产品中心', joinedAt: '2024-05-08', lastActive: '5 分钟前', online: true, isMe: false, avatarBg: 'linear-gradient(135deg,#00B85C,#5BD887)' },
  { id: 3, name: '陈晨', email: 'chenchen@company.com', roleType: 'editor', roleLabel: '✏️ 编辑者', dept: '设计部', joinedAt: '2024-06-20', lastActive: '1 小时前', online: false, isMe: false, avatarBg: 'linear-gradient(135deg,#FF7A59,#FFB088)' },
  { id: 4, name: '刘洋', email: 'liuyang@company.com', roleType: 'editor', roleLabel: '✏️ 编辑者', dept: '研发部', joinedAt: '2024-07-15', lastActive: '昨天', online: false, isMe: false, avatarBg: 'linear-gradient(135deg,#7C5CFC,#A78BFA)' },
  { id: 5, name: '赵雪', email: 'zhaoxue@company.com', roleType: 'viewer', roleLabel: '👁️ 只读', dept: '运营部', joinedAt: '2024-08-01', lastActive: '3 天前', online: false, isMe: false, avatarBg: 'linear-gradient(135deg,#E6A23C,#F0C060)' },
  { id: 6, name: '孙磊', email: 'sunlei@external.com', roleType: 'viewer', roleLabel: '👤 访客', dept: '外部合作', joinedAt: '2024-08-03', lastActive: '1 周前', online: false, isMe: false, avatarBg: 'linear-gradient(135deg,#0EA5E9,#67C3F3)' },
]);
const selectedMembers = ref([]);
const allSelected = computed(() => selectedMembers.value.length === members.length);
function toggleMemberSelect(id) {
  const idx = selectedMembers.value.indexOf(id);
  if (idx > -1) selectedMembers.value.splice(idx, 1); else selectedMembers.value.push(id);
}
function toggleSelectAll() {
  if (allSelected.value) selectedMembers.value = []; else selectedMembers.value = members.map(m => m.id);
}

const permissions = [
  { name: '查看文档', admin: true, manager: true, editor: true, viewer: true },
  { name: '创建 / 编辑文档', admin: true, manager: true, editor: true, viewer: false },
  { name: '删除文档', admin: true, manager: true, editor: '仅自己创建的', viewer: false },
  { name: '分享 / 邀请成员', admin: true, manager: true, editor: false, viewer: false },
  { name: '管理角色与权限', admin: true, manager: false, editor: false, viewer: false },
  { name: '查看操作日志', admin: true, manager: true, editor: false, viewer: false },
  { name: '使用 AI 助手', admin: true, manager: true, editor: true, viewer: '仅问答' },
];
function formatPerm(v) { if (v === true) return '✓'; if (v === false) return '✕'; return v; }

// ==================== 最近更新 ====================
const recentDocs = computed(() => [...mockDocuments].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)));

// ==================== AI 助手 ====================
const chatMessages = ref([]);
const chatInput = ref('');
const activeChatId = ref('c1');
const chatHistoryToday = reactive([
  { id: 'c1', question: '用户访谈方法有哪些？', time: '14:32' },
  { id: 'c2', question: 'Q3 产品需求评审纪要', time: '11:08' },
  { id: 'c3', question: '如何撰写 PRD', time: '09:45' },
]);
const chatHistoryYesterday = reactive([
  { id: 'y1', question: '新员工 onboarding 流程', time: '昨天' },
  { id: 'y2', question: '客户反馈分类标准', time: '昨天' },
]);
const quickQuestions = [
  { icon: '📋', q: '总结这篇文档的要点', hint: '输入 @ 文档名引用' },
  { icon: '🔍', q: '帮我找到关于 XX 的所有文档', hint: '跨知识库检索' },
  { icon: '✏️', q: '根据资料生成一份提纲', hint: 'AI 辅助创作' },
  { icon: '📊', q: '对比两个方案的优劣', hint: '智能分析' },
];
const scopeItems = reactive([
  { label: '团队知识库（128 篇）', checked: true },
  { label: '产品设计（24 篇）', checked: true },
  { label: '技术研发（36 篇）', checked: true },
  { label: '客户资料（不检索）', checked: false },
]);
const chatRefs = ref([
  { id: 1, title: '用户访谈与研究方法', meta: '引用 2 处 · 产品设计 / 用户研究' },
  { id: 2, title: '用户研究方法论对比', meta: '引用 1 处 · 产品设计 / 用户研究' },
  { id: 3, title: 'Q2 用户访谈实录与洞察', meta: '引用 1 处 · 产品设计 / 用户研究' },
]);

function clearChatMessages() { chatMessages.value = []; }
function askQuick(q) { chatInput.value = q; sendChatMessage(); }
function sendChatMessage() {
  if (!chatInput.value.trim()) return;
  chatMessages.value.push({ role: 'user', content: chatInput.value });
  const q = chatInput.value;
  chatInput.value = '';
  // 模拟AI回复
  setTimeout(() => {
    chatMessages.value.push({
      role: 'assistant',
      content: `<p>根据团队知识库中的资料，我为您找到以下信息：</p>
        <ul><li>关于"<strong>${q}</strong>"，在《${mockDocuments[0].title}》中有详细描述</li>
        <li>相关内容还出现在 ${Math.floor(Math.random() * 3 + 1)} 篇其他文档中</li></ul>
        <p>如需深入了解某篇文档，可以点击右侧引用面板跳转。</p>`,
    });
  }, 800);
}
</script>

<style scoped>
/* ====== CSS 变量 ====== */
.kb-app { --primary:#2B6FFF;--primary-hover:#1E5AE6;--primary-bg:#E8F1FF;
  --success:#00B85C;--success-bg:#DBFAE0;
  --warning:#E6A23C;--warning-bg:#FFF4D6;
  --danger:#F5483B;--danger-bg:#FFE6E3;
  --purple:#7C5CFC;--purple-bg:#EFE9FF;
  --text:#1F2937;--text-secondary:#6B7280;--text-tertiary:#9CA3AF;
  --border:#E5E7EB;--border-light:#F0F1F3;
  --bg:#F5F6F8;--bg-soft:#F9FAFB;--card:#FFFFFF;
  --radius-sm:6px;--radius:8px;--radius-lg:12px;--radius-xl:16px;
  display:flex;flex-direction:column;height:100%;background:var(--bg);font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei","Helvetica Neue",Arial,sans-serif;font-size:14px;color:var(--text);line-height:1.5; }

/* ====== 顶部导航 ====== */
.kb-topnav{display:flex;align-items:center;padding:0 20px;height:52px;background:#fff;border-bottom:1px solid var(--border);gap:24px;flex-shrink:0;z-index:10;}
.kb-logo{display:flex;align-items:center;gap:8px;font-weight:700;font-size:15px;flex-shrink:0;}
.kb-logo-mark{width:28px;height:28px;background:linear-gradient(135deg,#2B6FFF,#5B8CFF);border-radius:8px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:14px;font-weight:700;}
.kb-nav-tabs{display:flex;gap:4px;}
.kb-nav-tab{padding:6px 14px;border-radius:var(--radius-sm);color:var(--text-secondary);cursor:pointer;font-size:14px;background:none;border:none;}
.kb-nav-tab.active{background:var(--primary-bg);color:var(--primary);font-weight:600;}
.kb-topnav-right{margin-left:auto;display:flex;align-items:center;gap:12px;}
.kb-search-box{display:flex;align-items:center;gap:8px;background:var(--bg-soft);border:1px solid var(--border);border-radius:var(--radius);padding:6px 12px;width:260px;color:var(--text-tertiary);font-size:13px;cursor:text;}
.kb-search-box:hover{border-color:var(--primary);}
.kb-icon-btn{width:32px;height:32px;border-radius:var(--radius-sm);display:flex;align-items:center;justify-content:center;color:var(--text-secondary);cursor:pointer;font-size:16px;background:none;border:none;}
.kb-icon-btn:hover{background:var(--bg-soft);}
.kb-upload-btn{display:flex;align-items:center;gap:6px;background:var(--primary);color:#fff;border:none;border-radius:var(--radius);padding:7px 16px;font-size:13px;font-weight:600;cursor:pointer;white-space:nowrap;box-shadow:0 1px 2px rgba(43,111,255,.25);}
.kb-upload-btn:hover{background:var(--primary-hover);}
.kb-avatar{width:30px;height:30px;border-radius:50%;background:linear-gradient(135deg,#FF7A59,#FFB088);color:#fff;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;}
.kbd{margin-left:auto;background:#fff;border:1px solid var(--border);border-radius:4px;padding:1px 6px;font-size:11px;color:var(--text-tertiary);}

/* ====== Body 布局 ====== */
.kb-body{display:flex;flex:1;overflow:hidden;}

/* ====== 左侧边栏 ====== */
.kb-sidebar{width:220px;background:#FAFBFC;border-right:1px solid var(--border);padding:16px 12px;overflow-y:auto;flex-shrink:0;}
.sb-section{margin-bottom:20px;}
.sb-title{font-size:11px;color:var(--text-tertiary);font-weight:600;padding:6px 10px;text-transform:uppercase;letter-spacing:.4px;}
.sb-item{display:flex;align-items:center;gap:8px;padding:7px 10px;border-radius:var(--radius-sm);color:var(--text-secondary);font-size:13px;cursor:pointer;background:none;border:none;width:100%;text-align:left;}
.sb-item:hover{background:#F0F2F5;}
.sb-item.active{background:var(--primary-bg);color:var(--primary);font-weight:600;}
.sb-item .ico{width:16px;height:16px;flex-shrink:0;font-size:14px;}
.sb-item .count{margin-left:auto;background:var(--bg-soft);color:var(--text-tertiary);border-radius:999px;padding:1px 7px;font-size:11px;}
.sb-item.active .count{background:#fff;color:var(--primary);}

.usage-card{margin-top:12px;padding:12px;background:linear-gradient(135deg,#FFF9E6,#FFF4D6);border-radius:var(--radius);}
.usage-label{font-size:12px;color:var(--text-secondary);}
.usage-num{font-size:20px;font-weight:700;margin:4px 0;}
.usage-bar{height:6px;background:rgba(0,0,0,.06);border-radius:999px;overflow:hidden;}
.usage-fill{height:100%;background:var(--warning);}

/* ====== 主内容区 ====== */
.kb-main{flex:1;padding:24px 32px;overflow-y:auto;background:var(--bg);}

/* ====== 面包屑 ====== */
.kb-breadcrumb{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--text-tertiary);margin-bottom:16px;}
.kb-breadcrumb a{color:var(--text-secondary);cursor:pointer;text-decoration:none;}
.kb-breadcrumb a:hover{color:var(--primary);}
.kb-breadcrumb .sep{color:var(--text-tertiary);}

/* ====== 页面头部 ====== */
.page-header-row{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:20px;}
.page-header-row h2{font-size:20px;font-weight:700;margin:0;}
.page-desc{font-size:13px;color:var(--text-secondary);margin-top:4px;}
.header-actions{display:flex;gap:8px;align-items:center;}

/* ====== 统计卡片 ====== */
.stat-row{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:20px;}
.stat-card{background:#fff;border-radius:var(--radius-lg);padding:18px 20px;box-shadow:0 1px 2px rgba(0,0,0,.04);display:flex;align-items:flex-start;gap:14px;}
.stat-card .sicon{width:44px;height:44px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0;}
.stat-card .sinfo{flex:1;}
.stat-card .slabel{font-size:12px;color:var(--text-secondary);}
.stat-card .snum{font-size:26px;font-weight:700;margin:2px 0;}
.stat-card .ssub{font-size:11px;color:var(--text-tertiary);}
.stat-card .ssub.up{color:var(--success);font-weight:600;}

/* ====== 筛选栏 ====== */
.filter-bar{display:flex;align-items:center;gap:12px;padding:12px 16px;background:#fff;border-radius:var(--radius-lg);box-shadow:0 1px 2px rgba(0,0,0,.04);margin-bottom:16px;flex-wrap:wrap;}
.filter-search{background:var(--bg-soft);border:1px solid var(--border);border-radius:6px;padding:5px 10px;font-size:13px;color:var(--text);width:220px;outline:none;}
.filter-search:focus{border-color:var(--primary);}
.filter-chip{padding:4px 12px;border-radius:999px;font-size:12px;border:1px solid var(--border);color:var(--text-secondary);cursor:pointer;background:#fff;}
.filter-chip.active{background:var(--primary-bg);color:var(--primary);border-color:var(--primary);}
.filter-right{margin-left:auto;}

/* ====== 文档列表 ====== */
.doc-list{display:flex;flex-direction:column;gap:8px;}
.doc-card{background:#fff;border-radius:var(--radius-lg);padding:16px 20px;box-shadow:0 1px 2px rgba(0,0,0,.04);display:flex;align-items:center;gap:14px;cursor:pointer;transition:all .2s;}
.doc-card:hover{box-shadow:0 4px 12px rgba(0,0,0,.08);transform:translateY(-1px);}
.doc-card-icon{width:40px;height:40px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0;}
.doc-card-info{flex:1;min-width:0;}
.doc-card-title{font-size:15px;font-weight:600;margin-bottom:4px;line-height:1.4;}
.doc-card-desc{font-size:13px;color:var(--text-secondary);line-height:1.6;margin-bottom:6px;display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden;}
.doc-card-meta{display:flex;align-items:center;gap:8px;font-size:11px;color:var(--text-tertiary);flex-wrap:wrap;}
.doc-card-meta .dot{width:3px;height:3px;border-radius:50%;background:var(--text-tertiary);}
.doc-card-right{display:flex;align-items:center;gap:10px;flex-shrink:0;}

/* ====== 标签 ====== */
.tag{display:inline-flex;align-items:center;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:500;}
.tag-success{background:var(--success-bg);color:var(--success);}
.tag-warning{background:var(--warning-bg);color:var(--warning);}
.tag-primary{background:var(--primary-bg);color:var(--primary);}
.tag-default{background:var(--bg-soft);color:var(--text-secondary);}
.tag-danger{background:var(--danger-bg);color:var(--danger);}
.btn{display:inline-flex;align-items:center;gap:6px;padding:7px 14px;border-radius:var(--radius-sm);font-size:13px;font-weight:500;cursor:pointer;border:1px solid transparent;background:#fff;color:var(--text);white-space:nowrap;}
.btn:hover{background:var(--bg-soft);}
.btn-primary{background:var(--primary);color:#fff;border-color:var(--primary);}
.btn-primary:hover{background:var(--primary-hover);}
.btn-outline{border-color:var(--border);color:var(--text);}
.btn-outline:hover{border-color:var(--primary);color:var(--primary);}
.btn-ghost{color:var(--text-secondary);background:none;border:none;}
.btn-ghost.favorited{color:var(--warning);}
.action-dot{color:var(--text-tertiary);cursor:pointer;padding:4px;border-radius:4px;background:none;border:none;font-size:14px;}
.action-dot:hover{background:var(--bg-soft);color:var(--text);}

/* ====== 文档详情 ====== */
.doc-header{background:#fff;border-radius:var(--radius-lg);padding:20px 24px;box-shadow:0 1px 2px rgba(0,0,0,.04);margin-bottom:16px;}
.doc-title-row{display:flex;align-items:flex-start;gap:12px;margin-bottom:12px;}
.doc-title-row h1{font-size:22px;font-weight:700;flex:1;margin:0;}
.doc-actions{display:flex;gap:8px;}
.doc-meta{display:flex;align-items:center;gap:16px;font-size:12px;color:var(--text-secondary);flex-wrap:wrap;}
.meta-item{display:flex;align-items:center;gap:4px;}
.dot{width:3px;height:3px;border-radius:50%;background:var(--text-tertiary);}

/* AI摘要 */
.ai-summary-box{background:linear-gradient(135deg,#EFE9FF,#F5F0FF);border:1px solid #D8CCFF;border-radius:var(--radius-lg);padding:16px 20px;margin-bottom:16px;}
.ai-head{display:flex;align-items:center;gap:8px;margin-bottom:8px;font-size:13px;font-weight:600;color:var(--purple);}
.ai-summary-box p{font-size:13px;color:var(--text);line-height:1.7;margin:0;}
.ai-actions{display:flex;gap:8px;margin-top:10px;}
.ai-chip{background:#fff;border:1px solid #D8CCFF;color:var(--purple);padding:3px 10px;border-radius:999px;font-size:11px;cursor:pointer;}

/* 正文+目录 */
.doc-body{display:grid;grid-template-columns:1fr 240px;gap:20px;}
.doc-content{background:#fff;border-radius:var(--radius-lg);padding:32px 40px;box-shadow:0 1px 2px rgba(0,0,0,.04);min-height:400px;}
.doc-content :deep(h2){font-size:20px;font-weight:700;margin:24px 0 12px;}
.raw-doc-text{white-space:pre-wrap;word-break:break-word;line-height:1.9;font-size:14px;color:var(--text-primary);}
.empty-doc{color:var(--text-tertiary);font-style:italic;padding:24px 0;}
.doc-content :deep(h2:first-child){margin-top:0;}
.doc-content :deep(h3){font-size:16px;font-weight:600;margin:16px 0 8px;}
.doc-content :deep(p){margin-bottom:12px;line-height:1.8;}
.doc-content :deep(ul),.doc-content :deep(ol){padding-left:24px;margin-bottom:12px;}
.doc-content :deep(li){margin-bottom:6px;line-height:1.7;}
.doc-content :deep(blockquote){border-left:3px solid var(--primary);background:var(--primary-bg);padding:12px 16px;margin:12px 0;border-radius:0 var(--radius-sm) var(--radius-sm) 0;}
.doc-content :deep(code){background:var(--bg-soft);padding:2px 6px;border-radius:4px;font-family:"SF Mono",Menlo,Consolas,monospace;font-size:13px;color:#C53030;}
.doc-content :deep(table){width:100%;border-collapse:collapse;margin:12px 0;font-size:13px;}
.doc-content :deep(th),.doc-content :deep(td){border:1px solid var(--border);padding:8px 12px;text-align:left;}
.doc-content :deep(th){background:var(--bg-soft);font-weight:600;}

.doc-toc{background:#fff;border-radius:var(--radius-lg);padding:16px;box-shadow:0 1px 2px rgba(0,0,0,.04);height:fit-content;position:sticky;top:20px;}
.toc-title{font-size:12px;color:var(--text-tertiary);font-weight:600;margin-bottom:12px;text-transform:uppercase;letter-spacing:.5px;}
.toc-list{list-style:none;padding:0;margin:0;}
.toc-list li{padding:6px 8px;font-size:13px;color:var(--text-secondary);cursor:pointer;border-left:2px solid transparent;border-radius:0 var(--radius-sm) var(--radius-sm) 0;}
.toc-list li.active{color:var(--primary);background:var(--primary-bg);border-left-color:var(--primary);font-weight:500;}
.toc-list li.sub{padding-left:24px;font-size:12px;}
.toc-list li:hover:not(.active){background:var(--bg-soft);}

/* 评论 */
.comments{background:#fff;border-radius:var(--radius-lg);padding:20px 24px;box-shadow:0 1px 2px rgba(0,0,0,.04);margin-top:16px;}
.comments-header{display:flex;align-items:center;gap:8px;margin-bottom:16px;font-weight:600;}
.comment-input-wrap{display:flex;gap:8px;margin-bottom:16px;align-items:flex-end;}
.comment-input{width:100%;background:var(--bg-soft);border:1px solid var(--border);border-radius:var(--radius);padding:10px 14px;font-size:13px;color:var(--text);resize:vertical;font-family:inherit;outline:none;}
.comment-input:focus{border-color:var(--primary);}
.comment-list .comment{display:flex;gap:10px;padding:12px 0;border-bottom:1px solid var(--border-light);}
.comment-list .comment:last-child{border-bottom:none;}
.comment .avatar{width:28px;height:28px;font-size:11px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;flex-shrink:0;}
.comment-body{flex:1;}
.comment-author{font-size:13px;font-weight:600;}
.comment-time{font-size:11px;color:var(--text-tertiary);margin-left:6px;}
.comment-text{font-size:13px;margin-top:4px;}
.comment-actions{display:flex;gap:12px;margin-top:6px;font-size:12px;color:var(--text-tertiary);}
.comment-actions span{cursor:pointer;}
.comment-actions span:hover{color:var(--primary);}

/* ====== 新建文档 ====== */
.kb-create-page{max-width:900px;margin:0 auto;}
.new-content-wrap{padding:40px 0;}
.new-header{text-align:center;margin-bottom:32px;}
.new-header h1{font-size:24px;font-weight:700;margin-bottom:8px;}
.new-header p{color:var(--text-secondary);font-size:14px;}
.new-tabs{display:flex;gap:4px;background:#fff;padding:4px;border-radius:var(--radius);width:fit-content;margin:0 auto 28px;box-shadow:0 1px 2px rgba(0,0,0,.04);}
.new-tab{padding:8px 20px;border-radius:var(--radius-sm);font-size:13px;color:var(--text-secondary);cursor:pointer;font-weight:500;background:none;border:none;}
.new-tab.active{background:var(--primary);color:#fff;}
.template-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:24px;}
.template-card{background:#fff;border:1px solid var(--border);border-radius:var(--radius-lg);padding:20px;cursor:pointer;transition:all .2s;}
.template-card:hover{border-color:var(--primary);box-shadow:0 4px 12px rgba(0,0,0,.08);transform:translateY(-2px);}
.template-card .icon{width:40px;height:40px;border-radius:var(--radius);display:flex;align-items:center;justify-content:center;font-size:20px;margin-bottom:12px;}
.template-card .name{font-weight:600;margin-bottom:4px;font-size:14px;}
.template-card .desc{font-size:12px;color:var(--text-secondary);line-height:1.5;}
.divider-label{display:flex;align-items:center;gap:12px;color:var(--text-tertiary);font-size:12px;margin:24px 0 16px;}
.divider-label::before,.divider-label::after{content:'';flex:1;height:1px;background:var(--border);}
.upload-zone{background:#fff;border:2px dashed var(--border);border-radius:var(--radius-lg);padding:48px 24px;text-align:center;transition:all .2s;cursor:pointer;}
.upload-zone:hover{border-color:var(--primary);background:var(--primary-bg);}
.upload-zone .uicon{font-size:48px;color:var(--primary);margin-bottom:16px;}
.upload-zone h3{font-size:16px;margin-bottom:8px;}
.upload-zone p{color:var(--text-secondary);font-size:13px;margin-bottom:16px;}
.upload-zone .formats{display:flex;gap:8px;justify-content:center;margin-top:12px;}
.fmt{background:var(--bg-soft);padding:3px 10px;border-radius:4px;font-size:11px;color:var(--text-secondary);}
.upload-list{margin-top:20px;}
.upload-item{display:flex;align-items:center;gap:12px;background:#fff;border:1px solid var(--border);border-radius:var(--radius);padding:12px 16px;margin-bottom:8px;}
.file-icon{width:32px;height:32px;border-radius:var(--radius-sm);display:flex;align-items:center;justify-content:center;font-size:12px;color:#fff;font-weight:700;flex-shrink:0;}
.file-info{flex:1;min-width:0;}
.file-name{font-size:13px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.file-meta{font-size:11px;color:var(--text-tertiary);}
.lib-link{font-size:11px;color:var(--primary);cursor:pointer;margin-top:4px;display:inline-block;}
.lib-link:hover{text-decoration:underline;}
.progress-bar{height:4px;background:var(--bg-soft);border-radius:999px;overflow:hidden;margin-top:6px;}
.progress-bar .fill{height:100%;background:var(--primary);}

.blank-editor{background:#fff;border-radius:var(--radius-lg);padding:24px;box-shadow:0 1px 2px rgba(0,0,0,.04);}
.blank-title{width:100%;border:none;outline:none;font-size:26px;font-weight:700;margin-bottom:16px;color:var(--text);font-family:inherit;}
.blank-content{width:100%;border:none;outline:none;font-size:14px;line-height:1.8;color:var(--text);font-family:inherit;resize:vertical;background:transparent;}
.blank-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:16px;}

/* ====== 搜索 ====== */
.big-search{background:#fff;border-radius:var(--radius-lg);box-shadow:0 4px 12px rgba(0,0,0,.08);padding:6px 6px 6px 20px;display:flex;align-items:center;gap:12px;margin-bottom:20px;border:2px solid var(--primary);}
.big-search .sicon{font-size:20px;color:var(--primary);}
.big-search input{flex:1;border:none;outline:none;font-size:16px;color:var(--text);background:transparent;font-family:inherit;}
.big-search .clear{color:var(--text-tertiary);cursor:pointer;font-size:16px;padding:4px;}
.search-btn{background:var(--primary);color:#fff;padding:8px 20px;border-radius:var(--radius-sm);font-size:13px;font-weight:500;cursor:pointer;border:none;}
.search-result-info{font-size:13px;color:var(--text-secondary);margin-bottom:16px;}
.result-tabs{display:flex;gap:0;margin-bottom:16px;border-bottom:1px solid var(--border);}
.result-tab{padding:8px 16px;font-size:13px;color:var(--text-secondary);cursor:pointer;border-bottom:2px solid transparent;font-weight:500;background:none;border-top:none;border-left:none;border-right:none;}
.result-tab.active{color:var(--primary);border-bottom-color:var(--primary);}
.result-tab .num{font-size:11px;color:var(--text-tertiary);margin-left:4px;}
.result-list{display:flex;flex-direction:column;gap:10px;}
.result-item{background:#fff;border-radius:var(--radius-lg);padding:16px 20px;box-shadow:0 1px 2px rgba(0,0,0,.04);cursor:pointer;transition:all .2s;display:flex;gap:14px;}
.result-item:hover{box-shadow:0 4px 12px rgba(0,0,0,.08);transform:translateY(-1px);}
.ricon{width:36px;height:36px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0;}
.rbody{flex:1;min-width:0;}
.rtitle{font-size:15px;font-weight:600;margin-bottom:4px;line-height:1.4;}
.rexcerpt{font-size:13px;color:var(--text-secondary);line-height:1.6;margin-bottom:8px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.rmeta{display:flex;align-items:center;gap:8px;font-size:11px;color:var(--text-tertiary);}
.rmeta .dot{width:3px;height:3px;border-radius:50%;background:var(--text-tertiary);}
:deep(.highlight){background:#FFF3B0;color:#92600A;padding:0 3px;border-radius:3px;font-weight:500;}
.search-welcome{text-align:center;padding:60px 20px;}
.sw-icon{font-size:64px;margin-bottom:16px;}
.search-welcome h3{font-size:22px;margin-bottom:8px;}
.search-welcome p{color:var(--text-secondary);font-size:14px;}

/* ====== 收藏 ====== */
.page-title-row{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:20px;}
.page-title-row h2{font-size:20px;font-weight:700;margin:0;}
.sub{font-size:13px;color:var(--text-secondary);margin-top:4px;}
.right{display:flex;gap:8px;align-items:center;}
.view-toggle{padding:4px 12px;border-radius:999px;font-size:12px;border:1px solid var(--border);color:var(--text-secondary);cursor:pointer;background:#fff;}
.view-toggle.active{background:var(--primary-bg);color:var(--primary);border-color:var(--primary);}
.fav-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px;}
.fav-card{background:#fff;border-radius:var(--radius-lg);padding:18px 20px;box-shadow:0 1px 2px rgba(0,0,0,.04);cursor:pointer;transition:all .2s;position:relative;}
.fav-card:hover{box-shadow:0 4px 12px rgba(0,0,0,.08);transform:translateY(-2px);}
.fav-card .fstar{position:absolute;top:14px;right:14px;color:var(--warning);font-size:16px;}
.fav-card .ficon{width:36px;height:36px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:16px;margin-bottom:10px;}
.fav-card .ftitle{font-size:14px;font-weight:600;margin-bottom:6px;line-height:1.4;}
.fav-card .fdesc{font-size:12px;color:var(--text-secondary);line-height:1.6;margin-bottom:10px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.fav-card .fmeta{display:flex;align-items:center;gap:8px;font-size:11px;color:var(--text-tertiary);}
.fav-card .fmeta .dot{width:3px;height:3px;border-radius:50%;background:var(--text-tertiary);}

/* ====== 与我共享 ====== */
.share-list{display:flex;flex-direction:column;gap:10px;}
.share-item{background:#fff;border-radius:var(--radius-lg);padding:16px 20px;box-shadow:0 1px 2px rgba(0,0,0,.04);display:flex;align-items:center;gap:14px;}
.share-item .sicon{width:40px;height:40px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0;}
.sinfo{flex:1;min-width:0;}
.stitle{font-size:14px;font-weight:600;margin-bottom:4px;}
.smeta{font-size:12px;color:var(--text-tertiary);display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
.smeta .dot{width:3px;height:3px;border-radius:50%;background:var(--text-tertiary);}
.from-user{display:flex;align-items:center;gap:6px;}
.avatar-sm{width:18px;height:18px;font-size:8px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;}
.sactions{display:flex;gap:8px;flex-shrink:0;}

/* ====== 回收站 ====== */
.recycle-banner{background:var(--warning-bg);border:1px solid #F0D860;border-radius:var(--radius-lg);padding:12px 16px;margin-bottom:16px;display:flex;align-items:center;gap:10px;font-size:13px;}
.recycle-banner .ricon{font-size:18px;}
.recycle-banner .rtext{flex:1;}
.recycle-banner .rtext strong{color:var(--warning);}
.recycle-list{display:flex;flex-direction:column;gap:8px;}
.recycle-item{background:#fff;border-radius:var(--radius-lg);padding:14px 20px;box-shadow:0 1px 2px rgba(0,0,0,.04);display:flex;align-items:center;gap:14px;}
.recycle-item .ricon{width:36px;height:36px;border-radius:8px;background:var(--bg-soft);display:flex;align-items:center;justify-content:center;font-size:16px;color:var(--text-tertiary);flex-shrink:0;}
.rinfo{flex:1;min-width:0;}
.rname{font-size:14px;font-weight:500;margin-bottom:3px;color:var(--text-secondary);}
.rmeta{font-size:11px;color:var(--text-tertiary);display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
.rmeta .dot{width:3px;height:3px;border-radius:50%;background:var(--text-tertiary);}
.countdown{font-size:11px;font-weight:500;}
.countdown.danger{color:var(--danger);}
.ractions{display:flex;gap:8px;flex-shrink:0;}

/* ====== 成员管理 ====== */
.section-card{background:#fff;border-radius:var(--radius-lg);box-shadow:0 1px 2px rgba(0,0,0,.04);overflow:hidden;margin-bottom:16px;}
.tab-bar{display:flex;gap:0;border-bottom:1px solid var(--border-light);padding:0 20px;}
.tab-item{padding:12px 16px;font-size:13px;color:var(--text-secondary);cursor:pointer;border-bottom:2px solid transparent;font-weight:500;background:none;border-top:none;border-left:none;border-right:none;}
.tab-item.active{color:var(--primary);border-bottom-color:var(--primary);}
.tab-item .num{background:var(--bg-soft);color:var(--text-tertiary);border-radius:999px;padding:1px 7px;font-size:11px;margin-left:4px;}
.member-table-wrap{overflow-x:auto;}
.data-table{width:100%;border-collapse:collapse;font-size:13px;}
.data-table th{text-align:left;padding:10px 16px;background:var(--bg-soft);color:var(--text-secondary);font-weight:600;font-size:12px;border-bottom:1px solid var(--border);}
.data-table td{padding:12px 16px;border-bottom:1px solid var(--border-light);}
.checkbox{width:16px;height:16px;border:1.5px solid var(--border);border-radius:4px;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;}
.checkbox.checked{background:var(--primary);border-color:var(--primary);position:relative;}
.checkbox.checked::after{content:'✓';color:#fff;font-size:11px;position:absolute;}
.member-cell{display:flex;align-items:center;gap:10px;}
.member-cell .avatar{width:32px;height:32px;font-size:12px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;}
.member-cell .info .name{font-weight:500;display:flex;align-items:center;gap:6px;}
.member-cell .info .email{font-size:11px;color:var(--text-tertiary);}
.role-badge{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:6px;font-size:12px;font-weight:500;}
.role-admin{background:var(--primary-bg);color:var(--primary);}
.role-editor{background:var(--success-bg);color:var(--success);}
.role-viewer{background:var(--bg-soft);color:var(--text-secondary);}
.action-icon{color:var(--text-tertiary);cursor:pointer;padding:4px;border-radius:4px;font-size:14px;}
.perm-matrix{padding:0;}
.perm-row{display:grid;grid-template-columns:200px repeat(4,1fr);padding:10px 20px;border-bottom:1px solid var(--border-light);align-items:center;font-size:13px;}
.perm-row.head{background:var(--bg-soft);font-weight:600;font-size:12px;color:var(--text-secondary);}
.perm-row .perm-cell{text-align:center;}
.perm-yes{color:var(--success);font-size:16px;}
.perm-no{color:var(--text-tertiary);font-size:16px;}
.perm-partial{color:var(--warning);font-size:12px;}

/* ====== AI 助手 ====== */
.chat-layout{display:grid;grid-template-columns:240px 1fr 280px;height:calc(100vh - 120px);background:#fff;border-radius:var(--radius-lg);overflow:hidden;}
.chat-sidebar{background:#FAFBFC;border-right:1px solid var(--border);padding:16px 12px;overflow-y:auto;}
.chat-new-btn{width:100%;padding:10px;background:var(--primary);color:#fff;border-radius:8px;font-size:13px;font-weight:500;cursor:pointer;text-align:center;margin-bottom:16px;border:none;}
.chat-history-group{margin-bottom:16px;}
.chat-history-label{font-size:11px;color:var(--text-tertiary);font-weight:600;padding:4px 8px;text-transform:uppercase;letter-spacing:.4px;}
.chat-history-item{padding:8px 10px;border-radius:6px;font-size:13px;color:var(--text-secondary);cursor:pointer;line-height:1.4;background:none;border:none;width:100%;text-align:left;}
.chat-history-item:hover{background:var(--bg-soft);}
.chat-history-item.active{background:var(--primary-bg);color:var(--primary);font-weight:500;}
.chat-history-item .time{font-size:11px;color:var(--text-tertiary);margin-top:2px;}
.chat-main{display:flex;flex-direction:column;background:var(--bg);overflow:hidden;}
.chat-topbar{height:52px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;padding:0 24px;background:#fff;}
.chat-topbar .title{font-weight:600;font-size:14px;display:flex;align-items:center;gap:8px;}
.ai-badge{background:var(--purple-bg);color:var(--purple);padding:2px 8px;border-radius:999px;font-size:11px;font-weight:600;}
.chat-messages{flex:1;overflow-y:auto;padding:24px 40px;}
.chat-welcome{text-align:center;padding:30px 20px;}
.wicon{width:64px;height:64px;border-radius:16px;background:linear-gradient(135deg,var(--purple),#A78BFA);color:#fff;font-size:32px;display:flex;align-items:center;justify-content:center;margin:0 auto 16px;}
.chat-welcome h2{font-size:22px;margin-bottom:8px;}
.chat-welcome p{color:var(--text-secondary);margin-bottom:24px;font-size:14px;}
.quick-questions{display:grid;grid-template-columns:1fr 1fr;gap:12px;max-width:560px;margin:0 auto;}
.quick-q{background:#fff;border:1px solid var(--border);border-radius:10px;padding:14px 16px;cursor:pointer;text-align:left;transition:all .2s;}
.quick-q:hover{border-color:var(--purple);box-shadow:0 4px 12px rgba(0,0,0,.08);transform:translateY(-1px);}
.quick-q .qicon{font-size:20px;margin-bottom:6px;}
.quick-q .qtext{font-size:13px;font-weight:500;}
.quick-q .qhint{font-size:11px;color:var(--text-tertiary);margin-top:2px;}
.msg{margin-bottom:24px;max-width:760px;display:flex;gap:12px;}
.msg-user{flex-direction:row-reverse;}
.msg .avatar{width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;flex-shrink:0;color:#fff;}
.msg-user .bubble{background:var(--primary);color:#fff;padding:10px 14px;border-radius:12px 12px 2px 12px;font-size:14px;line-height:1.6;}
.msg-ai .bubble{background:#fff;padding:16px 20px;border-radius:2px 12px 12px 12px;box-shadow:0 1px 2px rgba(0,0,0,.04);font-size:14px;line-height:1.8;flex:1;}
.msg-ai .bubble :deep(p){margin-bottom:8px;}
.msg-ai .bubble :deep(ul){padding-left:20px;margin-bottom:8px;}
.msg-ai .bubble :deep(li){margin-bottom:4px;}
.chat-input-bar{padding:16px 40px 20px;background:var(--bg);border-top:1px solid var(--border);}
.chat-input{background:#fff;border:1px solid var(--border);border-radius:12px;padding:12px 16px;display:flex;align-items:flex-end;gap:12px;box-shadow:0 1px 2px rgba(0,0,0,.04);}
.chat-input .textarea{flex:1;font-size:14px;color:var(--text);min-height:24px;line-height:1.6;border:none;outline:none;resize:none;font-family:inherit;background:transparent;}
.send-btn{width:36px;height:36px;border-radius:8px;background:var(--primary);color:#fff;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:16px;flex-shrink:0;border:none;}
.chat-input-hint{display:flex;gap:8px;margin-top:8px;align-items:center;}
.chat-input-hint .h{font-size:12px;color:var(--text-tertiary);cursor:pointer;padding:3px 8px;border-radius:4px;}
.chat-input-hint .h:hover{background:#fff;}
.chat-input-hint .shortcut{margin-left:auto;font-size:11px;color:var(--text-tertiary);}
.chat-right{background:#fff;border-left:1px solid var(--border);padding:20px 16px;overflow-y:auto;}
.kb-scope{background:var(--purple-bg);border:1px solid #D8CCFF;border-radius:8px;padding:12px;margin-bottom:16px;}
.kb-scope .title{font-size:12px;font-weight:600;color:var(--purple);margin-bottom:8px;display:flex;align-items:center;gap:6px;}
.scope-item{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text-secondary);padding:3px 0;}
.scope-item .check{color:var(--success);}
.ref-panel-title{font-size:13px;font-weight:600;margin-bottom:4px;}
.ref-item{background:var(--bg-soft);border-radius:8px;padding:10px 12px;margin-bottom:8px;cursor:pointer;}
.ref-item:hover{background:var(--primary-bg);}
.ref-item .rt{font-size:13px;font-weight:500;line-height:1.4;}
.ref-item .rm{font-size:11px;color:var(--text-tertiary);margin-top:3px;}

/* ====== 通用 ====== */
.empty-state{padding:60px 20px;text-align:center;}
.kb-page{animation:fadeIn .2s ease;}
@keyframes fadeIn{from{opacity:0;}to{opacity:1;}}
</style>
