"""Generate candidate model answers for a task catalog, for evaluation.

Produces a JSONL of {id, answer} suitable for:
    evaluate_catalog.py --catalog <catalog> --candidate <this output>

Two modes:
  --mode gold          : emit each task's gold_sql verbatim (sanity: 100% pass).
  --mode baseline      : emit a naive baseline (first line heuristic / empty),
                         to show the harness correctly FAILS bad answers.
  --mode model         : call an OpenAI-compatible endpoint (llama-swap, vLLM,
                         Ollama, etc.) to generate an answer per task.

Usage (model mode):
    python generate_answers.py --catalog llm_task_catalog_eval.jsonl \
        --mode model --out candidate_answers.jsonl \
        --base-url http://localhost:11434/v1 --api-key sk-none --model my-oracle
    # then:
    python evaluate_catalog.py --catalog llm_task_catalog_eval.jsonl \
        --candidate candidate_answers.jsonl
"""
import argparse
import json
import sys
import urllib.request


def load_tasks(path):
    return [json.loads(l) for l in open(path) if l.strip()]


def gold_answers(tasks):
    return [{"id": t["id"], "answer": t.get("gold_sql", "")} for t in tasks]


def baseline_answers(tasks):
    """A deliberately weak baseline to prove the harness catches wrong answers.
    Emits the gold answer for half (to show it can pass) and a broken/empty
    statement for the other half (to show it fails)."""
    out = []
    for i, t in enumerate(tasks):
        if i % 2 == 0:
            out.append({"id": t["id"], "answer": t.get("gold_sql", "")})
        else:
            # naive / wrong answer: a plausible-looking but wrong statement
            out.append({"id": t["id"], "answer": "SELECT 1 FROM dual;"})
    return out


def model_answers(tasks, base_url, api_key, model, system_prompt):
    """Call an OpenAI-compatible chat endpoint for each task."""
    import json as _json
    out = []
    for t in tasks:
        prompt = t["task"]
        schema = t.get("schema", "")
        if schema:
            prompt += f"\n\nTarget schema: {schema}. "
        payload = {
            "model": model,
            "messages": [
                {"role": "system",
                 "content": system_prompt or
                            ("You are an expert Oracle Database engineer. "
                             "Respond with ONLY the SQL or PL/SQL needed to "
                             "complete the task. No explanation, no markdown.")},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
        }
        req = urllib.request.Request(
            base_url.rstrip("/") + "/chat/completions",
            data=_json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + api_key})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = _json.loads(resp.read().decode("utf-8"))
                answer = body["choices"][0]["message"]["content"].strip()
                out.append({"id": t["id"], "answer": answer})
        except Exception as e:
            print("  [error] %s: %s" % (t["id"], str(e)[:100]))
            out.append({"id": t["id"], "answer": ""})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--mode", choices=["gold", "baseline", "model"], default="gold")
    ap.add_argument("--out", default="candidate_answers.jsonl")
    ap.add_argument("--base-url", default="http://localhost:11434/v1",
                    help="OpenAI-compatible base URL (llama-swap/vLLM/Ollama)")
    ap.add_argument("--api-key", default="sk-none")
    ap.add_argument("--model", default="oracle-expert")
    ap.add_argument("--system-prompt", default=None)
    args = ap.parse_args()

    tasks = load_tasks(args.catalog)
    if args.mode == "gold":
        answers = gold_answers(tasks)
    elif args.mode == "baseline":
        answers = baseline_answers(tasks)
    else:
        answers = model_answers(tasks, args.base_url, args.api_key,
                                args.model, args.system_prompt)

    with open(args.out, "w") as f:
        for a in answers:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    print("wrote %d answers -> %s (mode=%s)" % (len(answers), args.out, args.mode))
    print("next: evaluate_catalog.py --catalog %s --candidate %s" % (args.catalog, args.out))


if __name__ == "__main__":
    main()
