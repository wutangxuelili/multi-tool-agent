"""图级测试：路由、多轮记忆、敏感操作闸门。

这些用例用脚本化的假 LLM（`ScriptedLLM`）驱动真实的 LangGraph 图，
因此**不需要 API Key、不需要网络**，可以在 CI 里跑。
对应两个真实缺陷的回归：
- P1-1：`State.messages` 缺 `add_messages` reducer → 第二轮看不到第一轮历史；
- P1-2：LLM 在模块导入期实例化 → 没有 .env 时连 `import agent.graph` 都失败，
  于是图、节点、人工确认闸门从来没有被任何测试碰过。
"""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

import main
from agent import nodes
from agent.graph import build_graph, looks_like_arithmetic, route_after_info
from utils import audit


class ScriptedLLM:
    """按脚本逐次返回 AIMessage 的假 LLM（可 bind_tools，返回自身）。"""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[list] = []
        self.bound_tool_names: list[str] = []

    def bind_tools(self, tools):
        self.bound_tool_names = [tool.name for tool in tools]
        return self

    def invoke(self, messages, config=None, **kwargs):
        self.calls.append(list(messages))
        if not self._responses:
            raise AssertionError("ScriptedLLM 脚本已用尽：图比预期多跑了一轮 LLM")
        return self._responses.pop(0)


def tool_call(name, args, call_id):
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def delete_call(call_id="c1", employee_id=1):
    return AIMessage(
        content="",
        tool_calls=[tool_call("delete_employee", {"employee_id": employee_id}, call_id)],
    )


@pytest.fixture
def audit_log(tmp_path, monkeypatch):
    """把审计文件重定向到临时目录。"""
    path = tmp_path / "sensitive_ops.jsonl"
    monkeypatch.setattr(audit, "AUDIT_PATH", path)
    return path


@pytest.fixture
def fake_llm(monkeypatch):
    """安装假 LLM 的工厂：install([...]) 返回那个 ScriptedLLM。"""

    def install(responses):
        llm = ScriptedLLM(responses)
        monkeypatch.setattr(nodes, "get_bound_llm", lambda names: llm)
        monkeypatch.setattr(nodes, "get_llm", lambda: llm)
        return llm

    return install


@pytest.fixture
def make_app():
    def _build(thread_id="t-test"):
        app = build_graph(InMemorySaver())
        return app, {"configurable": {"thread_id": thread_id}}

    return _build


# ---------- P1-1：多轮记忆 ----------


def test_multi_turn_keeps_history(fake_llm, make_app):
    llm = fake_llm(
        [
            AIMessage(content="收到1"),
            AIMessage(content="回答1"),
            AIMessage(content="收到2"),
            AIMessage(content="回答2"),
        ]
    )
    app, config = make_app()

    app.invoke({"messages": [HumanMessage(content="问题1")]}, config=config)
    app.invoke({"messages": [HumanMessage(content="问题2")]}, config=config)

    # 第二轮的 info_node 应当看得到第一轮的全部消息
    second_turn = [m.content for m in llm.calls[2]]
    assert second_turn == ["问题1", "收到1", "回答1", "问题2"] or all(
        text in second_turn for text in ("问题1", "回答1", "问题2")
    )

    stored = [m.content for m in app.get_state(config).values["messages"]]
    assert stored == ["问题1", "收到1", "回答1", "问题2", "收到2", "回答2"]


# ---------- P1-5：敏感操作闸门 ----------


def test_sensitive_tool_pauses_and_only_executes_after_approval(
    fake_llm, make_app, employee_count, audit_log
):
    fake_llm([delete_call(), AIMessage(content="已删除，正在汇总"), AIMessage(content="最终回答")])
    app, config = make_app()

    first = app.invoke({"messages": [HumanMessage(content="删掉 1 号员工")]}, config=config)

    # 1) 必须中断，且**没有真的删**
    assert "__interrupt__" in first
    assert employee_count() == 4
    assert app.get_state(config).values["pending_tool"]["name"] == "delete_employee"

    # 2) 同意后才执行
    app.invoke(Command(resume="yes"), config=config)
    assert employee_count() == 3

    # 3) 审计留痕
    records = [json.loads(line) for line in audit_log.read_text("utf-8").splitlines()]
    assert records[-1]["decision"] == "approved"
    assert records[-1]["tool"] == "delete_employee"
    assert records[-1]["args"] == {"employee_id": 1}
    assert records[-1]["thread_id"] == "t-test"


def test_rejecting_confirmation_does_not_delete(
    fake_llm, make_app, employee_count, audit_log
):
    fake_llm([delete_call(), AIMessage(content="已取消"), AIMessage(content="最终回答")])
    app, config = make_app()

    app.invoke({"messages": [HumanMessage(content="删掉 1 号员工")]}, config=config)
    app.invoke(Command(resume="no"), config=config)

    assert employee_count() == 4
    records = [json.loads(line) for line in audit_log.read_text("utf-8").splitlines()]
    assert records[-1]["decision"] == "rejected"


