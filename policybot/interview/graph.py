from __future__ import annotations
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from policybot.models import InterviewState, RequestInfo, IagType
from policybot.interview.orchestrator import Interview


class _GraphState(TypedDict, total=False):
    request: RequestInfo
    tool_name: str
    usage_inputs: list
    iag_type_override: IagType | None
    state: InterviewState


def build_interview_graph(itv: Interview):
    def assess_node(gs: _GraphState) -> _GraphState:
        result = itv.assess(
            gs["request"], gs["tool_name"], gs["usage_inputs"],
            gs.get("iag_type_override"),
        )
        return {"state": result}

    graph = StateGraph(_GraphState)
    graph.add_node("assess", assess_node)
    graph.add_edge(START, "assess")
    graph.add_edge("assess", END)
    return graph.compile()


def run_graph(itv: Interview, request: RequestInfo, tool_name: str,
              usage_inputs: list,
              iag_type_override: IagType | None = None) -> InterviewState:
    app = build_interview_graph(itv)
    out = app.invoke({
        "request": request, "tool_name": tool_name, "usage_inputs": usage_inputs,
        "iag_type_override": iag_type_override,
    })
    return out["state"]
