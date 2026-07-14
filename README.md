# fMRI DICOM to BIDS preprocessing pipeline

This repository provides small command-line utilities for converting raw fMRI DICOM archives into a BIDS-like dataset and a SLURM template for running fMRIPrep on Digital Alliance / DRAC systems.

The main conversion script is `dicom_to_bids.py`. It can convert zipped DICOM exports directly to BIDS, or it can work from DICOM folders that were unzipped first. Study-specific scanner naming rules are controlled by a JSON mapping file.

## Quick Start

### 1. Install the Python requirements

Recommended Python version: `3.10` or `3.11`.

On DRAC, first check which Python modules are available:

```bash
module spider python
```

Then load an available Python `3.10` or `3.11` module. The exact module name depends on the cluster software stack; examples may look like:

```bash
module load python/3.11
```

or:

```bash
module load python/3.10
```

After loading Python, confirm the version:

```bash
python --version
```

Then create the environment:

```bash
git clone https://github.com/efirdc/fmri_pipeline.git
cd fmri_pipeline

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows, activate the environment with:

```powershell
.\.venv\Scripts\activate
```

### 2. Create a study mapping file

Start from the example mapping:

```bash
cp bids_mapping.json my_study_mapping.json
```

Edit `my_study_mapping.json` so the scanner sequence names from your study map to the desired BIDS filenames. See [Mapping Files](#mapping-files) below.

### 3. Convert one subject first

Run a single-subject conversion before processing the full dataset.

```bash
python dicom_to_bids.py --mapping_file my_study_mapping.json run \
  --zip_dir /path/to/dicom_zips \
  --output_dir /path/to/bids_dataset \
  --work_dir /scratch/$USER/dicom_to_bids \
  --dataset_name MyStudy \
  --subjects 1 \
  --zero_padding 3 \
  --misc_dir /path/to/misc_nifti \
  --workers 1
```

Expected output structure:

```text
bids_dataset/
  sub-001/
    anat/
    func/
    fmap/      # if field maps were mapped
```

Review the output and the `misc_dir` contents before running all subjects.

### 4. Convert all subjects

```bash
python dicom_to_bids.py --mapping_file my_study_mapping.json run \
  --zip_dir /path/to/dicom_zips \
  --output_dir /path/to/bids_dataset \
  --work_dir /scratch/$USER/dicom_to_bids \
  --dataset_name MyStudy \
  --subjects all \
  --zero_padding 3 \
  --misc_dir /path/to/misc_nifti \
  --workers 4
```

`--work_dir` holds extracted DICOMs and intermediate dcm2niix outputs and is
deleted after the command finishes or fails. On a cluster, point it to
`$SLURM_TMPDIR` inside a compute job when possible, or to a study-specific
directory under `/scratch/$USER`. Do not place large temporary extraction trees
in quota-limited project storage.

The converter creates the required `dataset_description.json` in the BIDS root.
Use `--dataset_name` to give the dataset a meaningful name. If the file already
exists, the converter validates and preserves it rather than overwriting it.

### 5. Link fieldmaps if they should be used

If the study has fieldmaps and one fieldmap set applies to all functional runs for a subject, add BIDS fieldmap linkage metadata before running fMRIPrep:

```bash
python add_fieldmap_metadata.py \
  --bids-dir /path/to/bids_dataset \
  --field-id auto_fieldmap \
  --dry-run
```

If the dry run looks correct, run it again without `--dry-run`:

```bash
python add_fieldmap_metadata.py \
  --bids-dir /path/to/bids_dataset \
  --field-id auto_fieldmap
