"""Candidate generation for the executable catalog (Phase 3).

Two backends:
- ``generate_from_endpoint`` — OpenAI-compatible HTTP endpoint (llama-swap,
  vLLM, our own serving API). temperature defaults to 0 for determinism.
- ``generate_from_local`` — direct Transformers backend loading a base model +
  a LoRA adapter.

Both emit SQL/PLSQL-only answers (see ``SQL_ONLY_SYSTEM``) and write
``{id, answer}`` JSONL candidates suitable for evaluate_catalog.py.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from typing import Dict, Iterable, List, Optional

SQL_ONLY_SYSTEM = (
    "You are an expert Oracle Database engineer. Respond with ONLY the SQL or "
    "PL/SQL needed to complete the task. No explanation, no markdown, no "
    "prose."
)


def _tasks(catalog: str) -> List[dict]:
    return [json.loads(l) for l in open(catalog, encoding="utf-8") if l.strip()]


def _prompt_for(task: dict) -> str:
    prompt = task["task"]
    schema = task.get("schema", "")
    if schema:
        prompt += f"\n\nTarget schema: {schema}."
    return prompt


def generate_from_endpoint(
    catalog: str,
    base_url: str,
    model: str,
    api_key: str = "sk-none",
    out: str = "candidate_answers.jsonl",
    system_prompt: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: Optional[int] = None,
    progress: bool = True,
) -> List[Dict]:
    """Generate candidates by calling an OpenAI-compatible chat endpoint."""
    tasks = _tasks(catalog)
    results: List[Dict] = []
    sys_prompt = system_prompt or SQL_ONLY_SYSTEM
    for i, t in enumerate(tasks, start=1):
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": _prompt_for(t)},
            ],
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        req = urllib.request.Request(
            base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                answer = body["choices"][0]["message"]["content"].strip()
            results.append({"id": t["id"], "answer": answer})
        except Exception as exc:  # noqa: BLE001
            if progress:
                print(f"  [error] {t['id']}: {str(exc)[:100]}", file=sys.stderr)
            results.append({"id": t["id"], "answer": ""})
        if progress and (i % 25 == 0 or i == len(tasks)):
            print(f"  generated {i}/{len(tasks)}", file=sys.stderr)
    _write(out, results)
    return results


def generate_from_local(
    catalog: str,
    base_model: str,
    adapter_dir: Optional[str],
    out: str = "candidate_answers.jsonl",
    max_new_tokens: int = 1024,
    temperature: float = 0.0,
    device: str = "cuda",
    progress: bool = True,
    retriever=None,
) -> List[Dict]:
    """Generate candidates with a local Transformers model (+ optional LoRA)."""
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(base_model, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    load_kwargs: dict = {"device_map": "auto"}
    if device == "cuda" and torch.cuda.is_available():
        load_kwargs["torch_dtype"] = torch.bfloat16
    model = AutoModelForCausalLM.from_pretrained(base_model, **load_kwargs)
    if adapter_dir:
        model = PeftModel.from_pretrained(model, adapter_dir)
    model.eval()

    tasks = _tasks(catalog)
    results: List[Dict] = []
    gen_kwargs = dict(
        max_new_tokens=max_new_tokens,
        do_sample=temperature > 0,
        temperature=temperature if temperature > 0 else None,
    )
    with torch.no_grad():
        for i, t in enumerate(tasks, start=1):
            user_content = _prompt_for(t)
            if retriever is not None:
                user_content = retriever.build_context_prompt(user_content, mode="sql_only")
            chat = [
                {"role": "system", "content": SQL_ONLY_SYSTEM},
                {"role": "user", "content": user_content},
            ]
            prompt = tokenizer.apply_chat_template(chat, tokenize=False, add_generation_prompt=True)
            inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
            out_ids = model.generate(**inputs, **gen_kwargs)
            answer = tokenizer.decode(
                out_ids[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True
            ).strip()
            results.append({"id": t["id"], "answer": answer})
            if progress and (i % 25 == 0 or i == len(tasks)):
                print(f"  generated {i}/{len(tasks)}", file=sys.stderr)
    _write(out, results)
    return results


def _write(out: str, results: List[Dict]) -> None:
    with open(out, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(results)} candidates -> {out}")
