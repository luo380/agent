<template>
<a-layout class="kb-app">
  <!-- ===== 顶部导航 ===== -->
  <a-layout-header class="kb-topnav">
    <div class="kb-logo">
      <div class="kb-logo-mark">知</div>
      <span>知识中枢</span>
    </div>
    <a-menu mode="horizontal" class="kb-nav-tabs" :selectedKeys="[currentPage]" @click="handleMenu">
      <a-menu-item key="home">📚 知识库</a-menu-item>
      <a-menu-item key="ai">✨ AI 助手</a-menu-item>
    </a-menu>
    <div class="kb-topnav-right">
      <a-input-search
        class="kb-search-input"
        placeholder="搜索文档、知识库、成员…"
        @focus="navigateTo('search')"
        readonly
      />
      <a-button type="primary" @click="openUpload">📤 上传</a-button>
      <a-avatar style="background:linear-gradient(135deg,#FF7A59,#FFB088)">{{ userInitial }}</a-avatar>
    </div>
  </a-layout-header>

  <a-layout class="kb-body">
    <!-- ===== 左侧边栏 ===== -->
    <a-layout-sider class="kb-sidebar" width="224" theme="light" :collapsible="false">
      <a-menu mode="inline" class="kb-sidemenu" :selectedKeys="selectedMenuKeys" @click="handleMenu">
        <a-menu-item key="home">
          <span class="sb-ico">📁</span><span>团队知识库</span>
        </a-menu-item>
        <a-menu-item-group title="空间导航">
          <a-menu-item key="cat:product"><span class="sb-ico">🎨</span><span>产品设计</span></a-menu-item>
          <a-menu-item key="cat:tech"><span class="sb-ico">⚙️</span><span>技术研发</span></a-menu-item>
          <a-menu-item key="cat:ops"><span class="sb-ico">📊</span><span>运营手册</span></a-menu-item>
          <a-menu-item key="cat:customer"><span class="sb-ico">👥</span><span>客户资料</span></a-menu-item>
        </a-menu-item-group>
        <a-menu-item-group title="快捷入口">
          <a-menu-item key="recent"><span class="sb-ico">🕐</span><span>最近更新</span></a-menu-item>
          <a-menu-item key="favorites"><span class="sb-ico">⭐</span><span>我的收藏</span></a-menu-item>
          <a-menu-item key="shared"><span class="sb-ico">🔗</span><span>与我共享</span></a-menu-item>
        </a-menu-item-group>
        <a-menu-item-group title="空间设置">
          <a-menu-item key="members"><span class="sb-ico">👥</span><span>成员与权限</span></a-menu-item>
          <a-menu-item key="trash"><span class="sb-ico">🗑️</span><span>回收站</span></a-menu-item>
        </a-menu-item-group>
      </a-menu>
      <div class="usage-card">
        <div class="usage-label">存储空间</div>
        <div class="usage-num">3.2 GB<span style="font-size:13px;color:#9CA3AF"> / 5 GB</span></div>
        <a-progress :percent="65" :show-info="false" stroke-color="#faad14" />
      </div>
    </a-layout-sider>

    <!-- ===== 主内容区 ===== -->
    <a-layout-content class="kb-main">

      <!-- ================= 首页 / 文档列表 ================= -->
      <div v-if="currentPage === 'home'" class="kb-page">
        <div class="page-header-row">
          <div>
            <h2>{{ categoryName || '全部文档' }}</h2>
            <div class="page-desc">{{ categoryDesc || '浏览和管理所有知识库文档' }}</div>
          </div>
          <div class="header-actions">
            <a-button @click="navigateTo('create')">✏️ 新建</a-button>
            <a-button type="primary" @click="openUpload">📤 上传文档</a-button>
          </div>
        </div>

        <a-row :gutter="16" class="stat-row">
          <a-col :span="6" v-for="card in statCards" :key="card.label">
            <a-card :bordered="false" class="stat-card">
              <div class="stat-inner">
                <div class="sicon" :style="{ background: card.bg, color: card.color }">{{ card.icon }}</div>
                <div class="sinfo">
                  <div class="slabel">{{ card.label }}</div>
                  <div class="snum">{{ card.value }}</div>
                  <div class="ssub" :class="{ up: card.up }">{{ card.sub }}</div>
                </div>
              </div>
            </a-card>
          </a-col>
        </a-row>

        <div class="filter-bar">
          <a-input v-model:value="docSearchKey" placeholder="搜索当前列表…" allow-clear style="width:240px" />
          <a-radio-group v-model:value="activeFilter" option-type="button" button-style="solid">
            <a-radio-button v-for="c in filterChips" :key="c" :value="c">{{ c }}</a-radio-button>
          </a-radio-group>
          <div class="filter-right">
            <a-select v-model:value="sortBy" style="width:140px">
              <a-select-option value="recent">最近更新</a-select-option>
              <a-select-option value="name">按名称</a-select-option>
            </a-select>
          </div>
        </div>

        <a-list class="doc-list" :data-source="filteredDocList" :split="false" item-layout="horizontal">
          <template #renderItem="{ item }">
            <a-list-item class="doc-card" @click="openDocument(item)">
              <div class="doc-card-icon" :style="{ background: item.iconBg, color: item.iconColor }">{{ item.typeIcon }}</div>
              <div class="doc-card-info">
                <div class="doc-card-title">{{ item.title }}</div>
                <div class="doc-card-desc">{{ item.excerpt }}</div>
                <div class="doc-card-meta">
                  <span>{{ item.author }}</span><span class="dot"></span>
                  <span>{{ item.updatedAt }}</span><span class="dot"></span>
                  <span>{{ item.wordCount }} 字</span><span class="dot"></span>
                  <a-tag :color="item.statusColor">{{ item.statusText }}</a-tag>
                </div>
              </div>
              <div class="doc-card-right" @click.stop>
                <a-button type="text" :class="{ favorited: item.isFavorite }" @click="toggleFavorite(item)">
                  {{ item.isFavorite ? '★' : '☆' }}
                </a-button>
                <a-popconfirm title="删除后进入回收站，30 天内可恢复，确定删除？" ok-text="删除" cancel-text="取消" @confirm="deleteDoc(item)">
                  <a-button type="text" danger>🗑️</a-button>
                </a-popconfirm>
              </div>
            </a-list-item>
          </template>
          <template #empty><a-empty description="暂无文档" /></template>
        </a-list>
      </div>

      <!-- ================= 最近更新 ================= -->
      <div v-else-if="currentPage === 'recent'" class="kb-page">
        <div class="page-header-row">
          <div><h2>最近更新</h2><div class="page-desc">按最后修改时间排序的最新文档</div></div>
        </div>
        <a-list class="doc-list" :data-source="recentDocs" :split="false" item-layout="horizontal">
          <template #renderItem="{ item }">
            <a-list-item class="doc-card" @click="openDocument(item)">
              <div class="doc-card-icon" :style="{ background: item.iconBg, color: item.iconColor }">{{ item.typeIcon }}</div>
              <div class="doc-card-info">
                <div class="doc-card-title">{{ item.title }}</div>
                <div class="doc-card-desc">{{ item.excerpt }}</div>
                <div class="doc-card-meta">
                  <span>{{ item.author }}</span><span class="dot"></span>
                  <span>{{ item.updatedAt }}</span><span class="dot"></span>
                  <span>{{ item.wordCount }} 字</span><span class="dot"></span>
                  <a-tag :color="item.statusColor">{{ item.statusText }}</a-tag>
                </div>
              </div>
              <div class="doc-card-right" @click.stop>
                <a-button type="text" :class="{ favorited: item.isFavorite }" @click="toggleFavorite(item)">{{ item.isFavorite ? '★' : '☆' }}</a-button>
                <a-popconfirm title="删除后进入回收站，30 天内可恢复，确定删除？" ok-text="删除" cancel-text="取消" @confirm="deleteDoc(item)">
                  <a-button type="text" danger>🗑️</a-button>
                </a-popconfirm>
              </div>
            </a-list-item>
          </template>
        </a-list>
      </div>

      <!-- ================= 文档详情 ================= -->
      <div v-else-if="currentPage === 'detail' && currentDetailDoc" class="kb-page">
        <a-breadcrumb class="kb-breadcrumb">
          <a-breadcrumb-item><a @click="navigateTo('home')">团队知识库</a></a-breadcrumb-item>
          <a-breadcrumb-item>{{ categoryName || '文档' }}</a-breadcrumb-item>
          <a-breadcrumb-item>{{ currentDetailDoc.title }}</a-breadcrumb-item>
        </a-breadcrumb>

        <div class="doc-header">
          <div class="doc-title-row">
            <h1>{{ currentDetailDoc.title }}</h1>
            <div class="doc-actions">
              <a-button :class="{ favorited: currentDetailDoc.isFavorite }" @click="toggleFavorite(currentDetailDoc)">{{ currentDetailDoc.isFavorite ? '★ 已收藏' : '☆ 收藏' }}</a-button>
              <a-button>🔗 分享</a-button>
              <a-button @click="editDocument(currentDetailDoc)">✏️ 编辑</a-button>
              <a-popconfirm title="删除后进入回收站，30 天内可恢复，确定删除？" ok-text="删除" cancel-text="取消" @confirm="deleteDoc(currentDetailDoc)">
                <a-button danger>🗑️ 删除</a-button>
              </a-popconfirm>
            </div>
          </div>
          <div class="doc-meta">
            <span class="meta-item">👤 {{ currentDetailDoc.author }}</span>
            <span class="dot"></span>
            <span class="meta-item">🕓 {{ currentDetailDoc.updatedAt }}</span>
            <span class="dot"></span>
            <span class="meta-item">👁️ {{ currentDetailDoc.views }} 次阅读</span>
            <span class="dot"></span>
            <a-tag :color="currentDetailDoc.statusColor">{{ currentDetailDoc.statusText }}</a-tag>
          </div>
        </div>

        <div class="ai-summary-box" v-if="currentDetailDoc.aiSummary">
          <div class="ai-head">✨ AI 智能摘要</div>
          <p>{{ currentDetailDoc.aiSummary }}</p>
        </div>

        <div class="doc-body">
          <div class="doc-content">
            <div v-if="!currentDetailDoc.content" class="empty-doc">（该文档暂无正文内容）</div>
            <div v-else v-html="currentDetailDoc.content"></div>
          </div>
          <div class="doc-toc">
            <div class="toc-title">目录</div>
            <ul class="toc-list">
              <li v-for="(t, i) in currentDetailDoc.toc" :key="i"
                  :class="['toc-item', { active: activeTocIdx === i, sub: t.sub }]"
                  @click="scrollToToc(i)">{{ t.text }}</li>
            </ul>
          </div>
        </div>

        <div class="comments">
          <div class="comments-header">💬 评论 ({{ currentDetailDoc.comments.length }})</div>
          <div class="comment-input-wrap">
            <a-textarea v-model:value="newComment" placeholder="写下你的评论…" :auto-size="{ minRows: 2, maxRows: 4 }" />
            <a-button type="primary" @click="submitComment">发送</a-button>
          </div>
          <div class="comment-list">
            <div class="comment" v-for="(c, i) in currentDetailDoc.comments" :key="i">
              <div class="avatar" :style="{ background: c.avatarBg }">{{ c.author.charAt(0) }}</div>
              <div class="comment-body">
                <span class="comment-author">{{ c.author }}</span>
                <span class="comment-time">{{ c.time }}</span>
                <div class="comment-text">{{ c.text }}</div>
                <div class="comment-actions">
                  <span @click="likeComment(i)">👍 {{ c.likes }}</span>
                  <span>回复</span>
                </div>
              </div>
            </div>
            <a-empty v-if="!currentDetailDoc.comments.length" description="还没有评论" />
          </div>
        </div>

        <div class="related" v-if="currentDetailDoc.relatedDocs && currentDetailDoc.relatedDocs.length">
          <div class="toc-title" style="margin-bottom:12px">相关文档</div>
          <a-list :data-source="currentDetailDoc.relatedDocs" size="small">
            <template #renderItem="{ item }">
              <a-list-item class="related-item" @click="openDocumentById(item.id)">🔗 {{ item.title }}</a-list-item>
            </template>
          </a-list>
        </div>
      </div>

      <!-- ================= 新建文档 ================= -->
      <div v-else-if="currentPage === 'create'" class="kb-page kb-create-page">
        <a-card :bordered="false" class="new-card">
          <a-tabs v-model:activeKey="createActiveTab">
            <a-tab-pane key="template" tab="从模板新建">
              <div class="template-grid">
                <div class="template-card" v-for="tpl in templates" :key="tpl.name" @click="createFromTemplate(tpl)">
                  <div class="icon" :style="{ background: tpl.bg, color: tpl.color }">{{ tpl.icon }}</div>
                  <div class="name">{{ tpl.name }}</div>
                  <div class="desc">{{ tpl.desc }}</div>
                </div>
              </div>
            </a-tab-pane>
            <a-tab-pane key="blank" tab="空白文档">
              <div class="blank-editor">
                <input class="blank-title" v-model="newDocTitle" placeholder="无标题文档" />
                <a-textarea class="blank-content" v-model="newDocContent" placeholder="开始输入正文…" :auto-size="{ minRows: 8 }" />
                <div class="blank-actions">
                  <a-button @click="navigateTo('home')">取消</a-button>
                  <a-button type="primary" @click="createBlankDoc">创建文档</a-button>
                </div>
              </div>
            </a-tab-pane>
            <a-tab-pane key="upload" tab="上传文件">
              <div class="upload-zone" @click="triggerUpload" @dragover.prevent @drop.prevent="handleDrop">
                <div class="uicon">📤</div>
                <h3>拖拽文件到此处，或点击选择</h3>
                <p>支持 PDF / Word / Markdown / TXT / PPT / Excel 等格式</p>
                <input ref="fileInput" type="file" multiple hidden @change="handleFileSelect" />
              </div>
              <div class="upload-list" v-if="uploadList.length">
                <div class="upload-item" v-for="(file, idx) in uploadList" :key="idx">
                  <div class="file-icon" :style="{ background: file.color }">{{ file.ext }}</div>
                  <div class="file-info">
                    <div class="file-name">{{ file.name }}</div>
                    <div class="file-meta">{{ file.size }} · {{ file.status }}</div>
                    <div v-if="file.progress < 100" class="progress-bar"><div class="fill" :style="{ width: file.progress + '%' }"></div></div>
                    <a v-if="file.inLibrary" class="lib-link" @click="navigateTo('home')">✓ 已加入文档库 · 查看</a>
                  </div>
                  <a-tag :color="file.tagType">{{ file.tagText }}</a-tag>
                  <a-button type="text" size="small" class="action-del sm" @click.stop="removeUploadItem(idx)">✕</a-button>
                </div>
              </div>
            </a-tab-pane>
          </a-tabs>
        </a-card>
      </div>

      <!-- ================= 全局搜索 ================= -->
      <div v-else-if="currentPage === 'search'" class="kb-page">
        <div class="big-search">
          <span class="sicon">🔍</span>
          <input v-model="searchQuery" @input="doSearch" placeholder="输入关键词搜索文档、成员、知识库…" />
          <a-button type="primary" @click="doSearch">搜索</a-button>
        </div>
        <template v-if="!hasSearched">
          <div class="search-welcome">
            <div class="sw-icon">🔍</div>
            <h3>搜索知识库</h3>
            <p>输入关键词，快速找到文档、成员和相关知识</p>
          </div>
        </template>
        <template v-else>
          <a-tabs v-model:activeKey="searchResultTab">
            <a-tab-pane v-for="t in resultTabs" :key="t.key" :tab="`${t.label} (${t.count})`"></a-tab-pane>
          </a-tabs>
          <div class="result-list" v-if="searchResults.length">
            <div class="result-item" v-for="r in searchResults" :key="r.id" @click="r.doc && openDocument(r.doc)">
              <div class="ricon" :style="{ background: r.iconBg, color: r.iconColor }">{{ r.typeIcon }}</div>
              <div class="rbody">
                <div class="rtitle" v-html="highlightText(r.title)"></div>
                <div class="rexcerpt" v-html="highlightText(r.excerpt)"></div>
                <div class="rmeta">
                  <span v-if="r.category">{{ r.category }}</span><span class="dot" v-if="r.category"></span>
                  <span>{{ r.author }}</span><span class="dot"></span><span>{{ r.date }}</span>
                </div>
              </div>
            </div>
          </div>
          <a-empty v-else description="未找到相关结果" />
        </template>
      </div>

      <!-- ================= 我的收藏 ================= -->
      <div v-else-if="currentPage === 'favorites'" class="kb-page">
        <div class="page-title-row">
          <div><h2>我的收藏</h2><div class="sub">共 {{ favorites.length }} 篇收藏文档</div></div>
          <div class="right">
            <a-radio-group v-model:value="favViewMode" option-type="button" button-style="solid">
              <a-radio-button value="grid">卡片</a-radio-button>
              <a-radio-button value="list">列表</a-radio-button>
            </a-radio-group>
          </div>
        </div>
        <a-empty v-if="!favorites.length" description="还没有收藏任何文档" />
        <div v-else class="fav-grid" v-show="favViewMode === 'grid'">
          <div v-for="doc in favorites" :key="doc.id" class="fav-card" @click="openDocument(doc)">
            <span class="fstar">★</span>
            <div class="ficon" :style="{ background: doc.iconBg, color: doc.iconColor }">{{ doc.typeIcon }}</div>
            <div class="ftitle">{{ doc.title }}</div>
            <div class="fdesc">{{ doc.excerpt }}</div>
            <div class="fmeta"><span>{{ doc.author }}</span><span class="dot"></span><span>{{ doc.updatedAt }}</span></div>
          </div>
        </div>
        <a-list v-show="favViewMode === 'list'" :data-source="favorites" class="doc-list" :split="false" item-layout="horizontal">
          <template #renderItem="{ item }">
            <a-list-item class="doc-card" @click="openDocument(item)">
              <div class="doc-card-icon" :style="{ background: item.iconBg, color: item.iconColor }">{{ item.typeIcon }}</div>
              <div class="doc-card-info">
                <div class="doc-card-title">{{ item.title }}</div>
                <div class="doc-card-desc">{{ item.excerpt }}</div>
                <div class="doc-card-meta"><span>{{ item.author }}</span><span class="dot"></span><span>{{ item.updatedAt }}</span><span class="dot"></span><a-tag :color="item.statusColor">{{ item.statusText }}</a-tag></div>
              </div>
            </a-list-item>
          </template>
        </a-list>
      </div>

      <!-- ================= 与我共享 ================= -->
      <div v-else-if="currentPage === 'shared'" class="kb-page">
        <div class="page-title-row">
          <div><h2>与我共享</h2><div class="sub">共 {{ filteredSharedDocs.length }} 篇文档由他人共享给你</div></div>
          <div class="right">
            <a-radio-group v-model:value="shareFilter" option-type="button" button-style="solid">
              <a-radio-button value="all">全部</a-radio-button>
              <a-radio-button value="editable">可编辑</a-radio-button>
              <a-radio-button value="readonly">只读</a-radio-button>
            </a-radio-group>
          </div>
        </div>
        <a-list :data-source="filteredSharedDocs" class="share-list" :split="false">
          <template #renderItem="{ item }">
            <a-list-item class="share-item" @click="openSharedDoc(item)">
              <div class="sicon" :style="{ background: item.iconBg, color: item.iconColor }">{{ item.typeIcon }}</div>
              <div class="sinfo">
                <div class="stitle">{{ item.title }}</div>
                <div class="smeta">
                  <div class="from-user">
                    <span class="avatar-sm" :style="{ background: item.sharedByAvatar }">{{ item.sharedBy.charAt(0) }}</span>
                    来自 {{ item.sharedBy }} · {{ item.sharedTime }}
                  </div>
                </div>
                <div class="smeta">
                  <span>{{ item.category }}</span>
                  <a-tag :color="item.editable ? 'success' : 'default'">{{ item.editable ? '可编辑' : '只读' }}</a-tag>
                </div>
              </div>
              <div class="sactions"><a-button size="small" @click.stop="openSharedDoc(item)">打开</a-button></div>
            </a-list-item>
          </template>
        </a-list>
      </div>

      <!-- ================= 回收站 ================= -->
      <div v-else-if="currentPage === 'trash'" class="kb-page">
        <div class="page-title-row">
          <div><h2>回收站</h2><div class="sub">已删除的文档会保留 30 天，过后将自动彻底清除</div></div>
        </div>
        <div class="recycle-banner">
          <span class="ricon">♻️</span>
          <div class="rtext">回收站中的文档可在 <strong>30 天</strong> 内恢复，彻底删除后不可恢复。</div>
        </div>
        <div class="recycle-list">
          <div class="recycle-item" v-for="doc in trashDocs" :key="doc.id">
            <div class="ricon">📄</div>
            <div class="rinfo">
              <div class="rname">{{ doc.title }}</div>
              <div class="rmeta">
                <span>原路径：{{ doc.originalPath }}</span><span class="dot"></span>
                <span>{{ doc.deletedBy }} 删除于 {{ doc.deletedAt }}</span><span class="dot"></span>
                <span class="countdown" :class="{ danger: doc.daysLeft <= 10 }">剩余 {{ doc.daysLeft }} 天</span>
              </div>
            </div>
            <div class="ractions">
              <a-button size="small" @click="restoreDoc(doc)">↩️ 恢复</a-button>
              <a-popconfirm title="彻底删除后不可恢复，确定？" ok-text="彻底删除" cancel-text="取消" @confirm="purgeDoc(doc)">
                <a-button size="small" danger>彻底删除</a-button>
              </a-popconfirm>
            </div>
          </div>
          <a-empty v-if="!trashDocs.length" description="回收站为空" />
        </div>
      </div>

      <!-- ================= 成员与权限 ================= -->
      <div v-else-if="currentPage === 'members'" class="kb-page">
        <div class="page-header-row">
          <div><h2>成员与权限</h2><div class="page-desc">管理知识库成员、角色与访问权限</div></div>
          <div class="header-actions">
            <a-button type="primary" @click="showInviteModal = true">+ 邀请成员</a-button>
          </div>
        </div>

        <a-row :gutter="16" class="stat-row">
          <a-col :span="6" v-for="card in memberStats" :key="card.label">
            <a-card :bordered="false" class="stat-card">
              <div class="stat-inner">
                <div class="sicon" :style="{ background: card.bg, color: card.color }">{{ card.icon }}</div>
                <div class="sinfo">
                  <div class="slabel">{{ card.label }}</div>
                  <div class="snum">{{ card.value }}</div>
                  <div class="ssub">{{ card.sub }}</div>
                </div>
              </div>
            </a-card>
          </a-col>
        </a-row>

        <a-card :bordered="false" class="section-card">
          <a-tabs v-model:activeKey="memberTab">
            <a-tab-pane v-for="t in memberTabs" :key="t.key" :tab="`${t.label}${t.count !== undefined ? ' (' + t.count + ')' : ''}`"></a-tab-pane>
          </a-tabs>

          <div v-if="memberTab === 'list'">
            <a-table
              :columns="memberColumns"
              :data-source="members"
              :row-selection="rowSelection"
              row-key="id"
              :pagination="false"
              size="middle"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'member'">
                  <div class="member-cell">
                    <a-avatar :size="32" :style="{ background: record.avatarBg }">{{ record.name.charAt(0) }}</a-avatar>
                    <div class="info">
                      <div class="name">{{ record.name }}
                        <a-tag v-if="record.online" color="success">在线</a-tag>
                        <a-tag v-if="record.isMe" color="blue">我</a-tag>
                      </div>
                      <div class="email">{{ record.email }}</div>
                    </div>
                  </div>
                </template>
                <template v-else-if="column.key === 'role'">
                  <a-tag :color="roleColor(record.roleType)">{{ record.roleLabel }}</a-tag>
                </template>
                <template v-else-if="column.key === 'action'">
                  <a @click="toggleMemberSelect(record.id)">设置</a>
                  <a-popconfirm title="确定移出该成员？" ok-text="移出" cancel-text="取消" @confirm="removeMember(record)">
                    <a style="color:#ff4d4f;margin-left:12px">移出</a>
                  </a-popconfirm>
                </template>
              </template>
            </a-table>
          </div>

          <div v-else-if="memberTab === 'roles'" class="perm-matrix">
            <div class="perm-row head">
              <div class="perm-name">权限项</div>
              <div class="perm-cell">超级管理员</div>
              <div class="perm-cell">管理员</div>
              <div class="perm-cell">编辑者</div>
              <div class="perm-cell">只读</div>
            </div>
            <div class="perm-row" v-for="(p, i) in permissions" :key="i">
              <div class="perm-name">{{ p.name }}</div>
              <div class="perm-cell"><span :class="permClass(p.admin)">{{ formatPerm(p.admin) }}</span></div>
              <div class="perm-cell"><span :class="permClass(p.manager)">{{ formatPerm(p.manager) }}</span></div>
              <div class="perm-cell"><span :class="permClass(p.editor)">{{ formatPerm(p.editor) }}</span></div>
              <div class="perm-cell"><span :class="permClass(p.viewer)">{{ formatPerm(p.viewer) }}</span></div>
            </div>
          </div>

          <div v-else class="empty-state">
            <a-empty :description="memberTab === 'invites' ? '暂无邀请记录' : '暂无操作日志'" />
          </div>
        </a-card>

        <a-modal v-model:open="showInviteModal" title="邀请成员" @ok="showInviteModal = false" @cancel="showInviteModal = false">
          <a-form layout="vertical">
            <a-form-item label="邮箱地址">
              <a-input placeholder="输入成员邮箱，多个用逗号分隔" />
            </a-form-item>
            <a-form-item label="角色">
              <a-select default-value="editor">
                <a-select-option value="editor">编辑者</a-select-option>
                <a-select-option value="viewer">只读</a-select-option>
                <a-select-option value="admin">管理员</a-select-option>
              </a-select>
            </a-form-item>
          </a-form>
        </a-modal>
      </div>

      <!-- ================= AI 助手 ================= -->
      <div v-else-if="currentPage === 'ai'" class="kb-page">
        <div class="chat-layout">
          <div class="chat-sidebar">
            <a-button class="chat-new-btn" block @click="clearChatMessages">✨ 新建对话</a-button>
            <div class="chat-history-group">
              <div class="chat-history-label">今天</div>
              <button class="chat-history-item" v-for="h in chatHistoryToday" :key="h.id" :class="{ active: activeChatId === h.id }" @click="activeChatId = h.id">{{ h.question }}<div class="time">{{ h.time }}</div></button>
            </div>
            <div class="chat-history-group">
              <div class="chat-history-label">昨天</div>
              <button class="chat-history-item" v-for="h in chatHistoryYesterday" :key="h.id" @click="activeChatId = h.id">{{ h.question }}<div class="time">{{ h.time }}</div></button>
            </div>
          </div>
          <div class="chat-main">
            <div class="chat-topbar">
              <span class="title">💡 AI 智能助手 <a-tag color="success">在线</a-tag></span>
              <a-button type="text" @click="clearChatMessages">清空记录</a-button>
            </div>
            <div class="chat-messages">
              <template v-if="!chatMessages.length">
                <div class="chat-welcome">
                  <div class="wicon">✨</div>
                  <h2>你好，我是知识中枢 AI</h2>
                  <p>基于团队知识库为你解答问题、总结文档、生成内容</p>
                  <div class="quick-questions">
                    <button class="quick-q" v-for="(q, i) in quickQuestions" :key="i" @click="askQuick(q.q)">
                      <div class="qicon">{{ q.icon }}</div>
                      <div class="qtext">{{ q.q }}</div>
                      <div class="qhint">{{ q.hint }}</div>
                    </button>
                  </div>
                </div>
              </template>
              <template v-else>
                <div v-for="(m, i) in chatMessages" :key="i" class="msg" :class="m.role === 'user' ? 'msg-user' : 'msg-ai'">
                  <div class="avatar" :style="m.role === 'user' ? 'background:#1890ff' : 'background:linear-gradient(135deg,#722ed1,#9254de)'">{{ m.role === 'user' ? userInitial : 'AI' }}</div>
                  <div class="bubble" v-html="m.content"></div>
                </div>
              </template>
            </div>
            <div class="chat-input-bar">
              <div class="chat-input">
                <a-textarea v-model:value="chatInput" :auto-size="{ minRows: 1, maxRows: 4 }" @keydown.enter.exact.prevent="sendChatMessage" placeholder="输入问题，按 Enter 发送… 可使用 @ 引用文档、# 引用知识库" />
                <div class="send-btn" @click="sendChatMessage">↑</div>
              </div>
            </div>
          </div>
          <div class="chat-right">
            <div class="kb-scope">
              <div class="title">📚 检索范围</div>
              <div class="scope-item" v-for="(s, i) in scopeItems" :key="i"><span class="check">✓</span>{{ s.label }}</div>
            </div>
            <div class="ref-panel-title">📎 引用文档</div>
            <div class="ref-item" v-for="(ref, i) in chatRefs" :key="i" @click="openDocumentById(ref.id)">
              <div class="rt">{{ ref.title }}</div>
              <div class="rm">{{ ref.meta }}</div>
            </div>
          </div>
        </div>
      </div>

    </a-layout-content>
  </a-layout>
