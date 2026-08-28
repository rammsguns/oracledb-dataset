"""Prompt rendering and assistant-only loss masking (Phase 1 data contract)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

DEFAULT_SYSTEM = (
    "You are an expert Oracle Database engineer. Produce correct Oracle SQL or "
    "PL/SQL. Follow the requested response style exactly."
)


def row_to_chat(record: Dict[str, Any]) -> List[Dict[str, str]]:
    """Normalize a record into a chat message list ending with an assistant turn.

    Chat records pass through as-is; instruction-triplet records are wrapped in
    the default system + user/assistant structure (user content = instruction
    + optional ``input``).
    """
    if "messages" in record:
        return record["messages"]
    user = record["instruction"].strip()
    if record.get("input", "").strip():
        user += "\n\n" + record["input"].strip()
    return [
        {"role": "system", "content": DEFAULT_SYSTEM},
        {"role": "user", "content": user},
        {"role": "assistant", "content": record["output"].strip()},
    ]


def render_prompt_and_answer(
    record: Dict[str, Any], tokenizer, add_generation_prompt: bool = False
) -> Tuple[str, str]:
    """Render the prompt (chat template) and the target assistant answer.

    Returns ``(prompt_text, answer_text)`` where ``prompt_text`` is the chat
    template with ``add_generation_prompt=True`` (or the messages up to but
    excluding the assistant answer when ``add_generation_prompt=False``), and
    ``answer_text`` is the final assistant content.
    """
    chat = row_to_chat(record)
    answer = chat[-1]["content"].strip()
    prompt = tokenizer.apply_chat_template(
        chat[:-1], tokenize=False, add_generation_prompt=True
    )
    return prompt, answer


def tokenize_supervised(
    record: Dict[str, Any],
    tokenizer,
    max_length: int = 2048,
    label_pad: int = -100,
) -> Optional[Dict[str, Any]]:
    """Tokenize one record into an SFT example with assistant-only loss masking.

    The prompt span is labeled ``label_pad`` (-100) so the loss is computed only
    over assistant tokens. Returns None if no assistant tokens survive the
    truncation (caller should drop such examples).
    """
    prompt, answer = render_prompt_and_answer(record, tokenizer, add_generation_prompt=True)
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    answer_ids = tokenizer(answer + tokenizer.eos_token, add_special_tokens=False)["input_ids"]

    # Preserve the whole answer when possible; only truncate the prompt.
    if len(prompt_ids) + len(answer_ids) > max_length:
        keep_prompt = max(0, max_length - len(answer_ids))
        prompt_ids = prompt_ids[-keep_prompt:]
        answer_ids = answer_ids[:max_length]

    input_ids = (prompt_ids + answer_ids)[:max_length]
    labels = ([-100] * len(prompt_ids) + answer_ids)[:max_length]
    if len(prompt_ids) >= max_length:
        return None  # nothing left for supervision
    if not any(label != label_pad for label in labels):
        return None
    return {
        "input_ids": input_ids,
        "attention_mask": [1] * len(input_ids),
        "labels": labels,
    }
