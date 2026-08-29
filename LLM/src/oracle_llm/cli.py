"""Project-local CLI entry point for the Oracle LLM pipeline.

Subcommands:
    train      — run a QLoRA/LoRA SFT experiment (chat | sql_only | error_repair)
    validate   — validate + fingerprint one or more training JSONL files
    generate   — generate candidates from an endpoint or local model
    evaluate   — summarize evaluate_catalog.py results / compare runs
    promote    — apply the selection policy to a candidate run
    serve      — start the OpenAI-compatible FastAPI service
"""
from __future__ import annotations

import argparse
import sys


def _cmd_validate(argv):
    ap = argparse.ArgumentParser(prog="oracle-llm validate")
    ap.add_argument("files", nargs="+", help="training JSONL files to validate")
    ap.add_argument("--manifest", help="optional path to write a data manifest")
    args = ap.parse_args(argv)

    from oracle_llm.data.guards import assert_not_held_out
    from oracle_llm.data.loaders import load_records
    from oracle_llm.data.manifest import Manifest
    from oracle_llm.data.validate import validate_records

    assert_not_held_out(args.files)  # fail closed on the held-out catalog
    records = load_records(args.files)
    validate_records(records)
    print(f"PASS: {len(records)} records validated across {len(args.files)} file(s)")
    if args.manifest:
        m = Manifest([__import__("pathlib").Path(f) for f in args.files], records)
        m.save(args.manifest)
        print(f"manifest -> {args.manifest}")


def _cmd_train(argv):
    ap = argparse.ArgumentParser(prog="oracle-llm train")
    ap.add_argument("--config", required=True, help="training YAML (e.g. configs/training/qlora-7b.yaml)")
    ap.add_argument("--output-dir", required=True, help="adapter/artifact output directory")
    ap.add_argument("--no-eval", action="store_true", help="skip the validation holdout split")
    ap.add_argument("--overwrite", action="store_true", help="allow reusing an existing output dir")
    args = ap.parse_args(argv)

    from pathlib import Path

    from oracle_llm.training.config import load_config
    from oracle_llm.training.train import train_qlora

    out = Path(args.output_dir)
    if out.exists() and any(out.iterdir()) and not args.overwrite:
        ap.error(f"output dir not empty (use --overwrite to reuse): {out}")

    cfg = load_config(args.config, output_dir=str(out))
    eval_records = None
    if not args.no_eval and cfg.eval_file:
        from oracle_llm.data.loaders import load_records

        eval_records = load_records([cfg.eval_file])
    train_qlora(cfg, out, eval_records=eval_records)


def _cmd_generate(argv):
    ap = argparse.ArgumentParser(prog="oracle-llm generate")
    ap.add_argument("--catalog", required=True, help="task catalog JSONL")
    ap.add_argument("--out", default="candidates.jsonl")
    ap.add_argument("--backend", choices=["endpoint", "local"], default="endpoint")
    ap.add_argument("--base-url", default="http://localhost:8000/v1")
    ap.add_argument("--api-key", default="sk-none")
    ap.add_argument("--model", default="oracle-assistant")
    ap.add_argument("--base-model", help="local base model (backend=local)")
    ap.add_argument("--adapter", help="LoRA adapter dir (backend=local)")
    ap.add_argument("--max-new-tokens", type=int, default=1024)
    ap.add_argument("--schema-index", help="approved schema index JSON (injects "
                    "schema-context retrieval into sql_only prompts)")
    ap.add_argument("--compact", action="store_true", help="v3: low-noise DDL "
                    "(columns+PK+FK only, drop checks/descriptions)")
    ap.add_argument("--max-context-tokens", type=int, default=0,
                    help="v3: strict per-request context token budget (0=unlimited)")
    args = ap.parse_args(argv)

    from oracle_llm.evaluation.generate import generate_from_endpoint, generate_from_local

    retriever = None
    if args.schema_index:
        from oracle_llm.serving.retrieval import SchemaRetriever

        retriever = SchemaRetriever(args.schema_index)

    if args.backend == "local":
        generate_from_local(
            args.catalog, args.base_model, args.adapter, out=args.out,
            max_new_tokens=args.max_new_tokens, retriever=retriever,
            compact=args.compact, max_context_tokens=args.max_context_tokens,
        )
    else:
        generate_from_endpoint(
            args.catalog, args.base_url, args.model, api_key=args.api_key, out=args.out
        )


def _cmd_evaluate(argv):
    ap = argparse.ArgumentParser(prog="oracle-llm evaluate")
    ap.add_argument("results", nargs="+", help="one or more result JSONL files (evaluate_catalog.py output)")
    ap.add_argument("--out", help="optional path to write a comparison report JSON")
    args = ap.parse_args(argv)

    from oracle_llm.evaluation.summarize import (
        comparison_report,
        load_results,
        summarize_results,
    )

    runs = [load_results(r) for r in args.results]
    if len(runs) == 1:
        s = summarize_results(runs[0])
        print(f"tasks={s['tasks']} passed={s['passed']} ({s['passed_pct']}%) "
              f"executed_ok={s['executed_ok']} ({s['executed_ok_pct']}%) "
              f"exact={s['exact_result']} ({s['exact_result_pct']}%)")
        for k, v in s["by_kind"].items():
            print(f"  kind {k:<11} {v['passed']}/{v['total']}")
        for k, v in s["by_schema"].items():
            print(f"  schema {k:<15} {v['passed']}/{v['total']}")
        if args.out:
            import json
            from pathlib import Path

            Path(args.out).write_text(json.dumps(s, indent=2) + "\n")
            print(f"report -> {args.out}")
    else:
        rep = comparison_report(*runs)
        for i, s in enumerate(rep["runs"]):
            print(f"run {i}: tasks={s['tasks']} passed={s['passed']} ({s['passed_pct']}%) "
                  f"exact={s['exact_result']} ({s['exact_result_pct']}%)")
        if args.out:
            import json
            from pathlib import Path

            Path(args.out).write_text(json.dumps(rep, indent=2) + "\n")
            print(f"comparison -> {args.out}")