</a-layout>
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

const emit = defineEmits([
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

// antd 菜单点击：页面对应 navigateTo，分类项以 cat: 前缀区分
function handleMenu({ key }) {
  if (typeof key === 'string' && key.startsWith('cat:')) selectCategory(key.slice(4));
  else navigateTo(key);
}
const selectedMenuKeys = computed(() =>
  currentCategory.value ? ['cat:' + currentCategory.value] : [currentPage.value]
);

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
// 已删除的文档 id（防止外部接口回流时把刚删的文档加回列表）
const deletedIds = ref(new Set());

watch(
  () => props.knowledgeDocuments,
  (val) => {
    if (Array.isArray(val)) {
      const kept = val.filter((d) => !deletedIds.value.has(String(d.id)));
      mockDocuments.splice(0, mockDocuments.length, ...kept.map((d) => ({ ...d })));
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
  { icon: '📄', label: '总文档数', value: mockDocuments.length, sub: `${mockDocuments.filter(d => d.status === 'ready').length} 份可检索`, bg: '#E8F1FF', color: '#1890ff', up: true },
  { icon: '👥', label: '贡献成员', value: '6', sub: '本月活跃 5 人', bg: '#f6ffed', color: '#52c41a' },
  { icon: '👁️', label: '总阅读量', value: '2,214', sub: '↑ 12% 较上周', bg: '#f9f0ff', color: '#722ed1', up: true },
  { icon: '💬', label: '评论数', value: '38', sub: '本周新增 8 条', bg: '#fffbe6', color: '#faad14' },
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
  { name: '空白文档', desc: '从零开始撰写，适合自由格式的记录', icon: '📄', bg: '#E8F1FF', color: '#1890ff' },
  { name: '会议纪要', desc: '议题、决议、待办三段式结构，自动归档', icon: '📋', bg: '#f6ffed', color: '#52c41a' },
  { name: '需求文档 PRD', desc: '背景、目标、方案、排期完整框架', icon: '🎯', bg: '#fffbe6', color: '#faad14' },
  { name: '用户研究报告', desc: '访谈记录、洞察、机会点结构化模板', icon: '🔬', bg: '#f9f0ff', color: '#722ed1' },
  { name: '周报 / 月报', desc: '进展、风险、下周计划，支持数据图表', icon: '📈', bg: '#fff1f0', color: '#ff4d4f' },
  { name: 'SOP 操作手册', desc: '步骤化操作流程，支持图文与视频嵌入', icon: '📚', bg: '#e6f4ff', color: '#0EA5E9' },
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
  const colors = { PDF: '#ff4d4f', DOC: '#52c41a', XLS: '#faad14', PPT: '#722ed1', MD: '#1890ff' };
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
      item.status = '处理中';
      item.tagText = '处理中';
      item.tagType = 'warning';
      addUploadedDocToLibrary(file, item);
    } else {
      item.progress = Math.round(p);
    }
  }, 300);
}
function addUploadedDocToLibrary(file, item) {
  // 只有真实接口成功后，父组件才会通过回调标记已加入知识库。
  emit('upload-knowledge-document', file, (doc) => {
    item.inLibrary = Boolean(doc);
    if (doc) {
      item.status = doc.status === 'failed' ? '处理失败' : '已完成';
      item.tagText = doc.status === 'failed' ? '处理失败' : '可检索';
      item.tagType = doc.status === 'failed' ? 'error' : 'success';
    } else {
      item.status = '处理失败';
      item.tagText = '处理失败';
      item.tagType = 'error';
    }
  });
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
  { id: 'sh1', title: 'Q3 产品需求评审纪要', docId: 2, sharedBy: '王芳', sharedByAvatar: 'linear-gradient(135deg,#52c41a,#95de64)', sharedTime: '2 小时前分享', category: '产品设计', editable: true, typeIcon: '📊', iconBg: '#f6ffed', iconColor: '#52c41a' },
  { id: 'sh2', title: '用户行为数据汇总.xlsx', docId: null, sharedBy: '陈晨', sharedByAvatar: 'linear-gradient(135deg,#FF7A59,#FFB088)', sharedTime: '昨天分享', category: '产品设计', editable: false, typeIcon: '📊', iconBg: '#f6ffed', iconColor: '#52c41a' },
  { id: 'sh3', title: '微服务架构改造方案', docId: 5, sharedBy: '刘洋', sharedByAvatar: 'linear-gradient(135deg,#722ed1,#9254de)', sharedTime: '5 天前分享', category: '技术研发', editable: true, typeIcon: '⚙️', iconBg: '#e6f4ff', iconColor: '#0EA5E9' },
  { id: 'sh4', title: '8 月运营月报', docId: null, sharedBy: '赵雪', sharedByAvatar: 'linear-gradient(135deg,#faad14,#ffd666)', sharedTime: '1 周前分享', category: '运营手册', editable: false, typeIcon: '📈', iconBg: '#fffbe6', iconColor: '#faad14' },
  { id: 'sh5', title: '客户反馈原始记录 - 8月', docId: 9, sharedBy: '孙磊', sharedByAvatar: 'linear-gradient(135deg,#0EA5E9,#67C3F3)', sharedTime: '2 周前分享', category: '客户资料', editable: false, typeIcon: '📎', iconBg: '#fff1f0', iconColor: '#ff4d4f' },
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
// 从列表删除（进入回收站）
function deleteDoc(doc) {
  if (!doc) return;
  const id = String(doc.id);
  const idx = mockDocuments.findIndex((d) => String(d.id) === id);
  if (idx > -1) mockDocuments.splice(idx, 1);
  deletedIds.value.add(id);
  if (!trashDocs.some((t) => String(t.id) === id)) {
    trashDocs.unshift({
      id,
      title: doc.title,
      originalPath: (categoryMap[doc.category] || '知识库') + (doc.category ? ' / ' + doc.category : ''),
      deletedBy: '我',
      deletedAt: '刚刚',
      daysLeft: 30,
    });
  }
  if (currentDetailDoc.value && String(currentDetailDoc.value.id) === id) {
    currentDetailDoc.value = null;
    currentPage.value = 'home';
  }
  emit('delete-knowledge-document', id);
}

// 回收站 -> 彻底删除（不可恢复）
function purgeDoc(doc) {
  const idx = trashDocs.indexOf(doc);
  if (idx > -1) trashDocs.splice(idx, 1);
}

// 回收站 -> 恢复回列表
function restoreDoc(doc) {
  const idx = trashDocs.indexOf(doc);
  if (idx > -1) trashDocs.splice(idx, 1);
  const id = String(doc.id);
  deletedIds.value.delete(id);
  if (doc && !mockDocuments.some((d) => String(d.id) === id)) {
    mockDocuments.unshift({
      id,
      title: doc.title,
      category: 'product',
      typeIcon: '📄',
      iconBg: '#e6f4ff',
      iconColor: '#0EA5E9',
      excerpt: '已从回收站恢复',
      author: '我',
      updatedAt: '刚刚',
      statusColor: 'success',
      statusText: '可检索',
      isFavorite: false,
    });
  }
}

// 上传列表中移除某条记录（不影响已入库的文档）
function removeUploadItem(idx) {
  if (idx > -1 && idx < uploadList.length) uploadList.splice(idx, 1);
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
  { icon: '👥', label: '总成员数', value: 6, sub: '↑ 1 本月新增', bg: '#e6f7ff', color: '#1890ff' },
  { icon: '🔑', label: '管理员', value: 2, sub: '含 1 名超级管理员', bg: '#f6ffed', color: '#52c41a' },
  { icon: '✏️', label: '编辑者', value: 3, sub: '可创建和编辑文档', bg: '#fffbe6', color: '#faad14' },
  { icon: '⏳', label: '待处理邀请', value: 2, sub: '1 封已过期需重发', bg: '#fff1f0', color: '#ff4d4f' },
]);

const members = reactive([
  { id: 1, name: '张明', email: 'zhangming@company.com', roleType: 'admin', roleLabel: '🔑 超级管理员', dept: '产品中心', joinedAt: '2024-03-12', lastActive: '刚刚', online: true, isMe: true, avatarBg: 'linear-gradient(135deg,#1890ff,#69b1ff)' },
  { id: 2, name: '王芳', email: 'wangfang@company.com', roleType: 'admin', roleLabel: '🔑 管理员', dept: '产品中心', joinedAt: '2024-05-08', lastActive: '5 分钟前', online: true, isMe: false, avatarBg: 'linear-gradient(135deg,#52c41a,#95de64)' },
  { id: 3, name: '陈晨', email: 'chenchen@company.com', roleType: 'editor', roleLabel: '✏️ 编辑者', dept: '设计部', joinedAt: '2024-06-20', lastActive: '1 小时前', online: false, isMe: false, avatarBg: 'linear-gradient(135deg,#FF7A59,#FFB088)' },
  { id: 4, name: '刘洋', email: 'liuyang@company.com', roleType: 'editor', roleLabel: '✏️ 编辑者', dept: '研发部', joinedAt: '2024-07-15', lastActive: '昨天', online: false, isMe: false, avatarBg: 'linear-gradient(135deg,#722ed1,#9254de)' },
  { id: 5, name: '赵雪', email: 'zhaoxue@company.com', roleType: 'viewer', roleLabel: '👁️ 只读', dept: '运营部', joinedAt: '2024-08-01', lastActive: '3 天前', online: false, isMe: false, avatarBg: 'linear-gradient(135deg,#faad14,#ffd666)' },
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

const memberColumns = [
  { title: '成员', key: 'member', dataIndex: 'name' },
  { title: '角色', key: 'role', dataIndex: 'roleLabel' },
  { title: '部门', dataIndex: 'dept' },
  { title: '最近活跃', dataIndex: 'lastActive', width: 120 },
  { title: '操作', key: 'action', width: 140 },
];
const rowSelection = computed(() => ({
  selectedRowKeys: selectedMembers.value,
  onChange: (keys) => { selectedMembers.value = keys; },
  columnWidth: 48,
}));
function roleColor(type) {
  if (type === 'admin') return 'gold';
  if (type === 'editor') return 'green';
  return 'default';
}
function removeMember(m) {
  const idx = members.findIndex(x => x.id === m.id);
  if (idx > -1) members.splice(idx, 1);
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
function permClass(v) { if (v === true) return 'perm-yes'; if (v === false) return 'perm-no'; return 'perm-partial'; }

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
.kb-app { --primary:#1890ff;--primary-hover:#40a9ff;--primary-bg:#e6f7ff;
  --success:#52c41a;--success-bg:#f6ffed;
  --warning:#faad14;--warning-bg:#fffbe6;
  --danger:#ff4d4f;--danger-bg:#fff1f0;
  --purple:#722ed1;--purple-bg:#f9f0ff;
  --text:rgba(0,0,0,.88);--text-secondary:rgba(0,0,0,.65);--text-tertiary:rgba(0,0,0,.45);
  --border:#d9d9d9;--border-light:#f0f0f0;
  --bg:#f0f2f5;--bg-soft:#fafafa;--card:#FFFFFF;
  --radius-sm:6px;--radius:8px;--radius-lg:12px;--radius-xl:16px;
  display:flex;flex-direction:column;height:100%;background:var(--bg);font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei","Helvetica Neue",Arial,sans-serif;font-size:14px;color:var(--text);line-height:1.5; }

/* ====== 顶部导航 ====== */
.kb-topnav{display:flex;align-items:center;padding:0 20px;height:52px;background:#fff;border-bottom:1px solid var(--border);gap:24px;flex-shrink:0;z-index:10;}
.kb-logo{display:flex;align-items:center;gap:8px;font-weight:700;font-size:15px;flex-shrink:0;}
.kb-logo-mark{width:28px;height:28px;background:linear-gradient(135deg,#1890ff,#69b1ff);border-radius:8px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:14px;font-weight:700;}
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

/* ====== 删除/危险操作按钮 ====== */
.action-del{width:28px;height:28px;border-radius:var(--radius-sm);border:none;background:none;color:var(--text-tertiary);cursor:pointer;font-size:14px;display:flex;align-items:center;justify-content:center;transition:all .15s;}
.action-del:hover{background:#fff1f0;color:#ff4d4f;}
.action-del.sm{width:22px;height:22px;font-size:12px;}
.btn-danger{color:#ff4d4f !important;border-color:#ffccc7 !important;}
.btn-danger:hover{background:#fff1f0 !important;color:#cf1322 !important;border-color:#ff4d4f !important;}

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

.usage-card{margin-top:12px;padding:12px;background:linear-gradient(135deg,#FFF9E6,#fffbe6);border-radius:var(--radius);}
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
.stat-row{margin-bottom:20px;}
.stat-card{height:100%;}
.stat-inner{display:flex;align-items:flex-start;gap:14px;}
.stat-card .sicon{width:44px;height:44px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0;}
.stat-card .sinfo{flex:1;}
.stat-card .slabel{font-size:12px;color:var(--text-secondary);}
.stat-card .snum{font-size:26px;font-weight:700;margin:2px 0;}
.stat-card .ssub{font-size:11px;color:var(--text-tertiary);}
.stat-card .ssub.up{color:var(--success);font-weight:600;}

/* ====== 筛选栏 ====== */
.filter-bar{display:flex;align-items:center;gap:12px;padding:12px 16px;background:#fff;border-radius:var(--radius-lg);border:1px solid #f0f0f0;margin-bottom:16px;flex-wrap:wrap;}
.filter-search{background:var(--bg-soft);border:1px solid var(--border);border-radius:6px;padding:5px 10px;font-size:13px;color:var(--text);width:220px;outline:none;}
.filter-search:focus{border-color:var(--primary);}
.filter-chip{padding:4px 12px;border-radius:999px;font-size:12px;border:1px solid var(--border);color:var(--text-secondary);cursor:pointer;background:#fff;}
.filter-chip.active{background:var(--primary-bg);color:var(--primary);border-color:var(--primary);}
.filter-right{margin-left:auto;}

/* ====== 文档列表 ====== */
.doc-list{display:flex;flex-direction:column;gap:8px;}
.doc-card{background:#fff;border-radius:var(--radius-lg);padding:16px 20px;border:1px solid #f0f0f0;display:flex;align-items:center;gap:14px;cursor:pointer;transition:all .2s;}
.doc-card:hover{border-color:#91d5ff;}
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
.doc-header{background:#fff;border-radius:var(--radius-lg);padding:20px 24px;border:1px solid #f0f0f0;margin-bottom:16px;}
.doc-title-row{display:flex;align-items:flex-start;gap:12px;margin-bottom:12px;}
.doc-title-row h1{font-size:22px;font-weight:700;flex:1;margin:0;}
.doc-actions{display:flex;gap:8px;}
.doc-meta{display:flex;align-items:center;gap:16px;font-size:12px;color:var(--text-secondary);flex-wrap:wrap;}
.meta-item{display:flex;align-items:center;gap:4px;}
.dot{width:3px;height:3px;border-radius:50%;background:var(--text-tertiary);}

/* AI摘要 */
.ai-summary-box{background:linear-gradient(135deg,#f9f0ff,#F5F0FF);border:1px solid #efdbff;border-radius:var(--radius-lg);padding:16px 20px;margin-bottom:16px;}
.ai-head{display:flex;align-items:center;gap:8px;margin-bottom:8px;font-size:13px;font-weight:600;color:var(--purple);}
.ai-summary-box p{font-size:13px;color:var(--text);line-height:1.7;margin:0;}
.ai-actions{display:flex;gap:8px;margin-top:10px;}
.ai-chip{background:#fff;border:1px solid #efdbff;color:var(--purple);padding:3px 10px;border-radius:999px;font-size:11px;cursor:pointer;}

/* 正文+目录 */
.doc-body{display:grid;grid-template-columns:1fr 240px;gap:20px;}
.doc-content{background:#fff;border-radius:var(--radius-lg);padding:32px 40px;border:1px solid #f0f0f0;min-height:400px;}
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

.doc-toc{background:#fff;border-radius:var(--radius-lg);padding:16px;border:1px solid #f0f0f0;height:fit-content;position:sticky;top:20px;}
.toc-title{font-size:12px;color:var(--text-tertiary);font-weight:600;margin-bottom:12px;text-transform:uppercase;letter-spacing:.5px;}
.toc-list{list-style:none;padding:0;margin:0;}
.toc-list li{padding:6px 8px;font-size:13px;color:var(--text-secondary);cursor:pointer;border-left:2px solid transparent;border-radius:0 var(--radius-sm) var(--radius-sm) 0;}
.toc-list li.active{color:var(--primary);background:var(--primary-bg);border-left-color:var(--primary);font-weight:500;}
.toc-list li.sub{padding-left:24px;font-size:12px;}
.toc-list li:hover:not(.active){background:var(--bg-soft);}

/* 评论 */
.comments{background:#fff;border-radius:var(--radius-lg);padding:20px 24px;border:1px solid #f0f0f0;margin-top:16px;}
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
.new-tabs{display:flex;gap:4px;background:#fff;padding:4px;border-radius:var(--radius);width:fit-content;margin:0 auto 28px;border:1px solid #f0f0f0;}
.new-tab{padding:8px 20px;border-radius:var(--radius-sm);font-size:13px;color:var(--text-secondary);cursor:pointer;font-weight:500;background:none;border:none;}
.new-tab.active{background:var(--primary);color:#fff;}
.template-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:24px;}
.template-card{background:#fff;border:1px solid var(--border);border-radius:var(--radius-lg);padding:20px;cursor:pointer;transition:all .2s;}
.template-card:hover{border-color:var(--primary);}
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

.blank-editor{background:#fff;border-radius:var(--radius-lg);padding:24px;border:1px solid #f0f0f0;}
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
.result-item{background:#fff;border-radius:var(--radius-lg);padding:16px 20px;border:1px solid #f0f0f0;cursor:pointer;transition:all .2s;display:flex;gap:14px;}
.result-item:hover{border-color:#91d5ff;}
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
.fav-card{background:#fff;border-radius:var(--radius-lg);padding:18px 20px;border:1px solid #f0f0f0;cursor:pointer;transition:all .2s;position:relative;}
.fav-card:hover{border-color:#91d5ff;}
.fav-card .fstar{position:absolute;top:14px;right:14px;color:var(--warning);font-size:16px;}
.fav-card .ficon{width:36px;height:36px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:16px;margin-bottom:10px;}
.fav-card .ftitle{font-size:14px;font-weight:600;margin-bottom:6px;line-height:1.4;}
.fav-card .fdesc{font-size:12px;color:var(--text-secondary);line-height:1.6;margin-bottom:10px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.fav-card .fmeta{display:flex;align-items:center;gap:8px;font-size:11px;color:var(--text-tertiary);}
.fav-card .fmeta .dot{width:3px;height:3px;border-radius:50%;background:var(--text-tertiary);}

/* ====== 与我共享 ====== */
.share-list{display:flex;flex-direction:column;gap:10px;}
.share-item{background:#fff;border-radius:var(--radius-lg);padding:16px 20px;border:1px solid #f0f0f0;display:flex;align-items:center;gap:14px;}
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
.recycle-item{background:#fff;border-radius:var(--radius-lg);padding:14px 20px;border:1px solid #f0f0f0;display:flex;align-items:center;gap:14px;}
.recycle-item .ricon{width:36px;height:36px;border-radius:8px;background:var(--bg-soft);display:flex;align-items:center;justify-content:center;font-size:16px;color:var(--text-tertiary);flex-shrink:0;}
.rinfo{flex:1;min-width:0;}
.rname{font-size:14px;font-weight:500;margin-bottom:3px;color:var(--text-secondary);}
.rmeta{font-size:11px;color:var(--text-tertiary);display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
.rmeta .dot{width:3px;height:3px;border-radius:50%;background:var(--text-tertiary);}
.countdown{font-size:11px;font-weight:500;}
.countdown.danger{color:var(--danger);}
.ractions{display:flex;gap:8px;flex-shrink:0;}

/* ====== 成员管理 ====== */
.section-card{background:#fff;border-radius:var(--radius-lg);border:1px solid #f0f0f0;overflow:hidden;margin-bottom:16px;}
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
.wicon{width:64px;height:64px;border-radius:16px;background:linear-gradient(135deg,var(--purple),#9254de);color:#fff;font-size:32px;display:flex;align-items:center;justify-content:center;margin:0 auto 16px;}
.chat-welcome h2{font-size:22px;margin-bottom:8px;}
.chat-welcome p{color:var(--text-secondary);margin-bottom:24px;font-size:14px;}
.quick-questions{display:grid;grid-template-columns:1fr 1fr;gap:12px;max-width:560px;margin:0 auto;}
.quick-q{background:#fff;border:1px solid var(--border);border-radius:10px;padding:14px 16px;cursor:pointer;text-align:left;transition:all .2s;}
.quick-q:hover{border-color:var(--purple);}
.quick-q .qicon{font-size:20px;margin-bottom:6px;}
.quick-q .qtext{font-size:13px;font-weight:500;}
.quick-q .qhint{font-size:11px;color:var(--text-tertiary);margin-top:2px;}
.msg{margin-bottom:24px;max-width:760px;display:flex;gap:12px;}
.msg-user{flex-direction:row-reverse;}
.msg .avatar{width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;flex-shrink:0;color:#fff;}
.msg-user .bubble{background:var(--primary);color:#fff;padding:10px 14px;border-radius:12px 12px 2px 12px;font-size:14px;line-height:1.6;}
.msg-ai .bubble{background:#fff;padding:16px 20px;border-radius:2px 12px 12px 12px;border:1px solid #f0f0f0;font-size:14px;line-height:1.8;flex:1;}
.msg-ai .bubble :deep(p){margin-bottom:8px;}
.msg-ai .bubble :deep(ul){padding-left:20px;margin-bottom:8px;}
.msg-ai .bubble :deep(li){margin-bottom:4px;}
.chat-input-bar{padding:16px 40px 20px;background:var(--bg);border-top:1px solid var(--border);}
.chat-input{background:#fff;border:1px solid var(--border);border-radius:12px;padding:12px 16px;display:flex;align-items:flex-end;gap:12px;border:1px solid #f0f0f0;}
.chat-input .textarea{flex:1;font-size:14px;color:var(--text);min-height:24px;line-height:1.6;border:none;outline:none;resize:none;font-family:inherit;background:transparent;}
.send-btn{width:36px;height:36px;border-radius:8px;background:var(--primary);color:#fff;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:16px;flex-shrink:0;border:none;}
.chat-input-hint{display:flex;gap:8px;margin-top:8px;align-items:center;}
.chat-input-hint .h{font-size:12px;color:var(--text-tertiary);cursor:pointer;padding:3px 8px;border-radius:4px;}
.chat-input-hint .h:hover{background:#fff;}
.chat-input-hint .shortcut{margin-left:auto;font-size:11px;color:var(--text-tertiary);}
.chat-right{background:#fff;border-left:1px solid var(--border);padding:20px 16px;overflow-y:auto;}
.kb-scope{background:var(--purple-bg);border:1px solid #efdbff;border-radius:8px;padding:12px;margin-bottom:16px;}
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

/* ====== antd 适配补充 ====== */
.kb-sidemenu{border-right:none;}
.kb-sidemenu .sb-ico{display:inline-block;width:18px;text-align:center;margin-right:8px;font-size:14px;}
.sb-ico{font-size:14px;}
.toc-item{padding:6px 8px;font-size:13px;color:var(--text-secondary);cursor:pointer;border-left:2px solid transparent;border-radius:0 var(--radius-sm) var(--radius-sm) 0;}
.toc-item.active{color:var(--primary);background:var(--primary-bg);border-left-color:var(--primary);font-weight:500;}
.toc-item.sub{padding-left:24px;font-size:12px;}
.toc-item:hover:not(.active){background:var(--bg-soft);}
.new-card{border-radius:var(--radius-lg);}
.related{margin-top:16px;}
.related-item{cursor:pointer;color:var(--text-secondary);}
.related-item:hover{color:var(--primary);}
.perm-name{font-weight:600;color:var(--text-secondary);}
.perm-cell{text-align:center;}
</style>
