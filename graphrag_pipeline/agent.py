"""LangGraph Agentic RAG agent。

依据 LangChain 官方教程（https://docs.langchain.com/oss/python/langgraph/agentic-rag）：
- MessagesState 作为图状态
- generate_query_or_respond → tools → grade_results → generate_answer / rewrite
- 使用 ToolNode 自动处理工具调用循环

简化版（针对本项目的 KG 检索场景）：
- 工具返回的是结构化 JSON，无须复杂的相关性评分（KG 检索精度高）
- 直接走 query → tools → answer 三阶段
- 支持多次工具调用（Agent 可能先 kg_summary 再 find_metrics）
"""

from __future__ import annotations

from langchain_core.messages import SystemMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from .config import get_llm
from .kg_store import KGStore
from .tools import build_tools


SYSTEM_PROMPT = """你是一个基于知识图谱的问答助手。

你可以访问下列工具来查询知识图谱：
- kg_summary: 查看图谱整体内容（实体类别、关系类型、示例）
- find_entities: 关键词搜索实体（人名、机构名、指标名、数值都行）
- list_entities_by_class: 按类别列举（如所有 metric / 所有 organization）
- get_entity_detail: 用 entity_id 查实体详情
- get_entity_neighbors: 看某实体的所有一跳关系
- find_metrics: 数值指标专用查询（支持 metric_name + group 过滤）

工作原则：
1. 收到用户问题后，先选择合适的工具检索图谱，不要凭空回答
2. 对于"图谱里有什么"这类开放问题，先 kg_summary 摸清情况
3. 对于明确实体（"营业收入"、"Q1"、"张三"），直接 find_entities 或 find_metrics
4. 拿到工具结果后，基于真实数据生成回答（不要在文本中写 entity_id 或 document_id，前端会通过可点击 chip 自动展示溯源）
5. 如果第一次工具调用结果不充分，可以再调用其他工具补全
6. 最终回答用中文，简洁准确
7. 如果图谱中确实没有相关信息，直接说"知识图谱中未找到相关信息"，不要编造
"""


def build_agent(kg_store: KGStore):
    """构建 LangGraph Agentic RAG agent。

    Returns:
        compiled graph，可以 .invoke({"messages": [{"role":"user","content":"..."}]}) 调用
    """
    tools = build_tools(kg_store)
    llm = get_llm(temperature=0)
    llm_with_tools = llm.bind_tools(tools)

    async def call_model(state: MessagesState):
        """决策节点：判断是否要调用工具，或直接回答。

        必须是 async 函数，LangGraph stream_mode='messages' 才能逐 token 流式输出。
        同步 invoke 会等整个 LLM 调用完成后才返回，导致前端看不到流式效果。
        """
        messages = state["messages"]
        # 第一次进入时注入 system prompt
        if not messages or messages[0].type != "system":
            messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(messages)
        response = await llm_with_tools.ainvoke(messages)
        return {"messages": [response]}

    tool_node = ToolNode(tools)

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", tool_node)

    graph.add_edge(START, "agent")
    # 条件边：如果 LLM 输出包含 tool_calls，跳到 tools；否则结束
    graph.add_conditional_edges(
        "agent",
        tools_condition,
        {"tools": "tools", END: END},
    )
    # 工具执行后回到 agent 节点（可能继续调用工具或生成回答）
    graph.add_edge("tools", "agent")

    return graph.compile()


def ask(agent, question: str, recursion_limit: int = 12) -> dict:
    """对外问答入口。返回最终回答 + 工具调用轨迹。"""
    result = agent.invoke(
        {"messages": [{"role": "user", "content": question}]},
        config={"recursion_limit": recursion_limit},
    )
    messages = result.get("messages", [])

    # 提取最终 AI 文本
    answer = ""
    for msg in reversed(messages):
        if msg.type == "ai" and msg.content:
            answer = msg.content
            break

    # 提取工具调用轨迹（用于溯源/调试）
    tool_calls: list[dict] = []
    for msg in messages:
        if msg.type == "ai" and getattr(msg, "tool_calls", None):
            for call in msg.tool_calls:
                tool_calls.append({"name": call["name"], "args": call.get("args", {})})

    return {
        "question": question,
        "answer": answer,
        "tool_calls": tool_calls,
        "tool_call_count": len(tool_calls),
    }
