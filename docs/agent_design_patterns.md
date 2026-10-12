# Agent 设计模式笔记（multi-tool-agent）

## 如何使用这份笔记

**什么时候翻它：**

- **要设计一个新 Agent 时**——先看「职责分离」「状态机编排」「Human-in-the-loop」三节，判断你的场景要不要拆节点、要不要上 LangGraph。
- **要给 Agent 加一个新工具时**——看「统一 tool 层」和「工具桥接」，注意 `INFO_TOOL_NAMES` 那份手写清单要同步。
- **要改 `agent/graph.py` 或 `agent/nodes.py` 之前**——对照「状态机编排」里的坑（`messages` 没有 reducer、`needs_calc` 是死字段），避免重复踩。
- **代码 review / 看别人的 Agent 项目时**——把这 8 条当 checklist，逐条问"他这里是怎么处理的"。

**它的局限性：**

- **基于本项目的具体实现，不是通用教程。** 所有结论对应 LangGraph 1.2.12、mcp 2.3.0、Python 3.11、模型 `deepseek-v4-flash`。换模型后"模型会不会乖乖听话"这类判断可能失效。
- **不替代官方文档。** 这里只记"我们为什么这么选"，API 细节看 LangGraph / MCP 官方文档。
- **「取舍」大多是被坑过之后的个人判断**，不是客观结论。有争议的地方我保留了原始观察，方便你三个月后自己重新判断。
- **项目背景**：本项目经历过一次迁移——**v1** 是 `AgentExecutor` + `create_tool_calling_agent` 的单 Agent（4 个工具，无中断、无持久化），**v2** 是现在的 LangGraph 四节点（7 个工具）。v1 代码保留在 `历史版本文件/`。下面多处用 v1 做对照，因为"从哪来"比"现在是什么"更能说明取舍。

---

### 模式 1：ReAct 循环（LLM 决策 + 工具执行）

**解决什么问题**
工具调用的**顺序和次数无法预先写死**（用户可能一次问天气、也可能先查库再算差值），需要让 LLM 每轮自己决定"还调不调、调哪个"。

**本项目的实现**
`agent/nodes.py` 的 `info_node`，手写 for 循环，上限 `MAX_INFO_ROUNDS = 5`：调 LLM → 有 `tool_calls` 就执行并回填 `ToolMessage` → 再调 LLM，直到模型不再要求调工具。

```python
for round_num in range(MAX_INFO_ROUNDS):
    response = info_llm.invoke(messages)
    if not response.tool_calls:
        break
    # 执行工具，append ToolMessage，进入下一轮
```

**没用 `create_react_agent`**（`langgraph-prebuilt` 其实已经装了），因为必须在循环中间插一个分支：遇到敏感工具时**只记录、不执行**。预置函数不给这个插槽。

v1 对照：v1 把这套循环完全交给了 `AgentExecutor` + prompt 里的 `{agent_scratchpad}` 占位符，是隐式的，看不见也改不动。

**取舍**

- 代价：messages 拼接、轮数上限、工具结果回填全部要自己维护；`State.messages` 是普通 `list`（没有 `add_messages` reducer），所以节点必须**返回完整列表**，写错就丢历史。
- 用满 5 轮会**静默截断**，用户看不到"我还没查完"，只看到半截答案。
- **什么时候不该用**：流程固定的场景（比如"先查库存再下单"）直接写死顺序更便宜也更可控；ReAct 的灵活性是用 token 和不确定性换来的。

**实测效果**
20 任务里单工具类 **6/6 全通过**，且工具选择干净——#3 只调了 `search_web`、#4 只调了 `query_database`，没有出现"以防万一多调"。#19「北京和上海哪个更热」正确触发两次 `get_weather`，说明多轮循环生效。

---

### 模式 2：职责分离（多节点 vs 单 Agent）

**解决什么问题**
一个 Agent 绑上全部工具时，容易出现**该收尾的时候又去调工具**、或者算数题跑去搜网页。把不同职责拆成不同节点，各自只拿自己那套工具，能物理上排除一部分误用。

**本项目的实现**
`agent/nodes.py` 里按名单筛工具，再分别 `bind_tools`；prompt 也各自独立（`agent/prompts.py`）。

```python
INFO_TOOLS = [t for t in ALL_TOOLS if t.name in INFO_TOOL_NAMES]   # 6 个
CALC_TOOLS = [t for t in ALL_TOOLS if t.name in CALC_TOOL_NAMES]   # 只有 calculate
info_llm = _llm.bind_tools(INFO_TOOLS)
calc_llm = _llm.bind_tools(CALC_TOOLS)
```

