"""纯逻辑模块的单元测试。

不依赖 API Key、不依赖网络、不依赖外部服务。
"""

from agent.prompts import CALC_AGENT_PROMPT, INFO_AGENT_PROMPT, WRITER_AGENT_PROMPT
from agent.state import State


def test_state_has_required_keys():
    """State 的 TypedDict 应包含三个字段。"""
    keys = set(State.__annotations__.keys())
    assert keys == {"messages", "pending_tool", "needs_calc"}


def test_prompts_are_non_empty_strings():
    """三个系统提示词都应该是非空字符串。"""
    for prompt in [INFO_AGENT_PROMPT, CALC_AGENT_PROMPT, WRITER_AGENT_PROMPT]:
        assert isinstance(prompt, str)
        assert len(prompt.strip()) > 0


def test_calc_prompt_mentions_calculate():
    """计算节点的提示词应提到 calculate 工具。"""
    assert "calculate" in CALC_AGENT_PROMPT


def test_writer_prompt_forbids_fabrication():
    """写作节点的提示词应包含“不编造”的约束。"""
    assert "编造" in WRITER_AGENT_PROMPT or "不存在" in WRITER_AGENT_PROMPT
