from __future__ import annotations
import os
from policybot.llm.openrouter import OpenRouterProvider
from policybot.llm.fake import FakeLLMProvider
from policybot.preapproved.store import PreApprovedStore
from policybot.interview.orchestrator import Interview


def default_interview(db_path: str = "policybot.db") -> Interview:
    key = os.environ.get("OPENROUTER_API_KEY")
    llm = OpenRouterProvider(key) if key else FakeLLMProvider()
    return Interview(llm=llm, store=PreApprovedStore(db_path))