三个节点的分工：`info` 取数据、`calc` 只做算术、`writer` **不绑任何工具**（它没有工具可调，所以不可能在最后一步乱调）。v1 则是单个 agent 绑 4 个工具，靠一段长 prompt 约束行为。

**取舍**

- 代价：一次问答多 1~2 次 LLM 调用，延迟和成本直接上升（实测平均 4.2s/任务）。
- 节点之间**只有自然语言 message 传递**，没有结构化 handoff，`writer` 只能从对话历史里"读"信息，没法强约束。
- **最大的坑：拆分之后，"节点交接条件"必须显式写对。** 现在 `route_after_info` 靠检查 AI 输出里有没有 `需要计算` 这类中文关键词来决定进不进 `calc`——这个条件是**脆弱的**，模型一句"这不用调工具"就能绕过整条支线（详见模式 4）。
- **什么时候不该用**：工具少于 3 个、任务本就单跳时，拆节点只会增加延迟和出错面。

**实测效果**
多工具类 90%；但**分离出的 `calc` 支线命中率极低**——4 个计算类任务里通常一个都触发不到，`calculate` 多数跑测 0 次调用（最近一次运行仅 #8 触发）。分离本身没写错，**是交接条件写错了，收益基本落空**。

---

### 模式 3：Human-in-the-loop（人工确认）

**解决什么问题**
LLM 决定执行**不可逆操作**（删数据、发消息、付款）时，需要一个**它在 prompt 层面绕不过去**的闸门。写在 system prompt 里的"请先征求用户同意"是拦不住提示词注入的。

**本项目的实现**
`agent/nodes.py` + `agent/graph.py` + `main.py` 三处配合。核心是命中敏感名单就**只记录不执行**：

```python
SENSITIVE_TOOLS = {"delete_employee"}
...
if tool_name in SENSITIVE_TOOLS:
    pending = tool_call
    continue              # 不执行，交给 confirm_node
```

然后 `route_after_info` 看到 `pending_tool` 就转到 `confirm_node`，由 `interrupt(...)` 挂起；`main.py` 把 `__interrupt__` 翻译成 `[NEED_CONFIRM]` 前缀返回给调用方，用户回复后用 `Command(resume=answer)` 恢复。

**取舍**

- **决定权在代码不在 prompt**——这是优点，也是代价：新增一个敏感工具必须改 `SENSITIVE_TOOLS` 这个常量，改了要重新部署。
- 要求调用方**复用同一条 `thread_id`**，否则找不到中断现场（我在测试中踩过这个坑）。这是隐式契约，API 签名上看不出来。
- 目前只判断 `answer == "yes"`：**没有超时、没有审计日志、没有权限分级**。生产环境至少还要补"谁来确认"和"确认记录留痕"。
- **什么时候不该用**：高频只读操作（每次查询都要人点一下，人就成了瓶颈）。确认要留给"不可逆 + 低频 + 影响面大"的操作。

**实测效果**
敏感操作类 **3/3 全通过**：任务 #12 正确返回 `[NEED_CONFIRM]` 且数据库未被改动；#13 回复 yes 后 `delete_employee` 真的执行、员工被删除；#14 回复 no 后数据仍在、返回"已取消"。这条链路是目前项目里**最可靠**的部分。

---

### 模式 4：状态机编排（StateGraph）

**解决什么问题**
Agent 的执行路径天然带分支（要不要算、要不要确认、要不要再来一轮），用散落各处的 `if/else` 拼会很快失控，也没法持久化中间态。

**本项目的实现**
`agent/graph.py` 的 `build_graph()`：`StateGraph(State)` 注册 4 个节点，用 `add_conditional_edges` 做分流，用 `add_edge` 描述回流。

```python
graph.add_conditional_edges("info", route_after_info,
    {"confirm": "confirm", "calc": "calc", "writer": "writer"})
graph.add_edge("confirm", "info")    # 确认后回到信息收集
graph.add_edge("calc", "writer")
```

`route_after_info` 把优先级写在函数里：**敏感操作 > 需要计算 > 默认撰写**。

**取舍**

- **状态定义有坑**：`agent/state.py` 的 `State` 是 `TypedDict`，`messages: list` **没有 reducer**，所以每个节点都返回 `state["messages"] + 新增`，一不小心写成覆盖就丢历史。
- **`State.needs_calc` 是死字段**：声明了、注释写了"由 info_agent 设置"，但全项目**从未被读写**。实际判断改用了 `CALC_KEYWORDS` 字符串匹配，这正是 `calc` 支线失效的根因。**声明了却没接线的状态字段，比没有更危险**——它会让人以为功能已经实现。
- 取舍本质：图越复杂，`route_*` 这类纯函数的可测试性就越关键（好消息是它确实好测，输入 state 输出字符串）。
- **什么时候不该用**：线性流程（取数 → 总结）用两行代码就够，上 StateGraph 是过度设计。

