from __future__ import annotations

import argparse
from pathlib import Path

from pubtator_link.benchmarks.models import BenchmarkMode
from pubtator_link.benchmarks.runner import run_suite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pubtator-link benchmark")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--suite", required=True)
    run_parser.add_argument("--answer-stack", default="dry_run:deterministic")
    run_parser.add_argument("--artifact-dir", default="benchmarks/results")
    run_parser.add_argument("--mode", choices=[mode.value for mode in BenchmarkMode])
    run_parser.add_argument("--case-count", type=int)
    run_parser.add_argument("--no-db", action="store_true")
    run_parser.add_argument("--database-url")
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--resume", action="store_true")
    run_parser.add_argument("--shard")
    run_parser.add_argument("--shard-of")
    analyze_parser = subparsers.add_parser("analyze")
    analyze_parser.add_argument("--run-id")
    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("--left")
    compare_parser.add_argument("--right")
    judge_parser = subparsers.add_parser("judge")
    judge_parser.add_argument("--run-id")
    judge_parser.add_argument("--self-judge-model")

    args = parser.parse_args(argv)
    if args.command == "compare":
        if (
            not args.left
            or not args.right
            or not Path(args.left).exists()
            or not Path(args.right).exists()
        ):
            parser.print_usage()
            return 2
        return 0
    if args.command in {"analyze", "judge"}:
        if not args.run_id:
            parser.print_usage()
            return 2
        return 0
    if args.command != "run":
        return 2
    if args.resume or args.shard or args.shard_of:
        parser.print_usage()
        return 2
    run_suite(
        suite_path=Path(args.suite),
        answer_stack=args.answer_stack,
        artifact_dir=Path(args.artifact_dir),
        mode=BenchmarkMode(args.mode) if args.mode else None,
        case_count=args.case_count,
        no_db=args.no_db,
        dry_run=args.dry_run,
        database_url=args.database_url,
    )
    return 0
