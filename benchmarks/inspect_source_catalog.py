"""Inspect pinned upstream source metadata only; no preparation, execution or model calls."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from benchmarks.evaluation.source_catalog import CatalogError, load_catalog, summarize_catalog


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog", type=Path, default=ROOT / "benchmarks/opensource_catalog30.json"
    )
    args = parser.parse_args(argv)
    try:
        result = summarize_catalog(load_catalog(args.catalog))
    except (CatalogError, OSError, UnicodeError) as exc:
        print(f"Source catalog rejected: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
