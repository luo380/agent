from core.service.rag import LIST_MEMBERSHIP_GROUNDING_RULE as LEGACY_RULE, build_rag_messages
from core.service.rag_langchain_native import (
    LIST_MEMBERSHIP_GROUNDING_RULE as NATIVE_RULE,
    build_answer_instruction,
)


def test_native_build_answer_instruction_mentions_list_membership_grounding_rule():
    assert NATIVE_RULE in build_answer_instruction("context", True)


def test_legacy_build_rag_messages_mentions_list_membership_grounding_rule():
    messages = build_rag_messages("question", "context", True)
    assert LEGACY_RULE in messages[1]["content"]
