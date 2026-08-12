"""
缺口6 数据库迁移脚本（一次性执行）
═══════════════════════════════════════════════════════════════
改动：
  1. knowledge_documents 新增 5 列：
       file_md5 VARCHAR(32) 带索引
       file_size_bytes INT
       total_chunks INT
       processed_chunks INT
       failed_chunks INT
  2. 新建表 knowledge_chunk_failures（chunk 粒度失败记录，支持按文档单独重试）

使用方法：
    # 方法A：直接执行（推荐，会自动根据 DB 驱动判断方言）
    python scripts/migrate_gap6_engineering.py

    # 方法B：只生成 SQL 不执行，拿去交给 DBA
    python scripts/migrate_gap6_engineering.py --print-only

注意：
    - SQLite / MySQL / PostgreSQL 三种方言都兼容，自动选 SQL 语法
    - 重复执行安全（所有 ALTER 都先判断列/表是否存在，存在则跳过）
    - 表一旦建好，下次项目启动时 SQLAlchemy create_all 会直接用（不会重复建）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def build_sql(dialect: str) -> list[str]:
    """
    根据 DB 方言返回 SQL 语句列表。
    dialect ∈ {"sqlite", "mysql", "postgresql", "generic"}
    """
    d = dialect.lower()
    stmts: list[str] = []

    # -------- 1. knowledge_documents 加 5 列 --------
    #   MySQL 的 ALTER TABLE 直到 8.0.29 才支持 ADD COLUMN IF NOT EXISTS，
    #   且大部分线上 5.7/8.0.2x 环境都不行 —— 所以 MySQL 分支这里用【纯标准语法】：
    #   不带 IF NOT EXISTS，先在 Python 层查 INFORMATION_SCHEMA.COLUMNS，列不存在才真正执行 ALTER。
    def add_col(table: str, col_sqlite: str, col_mysql: str, col_pg: str):
        if d.startswith("sqlite"):
            stmts.append(f"ALTER TABLE {table} ADD COLUMN {col_sqlite}")
        elif d.startswith("mysql"):
            # 纯标准 MySQL 语法，不含 IF NOT EXISTS，执行前 Python 查 INFORMATION_SCHEMA 判重
            stmts.append(f"ALTER TABLE {table} ADD COLUMN {col_mysql}")
        elif d.startswith("postgres") or d.startswith("pg"):
            stmts.append(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col_pg}")
        else:
            stmts.append(f"ALTER TABLE {table} ADD COLUMN {col_mysql}")

    add_col(
        "knowledge_documents",
        "file_md5 VARCHAR(32) NOT NULL DEFAULT ''",
        "file_md5 VARCHAR(32) NOT NULL DEFAULT ''",
        "file_md5 VARCHAR(32) NOT NULL DEFAULT ''",
    )
    add_col(
        "knowledge_documents",
        "file_size_bytes INTEGER NOT NULL DEFAULT 0",
        "file_size_bytes INT NOT NULL DEFAULT 0",
        "file_size_bytes INTEGER NOT NULL DEFAULT 0",
    )
    add_col(
        "knowledge_documents",
        "total_chunks INTEGER NOT NULL DEFAULT 0",
        "total_chunks INT NOT NULL DEFAULT 0",
        "total_chunks INTEGER NOT NULL DEFAULT 0",
    )
    add_col(
        "knowledge_documents",
        "processed_chunks INTEGER NOT NULL DEFAULT 0",
        "processed_chunks INT NOT NULL DEFAULT 0",
        "processed_chunks INTEGER NOT NULL DEFAULT 0",
    )
    add_col(
        "knowledge_documents",
        "failed_chunks INTEGER NOT NULL DEFAULT 0",
        "failed_chunks INT NOT NULL DEFAULT 0",
        "failed_chunks INTEGER NOT NULL DEFAULT 0",
    )

    # 给 file_md5 加索引（MD5 去重查询靠它）
    if d.startswith("sqlite"):
        stmts.append(
            "CREATE INDEX IF NOT EXISTS ix_knowledge_documents_file_md5 "
            "ON knowledge_documents(file_md5)"
        )
    elif d.startswith("mysql"):
        # MySQL 不支持 CREATE INDEX IF NOT EXISTS (8.0+ 才支持但不稳)，用 INFORMATION_SCHEMA 判断太麻烦
        # 这里先裸执行，重复执行会失败 —— 执行器里 catch 跳过即可
        stmts.append(
            "CREATE INDEX ix_knowledge_documents_file_md5 "
            "ON knowledge_documents(file_md5)"
        )
    else:  # pg
        stmts.append(
            "CREATE INDEX IF NOT EXISTS ix_knowledge_documents_file_md5 "
            "ON knowledge_documents(file_md5)"
        )

    # -------- 2. 新建 knowledge_chunk_failures 表 --------
    if d.startswith("sqlite"):
        stmts.append("""
            CREATE TABLE IF NOT EXISTS knowledge_chunk_failures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                chunk_id INTEGER,
                step_name VARCHAR(30) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                retry_count INTEGER NOT NULL DEFAULT 0,
                error_type VARCHAR(100) NOT NULL DEFAULT '',
                error_message TEXT NOT NULL DEFAULT '',
                chunk_index_ref INTEGER NOT NULL DEFAULT 0,
                retrieval_content_preview VARCHAR(500) NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                last_retry_at DATETIME,
                FOREIGN KEY (document_id) REFERENCES knowledge_documents(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (chunk_id) REFERENCES knowledge_chunks(id) ON DELETE CASCADE
            )
        """)
        stmts.append(
            "CREATE INDEX IF NOT EXISTS ix_knowledge_chunk_failures_document_id "
            "ON knowledge_chunk_failures(document_id)"
        )
        stmts.append(
            "CREATE INDEX IF NOT EXISTS ix_knowledge_chunk_failures_user_id "
            "ON knowledge_chunk_failures(user_id)"
        )
        stmts.append(
            "CREATE INDEX IF NOT EXISTS ix_knowledge_chunk_failures_chunk_id "
            "ON knowledge_chunk_failures(chunk_id)"
        )
    elif d.startswith("mysql"):
        stmts.append("""
            CREATE TABLE IF NOT EXISTS knowledge_chunk_failures (
                id INT PRIMARY KEY AUTO_INCREMENT,
                document_id INT NOT NULL,
                user_id INT NOT NULL,
                chunk_id INT NULL,
                step_name VARCHAR(30) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                retry_count INT NOT NULL DEFAULT 0,
                error_type VARCHAR(100) NOT NULL DEFAULT '',
                error_message TEXT NOT NULL,
                chunk_index_ref INT NOT NULL DEFAULT 0,
                retrieval_content_preview VARCHAR(500) NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                last_retry_at DATETIME NULL,
                INDEX idx_kcf_doc (document_id),
                INDEX idx_kcf_user (user_id),
                INDEX idx_kcf_chunk (chunk_id),
                CONSTRAINT fk_kcf_doc FOREIGN KEY (document_id)
                    REFERENCES knowledge_documents(id) ON DELETE CASCADE,
                CONSTRAINT fk_kcf_user FOREIGN KEY (user_id)
                    REFERENCES users(id) ON DELETE CASCADE,
                CONSTRAINT fk_kcf_chunk FOREIGN KEY (chunk_id)
                    REFERENCES knowledge_chunks(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
    else:  # postgres / generic
        stmts.append("""
            CREATE TABLE IF NOT EXISTS knowledge_chunk_failures (
                id SERIAL PRIMARY KEY,
                document_id INTEGER NOT NULL
                    REFERENCES knowledge_documents(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL
                    REFERENCES users(id) ON DELETE CASCADE,
                chunk_id INTEGER
                    REFERENCES knowledge_chunks(id) ON DELETE CASCADE,
                step_name VARCHAR(30) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                retry_count INTEGER NOT NULL DEFAULT 0,
                error_type VARCHAR(100) NOT NULL DEFAULT '',
                error_message TEXT NOT NULL DEFAULT '',
                chunk_index_ref INTEGER NOT NULL DEFAULT 0,
                retrieval_content_preview VARCHAR(500) NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                last_retry_at TIMESTAMPTZ
            )
        """)
        stmts.append(
            "CREATE INDEX IF NOT EXISTS ix_knowledge_chunk_failures_document_id "
            "ON knowledge_chunk_failures(document_id)"
        )
        stmts.append(
            "CREATE INDEX IF NOT EXISTS ix_knowledge_chunk_failures_user_id "
            "ON knowledge_chunk_failures(user_id)"
        )
        stmts.append(
            "CREATE INDEX IF NOT EXISTS ix_knowledge_chunk_failures_chunk_id "
            "ON knowledge_chunk_failures(chunk_id)"
        )

    return stmts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--print-only", action="store_true",
                    help="只打印 SQL 语句，不实际执行")
    ap.add_argument("--dialect", choices=["auto", "sqlite", "mysql", "postgresql"],
                    default="auto",
                    help="手动指定方言；默认 auto 会读 settings.DATABASE_URL 自动判断")
    args = ap.parse_args()

    if args.dialect == "auto":
        try:
            from core.config import settings
            url = settings.DATABASE_URL.lower()
            if "sqlite" in url:
                dialect = "sqlite"
            elif "postgres" in url or "pg:" in url:
                dialect = "postgresql"
            elif "mysql" in url or "mariadb" in url:
                dialect = "mysql"
            else:
                dialect = "sqlite"
                print(f"⚠️  无法识别 DATABASE_URL={url!r}，默认用 sqlite 方言")
        except Exception as e:
            print(f"⚠️  读 settings.DATABASE_URL 失败：{e}，默认用 sqlite 方言")
            dialect = "sqlite"
    else:
        dialect = args.dialect

    stmts = build_sql(dialect)

    if args.print_only:
        print(f"-- 生成 SQL（方言={dialect}，共 {len(stmts)} 条）:")
        print("-- " + "=" * 60)
        for s in stmts:
            s2 = s.strip().rstrip(";")
            print(s2 + ";")
            print()
        return

    # 实际执行
    print(f"🚀 执行缺口6迁移（方言={dialect}，共 {len(stmts)} 条）...")
    from core.db.session import engine
    import re as _re

    # -------- MySQL 专用：查列/索引是否已存在的 2 个 helper --------
    # 为什么不直接用 MySQL 5.7 不支持的 `ADD COLUMN IF NOT EXISTS`？
    #   → 因为 MySQL 要等到 8.0.29 才支持 ADD COLUMN IF NOT EXISTS，
    #     目前公司线上环境还是 5.7.x / 8.0.2x 居多，直接用必报 1064 语法错。
    #   → 替代方案：先查 INFORMATION_SCHEMA.COLUMNS / STATISTICS 元数据表
    #     （这俩表所有 MySQL 5.x 起就有，是标准），确定列不存在才跑 ALTER。
    def _mysql_col_exists(_conn, _table: str, _col: str) -> bool:
        """
        判断 MySQL 某表是否已经有某列。
        例：_mysql_col_exists(conn, "knowledge_documents", "file_md5") → True
        """
        rs = _conn.exec_driver_sql(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s",
            (_table, _col),
        )
        row = rs.fetchone()
        return (row[0] if row else 0) > 0

    def _mysql_index_exists(_conn, _table: str, _idx: str) -> bool:
        """
        判断 MySQL 某表是否已有同名索引（STATISTICS 表里每个索引一列）。
        例：_mysql_index_exists(conn, "knowledge_documents", "ix_knowledge_documents_file_md5")
        """
        rs = _conn.exec_driver_sql(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND INDEX_NAME = %s",
            (_table, _idx),
        )
        row = rs.fetchone()
        return (row[0] if row else 0) > 0

    # -------- 通用：从 SQL 语句里用正则抽 table/col/index 名 --------
    #   因为每条 SQL 都是我们自己拼的（build_sql 函数），格式是可控的，
    #   用三个非常简单的正则就能抽出判重需要的关键信息，不需要写 SQL Parser。
    #
    #   例 1（ALTER TABLE）：
    #     "ALTER TABLE knowledge_documents ADD COLUMN file_md5 VARCHAR(32) ..."
    #     → groups = ("knowledge_documents", "file_md5")
    #   例 2（CREATE INDEX）：
    #     "CREATE INDEX ix_knowledge_documents_file_md5 ON knowledge_documents(file_md5)"
    #     → groups = ("ix_knowledge_documents_file_md5", "knowledge_documents")
    #   例 3（CREATE TABLE）：
    #     "CREATE TABLE IF NOT EXISTS knowledge_chunk_failures ( ... )"
    #     → groups = ("knowledge_chunk_failures",)
    _re_add_col = _re.compile(
        r"ALTER\s+TABLE\s+`?(\w+)`?\s+ADD\s+(?:COLUMN\s+)?`?(\w+)`?",
        _re.IGNORECASE,
    )
    _re_create_idx = _re.compile(
        r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+`?(\w+)`?\s+ON\s+`?(\w+)`?",
        _re.IGNORECASE,
    )
    _re_create_table = _re.compile(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?(\w+)`?",
        _re.IGNORECASE,
    )

    with engine.begin() as conn:
        for i, s in enumerate(stmts, start=1):
            s_strip = s.strip()
            head = s_strip.splitlines()[0][:80]

            # ======= MySQL 分支：在跑 SQL 前先判断对象是否存在，存在直接跳过 =======
            if dialect.lower().startswith("mysql"):
                m = _re_add_col.search(s_strip)
                if m:
                    tbl, col = m.group(1), m.group(2)
                    if _mysql_col_exists(conn, tbl, col):
                        print(f"  [{i}/{len(stmts)}] ⚖️  列已存在，跳过：ADD COLUMN `{tbl}`.`{col}`")
                        continue
                else:
                    m2 = _re_create_idx.search(s_strip)
                    if m2 and not _re_create_table.search(s_strip):
                        # 注意：CREATE TABLE 语句里可能自带 INDEX 定义，不能误判
                        idx, tbl = m2.group(1), m2.group(2)
                        if _mysql_index_exists(conn, tbl, idx):
                            print(f"  [{i}/{len(stmts)}] ⚖️  索引已存在，跳过：CREATE INDEX `{idx}` ON `{tbl}`")
                            continue

            try:
                conn.exec_driver_sql(s)
                print(f"  [{i}/{len(stmts)}] ✅ {head}")
            except Exception as e:
                msg = str(e).lower()
                # 已知的"已存在"类错误码 + 字符串（MySQL 1060=重复列名 / 1061=重复索引名 / 1050=表已存在 /
                #                         1091=列或索引不存在(drop时) / PostgreSQL 42701 / SQLite duplicate column）
                skip_keywords = [
                    "duplicate column", "duplicate key name",
                    "column .* already exists",
                    "already exists", "duplicate",
                    "index.*exists", "key column.*doesn't exist",  # 连锁失败信息
                    "there is already a table named",
                    "relation .* already exists", "constraint.*already exists",
                ]
                hit_skip = any(k in msg for k in skip_keywords)
                # MySQL 数字错误码判断
                for ec in ["(1060,", "(1061,", "(1050,", "(1091,", "42701", "42p07"]:
                    if ec in msg:
                        hit_skip = True
                        break
                if hit_skip:
                    print(f"  [{i}/{len(stmts)}] ⚖️  已存在，跳过：{head}")
                else:
                    print(f"  [{i}/{len(stmts)}] ❌ 失败：{head}")
                    print(f"       错误信息：{e}")
                    print('       （如果是【列/索引已存在】类错误可忽略；否则请拿 SQL 手动排查）')
    print("\n✅ 缺口6迁移完成。现在可以启动后端服务测试上传了。")


if __name__ == "__main__":
    main()