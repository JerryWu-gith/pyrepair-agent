"""Prepare pinned source/reference data, or verify it offline. Never run task code or models."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from benchmarks.evaluation.catalog_references import prepare_references, verify_references
from benchmarks.evaluation.catalog_source_cache import metadata_fetcher
from benchmarks.evaluation.source_catalog import load_catalog


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog", type=Path, default=ROOT / "benchmarks/opensource_catalog30.json"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    if args.verify_only and (args.resume or args.metadata is not None):
        parser.error("verify-only cannot select preparation or metadata transport")
    try:
        catalog = load_catalog(args.catalog)
        if args.verify_only:
            result = verify_references(catalog, args.output)
        else:
            options = {
                "resume": args.resume,
                "progress": lambda case: print(
                    "Reference prepared: " + case, file=sys.stderr, flush=True
                ),
            }
            if args.metadata is not None:
                options["fetch"] = metadata_fetcher(args.metadata)
            result = prepare_references(catalog, args.output, **options)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Reference preparation rejected: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
