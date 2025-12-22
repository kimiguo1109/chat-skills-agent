"""
Request Context - 请求级别的上下文管理

使用 contextvars 在请求处理期间传递用户 token 等信息，
无需修改所有函数签名。
"""
from contextvars import ContextVar
from typing import Optional

# 用户 API Token（从请求 headers 中提取）
_user_api_token: ContextVar[Optional[str]] = ContextVar('user_api_token', default=None)


def set_user_api_token(token: Optional[str]) -> None:
    """设置当前请求的用户 API Token"""
    _user_api_token.set(token)


def get_user_api_token() -> Optional[str]:
    """获取当前请求的用户 API Token"""
    return _user_api_token.get()


def clear_user_api_token() -> None:
    """清除当前请求的用户 API Token"""
    _user_api_token.set(None)

