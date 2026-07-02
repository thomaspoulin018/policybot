import pytest
from policybot.llm.fake import FakeLLMProvider
from policybot.llm.provider import LLMProvider


def test_fake_is_a_provider():
    assert isinstance(FakeLLMProvider(), LLMProvider)


def test_fake_returns_queued_json_and_records_calls():
    fake = FakeLLMProvider(json_responses=[{"a": 1}, {"b": 2}])
    assert fake.complete_json("sys", "u1") == {"a": 1}
    assert fake.complete_json("sys", "u2") == {"b": 2}
    assert fake.calls == [("sys", "u1"), ("sys", "u2")]


def test_fake_json_exhausted_raises():
    fake = FakeLLMProvider(json_responses=[{"a": 1}])
    fake.complete_json("s", "u")
    with pytest.raises(IndexError):
        fake.complete_json("s", "u")


def test_fake_draft_text():
    fake = FakeLLMProvider(text_responses=["bonjour"])
    assert fake.draft_text("s", "u") == "bonjour"
