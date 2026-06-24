from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    直接继承 DeclarativeBase 也行，但包一层 Base 是工程惯例，好处：
    统一扩展：后续想给所有模型加公共字段（如 created_at、updated_at），只需在 Base 里加
    统一配置：比如注册事件监听、自定义类型映射
    项目隔离：不同模块可以定义不同的 Base，避免互相干扰
    """
    pass