**实测效果**
整体完成率 **87.5%**（16 ✅ / 3 ⚠️ / 1 ❌），语义放宽判定 97.5%。分支命中情况：`confirm` 分支 3/3 正常，`calc` 分支在 4 个计算类任务里仅 #8 命中——**图搭对了，但那条边的条件不可靠**。

---

### 模式 5：持久化 checkpoint

**解决什么问题**
"暂停等人工确认"这件事**可能跨进程**：用户看到确认提示后关掉程序，第二天再回复。暂停中的会话状态必须落盘，否则人工确认无从恢复。

**本项目的实现**
`agent/graph.py` 编译时挂 `SqliteSaver`，会话身份由 `thread_id` 决定。

```python
checkpointer = SqliteSaver(sqlite3.connect("checkpoints.db", check_same_thread=False))
graph.compile(checkpointer=checkpointer)

config = {"configurable": {"thread_id": thread_id}}   # 调用侧
```

`main.py` 的 `run_agent` / `resume_agent` 都只是薄封装：前者发 `HumanMessage`，后者发 `Command(resume=...)`。

**取舍**

- **写入量**：每次 invoke 都落一份快照，`checkpoints.db` 已经 2.7 MB，没有清理策略，长期跑会持续膨胀。
- `sqlite3.connect(...)` 是**模块级单例 + `check_same_thread=False`**，多线程共享同一个连接有风险；`build_graph()` 在 import 时就执行（`app = build_graph()`），副作用发生在导入期。
- **`thread_id` 变成隐式契约**：传错不会报错，只会静默开一条新会话，表现是"确认后答非所问"。API 上只能靠 docstring 提醒。
- v1 完全没有这层（`AgentExecutor` 是内存态），所以 v1 根本做不了 HITL——**checkpoint 是模式 3 的前置条件**，这两个模式要一起上。

**实测效果**
支撑了 #12 → #13 的跨调用恢复（第一次调用只返回中断，第二次调用才真正执行删除）。也正因为这条契约，我在评测脚本里必须给每个任务独立的 `thread_id`，并让"确认"步骤复用产生中断的那一条。

---

### 模式 6：结构化输出（Pydantic 约束）

**解决什么问题**
LLM 的自由文本里，字段名和类型都不稳定，下游没法可靠取值——需要 schema 把"形状"钉死。

**本项目的实现**
**注意：主链路只用到了"工具参数 schema"这一层，LLM 侧的结构化输出并没有进主链路。** 7 个工具全部声明 `args_schema`：

```python
class ReadFileArgs(BaseModel):
    path: str = Field(min_length=1, description="相对 documents/ 的路径")

@tool(args_schema=ReadFileArgs)
def read_file_mcp(path: str) -> str:
```

另外 `internal_api/server.py` 用 `response_model=AnnouncementList` 约束 HTTP 响应。`with_structured_output(...)` **只出现在独立实验脚本 `test_structured_output.py` 里**（`method="json_mode"` + `field_validator` 把 `"25℃"` 清洗成 `25`），没有接进图。

**取舍**

- `Field(description=...)` 实际上**就是在给 LLM 写提示词**——description 写含糊，模型就传错参数（实测模型会把 `documents/test.txt` 整串传进来，而参数要的是相对 `documents/` 的 `test.txt`）。
- 它只约束了**入参形状**，约束不了**回答内容**。边界任务照样编数据（#18 把 9 月 30 日的过期行情当"今天"播报），这类问题得靠 prompt 和路由解决，schema 帮不上。
- 真需要稳定的中间结构（比如"提取出的实体列表"）时，应该用 `with_structured_output` 而不是字符串解析——本项目没走这条路，因为节点之间只传自然语言。
- **代价**：`field_validator` 这类清洗逻辑好写但隐蔽，出问题时现象是"值莫名其妙不对"，不是报错。

**实测效果**
工具参数层面没出现过类型错误；但输出层面仍是自由文本——#8 的平均薪资写成 `29,333.33`（千分位），说明**没有 schema 兜底，格式完全由模型决定**。

---

### 模式 7：工具桥接（Bridge，MCP ↔ LangChain）

**解决什么问题**
MCP 工具是**异步、跨进程、JSON-RPC** 的，而 LangGraph 节点里要的是**同步 `@tool`**。两套世界之间需要一个转接头。

**本项目的实现**
`tools/mcp_bridge.py` 用 `@tool` 包一层，内部用 `asyncio.run` 把异步客户端拉进同步世界：

```python
@tool(args_schema=ReadFileArgs)
def read_file_mcp(path: str) -> str:
    return asyncio.run(call_read_file(path))
```

