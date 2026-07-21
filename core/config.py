"""
配置管理模块

该模块负责管理应用程序的所有配置参数，支持从环境变量和 .env 文件中读取配置。
配置项采用类型安全的方式定义，并提供合理的默认值，便于开发和部署。
"""

# 导入路径处理库，用于获取项目根目录
from pathlib import Path
# 导入操作系统相关功能，用于读取环境变量
import os

# 导入 dotenv 库，用于加载 .env 文件中的环境变量
from dotenv import load_dotenv

# 获取项目根目录路径：当前文件所在目录的父目录的父目录
BASE_DIR = Path(__file__).resolve().parent.parent
# 加载项目根目录下的 .env 文件，将其中的环境变量注入到 os.environ 中
load_dotenv(BASE_DIR / ".env")


class Settings:
    """
    应用程序配置类

    该类集中管理所有配置参数，每个配置项都从环境变量读取，
    如果环境变量未设置，则使用默认值。

    属性说明：
    --------
    LLM 相关配置：
        OPENAI_BASE_URL: OpenAI API 的基础 URL，默认指向本地 LM Studio 服务
        OPENAI_API_KEY: OpenAI API 密钥，默认值适用于本地开发
        LLM_MODEL: 大语言模型名称，默认使用 Qwen3-1.7B 模型
        EMBEDDING_MODEL: 嵌入模型名称，用于生成文本向量
        LLM_TEMPERATURE: 模型温度参数，控制输出随机性（0=确定性，1=随机性较高）

    认证相关配置：
        SECRET_KEY: JWT 令牌签名密钥，生产环境应设置为长随机字符串
        ALGORITHM: JWT 加密算法，默认使用 HS256
        ACCESS_TOKEN_EXPIRE_MINUTES: 访问令牌过期时间（分钟），默认 1440 分钟（24小时）

    数据库相关配置：
        DATABASE_URL: 完整的数据库连接 URL，格式为 dialect+driver://user:password@host:port/dbname
        DATABASE_SERVER_URL: 数据库服务器连接 URL（不含数据库名），用于数据库初始化
        DATABASE_NAME: 数据库名称

    RAG（检索增强生成）相关配置：
        KNOWLEDGE_UPLOAD_DIR: 知识库上传文件的存储目录
        FAISS_INDEX_DIR: FAISS 向量索引文件的存储目录
        RAG_CHUNK_SIZE: 文本分块大小（字符数），默认 500 字符
        RAG_CHUNK_OVERLAP: 文本分块重叠大小（字符数），默认 100 字符
    """

    # ========== LLM 相关配置 ==========
    # OpenAI API 基础 URL，支持自定义部署（如本地 LM Studio、OpenAI 官方或其他兼容服务）
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "http://localhost:1234/v1")
    # OpenAI API 密钥，本地开发环境可使用任意非空值
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "lm-studio")
    # 大语言模型名称，需与部署的模型服务匹配
    LLM_MODEL: str = os.getenv("LLM_MODEL", "qwen/qwen3-1.7b")
    # 嵌入模型名称，用于将文本转换为向量表示
    EMBEDDING_MODEL: str = os.getenv(
        "EMBEDDING_MODEL",
        "text-embedding-nomic-embed-text-v1.5",
    )
    # 模型温度参数，0 表示确定性输出，值越大输出越随机
    LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0"))

    # ========== 认证相关配置 ==========
    # JWT 签名密钥，用于生成和验证访问令牌
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-to-a-long-random-string")
    # JWT 加密算法
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    # 访问令牌过期时间，单位为分钟，默认 24 小时
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
        os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440")
    )

    # ========== 数据库相关配置 ==========
    # 数据库连接 URL，支持 MySQL、PostgreSQL 等 SQLAlchemy 支持的数据库
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "mysql+pymysql://root:root@127.0.0.1:3306/agent_v1",
    )
    # 数据库服务器 URL（不含数据库名），用于创建数据库等管理操作
    DATABASE_SERVER_URL: str = os.getenv(
        "DATABASE_SERVER_URL",
        "mysql+pymysql://root:root@127.0.0.1:3306",
    )
    # 数据库名称
    DATABASE_NAME: str = os.getenv("DATABASE_NAME", "agent_v1")

    # ========== RAG 相关配置 ==========
    # 知识库上传文件存储目录，默认位于项目根目录下的 data/knowledge_uploads
    KNOWLEDGE_UPLOAD_DIR: str = os.getenv(
        "KNOWLEDGE_UPLOAD_DIR",
        str(BASE_DIR / "data" / "knowledge_uploads"),
    )
    # FAISS 向量索引存储目录，默认位于项目根目录下的 tmp/faiss_indexes
    FAISS_INDEX_DIR: str = os.getenv(
        "FAISS_INDEX_DIR",
        str(BASE_DIR / "tmp" / "faiss_indexes"),
    )
    # RAG 文本分块大小，影响检索精度和效率
    RAG_CHUNK_SIZE: int = int(os.getenv("RAG_CHUNK_SIZE", "500"))
    # RAG 文本分块重叠大小，确保相邻分块之间有上下文衔接
    RAG_CHUNK_OVERLAP: int = int(os.getenv("RAG_CHUNK_OVERLAP", "100"))


# 创建 Settings 类的实例，供其他模块导入使用
settings = Settings()