"""Link one BIDS fieldmap set to functional runs using BIDS B0 metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, data: dict[str, object]) -> None:
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
        file.write("\n")


def update_value(path: Path, key: str, value: str) -> bool:
    data = load_json(path)
    if data.get(key) == value:
        return False
    data[key] = value
    write_json(path, data)
    return True


def add_fieldmap_metadata(
    bids_dir: str,
    field_id: str = "auto_fieldmap",
    exclude_fieldmap_name: str = "",
    dry_run: bool = False,
) -> dict[str, object]:
    """Link every subject's selected fieldmaps to all of their functional runs.

    This helper is intended for datasets with one fieldmap acquisition (or one
    fieldmap set) per subject that applies to every functional run. Datasets
    with multiple fieldmaps covering different runs should assign distinct
    identifiers with a study-specific mapping instead.
    """

    bids_root = Path(bids_dir).resolve()
    if not bids_root.is_dir():
        raise FileNotFoundError(f"BIDS directory not found: {bids_root}")

    rows: list[dict[str, object]] = []
    total_updates = 0
    incomplete_subjects: list[str] = []

    for subject_dir in sorted(bids_root.glob("sub-*")):
        if not subject_dir.is_dir():
            continue

        func_jsons = sorted((subject_dir / "func").glob("*_bold.json"))
        fmap_jsons = sorted((subject_dir / "fmap").glob("*.json"))
        if exclude_fieldmap_name:
            fmap_jsons = [
                path for path in fmap_jsons if exclude_fieldmap_name not in path.name
            ]

        updates = 0
        if not dry_run:
            for path in fmap_jsons:
                updates += update_value(path, "B0FieldIdentifier", field_id)
            for path in func_jsons:
                updates += update_value(path, "B0FieldSource", field_id)

        complete = bool(func_jsons and fmap_jsons)
        if complete and not dry_run:
            complete = all(
                load_json(path).get("B0FieldSource") == field_id
                for path in func_jsons
            ) and all(
                load_json(path).get("B0FieldIdentifier") == field_id
                for path in fmap_jsons
            )
        if not complete:
            incomplete_subjects.append(subject_dir.name)

        total_updates += updates
        rows.append(
            {
                "subject_id": subject_dir.name,
                "functional_jsons": len(func_jsons),
                "fieldmap_jsons": len(fmap_jsons),
                "updated_jsons": updates,
                "complete": complete,
            }
        )

    summary: dict[str, object] = {
        "bids_dir": str(bids_root),
        "field_id": field_id,
        "dry_run": dry_run,
        "subjects": len(rows),
        "updated_jsons": total_updates,
        "incomplete_subjects": incomplete_subjects,
        "rows": rows,
    }
    print(json.dumps(summary, indent=2))
    if incomplete_subjects:
        raise RuntimeError(
            "Missing functional or fieldmap JSON files for: "
            + ", ".join(incomplete_subjects)
        )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Link one fieldmap set per subject to all functional runs using "
            "B0FieldIdentifier/B0FieldSource."
        )
    )
    parser.add_argument("--bids-dir", required=True)
    parser.add_argument("--field-id", default="auto_fieldmap")
    parser.add_argument(
        "--exclude-fieldmap-name",
        default="",
        help="Ignore fieldmap JSON files whose filename contains this text.",
    )
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()
    add_fieldmap_metadata(
        bids_dir=arguments.bids_dir,
        field_id=arguments.field_id,
        exclude_fieldmap_name=arguments.exclude_fieldmap_name,
        dry_run=arguments.dry_run,
    )