```

See [Fieldmap Linkage](#fieldmap-linkage) for details.

### 6. Run fMRIPrep

Copy `fmriprep_job_template.sh` into the project directory where the BIDS dataset lives, edit the paths and SLURM settings, then submit:

```bash
sbatch fmriprep_job_template.sh
```

See [Obtaining fMRIPrep and FreeSurfer files on DRAC](#obtaining-fmriprep-and-freesurfer-files-on-drac) before running the template for the first time.

For a new dataset, run a small test first before submitting a large subject array.

## Requirements

### DICOM to BIDS conversion

- Python `3.10` or `3.11` recommended
- Python packages from `requirements.txt`
- `dcm2niix` for DICOM to NIfTI conversion
- Enough disk space for raw DICOMs, temporary unzipped DICOMs, BIDS output, and optional miscellaneous converted files

The converter checks for `dcm2niix` on the system `PATH`. If it is not found, the script attempts to download a local copy into `./dcm2niix/`.

On DRAC, use the module system to select Python before creating the virtual environment:

```bash
module spider python
module load python/3.11
python --version
python -m venv .venv
```

If `python/3.11` is not available on the cluster, load an available `3.10` or `3.11` module shown by `module spider python`.

Record the `dcm2niix` version used for a project:

```bash
dcm2niix -v
```

### fMRIPrep on DRAC / Digital Alliance

The included `fmriprep_job_template.sh` assumes:

- SLURM jobs are submitted with `sbatch`.
- The account is a Digital Alliance allocation such as `def-ACCOUNT`.
- Apptainer is available through the module system:

```bash
module load apptainer
```

- fMRIPrep is run from an Apptainer/Singularity container image.
- A FreeSurfer license file is available.
- The BIDS root contains `dataset_description.json`.

Use the latest fMRIPrep image for new projects unless there is a project-specific reason to use an older version. This repository's template has been tested with:

```text
fMRIPrep 24.1.1
```

Record the exact fMRIPrep version used with the project outputs because preprocessing results can change across versions.

## Obtaining fMRIPrep and FreeSurfer files on DRAC

Create a project folder for containers and licenses. For example:

```bash
cd /path/to/your/project
mkdir -p containers licenses
```

### fMRIPrep container

Load Apptainer:

```bash
module load apptainer
```

Pull the latest fMRIPrep image from Docker Hub:

```bash
apptainer pull containers/fmriprep_latest.sif docker://nipreps/fmriprep:latest
```

For a versioned image, replace `latest` with a specific fMRIPrep version and use a versioned filename:

```bash
apptainer pull containers/fmriprep_24.1.1.sif docker://nipreps/fmriprep:24.1.1
```

Check the version:

```bash
apptainer exec containers/fmriprep_latest.sif fmriprep --version
```

Then set `fmriprep_sif` in `fmriprep_job_template.sh` to the image path. For example:

```text
fmriprep_sif="${project}/containers/fmriprep_latest.sif"
```

### FreeSurfer license

fMRIPrep requires a FreeSurfer license file. The license is free and can be requested from the FreeSurfer registration page:

```text
https://surfer.nmr.mgh.harvard.edu/registration.html
```

Save the file as:

```text
licenses/license.txt
```

Then set `license_file` in `fmriprep_job_template.sh` to that path. For example:

```text
license_file="${project}/licenses/license.txt"
```

## Input Data Assumptions

The ZIP workflow assumes:

- Input files are `.zip` archives.
- Subject IDs can be parsed from ZIP filenames by splitting on underscores.
- After extraction, each subject folder contains a `study/` directory with DICOM files.

For example, these filenames are valid for subject `1`:

```text
StudyName_1.zip
StudyName_001.zip
MyProject_001_scanexport.zip
```

The script reads the text after the first underscore as the subject ID. With `--zero_padding 3`, `StudyName_1.zip` and `StudyName_001.zip` both become `sub-001`.

These filenames are not valid for the current ZIP workflow:

```text
sub-001.zip          # no underscore before the subject number
StudyName-sub001.zip # subject number is not the second underscore-separated field
StudyName_ABC.zip    # subject ID is not numeric
```

If scanner exports use a different layout, use the two-step workflow and inspect the unzipped folders before conversion.

## Conversion Workflows

### Direct ZIP to BIDS

```bash
python dicom_to_bids.py --mapping_file my_study_mapping.json run \
  --zip_dir /path/to/dicom_zips \
  --output_dir /path/to/bids_dataset \
  --work_dir /scratch/$USER/dicom_to_bids \
  --subjects all \
  --zero_padding 3 \
  --misc_dir /path/to/misc_nifti \
  --workers 4
