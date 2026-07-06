#!/usr/bin/env python
"""BIDS-driven FSL FEAT preprocessing helpers.

This module intentionally stays small and file-oriented:

* discover BIDS functional runs and matching T1w images
* generate one FEAT FSF file per run
* summarize FEAT registration outputs
* create lightweight APNG registration QC
* warp MNI ROI masks back into native FEAT/EPI space

The heavy work is still done by FSL commands inside SLURM jobs.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


NIFTI_SUFFIXES = (".nii.gz", ".nii")


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _nifti_json_path(nifti_path: Path) -> Path:
    name = nifti_path.name
    if name.endswith(".nii.gz"):
        return nifti_path.with_name(name[:-7] + ".json")
    if name.endswith(".nii"):
        return nifti_path.with_suffix(".json")
    return nifti_path.with_suffix(".json")


def _strip_nii_suffix(path: Path) -> str:
    name = str(path)
    for suffix in NIFTI_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _entities_from_bids_name(path: Path) -> dict[str, str]:
    entities: dict[str, str] = {}
    for part in path.name.split("_"):
        if "-" not in part:
            continue
        key, value = part.split("-", 1)
        value = value.replace(".nii.gz", "").replace(".nii", "").replace(".json", "")
        entities[key] = value
    return entities


def _safe_label(*parts: str | None) -> str:
    return "_".join(p for p in parts if p)


def _require_program(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Required executable not found on PATH: {name}")


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print("RUN:", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def _nvols(path: Path) -> int | None:
    try:
        import nibabel as nib

        shape = nib.load(str(path)).shape
        return int(shape[3]) if len(shape) > 3 else 1
    except Exception:
        return None


def _shape(path: Path) -> str:
    try:
        import nibabel as nib

        return "x".join(str(x) for x in nib.load(str(path)).shape)
    except Exception:
        return ""


def _prefer_t1w(paths: list[Path], subject: str) -> Path:
    def score(path: Path) -> tuple[int, int, str]:
        name = path.name
        exact = 0 if name == f"{subject}_T1w.nii.gz" else 1
        derived = 1 if any(x in name for x in ("desc-", "space-", "brain")) else 0
        return (exact, derived, len(name), name)

    if not paths:
        raise ValueError(f"No T1w image found for {subject}")
    return sorted(paths, key=score)[0]


def discover_runs(
    bids_root: str,
    output_csv: str,
    *,
    output_root: str = "",
    include_tasks: str = "",
    exclude_tasks: str = "soundcheck",
    subjects: str = "",
    remote_bids_root: str = "",
    remote_output_root: str = "",
) -> None:
    """Discover BIDS BOLD runs and matching T1w files."""

    bids = Path(bids_root).resolve()
    include = {x.strip() for x in include_tasks.split(",") if x.strip()}
    exclude = {x.strip() for x in exclude_tasks.split(",") if x.strip()}
    subject_filter = {x.strip().replace("sub-", "") for x in subjects.split(",") if x.strip()}

    rows: list[dict[str, Any]] = []
    for sub_dir in sorted(bids.glob("sub-*")):
        if not sub_dir.is_dir():
            continue
        subject = sub_dir.name
        subject_id = subject.replace("sub-", "")
        if subject_filter and subject_id not in subject_filter and subject not in subject_filter:
            continue
        t1w_paths = sorted((sub_dir / "anat").glob("*_T1w.nii.gz"))
        try:
            t1w = _prefer_t1w(t1w_paths, subject)
        except ValueError as exc:
            print(f"WARNING: {exc}", file=sys.stderr)
            continue
        for bold in sorted((sub_dir / "func").glob("*_bold.nii.gz")):
            entities = _entities_from_bids_name(bold)
            task = entities.get("task", "")
            if include and task not in include:
                continue
            if task in exclude:
                continue
            run = entities.get("run", "")
            session = entities.get("ses", "")
            bold_json = _nifti_json_path(bold)
            metadata = _load_json(bold_json) if bold_json.exists() else {}
            tr = metadata.get("RepetitionTime", "")
            npts = _nvols(bold)
            run_label = _safe_label(subject, f"task-{task}", f"run-{run}" if run else "")
            feat_dir = Path(output_root) / subject / "func" / f"{run_label}.feat" if output_root else Path("")
            row = {
                "row_id": len(rows) + 1,
                "subject": subject,
                "subject_id": subject_id,
                "session": session,
                "task": task,
                "run": run,
                "run_label": run_label,
                "bold_path": str(bold),
                "bold_json": str(bold_json),
                "t1w_path": str(t1w),
                "tr": tr,
                "npts": npts if npts is not None else "",
                "output_feat_dir": str(feat_dir) if output_root else "",
            }
            rows.append(row)

    if remote_bids_root:
        rows = [_replace_prefix(row, str(bids), remote_bids_root, ["bold_path", "bold_json", "t1w_path"]) for row in rows]
    if remote_output_root:
        for row in rows:
            row["output_feat_dir"] = "/".join(
                [
                    remote_output_root.rstrip("/"),
                    row["subject"],
                    "func",
                    f"{row['run_label']}.feat",
                ]
            )

    fieldnames = [
        "row_id",
        "subject",
        "subject_id",
        "session",
        "task",
        "run",
        "run_label",
        "bold_path",
        "bold_json",
        "t1w_path",
        "tr",
        "npts",
        "output_feat_dir",
    ]
    _write_csv(Path(output_csv), rows, fieldnames)
    _write_json(
        Path(output_csv).with_suffix(".summary.json"),
        {
            "bids_root": str(bids),
            "remote_bids_root": remote_bids_root,
            "remote_output_root": remote_output_root,
            "n_runs": len(rows),
            "tasks": sorted({row["task"] for row in rows}),
            "subjects": sorted({row["subject"] for row in rows}),
        },
    )


def _replace_prefix(row: dict[str, Any], old: str, new: str, keys: Iterable[str]) -> dict[str, Any]:
    out = dict(row)
    old_norm = old.replace("\\", "/").rstrip("/")
    new_norm = new.rstrip("/")
    for key in keys:
        value = str(out.get(key, ""))
        value_norm = value.replace("\\", "/")
        if value_norm.startswith(old_norm):
            out[key] = new_norm + value_norm[len(old_norm) :]
    return out


def _default_config() -> dict[str, Any]:
    return {
        "discard_initial_volumes": 5,
        "highpass_seconds": 100,
        "smooth_fwhm_mm": 5,
        "bet_func": True,
        "slice_timing": 0,
        "motion_correction": True,
        "func_to_t1_registration": True,
        "func_to_t1_search": 90,
        "func_to_t1_dof": "BBR",
        "standard_registration": True,
        "standard_search": 90,
        "standard_dof": 12,
        "standard_nonlinear": False,
        "standard_image": "${FSLDIR}/data/standard/MNI152_T1_2mm_brain",
        "fieldmap_unwarp": False,
        "unwarp_dir": "y-",
        "overwrite": False,
    }


def _read_config(path: str | None) -> dict[str, Any]:
    config = _default_config()
    if path:
        user = _load_json(Path(path))
        config.update(user)
    return config


def _expand_fsl_path(path: str) -> str:
    fsldir = os.environ.get("FSLDIR", "")
    return path.replace("${FSLDIR}", fsldir).rstrip("/")


def _set_line(lines: list[str], key: str, value: str) -> None:
    pattern = re.compile(rf"^set {re.escape(key)}(?:\s|$)")
    replacement = f"set {key} {value}\n"
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = replacement
            return
    lines.append(replacement)


def _quote(value: str | Path) -> str:
    return '"' + str(value).replace("\\", "/") + '"'


def _template_lines() -> list[str]:
    return DEFAULT_FSF_TEMPLATE.strip().splitlines(keepends=True)


def write_fsf(
    manifest_csv: str,
    config_json: str,
    fsf_dir: str,
    *,
    row_id: int | None = None,
    fsf_template: str = "",
) -> None:
    """Write FEAT FSF files for one manifest row or all rows."""

    config = _read_config(config_json)
    rows = _read_csv(Path(manifest_csv))
    if row_id is not None:
        rows = [row for row in rows if int(row["row_id"]) == row_id]
        if not rows:
            raise ValueError(f"row_id not found in manifest: {row_id}")
    template_value = fsf_template or str(config.get("fsf_template", "") or "")
    template_path = Path(template_value) if template_value else None
    base_lines = template_path.read_text(encoding="utf-8").splitlines(keepends=True) if template_path else _template_lines()
    out_dir = Path(fsf_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        lines = list(base_lines)
        output_feat = Path(row["output_feat_dir"])
        tr = row.get("tr") or config.get("tr") or "1.0"
        npts = row.get("npts") or _nvols(Path(row["bold_path"])) or 0
        standard = _expand_fsl_path(str(config["standard_image"]))
        _set_line(lines, "fmri(outputdir)", _quote(output_feat))
        _set_line(lines, "fmri(tr)", str(tr))
        _set_line(lines, "fmri(npts)", str(npts))
        _set_line(lines, "fmri(ndelete)", str(config["discard_initial_volumes"]))
        _set_line(lines, "fmri(mc)", "1" if config["motion_correction"] else "0")
        _set_line(lines, "fmri(st)", str(config["slice_timing"]))
        _set_line(lines, "fmri(bet_yn)", "1" if config["bet_func"] else "0")
        _set_line(lines, "fmri(smooth)", str(config["smooth_fwhm_mm"]))
        _set_line(lines, "fmri(temphp_yn)", "1" if config["highpass_seconds"] else "0")
        _set_line(lines, "fmri(paradigm_hp)", str(config["highpass_seconds"] or 0))
        _set_line(lines, "fmri(regunwarp_yn)", "1" if config["fieldmap_unwarp"] else "0")
        _set_line(lines, "fmri(unwarp_dir)", str(config["unwarp_dir"]))
        _set_line(lines, "fmri(reghighres_yn)", "1" if config["func_to_t1_registration"] else "0")
        _set_line(lines, "fmri(reghighres_search)", str(config["func_to_t1_search"]))
        _set_line(lines, "fmri(reghighres_dof)", str(config["func_to_t1_dof"]))
        _set_line(lines, "fmri(regstandard_yn)", "1" if config["standard_registration"] else "0")
        _set_line(lines, "fmri(regstandard)", _quote(standard))
        _set_line(lines, "fmri(regstandard_search)", str(config["standard_search"]))
        _set_line(lines, "fmri(regstandard_dof)", str(config["standard_dof"]))
        _set_line(lines, "fmri(regstandard_nonlinear_yn)", "1" if config["standard_nonlinear"] else "0")
        _set_line(lines, "fmri(overwrite_yn)", "1" if config["overwrite"] else "0")
        _set_line(lines, "feat_files(1)", _quote(_strip_nii_suffix(Path(row["bold_path"]))))
        _set_line(lines, "highres_files(1)", _quote(_strip_nii_suffix(Path(row["t1w_path"]))))
        fsf_path = out_dir / f"{int(row['row_id']):05d}_{row['run_label']}.fsf"
        fsf_path.write_text("".join(lines), encoding="utf-8")
        print(fsf_path)


def run_feat_for_row(manifest_csv: str, config_json: str, row_id: int, work_dir: str) -> None:
    """Generate an FSF for one manifest row and run FEAT."""

    _require_program("feat")
    work = Path(work_dir).resolve()
    fsf_dir = work / "fsf"
    write_fsf(manifest_csv, config_json, str(fsf_dir), row_id=row_id)
    fsf_paths = sorted(fsf_dir.glob(f"{row_id:05d}_*.fsf"))
    if len(fsf_paths) != 1:
        raise RuntimeError(f"Expected one FSF for row {row_id}, found {len(fsf_paths)}")
    _run(["feat", str(fsf_paths[0])])


def summarize(manifest_csv: str, output_csv: str) -> None:
    """Summarize FEAT output and registration-product availability."""

    rows = []
    for row in _read_csv(Path(manifest_csv)):
        feat_dir = Path(row["output_feat_dir"])
        reg = feat_dir / "reg"
        out = dict(row)
        out.update(
            {
                "feat_exists": feat_dir.exists(),
                "report_exists": (feat_dir / "report.html").exists(),
                "report_reg_exists": (feat_dir / "report_reg.html").exists(),
                "example_func_exists": (feat_dir / "example_func.nii.gz").exists(),
                "filtered_func_exists": (feat_dir / "filtered_func_data.nii.gz").exists(),
                "example_func_shape": _shape(feat_dir / "example_func.nii.gz") if (feat_dir / "example_func.nii.gz").exists() else "",
                "example_func2highres_mat": (reg / "example_func2highres.mat").exists(),
                "highres2example_func_mat": (reg / "highres2example_func.mat").exists(),
                "highres2standard_mat": (reg / "highres2standard.mat").exists(),
                "standard2highres_mat": (reg / "standard2highres.mat").exists(),
                "example_func2standard_mat": (reg / "example_func2standard.mat").exists(),
                "example_func2standard_warp": (reg / "example_func2standard_warp.nii.gz").exists(),
            }
        )
        rows.append(out)
    fieldnames = list(rows[0].keys()) if rows else []
    _write_csv(Path(output_csv), rows, fieldnames)
    _write_json(
        Path(output_csv).with_suffix(".summary.json"),
        {
            "n_rows": len(rows),
            "n_feat_exists": sum(bool(row.get("feat_exists")) for row in rows),
            "n_complete_linear_reg": sum(
                bool(row.get("example_func2highres_mat"))
                and bool(row.get("highres2standard_mat"))
                and bool(row.get("example_func2standard_mat"))
                for row in rows
            ),
        },
    )


def _load_3d(path: Path):
    import nibabel as nib
    import numpy as np

    img = nib.load(str(path))
    data = img.get_fdata(dtype=np.float32)
    if data.ndim == 4:
        data = data[..., 0]
    return data


def _normalize_slice(arr):
    import numpy as np

    finite = np.isfinite(arr)
    if not finite.any():
        return np.zeros(arr.shape, dtype=np.uint8)
    lo, hi = np.percentile(arr[finite], [2, 98])
    if hi <= lo:
        hi = lo + 1
    out = np.clip((arr - lo) / (hi - lo), 0, 1)
    return (out * 255).astype(np.uint8)


def _slice_grid(path: Path, title: str, *, size: int = 168):
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    data = _load_3d(path)
    axes = [2, 1, 0]
    rows = []
    for axis in axes:
        n = data.shape[axis]
        idxs = [max(0, min(n - 1, round(x))) for x in np.linspace(n * 0.18, n * 0.82, 7)]
        tiles = []
        for idx in idxs:
            sl = np.take(data, idx, axis=axis)
            sl = np.rot90(sl)
            im = Image.fromarray(_normalize_slice(sl)).convert("RGB")
            im.thumbnail((size, size), Image.Resampling.BILINEAR)
            canvas = Image.new("RGB", (size, size), (0, 0, 0))
            canvas.paste(im, ((size - im.width) // 2, (size - im.height) // 2))
            draw = ImageDraw.Draw(canvas)
            draw.rectangle((2, size - 23, 58, size - 2), fill=(0, 0, 0))
            draw.text((6, size - 20), f"{idx}", fill=(255, 255, 255))
            tiles.append(canvas)
        row = Image.new("RGB", (size * 7, size), (0, 0, 0))
        for i, tile in enumerate(tiles):
            row.paste(tile, (i * size, 0))
        rows.append(row)
    header = Image.new("RGB", (size * 7, 36), (0, 0, 0))
    draw = ImageDraw.Draw(header)
    draw.text((8, 8), title, fill=(255, 255, 255))
    out = Image.new("RGB", (size * 7, size * 3 + 36), (0, 0, 0))
    out.paste(header, (0, 0))
    for i, row in enumerate(rows):
        out.paste(row, (0, 36 + i * size))
    return out


def make_qc(manifest_csv: str, output_root: str, *, row_id: int | None = None, duration_ms: int = 900) -> None:
    """Create APNG flip QC for completed FEAT runs."""

    from PIL import Image

    rows = _read_csv(Path(manifest_csv))
    if row_id is not None:
        rows = [row for row in rows if int(row["row_id"]) == row_id]
    flat = Path(output_root) / "flat_review"
    nested = Path(output_root) / "by_run"
    flat.mkdir(parents=True, exist_ok=True)
    nested.mkdir(parents=True, exist_ok=True)
    for row in rows:
        feat = Path(row["output_feat_dir"])
        if not feat.exists():
            continue
        run_label = row["run_label"]
        run_dir = nested / row["subject"] / run_label
        run_dir.mkdir(parents=True, exist_ok=True)
        pairs = [
            ("func_vs_t1w", feat / "example_func.nii.gz", Path(row["t1w_path"])),
            ("func_mni", feat / "reg" / "example_func2standard.nii.gz", Path(os.environ.get("FSLDIR", "")) / "data/standard/MNI152_T1_2mm_brain.nii.gz"),
        ]
        for label, first_path, second_path in pairs:
            if not first_path.exists() or not second_path.exists():
                continue
            frames = [
                _slice_grid(first_path, f"{run_label}: {label} frame 1"),
                _slice_grid(second_path, f"{run_label}: {label} frame 2"),
            ]
            out_name = f"{int(row['row_id']):05d}_{run_label}_{label}.png"
            for out_path in (flat / out_name, run_dir / out_name):
                frames[0].save(
                    out_path,
                    format="PNG",
                    save_all=True,
                    append_images=[frames[1]],
                    duration=duration_ms,
                    loop=0,
                    disposal=2,
                )
                print(out_path)


def build_roi_masks(
    manifest_csv: str,
    roi_config_json: str,
    output_root: str,
    *,
    row_id: int | None = None,
) -> None:
    """Warp MNI-space masks to native FEAT example_func space."""

    _require_program("flirt")
    _require_program("convert_xfm")
    roi_config = _load_json(Path(roi_config_json))
    rois = roi_config.get("rois", {})
    if not rois:
        raise ValueError("ROI config must contain a non-empty 'rois' object")
    rows = _read_csv(Path(manifest_csv))
    if row_id is not None:
        rows = [row for row in rows if int(row["row_id"]) == row_id]
    for row in rows:
        feat = Path(row["output_feat_dir"])
        reg = feat / "reg"
        example = feat / "example_func.nii.gz"
        if not example.exists():
            continue
        standard2example = reg / "standard2example_func.mat"
        if not standard2example.exists():
            if not (reg / "standard2highres.mat").exists() or not (reg / "highres2example_func.mat").exists():
                print(f"WARNING: missing inverse transform for {row['run_label']}", file=sys.stderr)
                continue
            _run(
                [
                    "convert_xfm",
                    "-omat",
                    str(standard2example),
                    "-concat",
                    str(reg / "highres2example_func.mat"),
                    str(reg / "standard2highres.mat"),
                ]
            )
        out_dir = Path(output_root) / row["subject"] / "func" / row["run_label"]
        out_dir.mkdir(parents=True, exist_ok=True)
        for roi_name, roi_path in rois.items():
            out_path = out_dir / f"{row['run_label']}_space-native_desc-{roi_name}_mask.nii.gz"
            _run(
                [
                    "flirt",
                    "-in",
                    str(Path(roi_path)),
                    "-ref",
                    str(example),
                    "-applyxfm",
                    "-init",
                    str(standard2example),
                    "-interp",
                    "nearestneighbour",
                    "-out",
                    str(out_path),
                ]
            )
            print(out_path)


DEFAULT_FSF_TEMPLATE = r'''
# FEAT version number
set fmri(version) 6.00
set fmri(inmelodic) 0
set fmri(level) 1
set fmri(analysis) 1
set fmri(relative_yn) 0
set fmri(help_yn) 1
set fmri(featwatcher_yn) 1
set fmri(sscleanup_yn) 0
set fmri(outputdir) ""
set fmri(tr) 1.0
set fmri(npts) 0
set fmri(ndelete) 0
set fmri(tagfirst) 1
set fmri(multiple) 1
set fmri(inputtype) 2
set fmri(filtering_yn) 1
set fmri(brain_thresh) 10
set fmri(critical_z) 5.3
set fmri(noise) 0.66
set fmri(noisear) 0.34
set fmri(mc) 1
set fmri(sh_yn) 0
set fmri(regunwarp_yn) 0
set fmri(gdc) ""
set fmri(dwell) 0.0
set fmri(te) 0.0
set fmri(signallossthresh) 10
set fmri(unwarp_dir) y-
set fmri(st) 0
set fmri(st_file) ""
set fmri(bet_yn) 1
set fmri(smooth) 5
set fmri(norm_yn) 0
set fmri(perfsub_yn) 0
set fmri(temphp_yn) 1
set fmri(templp_yn) 0
set fmri(melodic_yn) 0
set fmri(stats_yn) 0
set fmri(prewhiten_yn) 1
set fmri(motionevs) 0
set fmri(motionevsbeta) ""
set fmri(scriptevsbeta) ""
set fmri(robust_yn) 0
set fmri(mixed_yn) 2
set fmri(randomisePermutations) 5000
set fmri(evs_orig) 1
set fmri(evs_real) 2
set fmri(evs_vox) 0
set fmri(ncon_orig) 1
set fmri(ncon_real) 1
set fmri(nftests_orig) 0
set fmri(nftests_real) 0
set fmri(constcol) 0
set fmri(poststats_yn) 0
set fmri(threshmask) ""
set fmri(thresh) 3
set fmri(prob_thresh) 0.05
set fmri(z_thresh) 3.1
set fmri(zdisplay) 0
set fmri(zmin) 2
set fmri(zmax) 8
set fmri(rendertype) 1
set fmri(bgimage) 1
set fmri(tsplot_yn) 1
set fmri(reginitial_highres_yn) 0
set fmri(reginitial_highres_search) 90
set fmri(reginitial_highres_dof) 3
set fmri(reghighres_yn) 1
set fmri(reghighres_search) 90
set fmri(reghighres_dof) BBR
set fmri(regstandard_yn) 1
set fmri(alternateReference_yn) 0
set fmri(regstandard) "${FSLDIR}/data/standard/MNI152_T1_2mm_brain"
set fmri(regstandard_search) 90
set fmri(regstandard_dof) 12
set fmri(regstandard_nonlinear_yn) 0
set fmri(regstandard_nonlinear_warpres) 10
set fmri(paradigm_hp) 100
set fmri(totalVoxels) 0
set fmri(fnirt_config) "T1_2_MNI152_2mm"
set fmri(ncopeinputs) 0
set feat_files(1) ""
set fmri(confoundevs) 0
set highres_files(1) ""
set fmri(evtitle1) ""
set fmri(shape1) 10
set fmri(convolve1) 0
set fmri(convolve_phase1) 0
set fmri(tempfilt_yn1) 1
set fmri(deriv_yn1) 0
set fmri(skip1) 0
set fmri(off1) 0
set fmri(on1) 0
set fmri(phase1) 0
set fmri(stop1) -1
set fmri(gammasigma1) 3
set fmri(gammadelay1) 6
set fmri(ortho1.0) 0
set fmri(ortho1.1) 0
set fmri(con_mode_old) orig
set fmri(con_mode) orig
set fmri(conpic_real.1) 1
set fmri(conname_real.1) ""
set fmri(con_real1.1) 1
set fmri(con_real1.2) 0
set fmri(conpic_orig.1) 1
set fmri(conname_orig.1) ""
set fmri(con_orig1.1) 1
set fmri(conmask_zerothresh_yn) 0
set fmri(conmask1_1) 0
set fmri(alternative_mask) ""
set fmri(init_initial_highres) ""
set fmri(init_highres) ""
set fmri(init_standard) ""
set fmri(overwrite_yn) 0
'''


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("discover-runs")
    p.add_argument("--bids-root", required=True)
    p.add_argument("--output-csv", required=True)
    p.add_argument("--output-root", default="")
    p.add_argument("--include-tasks", default="")
    p.add_argument("--exclude-tasks", default="soundcheck")
    p.add_argument("--subjects", default="")
    p.add_argument("--remote-bids-root", default="")
    p.add_argument("--remote-output-root", default="")

    p = sub.add_parser("write-fsf")
    p.add_argument("--manifest-csv", required=True)
    p.add_argument("--config-json", required=True)
    p.add_argument("--fsf-dir", required=True)
    p.add_argument("--row-id", type=int)
    p.add_argument("--fsf-template", default="")

    p = sub.add_parser("run-feat-row")
    p.add_argument("--manifest-csv", required=True)
    p.add_argument("--config-json", required=True)
    p.add_argument("--row-id", type=int, required=True)
    p.add_argument("--work-dir", required=True)

    p = sub.add_parser("summarize")
    p.add_argument("--manifest-csv", required=True)
    p.add_argument("--output-csv", required=True)

    p = sub.add_parser("make-qc")
    p.add_argument("--manifest-csv", required=True)
    p.add_argument("--output-root", required=True)
    p.add_argument("--row-id", type=int)
    p.add_argument("--duration-ms", type=int, default=900)

    p = sub.add_parser("build-roi-masks")
    p.add_argument("--manifest-csv", required=True)
    p.add_argument("--roi-config-json", required=True)
    p.add_argument("--output-root", required=True)
    p.add_argument("--row-id", type=int)

    args = parser.parse_args(argv)
    kwargs = vars(args)
    command = kwargs.pop("command")
    if command == "discover-runs":
        discover_runs(**kwargs)
    elif command == "write-fsf":
        write_fsf(**kwargs)
    elif command == "run-feat-row":
        run_feat_for_row(**kwargs)
    elif command == "summarize":
        summarize(**kwargs)
    elif command == "make-qc":
        make_qc(**kwargs)
    elif command == "build-roi-masks":
        build_roi_masks(**kwargs)
    else:
        raise AssertionError(command)


if __name__ == "__main__":
    main()
