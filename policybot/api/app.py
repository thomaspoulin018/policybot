from __future__ import annotations
import sys
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from policybot.models import InterviewState, RequestInfo
from policybot.interview.orchestrator import Interview, UnknownToolError
from policybot.interview.graph import run_graph
from policybot.classify.tool_type import tool_type_question
from policybot.report.renderer import render_html
from policybot.api.deps import default_interview

# Load .env so the OpenRouter and LangSmith keys are picked up automatically on a
# real run. Skipped under pytest so the suite never turns tracing on (see also
# tests/conftest.py, which hard-disables it even if exported in the shell).
if "pytest" not in sys.modules:
    load_dotenv()


def create_app(itv: Interview) -> FastAPI:
    app = FastAPI(title="PolicyBot")

    @app.post("/assess", response_model=None)
    def assess(payload: dict) -> InterviewState | JSONResponse:
        try:
            return run_graph(
                itv,
                RequestInfo(**payload["request"]),
                payload["tool_name"],
                payload["usage_inputs"],
                payload.get("iag_type_override"),
            )
        except UnknownToolError:
            return JSONResponse(
                status_code=422,
                content={
                    "error": "unknown_tool",
                    "question": tool_type_question().model_dump(),
                },
            )

    @app.post("/report", response_class=HTMLResponse)
    def report(state: InterviewState) -> str:
        return render_html(state)

    return app


app = create_app(default_interview())
