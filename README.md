# fMRI DICOM to BIDS Conversion Pipeline

This repository contains a set of Python scripts to convert raw fMRI DICOM data into the Brain Imaging Data Structure (BIDS) format. The pipeline is designed to be configurable and adaptable for different studies from the same scanner.

The main script, `dicom_to_bids.py`, can run the entire conversion process in a single step, from zipped DICOM archives to a BIDS-compliant dataset.

## Setup

This guide provides instructions for setting up the pipeline on a local machine or a Digital Research Alliance of Canada (DRAC) cluster.

### Prerequisites

Before you begin, ensure you have Python 3.8 or higher available.

**For Local Machines:**
If you don't have Python, you can download it from the [official Python website](https://www.python.org/downloads/).

**For DRAC Clusters:**
Python 3.11 is loaded by default on DRAC clusters.

### Installation Steps

1.  **Clone the Repository**

    On a DRAC cluster, it's good practice to store projects in a designated directory. We recommend cloning into a path like `$HOME/projects/def-{group_name}/{your_user_name}/`.

    First, create this directory structure if it doesn't exist, then clone the repository:
    ```bash
    # Replace with your actual group and user names
    mkdir -p $$HOME/projects/def-{group_name}/{your_user_name}/
    cd $$HOME/projects/def-{group_name}/{your_user_name}/

    # Clone the repository
    git clone https://github.com/efirdc/fmri_pipeline.git
    cd fmri_pipeline
    ```

2.  **Create and Activate a Virtual Environment**

    A virtual environment isolates project-specific dependencies. We will create it inside the cloned `fmri_pipeline` directory.

    **On Windows:**
    ```bash
    # Create the virtual environment
    python -m venv .venv

    # Activate the virtual environment
    .\\.venv\\Scripts\\activate
    ```

    **On macOS and Linux (including DRAC):**
    ```bash
    # Create the virtual environment
    python3 -m venv .venv

    # Activate the virtual environment
    source .venv/bin/activate
    ```
    You will know the environment is active when you see `(.venv)` at the beginning of your command prompt.

3.  **Install Required Packages**

    With the virtual environment activated, install the necessary Python packages using pip:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Verify the Installation**

    Check that the main script is executable and the dependencies are installed correctly by running:
    ```bash
    python dicom_to_bids.py --help
    ```
    This command should display the script's help menu, confirming that the setup is complete.

## Conversion Process

The pipeline can be run in two ways: a streamlined single-step process from zip files, or a two-step manual process.

### Recommended: Single-Step Conversion from ZIP Archives

This is the easiest method. The script will handle unzipping, converting, and cleaning up temporary files automatically.

**Usage:**
```bash
python dicom_to_bids.py run --zip-dir <dir> --output-dir <dir> [--subjects <list>] [--zero-padding <int>] [--misc-dir <dir>]
```
*   `--zip-dir`: Path to the directory containing the zipped DICOM archives.
*   `--output-dir`: The root directory for the final BIDS dataset.
*   `--subjects`: (Optional) A string to specify subjects. Defaults to `"all"`.
    *   Comma-separated list: `1,2,5`
    *   Range: `1-5`
    *   Combination: `1,3-5,10`
*   `--zero-padding`: (Optional) The number of digits for the subject ID (e.g., `3` for `sub-001`). Defaults to `2`.
*   `--misc-dir`: (Optional) If provided, any converted files that do not match a rule in `bids_mapping.json` will be saved to this separate directory, organized by subject (e.g., `<misc-dir>/sub-001/`). By default, these files are discarded.

**Example:**
```bash
python dicom_to_bids.py run --zip-dir 3DfMRI/dicom_zips --output-dir 3DfMRI/bids_dataset --subjects 1-5,8 --zero-padding 3 --misc-dir 3DfMRI/misc_nifti
```

### Error Handling and Logging

If `dcm2niix` fails to convert a subject's data (e.g., due to a corrupted DICOM file), the pipeline will **not** stop. It will log detailed information about the failure to a timestamped log file inside a `logs` directory (e.g., `./logs/conversion_2023-10-27_10-30-00.log`).

The script will print a warning to the console and continue processing the remaining subjects. After the run is complete, you can inspect the relevant log file to see which subjects failed and why, allowing you to investigate the problematic data without interrupting the entire workflow.

