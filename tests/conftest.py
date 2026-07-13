import os
import tempfile

# Keep the test suite offline and deterministic: LangSmith tracing must never be
# active during pytest, even if the developer exported the toggle in their shell
# or it leaks in via a loaded .env. Runs at conftest import, before any test
# module (and thus policybot.api.app) is collected.
for _var in ("LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING"):
    os.environ.pop(_var, None)

# Redirect the internal trace log (policybot.tracing) to a throwaway temp file so
# running the suite never writes into the repo's logs/ directory.
os.environ.setdefault(
    "POLICYBOT_LOG_PATH",
    os.path.join(tempfile.mkdtemp(prefix="policybot-logs-"), "policybot.jsonl"),
)

# Generated PDFs can contain report details, so tests write them outside the repo.
os.environ.setdefault(
    "POLICYBOT_PDF_OUTPUT_DIR",
    os.path.join(tempfile.mkdtemp(prefix="policybot-output-"), "pdf"),
)

# Generated Word files can contain report details, so tests write them outside the repo.
os.environ.setdefault(
    "POLICYBOT_DOCX_OUTPUT_DIR",
    os.path.join(tempfile.mkdtemp(prefix="policybot-output-"), "docx"),
)