def _cmd_promote(argv):
    ap = argparse.ArgumentParser(prog="oracle-llm promote")
    ap.add_argument("--run-metadata", required=True, help="run provenance.json")
    ap.add_argument("--results", required=True, help="run result JSONL")
    ap.add_argument("--gold-results", required=True, help="gold-harness result JSONL")
    ap.add_argument("--baseline-results", required=True, help="base-baseline result JSONL")
    ap.add_argument("--manifest", help="optional frozen MANIFEST.md path")
    ap.add_argument("--out", default="promotion.json")
    args = ap.parse_args(argv)

    from oracle_llm.evaluation.summarize import load_results, summarize_results
    from oracle_llm.training.selection import check_promotion

    gold = summarize_results(load_results(args.gold_results))
    baseline = summarize_results(load_results(args.baseline_results))
    decision = check_promotion(
        run_metadata_path=args.run_metadata,
        results_path=args.results,
        gold_summary=gold,
        baseline_summary=baseline,
        frozen_manifest_path=args.manifest,
    )
    import json
    from pathlib import Path

    Path(args.out).write_text(json.dumps(decision.to_dict(), indent=2) + "\n")
    print(f"decision: {decision.status}")
    for r in decision.reasons:
        print(f"  - {r}")
    print(f"report -> {args.out}")


def _cmd_gate(argv):
    ap = argparse.ArgumentParser(prog="oracle-llm gate")
    ap.add_argument("--results", required=True, help="candidate result JSONL")
    ap.add_argument("--out", default="promotion_gate.json")
    ap.add_argument("--min-pass-pct", type=float, help="override min pass %% threshold")
    ap.add_argument("--min-ce-matched", type=int, help="override min controlled-error matched")
    args = ap.parse_args(argv)

    from oracle_llm.training.selection import (
        DEFAULT_PROMOTION_THRESHOLDS,
        check_promotion_thresholds,
    )

    t = dict(DEFAULT_PROMOTION_THRESHOLDS)
    if args.min_pass_pct is not None:
        t["min_passed_pct"] = args.min_pass_pct
    if args.min_ce_matched is not None:
        t["min_controlled_error_matched"] = args.min_ce_matched
    decision = check_promotion_thresholds(args.results, thresholds=t)
    import json
    from pathlib import Path

    Path(args.out).write_text(json.dumps(decision.to_dict(), indent=2) + "\n")
    print(f"gate: {decision.status} (thresholds {t})")
    for r in decision.reasons:
        print(f"  - {r}")
    print(f"report -> {args.out}")


def _cmd_serve(argv):
    ap = argparse.ArgumentParser(prog="oracle-llm serve")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--model-id", default="oracle-assistant")
    ap.add_argument("--adapter-version", default="unknown")
    ap.add_argument("--base-model", help="base model id (loads a real backend)")
    ap.add_argument("--adapter", help="LoRA adapter dir (loads a real backend)")
    ap.add_argument("--max-new-tokens", type=int, default=1024)
    ap.add_argument("--schema-index", help="path to approved schema index JSON "
                    "(enables schema-context retrieval in sql_only mode)")
    ap.add_argument("--read-only", action="store_true",
                    help="staged read-only pilot: refuse DML/DDL requests (SELECT only)")
    args = ap.parse_args(argv)

    from oracle_llm.serving.app import _Backend, serve

    backend = _Backend(model_id=args.model_id, adapter_version=args.adapter_version)
    if args.base_model:
        from oracle_llm.serving.backend import TransformersBackend

        backend.generate = TransformersBackend(
            args.base_model, args.adapter, max_new_tokens=args.max_new_tokens
        ).generate

    retriever = None
    if args.schema_index:
        from oracle_llm.serving.retrieval import SchemaRetriever

        retriever = SchemaRetriever(args.schema_index)

    serve(
        host=args.host, port=args.port,
        backend=backend, default_max_tokens=args.max_new_tokens,
        retriever=retriever, read_only=args.read_only,
    )


def main(argv=None):
    ap = argparse.ArgumentParser(prog="oracle-llm", description="Oracle Database LLM pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate", help="validate training JSONL files")
    sub.add_parser("train", help="run a QLoRA/LoRA SFT experiment")
    sub.add_parser("generate", help="generate candidate answers")
    sub.add_parser("evaluate", help="summarize / compare evaluation results")
    sub.add_parser("promote", help="apply the selection policy")
    sub.add_parser("gate", help="gate a candidate against selected-adapter thresholds")
    sub.add_parser("serve", help="start the OpenAI-compatible API")
    args, rest = ap.parse_known_args(argv)

    dispatch = {
        "validate": _cmd_validate,
        "train": _cmd_train,
        "generate": _cmd_generate,
        "evaluate": _cmd_evaluate,
        "promote": _cmd_promote,
        "gate": _cmd_gate,
        "serve": _cmd_serve,
    }
    return dispatch[args.cmd](rest)


if __name__ == "__main__":
    sys.exit(main())
