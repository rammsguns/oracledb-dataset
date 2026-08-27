#!/usr/bin/env python3
"""Load the Oracle dataset for fine-tuning via HuggingFace datasets.

Usage:
    from datasets import load_dataset
    ds = load_dataset("json", data_files={
        "train": "oracle_train_alpaca.jsonl",
        "eval":  "oracle_eval_holdout.jsonl",
    })
"""
import json

def yield_examples(path):
    with open(path) as f:
        for line in f:
            yield json.loads(line)

if __name__ == "__main__":
    for split in ["oracle_train_alpaca.jsonl", "oracle_eval_holdout.jsonl"]:
        n = sum(1 for _ in yield_examples(split))
        print(f"{split}: {n} examples")
