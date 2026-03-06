# fMRI DICOM To BIDS Pipeline

This repository contains reusable scripts for converting raw fMRI DICOM data into BIDS. The code is intended to stay generic across studies; study-specific scanner naming rules, post-processing, and cluster job scripts should usually live in the consuming project, not here.

The main entry point is `dicom_to_bids.py`, which can run the full ZIP -> DICOM -> BIDS conversion in one step.

## What Lives Here

- `dicom_to_bids.py`: main converter
- `unzip_dicoms.py`: optional standalone unzip step
- `bids_mapping.json`: generic example mapping file
- `fmriprep_job_template.sh`: generic SLURM template for downstream `fMRIPrep`

## Setup

Create an environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows, activate the environment with:

```bash
.venv\Scripts\activate
```

## Conversion Workflow

The converter supports two common workflows:

1. a single-step ZIP-to-BIDS run
2. a two-step unzip-then-convert run

### Single-Step ZIP To BIDS

```bash
python dicom_to_bids.py --mapping_file /path/to/study_mapping.json run \
  --zip_dir /path/to/dicom_zips \
  --output_dir /path/to/bids_dataset \
  --subjects "all" \
  --zero_padding 3 \
  --misc_dir /path/to/misc_nifti \
  --workers 4
```

Important arguments:

- `--mapping_file`: path to the study-specific JSON mapping file
- `--zip_dir`: directory containing zipped DICOM archives
- `--output_dir`: root BIDS output directory
- `--subjects`: `"all"`, a comma-separated list, a range, or a combination such as `1,3-5,10`
- `--zero_padding`: number of digits in the BIDS subject label
- `--misc_dir`: optional destination for unmatched converted files
- `--workers`: number of parallel subject workers

### Two-Step Workflow

Unzip first:

```bash
python unzip_dicoms.py \
  --input_dir /path/to/dicom_zips \
  --output_dir /path/to/raw_dicom \
  --subjects "all" \
  --zero_padding 3
```

Then convert:

```bash
python dicom_to_bids.py --mapping_file /path/to/study_mapping.json run \
  --input_dir /path/to/raw_dicom \
  --output_dir /path/to/bids_dataset \
  --subjects "all" \
  --zero_padding 3 \
  --misc_dir /path/to/misc_nifti \
  --workers 4
```

## Converter Behavior

### `dcm2niix`

- The converter checks for `dcm2niix` on the system `PATH` first.
- If it is not available, the script downloads a local copy into `./dcm2niix/`.
- Converted files are generated with the filename format `%d_%s`, which preserves the series description plus series number. This is safer than protocol-name-only output when multiple acquisitions share similar protocol labels.

### Parallel Processing

- Subjects can be processed serially or in parallel with `--workers`.
- Failures for one subject do not stop the entire batch.

### Logging And Cleanup

- Failed `dcm2niix` conversions are written to timestamped logs in `./logs/`.
- Temporary unzipped raw DICOM directories and conversion staging folders are cleaned up at the end of the run, including on interrupt.

### Unmatched Files

- If `--misc_dir` is provided, unmatched files are saved there by subject.
- If `--misc_dir` is omitted, unmatched files are discarded.

## Study-Specific Mapping Files

`bids_mapping.json` in this repo is only a generic example. Real projects should usually supply their own mapping file with `--mapping_file`.

The mapping file is a JSON object keyed by BIDS modality, for example:

```json
{
  "anat": {
    "^MPRAGE_(\\d+)\\.": "T1w"
  },
  "fmap": {
    "^FieldMap_(\\d+)_e1\\.": "magnitude1",
    "^FieldMap_(\\d+)_e2\\.": "magnitude2",
    "^FieldMap_(\\d+)_e2_ph\\.": "phasediff"
  },
  "func": {
    "^MainTask_run(\\d+)_(\\d+)\\.": "task-main_run-{run}_bold"
  }
}
```

Rules are matched in order, so put the most specific regexes before broader fallback rules.

## `fMRIPrep` Template

`fmriprep_job_template.sh` is a generic DRAC/SLURM template that:

- stages one BIDS subject into `$SLURM_TMPDIR`
- copies `dataset_description.json`
- mounts a FreeSurfer license into the container
- runs `fMRIPrep` with Apptainer
- copies outputs back to a shared project directory

Copy it into your project and customize the account, email, paths, subject formatting, and `fMRIPrep` options there.

## Recommended Project Split

For a study-specific analysis repo, the clean split is usually:

- keep generic conversion code in `fmri_pipeline`
- keep scanner-specific mapping files in the study repo
- keep study-specific post-processing scripts in the study repo
- keep cluster job scripts in the study repo