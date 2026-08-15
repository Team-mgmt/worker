from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from worker.core.database import AsyncSessionLocal
from worker.services.matching_ablation_service import (
    MatchingAblationCase,
    cases_from_artifacts,
    evaluate_ablation_cases,
)
from worker.services.matching_service import normalize_core_title, query_catalog_candidate_rows, split_call_number


def _load_cases(artifact_root: Path) -> list[MatchingAblationCase]:
    cases: list[MatchingAblationCase] = []
    for result_path in artifact_root.rglob("result.json"):
        ground_truth_path = result_path.with_name("ground-truth.json")
        if not ground_truth_path.is_file():
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        ground_truth = json.loads(ground_truth_path.read_text(encoding="utf-8"))
        cases.extend(cases_from_artifacts(result, ground_truth))
    return cases


async def _candidate_pools(
    cases: list[MatchingAblationCase],
) -> list[tuple[MatchingAblationCase, list[Any]]]:
    evaluated: list[tuple[MatchingAblationCase, list[Any]]] = []
    pool_cache: dict[tuple[str, str], list[Any]] = {}
    async with AsyncSessionLocal() as session:
        for index, case in enumerate(cases, start=1):
            class_no, _ = split_call_number(case.ocr.call_number or "")
            scope = f"class:{class_no}" if class_no else f"title:{normalize_core_title(case.ocr.title, case.ocr.author)}"
            cache_key = (case.library_code, scope)
            rows = pool_cache.get(cache_key)
            if rows is None:
                rows = await query_catalog_candidate_rows(
                    session,
                    case.library_code,
                    case.ocr,
                    use_exact_shortcut=False,
                    evaluation_broad_pool=True,
                )
                pool_cache[cache_key] = rows
            evaluated.append((case, rows))
            print(
                f"[{index}/{len(cases)}] run={case.run_id} "
                f"library={case.library_code} candidates={len(rows)}",
                flush=True,
            )
    return evaluated


def _markdown(report: dict[str, Any]) -> str:
    labels = {
        "baseline": "Baseline (RapidFuzz)",
        "preprocessed_fuzzy": "전처리 + RapidFuzz",
        "tfidf": "전처리 + n-gram TF-IDF",
        "final": "최종 결합",
    }
    lines = [
        "| 전략 | N | Top-1 | Top-3 | 제목 정확도 | 청구기호 정확도 | 오확정률 | 평균 ms | P95 ms | 후보 누락 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for strategy, metrics in report.items():
        lines.append(
            "| {label} | {n} | {top1:.1%} | {top3:.1%} | {title:.1%} | {call:.1%} | "
            "{false_rate:.1%} | {mean:.2f} | {p95:.2f} | {miss} |".format(
                label=labels[strategy],
                n=metrics["evaluated_count"],
                top1=metrics["top1_accuracy"],
                top3=metrics["top3_accuracy"],
                title=metrics["title_normalized_accuracy"],
                call=metrics["call_number_exact_accuracy"],
                false_rate=metrics["false_confirmation_rate"],
                mean=metrics["reranking_latency_mean_ms"],
                p95=metrics["reranking_latency_p95_ms"],
                miss=metrics["candidate_pool_miss_count"],
            )
        )
    return "\n".join(lines) + "\n"


async def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate ShelfAlign catalog-matching ablations.")
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("outputs/matching-ablation.json"))
    parser.add_argument("--markdown", type=Path, default=Path("outputs/matching-ablation.md"))
    args = parser.parse_args()

    cases = _load_cases(args.artifact_root)
    if not cases:
        raise SystemExit("No polygon-aligned result.json/ground-truth.json cases were found.")
    cases_with_rows = await _candidate_pools(cases)
    overall = evaluate_ablation_cases(cases_with_rows)
    libraries = {
        library_code: evaluate_ablation_cases(
            [(case, rows) for case, rows in cases_with_rows if case.library_code == library_code]
        )
        for library_code in sorted({case.library_code for case in cases})
    }
    payload = {
        "schema_version": "1.0",
        "case_count": len(cases),
        "overall": overall,
        "libraries": libraries,
        "latency_scope": "Python reranking only; DB query, detection, and OCR excluded",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    args.markdown.write_text(_markdown(overall), encoding="utf-8")
    print(f"Wrote {args.output} and {args.markdown}")


if __name__ == "__main__":
    asyncio.run(main())