### Alternative: Two-Step Manual Conversion

This method gives you more control. For example, you might want to inspect the unzipped DICOM files before converting them.

**Step 1: Unzip DICOM Archives**
```bash
python unzip_dicoms.py --input-dir 3DfMRI/dicom_zips --output-dir 3DfMRI/raw_dicom --zero-padding 3
```

**Step 2: Convert to BIDS**
```bash
python dicom_to_bids.py run --input-dir 3DfMRI/raw_dicom --output-dir 3DfMRI/bids_dataset --zero-padding 3 --misc-dir 3DfMRI/misc_nifti
```

---

## The `bids_mapping.json` File

This file is the brain of the conversion process. It uses **regular expressions** (regex) to match the descriptive filenames generated by `dcm2niix` to their proper BIDS format.

The file has two main sections, `anat` and `func`, corresponding to the BIDS modalities. The script checks each converted filename against the patterns in this file. **The patterns are checked in order, so more specific patterns should always be placed before more general ones.**

### Example 1: Basic Anatomical Scan

*   **dcm2niix output filename:** `MPRAGE_7001.nii.gz`
*   **JSON Mapping Rule:**
    ```json
    "anat": {
      "^MPRAGE_.*": "T1w"
    }
    ```
*   **Explanation:**
    *   `^MPRAGE_.*`: This regex pattern breaks down as:
        *   `^`: Asserts that the pattern must start at the beginning of the filename.
        *   `MPRAGE_`: Matches the literal characters "MPRAGE_".
        *   `.*`: A wildcard that matches any character (`.`) zero or more times (`*`).
    *   `"T1w"`: If the pattern matches, the script assigns the BIDS suffix `T1w`.
*   **Final BIDS Filename:** `sub-001_T1w.nii.gz`

### Example 2: Functional Scan with Run Number

*   **dcm2niix output filename:** `SMS_EPI_iso2p2_TR2_RUN2_12.nii.gz`
*   **JSON Mapping Rule:**
    ```json
    "func": {
      "^SMS_EPI_iso2p2_TR2_RUN(\\d+)_.*": "task-main_run-{run}_bold"
    }
    ```
*   **Explanation:**
    *   `^SMS_EPI_iso2p2_TR2_RUN`: Matches the literal text at the start of the filename.
    *   `(\\d+)`: This is the most important part.
        *   `\d+`: Matches one or more digits (0-9).
        *   `()`: The parentheses create a **capturing group**. The script saves the number found here (e.g., "2"). In JSON, the backslash must be escaped, so it's written as `\\d+`.
    *   `_.*`: Matches the underscore after the number and the rest of the filename.
    *   `"task-main_run-{run}_bold"`: This is the output template. The script replaces `{run}` with the number it captured.
*   **Final BIDS Filename:** `sub-001_task-main_run-2_bold.nii.gz`

### Example 3: Handling Repeated Runs (Order Matters!)

*   **dcm2niix output filenames:**
    1.  `SMS_EPI_iso2p2_TR2_RUN2_Repeat_14.nii.gz`
    2.  `SMS_EPI_iso2p2_TR2_RUN2_12.nii.gz`
*   **JSON Mapping Rule:**
    ```json
    "func": {
      "^SMS_EPI_iso2p2_TR2_RUN(\\d+)_Repeat_.*": "task-main_run-{run}_acq-repeat_bold",
      "^SMS_EPI_iso2p2_TR2_RUN(\\d+)_.*": "task-main_run-{run}_bold"
    }
    ```
*   **Explanation:**
    *   The script first checks against the `_Repeat_` pattern. Filename #1 matches, captures the run number "2", and is renamed with the `acq-repeat` entity.
    *   Filename #2 does **not** match the `_Repeat_` pattern, so the script moves to the next rule. It matches the more general `RUN(\\d+)` pattern and is renamed normally.
    *   If the general rule came first, both files would match it, and the specific `_Repeat_` rule would never be reached, causing a filename collision.
*   **Final BIDS Filenames:**
    1.  `sub-001_task-main_run-2_acq-repeat_bold.nii.gz`
    2.  `sub-001_task-main_run-2_bold.nii.gz` 

If a converted file does not match any pattern, it will be placed in the directory specified by `--misc-dir` **only if that option is provided**. Otherwise, it is discarded. This is useful for identifying scans that need a new mapping rule. 