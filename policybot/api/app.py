from __future__ import annotations
import os
import sys
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from policybot.models import InterviewState, RequestInfo, ContractOfferingIdentity
from policybot.interview.orchestrator import Interview, UnknownToolError
from policybot.interview.graph import run_graph
from policybot.classify.tool_type import tool_type_question
from policybot.report.renderer import render_html, write_docx, write_pdf
from policybot.api.deps import default_interview
from policybot.web.routes import router as web_router
from policybot.tracing import trace_step

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "web", "static")

# Load .env so the OpenRouter and LangSmith keys are picked up automatically on a
# real run. Skipped under pytest so the suite never turns tracing on (see also
# tests/conftest.py, which hard-disables it even if exported in the shell).
if "pytest" not in sys.modules:
    load_dotenv()


def create_app(itv: Interview) -> FastAPI:
    app = FastAPI(title="PolicyBot")
    app.state.interview = itv
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
    app.include_router(web_router)

    @app.post("/assess", response_model=None)
    def assess(payload: dict) -> InterviewState | JSONResponse:
        with trace_step(None, "api_assess", tool_name=payload.get("tool_name")) as extra:
            try:
                result = run_graph(
                    itv,
                    RequestInfo(**payload["request"]),
                    payload["tool_name"],
                    payload["usage_inputs"],
                    payload.get("iag_type_override"),
                    ContractOfferingIdentity.model_validate(payload["offering"])
                    if payload.get("offering") else None,
                )
                extra["response"] = "ok"
                return result
            except UnknownToolError:
                extra["response"] = "422_unknown_tool"
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

    @app.post("/report/pdf", response_model=None)
    def report_pdf(state: InterviewState) -> FileResponse | JSONResponse:
        try:
            path = write_pdf(state)
        except Exception as exc:
            return JSONResponse(status_code=503, content={"error": "pdf_export_failed", "detail": str(exc)})
        return FileResponse(path, media_type="application/pdf", filename=path.name)

    @app.post("/report/docx", response_model=None)
    def report_docx(state: InterviewState) -> FileResponse | JSONResponse:
        try:
            path = write_docx(state)
        except Exception as exc:
            return JSONResponse(status_code=503, content={"error": "docx_export_failed", "detail": str(exc)})
        return FileResponse(
            path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=path.name,
        )

    return app


app = create_app(default_interview())
