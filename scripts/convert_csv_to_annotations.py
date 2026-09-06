#!/usr/bin/env python3
"""Convert Action Annotation CSV into JSONL conforming to Task 3 Schema."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml
from jsonschema import validate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert CSV action annotations to schema-validated JSONL")
    parser.add_argument("--csv", type=Path, default=Path("data/annotations/action_annotation_template.csv"), help="Input CSV file")
    parser.add_argument("--taxonomy", type=Path, default=Path("configs/action_recognition/taxonomy_v2.yaml"), help="Taxonomy YAML")
    parser.add_argument("--schema", type=Path, default=Path("schemas/action_annotation_v2.json"), help="Annotation JSON Schema")
    parser.add_argument("--output", type=Path, default=Path("data/action_recognition/annotations_v2.jsonl"), help="Output JSONL")
    parser.add_argument("--annotator-id", default="human_annotator_1", help="Annotator provenance (default: legacy value)")
    parser.add_argument("--allow-unknown", action="store_true", help="Only for legacy migration; do not fail unknown/wrong-category labels")
    args = parser.parse_args(argv)

    # Load taxonomy
    with args.taxonomy.open("r", encoding="utf-8") as f:
        tax = yaml.safe_load(f)

    valid_labels = set()
    labels_by_category: Dict[str, set[str]] = {}
    for cat_name, cat_info in tax.get("categories", {}).items():
        labels_by_category[cat_name] = set()
        for l in cat_info.get("labels", []):
            label_id = l["id"] if isinstance(l, dict) else l
            valid_labels.add(label_id)
            labels_by_category[cat_name].add(label_id)

    # Load JSON schema
    schema = json.loads(args.schema.read_text(encoding="utf-8"))

    # Read CSV
    if not args.csv.exists():
        print(f"Error: CSV file not found: {args.csv}")
        return 1

    records: List[Dict[str, Any]] = []
    validation_errors: List[str] = []
    source_hash = hashlib.sha256(args.csv.read_bytes()).hexdigest()
    with args.csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row_idx, row in enumerate(reader, start=1):
            v_id = row["video_id"].strip()
            track_id = int(row.get("track_id", 1))
            role = row.get("role", "lecturer").strip()
            start_s = float(row["start_seconds"])
            end_s = float(row["end_seconds"])
            category = row.get("category", "").strip()
            raw_action_str = row["action_label"].strip()
            conf = float(row.get("confidence", 1.0))
            notes = row.get("notes", "").strip()

            if end_s <= start_s:
                print(f"[Error Row {row_idx}] Invalid interval: start {start_s} >= end {end_s}")
                return 1

            # Support multiple actions separated by ';' or '+' or ','
            actions = sorted({a.strip() for a in raw_action_str.replace("+", ";").replace(",", ";").split(";") if a.strip()})
            if not actions:
                print(f"[Error Row {row_idx}] Empty action_label")
                return 1

            row_errors: List[str] = []
            if category not in labels_by_category:
                row_errors.append(f"unknown category: {category!r}")
            for act in actions:
                if act not in valid_labels:
                    row_errors.append(f"unknown action label: {act!r}")
                elif act not in labels_by_category.get(category, set()):
                    row_errors.append(f"action label {act!r} does not belong to category {category!r}")
            if row_errors:
                validation_errors.extend(f"Row {row_idx}: {message}" for message in row_errors)
                if not args.allow_unknown:
                    continue

            rec = {
                "annotation_id": f"ann_{v_id}_{row_idx:04d}",
                "video_id": v_id,
                "track_id": track_id,
                "role": role,
                "start_seconds": round(start_s, 3),
                "end_seconds": round(end_s, 3),
                "category": category,
                "actions": actions,
                "taxonomy_version": str(tax.get("taxonomy_version", "unknown")),
                "annotator_id": row.get("annotator_id", "").strip() or args.annotator_id,
                "annotator_confidence": round(conf, 2),
                "observability": row.get("observability", "unknown").strip() or "unknown",
                "annotation_status": row.get("annotation_status", "draft").strip() or "draft",
                "review_status": row.get("review_status", "unreviewed").strip() or "unreviewed",
                "revision": int(row.get("revision") or 0),
                "source_file_sha256": source_hash,
                "notes": notes,
            }

            validate(instance=rec, schema=schema)
            records.append(rec)

    if validation_errors and not args.allow_unknown:
        for error in validation_errors:
            print(f"[Error] {error}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print("=" * 60)
    print(f"Successfully converted {len(records)} action annotations!")
    print(f"Source: {args.csv}")
    print(f"Output: {args.output}")
    print(f"Validated against JSON Schema: PASSED")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