真正的协议细节在 `mcp_servers/client.py`：`stdio_client` 启动 Server 子进程 → `ClientSession` → `session.initialize()` 握手 → `session.call_tool("read_file", {...})`，带 `CALL_TIMEOUT = 30.0`，并把所有异常**转成字符串返回而不是抛出**。Server 侧（`mcp_servers/file_server.py`）用 `ALLOWED_DIR` 做路径白名单。

**取舍**

- **`asyncio.run` 不能在有事件循环的环境里调用**（会 `RuntimeError`，代码专门 catch 了并返回错误字符串）。也就是说这个桥**永远进不了 async 框架**——想在 FastAPI 里直接用它是行不通的。
- **每次调用都重启一次 Server 子进程并重新握手**：单次实测 **1.27s**，比本地 `@tool` 慢一个数量级。连续读多个文件时这个开销会被放大。
- **异常被吞成字符串**是双刃剑：Agent 不会崩、能继续对话，但调用方拿不到栈信息，排查只能翻 stderr。
- **什么时候不该用**：能力本身只是本地读文件、且没有多宿主复用需求时，直接写 `open()` 更简单。

**实测效果**
MCP 读取类 **2/2 通过**：#6 正确返回 `Hello from MCP!`，#17 正确报"文件不存在"。路径白名单也验证有效——传 `../test.txt` 被拒绝，传 `sub/../test.txt` 归一化后正常放行。

---

### 模式 8：统一 tool 层（TOOL_MAP）

**解决什么问题**
手写的 ReAct 循环从 LLM 拿到的是**工具名字符串**（`tool_call["name"]`），得换成可执行对象；同一份工具集还要喂给 `bind_tools`。

**本项目的实现**
`tools/__init__.py` 把本地与 MCP 工具拍平，再建名字索引：

```python
LOCAL_TOOLS = [get_weather, calculate, search_web, query_database,
               delete_employee, *INTERNAL_API_TOOLS]   # 6 个
ALL_TOOLS = LOCAL_TOOLS + MCP_TOOLS                   # +1 = 7 个
TOOL_MAP = {t.name: t for t in ALL_TOOLS}
```

节点用 `TOOL_MAP[tool_name].invoke(tool_args)` 执行，`ALL_TOOLS` 用来 `bind_tools`——**一份注册、两处消费**。

**取舍**

- `TOOL_MAP[...]` 是**字典下标，没有防御**：模型幻觉出不存在的工具名就直接 `KeyError` 带崩节点（没管索引）。
- 本地与 MCP 工具共用一个命名空间，**重名静默覆盖**。
- `nodes.py` 里还有第二份手写清单 `INFO_TOOL_NAMES`，靠人肉与 `ALL_TOOLS` 同步；忘同步就会"注册了但从不被用"。

**实测效果**
7 个工具里 **6 个都被真实调用过**；**`calculate` 最难被选中**——多数跑测 0 次，最近一次由 #8 命中。同一注册表，差别只在路由——**注册 ≠ 会被调用**。

---

## 模式覆盖情况速查

| # | 模式 | 采用情况 | 关键文件 |
|---|---|---|---|
| 1 | ReAct 循环 | ✅ 采用（手写循环，未用 `create_react_agent`） | `agent/nodes.py` |
| 2 | 职责分离 | ✅ 采用（info / calc / writer 三职责 + confirm） | `agent/nodes.py`、`agent/prompts.py` |
| 3 | Human-in-the-loop | ✅ 采用（interrupt + 敏感工具名单） | `agent/nodes.py`、`agent/graph.py`、`main.py` |
| 4 | 状态机编排 | ✅ 采用（StateGraph + 条件边） | `agent/graph.py`、`agent/state.py` |
| 5 | 持久化 checkpoint | ✅ 采用（SqliteSaver） | `agent/graph.py` |
| 6 | 结构化输出 | ⚠️ **部分采用**——Pydantic 只用在工具入参与 API 响应；**LLM 侧 `with_structured_output` 未进入主链路**（仅存在于实验脚本 `test_structured_output.py`） | `tools/*.py`、`internal_api/server.py` |
| 7 | 工具桥接 | ✅ 采用（MCP → LangChain） | `tools/mcp_bridge.py`、`mcp_servers/client.py` |
| 8 | 统一 tool 层 | ✅ 采用（ALL_TOOLS + TOOL_MAP） | `tools/__init__.py` |

**唯一"未采用"的是模式 6 的 LLM 侧结构化输出。** 原因：本项目的节点之间只传递自然语言 message，没有需要强类型解析的中间产物；真正需要 schema 的地方（工具入参）已经用 `args_schema` 覆盖了。如果以后要加"信息抽取""结构化路由"，再引入 `with_structured_output` 也不迟。