```

### Unzip first, then convert

Unzip:

```bash
python unzip_dicoms.py \
  --input_dir /path/to/dicom_zips \
  --output_dir /path/to/raw_dicom \
  --subjects all \
  --zero_padding 3
```

Convert:

```bash
python dicom_to_bids.py --mapping_file my_study_mapping.json run \
  --input_dir /path/to/raw_dicom \
  --output_dir /path/to/bids_dataset \
  --subjects all \
  --zero_padding 3 \
  --misc_dir /path/to/misc_nifti \
  --workers 4
```

### Subject selection

The `--subjects` argument accepts:

```bash
--subjects all
--subjects 1
--subjects 1,3,5
--subjects 1-10
--subjects 1,3-5,10
```

With `--zero_padding 3`, subject `1` becomes `sub-001`.

## Mapping Files

`bids_mapping.json` is a generic example. Most projects need their own mapping file.

The mapping file is a JSON object organized by BIDS modality. Each entry maps text from the converted scanner filename to a BIDS suffix.

The left side can be a simple filename prefix. It can also use one small regular-expression feature: parentheses capture a number that can be reused as `{run}` on the right side.

Example:

```json
{
  "anat": {
    "MPRAGE_(\\d+)": "T1w"
  },
  "fmap": {
    "FieldMap_(\\d+)_e1": "magnitude1",
    "FieldMap_(\\d+)_e2": "magnitude2",
    "FieldMap_(\\d+)_e2_ph": "phasediff"
  },
  "func": {
    "SMS_EPI_iso2p2_TR2_RUN(\\d+)": "task-main_run-{run}_bold"
  }
}
```

Rules are checked in order. Put specific rules before broad fallback rules.

Files that do not match any rule are moved to `--misc_dir` if that argument is provided. A large number of files in `misc_dir` usually means the mapping file needs to be updated.

### How the matching rules work

The left side of each mapping rule is matched against the filename produced by `dcm2niix`.

Most of the rule can be ordinary text copied from the scanner sequence name.

For example:

```json
"MPRAGE_(\\d+)": "T1w"
```

This means:

- `MPRAGE_` matches the literal text `MPRAGE_`.
- `(\\d+)` captures one or more digits, such as a series number.
- `"T1w"` is the BIDS suffix to use when the pattern matches.

For functional runs:

```json
"SMS_EPI_iso2p2_TR2_RUN(\\d+)": "task-main_run-{run}_bold"
```

The captured run number is used as `{run}`. A filename like:

```text
SMS_EPI_iso2p2_TR2_RUN2_12.nii.gz
```

would become:

```text
sub-001_task-main_run-2_bold.nii.gz
```

In JSON files, backslashes have special meaning, so the digit shortcut `\d` has to be written as `\\d`.

The exact scanner text depends on the study. A useful workflow is to convert one subject, check filenames in `misc_dir`, then adjust the mapping rules until expected files land in `anat/`, `func/`, and `fmap/`.

## Converter Behavior

### `dcm2niix`

`dcm2niix` is run with:

```text
-f %d_%s -p y -z y
```

This preserves the series description and series number in the intermediate converted filenames before the mapping rules rename files into BIDS format.

### Parallel processing

Use `--workers` to process multiple subjects in parallel.

```bash
--workers 1   # serial, easier to debug
--workers 4   # faster, useful after the mapping has been tested
```

Failures for one subject are logged and do not necessarily stop the full batch.

### Logs and temporary files

- Failed `dcm2niix` conversions are written to timestamped logs in `./logs/`.
- Temporary conversion folders are cleaned up at the end of the run.
- If interrupted, the script attempts cleanup before exiting.

## Fieldmap Linkage

Putting fieldmap files in `sub-*/fmap/` is not always enough for fMRIPrep to use them. fMRIPrep also needs metadata connecting the fieldmaps to the functional BOLD runs.

This repository includes `add_fieldmap_metadata.py` for a common simple case: one fieldmap acquisition, or one fieldmap set, applies to all functional runs for each subject.

Run a dry run first:

```bash
python add_fieldmap_metadata.py \
  --bids-dir /path/to/bids_dataset \
  --field-id auto_fieldmap \
  --dry-run
