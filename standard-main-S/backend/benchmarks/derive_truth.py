"""Create a ground-truth file from a connectivity-graph document.

Usage:
    python benchmarks/derive_truth.py "<fixtures>/connectivity_graph 18.json" \
        --image pid-images/pid18.png --out "<fixtures>/ground_truth/pid18.json"

The truth file IS a connectivity-graph document (so scoring compares like with
like) plus a `truth` header recording where it came from and whether a person
has verified it. Derived files start unverified: a benchmark is only as good as
its labels, so check the tags and connections by hand against the drawing and
then set `truth.verified_by`.
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path


def image_size(path: Path) -> tuple[int, int] | None:
    """(width, height) of a PNG from its header, without an imaging library."""
    try:
        with path.open("rb") as fh:
            head = fh.read(24)
    except OSError:
        return None
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", head[16:24])


def derive(source: Path, image: str, fixtures: Path | None = None) -> dict:
    doc = json.loads(source.read_text(encoding="utf-8"))
    size = image_size((fixtures or source.parent) / image)
    doc["truth"] = {
        "image": image,
        "image_width": size[0] if size else None,
        "image_height": size[1] if size else None,
        "derived_from": source.name,
        "verified_by": None,
        "note": ("Derived automatically; provenance of the source graph is unrecorded. "
                 "Verify tags and connections against the drawing before trusting scores."),
    }
    return doc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source", type=Path)
    ap.add_argument("--image", required=True, help="image path relative to the fixtures folder")
    ap.add_argument("--fixtures", type=Path, default=None,
                    help="folder --image is relative to (default: the source's folder)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    doc = derive(args.source, args.image, args.fixtures)
    args.out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
