"""Run the fixed NewsWeaver evaluation fixture."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from newsweaver.evaluation import evaluate_fixture  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate NewsWeaver on a fixed local fixture")
    parser.add_argument(
        "fixture",
        nargs="?",
        type=Path,
        default=ROOT / "tests" / "fixtures" / "eval" / "baseline.json",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()
    result = evaluate_fixture(json.loads(args.fixture.read_text(encoding="utf-8")))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    metrics = result["metrics"]
    print(f"Fixture:                  {result['fixture']}")
    print(f"Citation validity:        {metrics['citation_validity']:.0%}")
    print(f"Unsupported claims:       {metrics['unsupported_claim_rate']:.0%}")
    print(f"Claim coverage:           {metrics['claim_coverage']:.0%}")
    print(f"Event duplication:        {metrics['duplicate_event_rate']:.0%}")
    print(f"Important event recall:   {metrics['important_event_recall']:.0%}")
    print(f"Source diversity:         {metrics['source_diversity']:.2f}")
    print(f"Trend consistency:        {metrics['trend_consistency']:.0%}")
    print(f"Extraction success:       {metrics['extraction_success_rate']:.0%}")
    print(f"Token usage:              {metrics['token_usage']['total']}")
    print(f"Estimated cost:           ${metrics['estimated_generation_cost']:.6f}")
    print(f"Recorded latency:         {metrics['latency_seconds']:.2f}s")


if __name__ == "__main__":
    main()