def test_multiple_sensitive_calls_in_one_message_are_all_answered(
    fake_llm, make_app, employee_count
):
    """一轮里出现两个敏感调用：只确认第一个，但两个都要有 ToolMessage 回应。

    否则历史里会留下"有 tool_call 没有响应"的 AIMessage，
    下一次请求会被 OpenAI 兼容端点判为 400。
    """
    two_calls = AIMessage(
        content="",
        tool_calls=[
            tool_call("delete_employee", {"employee_id": 1}, "c1"),
            tool_call("delete_employee", {"employee_id": 2}, "c2"),
        ],
    )
    fake_llm([two_calls, AIMessage(content="已取消"), AIMessage(content="最终回答")])
    app, config = make_app()

    result = app.invoke({"messages": [HumanMessage(content="删掉 1 号和 2 号")]}, config=config)
    assert "__interrupt__" in result
    assert employee_count() == 4

    # 中断时：c1 在等确认（尚无 ToolMessage），c2 已被显式回答"未执行"
    state = app.get_state(config).values
    assert state["pending_tool"]["id"] == "c1"
    answered = {m.tool_call_id for m in state["messages"] if isinstance(m, ToolMessage)}
    assert answered == {"c2"}

    # 确认被拒后：c1 也补上了回应，历史里不再有悬空的 tool_call
    app.invoke(Command(resume="no"), config=config)
    final = app.get_state(config).values
    answered = {m.tool_call_id for m in final["messages"] if isinstance(m, ToolMessage)}
    assert answered == {"c1", "c2"}
    assert employee_count() == 4

    # 两个 tool_call 各自都有且只有一条回应
    tool_call_ids = [
        c["id"] for m in final["messages"] for c in getattr(m, "tool_calls", []) or []
    ]
    assert sorted(tool_call_ids) == ["c1", "c2"]
    assert len([m for m in final["messages"] if isinstance(m, ToolMessage)]) == 2


def test_execution_layer_refuses_unapproved_sensitive_tool(temp_db):
    """闸门在执行层：即使换个节点拿到敏感工具名，也执行不了。"""
    result = nodes._execute_tool("delete_employee", {"employee_id": 1})
    assert "拒绝执行" in result


def test_execution_layer_handles_unknown_tool():
    assert "未知工具" in nodes._execute_tool("no_such_tool", {})


def test_confirm_node_discards_malformed_pending_tool():
    """损坏的 checkpoint 不能让整张图抛 KeyError。"""
    assert nodes.confirm_node({"pending_tool": {"name": "delete_employee"}}) == {
        "pending_tool": None
    }
    assert nodes.confirm_node({"pending_tool": "not-a-dict"}) == {"pending_tool": None}
    assert nodes.confirm_node({"pending_tool": None}) == {}


# ---------- 路由与确认语义 ----------


def test_route_after_info_prefers_pending_tool():
    state = {"messages": [AIMessage(content="需要计算")], "pending_tool": {"name": "x"}}
    assert route_after_info(state) == "confirm"


def test_route_after_info_detects_calc_keyword():
    state = {"messages": [AIMessage(content="数据齐了，需要计算")], "pending_tool": None}
    assert route_after_info(state) == "calc"


def test_route_after_info_defaults_to_writer():
    state = {"messages": [AIMessage(content="信息已收集完毕")], "pending_tool": None}
    assert route_after_info(state) == "writer"


# ---------- calc 路由：看用户提问，而不是只看 AI 自述（P2-3） ----------


@pytest.mark.parametrize(
    "text",
    [
        "(25 + 17) * 3 等于多少？",
        "帮我算 10/0",
        "技术部平均薪资是多少？",
        "公司总共有多少人？",
        "3×4 是多少",
        "15% 的 200 是多少",
    ],
)
def test_looks_like_arithmetic_positive(text):
    assert looks_like_arithmetic(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "",
        "今天北京天气怎么样？",
        "读取 documents/test.txt",
        "搜一下 FastAPI 是什么",
        "公司有哪些部门？",
    ],
)
def test_looks_like_arithmetic_negative(text):
    assert looks_like_arithmetic(text) is False


def test_route_uses_user_question_even_if_ai_stays_silent():
    """用户问的是算术题、AI 却说"我直接心算"，也必须进 calc（旧实现会漏掉）。"""
    state = {
        "messages": [
            HumanMessage(content="帮我算 (25+17)*3"),
            AIMessage(content="好的，我直接心算"),
        ],
        "pending_tool": None,
    }
    assert route_after_info(state) == "calc"


@pytest.mark.parametrize(
    "answer,expected",
    [
        ("yes", True),
        ("YES", True),
        (" y ", True),
        ("确认", True),
        ("同意", True),
        ("no", False),
        ("", False),
        ("随便吧", False),
    ],
)
def test_is_affirmative_normalizes_answer(answer, expected):
    assert nodes.is_affirmative(answer) is expected


# ---------- 对外 API（P1-6） ----------


def test_new_thread_id_is_unique():
    first, second = main.new_thread_id("u1"), main.new_thread_id("u1")
    assert first != second
    assert first.startswith("u1-")


def test_run_agent_and_resume_agent_end_to_end(
    fake_llm, employee_count, audit_log, monkeypatch
):
    fake_llm([delete_call(), AIMessage(content="已删除"), AIMessage(content="最终回答")])
    monkeypatch.setattr(main, "app", build_graph(InMemorySaver()))

    thread_id = main.new_thread_id("pytest")
    reply = main.run_agent("删掉 1 号员工", thread_id=thread_id)
    assert reply.startswith(main.CONFIRM_PREFIX)
    assert employee_count() == 4

    assert main.resume_agent("yes", thread_id=thread_id) == "最终回答"
    assert employee_count() == 3


def test_resume_without_pending_interrupt_returns_error(monkeypatch):
    monkeypatch.setattr(main, "app", build_graph(InMemorySaver()))
    reply = main.resume_agent("yes", thread_id="never-started")
    assert reply.startswith(main.ERROR_PREFIX)
