# cli.py
import argparse
import json
from pathlib import Path

from .workflow import run_business_research


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Calm Engineer Agentic Business Research Agent"
    )
    parser.add_argument("niche", help="Niche or business idea, e.g. 'AI for dentists'")
    parser.add_argument(
        "--audience",
        help="Optional: target audience, e.g. 'solo dentists in North America'",
    )
    parser.add_argument(
        "--geo",
        dest="geography",
        help="Optional: primary geography, e.g. 'US', 'Canada', or 'Global'",
    )
    parser.add_argument(
        "--constraints",
        help="Optional: constraints like budget/time/skills.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional: path to save raw JSON report.",
    )

    args = parser.parse_args()

    report = run_business_research(
        niche=args.niche,
        audience=args.audience,
        geography=args.geography,
        constraints=args.constraints,
    )

    # Pretty print to console
    print("\n=== Business Research Summary ===\n")
    print(f"Niche: {report.get('niche')}\n")
    print("Audience summary:\n", report.get("audience_summary", ""), "\n")

    print("Top problems:")
    for i, p in enumerate(report.get("top_problems", []), start=1):
        print(f"{i}. {p.get('problem')}")
        print(f"   Why it matters: {p.get('why_it_matters')}")
        if p.get("current_solutions"):
            print("   Current solutions:", p.get("current_solutions"))
        print()

    print("\nOffer ideas:")
    for i, o in enumerate(report.get("offer_ideas", []), start=1):
        print(f"{i}. {o.get('offer_name')} ({o.get('offer_type')})")
        print(f"   Who it helps: {o.get('who_it_helps')}")
        print(f"   Deliverables: {o.get('deliverables')}")
        if o.get("time_to_build_days") is not None:
            print(f"   Time to build (days): {o.get('time_to_build_days')}")
        if o.get("difficulty"):
            print(f"   Difficulty: {o.get('difficulty')}")
        print()

    if args.out:
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nSaved full JSON report to {args.out}")


if __name__ == "__main__":
    main()
