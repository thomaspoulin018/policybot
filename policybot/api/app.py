from __future__ import annotations
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from policybot.models import InterviewState, RequestInfo
from policybot.interview.orchestrator import Interview
from policybot.interview.graph import run_graph
from policybot.report.renderer import render_html
from policybot.api.deps import default_interview


def create_app(itv: Interview) -> FastAPI:
    app = FastAPI(title="PolicyBot")

    @app.post("/assess")
    def assess(payload: dict) -> InterviewState:
        return run_graph(
            itv,
            RequestInfo(**payload["request"]),
            payload["tool_name"],
            payload["usage_inputs"],
        )

    @app.post("/report", response_class=HTMLResponse)
    def report(state: InterviewState) -> str:
        return render_html(state)

    return app


app = create_app(default_interview())
