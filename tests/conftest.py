import os

# Keep the test suite offline and deterministic: LangSmith tracing must never be
# active during pytest, even if the developer exported the toggle in their shell
# or it leaks in via a loaded .env. Runs at conftest import, before any test
# module (and thus policybot.api.app) is collected.
for _var in ("LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING"):
    os.environ.pop(_var, None)
