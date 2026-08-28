"""Transformers-backed generation backend for the serving API (Phase 5).

Loads a base model + optional LoRA adapter and provides an OpenAI-style
``generate(messages, temperature)`` callable used by the FastAPI app. The
backend is constructed lazily (model loaded on first request) so the API can
start and report readiness before the (potentially slow) model load completes.
"""
from __future__ import annotations

import threading
from typing import List, Optional

import torch

from oracle_llm.serving.prompts import SQL_ONLY_SYSTEM


class TransformersBackend:
    """A callable backend wrapping a Transformers causal-LM + LoRA adapter."""

    def __init__(
        self,
        base_model: str,
        adapter: Optional[str] = None,
        max_new_tokens: int = 1024,
        device: str = "cuda",
    ):
        self.base_model = base_model
        self.adapter = adapter
        self.max_new_tokens = max_new_tokens
        self.device = device
        self._lock = threading.Lock()
        self._loaded = False
        self._model = None
        self._tokenizer = None

    def _ensure_loaded(self):
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            from peft import PeftModel
            from transformers import AutoModelForCausalLM, AutoTokenizer

            tokenizer = AutoTokenizer.from_pretrained(self.base_model, use_fast=True)
            if tokenizer.pad_token is None:
                tokenizer.pad_token = tokenizer.eos_token
            load_kwargs: dict = {"device_map": "auto"}
            if self.device == "cuda" and torch.cuda.is_available():
                load_kwargs["dtype"] = torch.bfloat16
            model = AutoModelForCausalLM.from_pretrained(self.base_model, **load_kwargs)
            if self.adapter:
                model = PeftModel.from_pretrained(model, self.adapter)
            model.eval()
            self._tokenizer = tokenizer
            self._model = model
            self._loaded = True

    def generate(self, messages: List[dict], temperature: float) -> str:
        """Run a chat completion over ``messages`` (list of {role, content})."""
        self._ensure_loaded()
        tokenizer = self._tokenizer
        model = self._model
        prompt = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        gen_kwargs = dict(
            max_new_tokens=self.max_new_tokens,
            do_sample=temperature > 0,
            temperature=temperature if temperature > 0 else None,
        )
        with torch.no_grad():
            out_ids = model.generate(**inputs, **gen_kwargs)
        return tokenizer.decode(
            out_ids[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True
        ).strip()