```

The dry run prints a JSON summary with subject counts, functional JSON counts, and fieldmap JSON counts.

If the summary is correct, write the metadata:

```bash
python add_fieldmap_metadata.py \
  --bids-dir /path/to/bids_dataset \
  --field-id auto_fieldmap
```

The script writes:

- `B0FieldIdentifier` to each selected fieldmap JSON.
- `B0FieldSource` to each functional BOLD JSON.

If the BIDS directory contains an alternate fieldmap acquisition that should not be linked, exclude matching files by name:

```bash
python add_fieldmap_metadata.py \
  --bids-dir /path/to/bids_dataset \
  --field-id auto_fieldmap \
  --exclude-fieldmap-name scout
```

This helper intentionally handles only the simple one-fieldmap-set-per-subject case. If different fieldmap sets apply to different runs, assign distinct B0 identifiers and map each functional run to the appropriate fieldmap using project-specific logic.

## fMRIPrep SLURM Template

`fmriprep_job_template.sh` is a generic DRAC/SLURM template. It:

- runs one subject per SLURM array task,
- stages the subject into `$SLURM_TMPDIR`,
- copies `dataset_description.json`,
- mounts the FreeSurfer license,
- runs fMRIPrep through Apptainer,
- copies outputs back to the project output directory.

The template stages the complete subject directory, including `fmap/`. Do not add `--ignore fieldmaps` if fieldmaps should be used.

Before running it, edit:

- `#SBATCH --account`
- `#SBATCH --mail-user`
- `#SBATCH --array`
- `project`
- `bids_root`
- `output_root`
- `fmriprep_sif`
- `license_file`
- fMRIPrep options such as `--output-spaces`

## QC Checklist

### After DICOM to BIDS conversion

- Each subject has the expected folders, usually `anat/`, `func/`, and sometimes `fmap/`.
- Each subject has a T1w anatomical image in `anat/`.
- Each expected task run appears in `func/`.
- Functional runs have matching `.nii.gz` and `.json` files.
- Field maps, if collected and intended for preprocessing, appear in `fmap/`.
- Fieldmap JSON files contain linkage metadata such as `B0FieldIdentifier`, and functional BOLD JSON files contain the matching `B0FieldSource`, if fieldmaps should be used.
- `misc_dir` is empty or contains only files that are not needed.
- Subject labels are consistent, for example `sub-001` rather than a mix of `sub-1` and `sub-001`.
- Run numbers are correct and in the expected order.
- No expected run is missing because a mapping pattern failed.

Useful inspection commands:

```bash
find /path/to/bids_dataset -maxdepth 3 -type f | head
find /path/to/bids_dataset/sub-001 -type f
```

Running a BIDS validator before fMRIPrep is recommended.

### During fMRIPrep

- SLURM jobs start successfully.
- Jobs use the expected account and subject array.
- Logs do not report missing BIDS subject folders.
- Logs do not report a missing FreeSurfer license.
- Logs do not report a missing fMRIPrep container.
- Jobs finish as `COMPLETED`, not `FAILED`, `TIMEOUT`, or `OUT_OF_MEMORY`.

### After fMRIPrep

- Each subject has an output folder under the fMRIPrep output directory.
- Each subject has an HTML report.
- Check the HTML reports for several subjects, especially early subjects and any rerun subjects.
- In the reports, inspect:
  - anatomical brain mask,
  - functional-to-anatomical registration,
  - susceptibility distortion correction or fieldmap reports if used,
  - motion summaries,
  - repeated warnings or errors.

The presence of fieldmap files alone does not prove fMRIPrep used them. Check the fMRIPrep HTML report or logs to confirm susceptibility distortion correction was applied when expected.

Poor registration, missing runs, failed fieldmap use, or systematic warnings should be resolved before downstream analysis.

## Files

- `dicom_to_bids.py`: main DICOM to BIDS converter.
- `unzip_dicoms.py`: optional standalone unzip step.
- `add_fieldmap_metadata.py`: links one fieldmap set per subject to functional BOLD runs using BIDS B0 metadata.
- `bids_mapping.json`: example mapping file.
- `fmriprep_job_template.sh`: generic DRAC/SLURM fMRIPrep template.
- `requirements.txt`: Python packages needed for conversion.
