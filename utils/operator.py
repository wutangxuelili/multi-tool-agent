"""当前操作人（谁批准了这次敏感操作）的上下文传递。

为什么需要：`delete_employee` 要把"谁删的"写进归档表，但工具函数是
LLM 面向的，签名里不能塞 operator 参数。用一个 ContextVar 让
`confirm_node`（它知道 thread_id）把操作人传给工具，既不污染工具签名，
也不需要全局可变状态。

- `operator_scope(thread_id)`：在敏感操作执行期间设置操作人
- `get_operator()`：工具侧读取，未设置时返回 None
"""

from contextlib import contextmanager
from contextvars import ContextVar

_current_operator: ContextVar[str | None] = ContextVar("current_operator", default=None)


def get_operator() -> str | None:
    """当前操作人标识（通常是 thread_id）；不在敏感操作上下文中时为 None。"""
    return _current_operator.get()


def set_operator(operator: str | None):
    """设置操作人，返回可用于 reset 的 token。"""
    return _current_operator.set(operator)


def reset_operator(token) -> None:
    _current_operator.reset(token)


@contextmanager
def operator_scope(operator: str | None):
    """在 with 块内把操作人设为 operator。"""
    token = _current_operator.set(operator)
    try:
        yield
    finally:
        _current_operator.reset(token)
