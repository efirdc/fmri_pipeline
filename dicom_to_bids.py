import os
import sys
import shutil
import re
import json
from pathlib import Path
import fire
import subprocess
import requests
from unzip_dicoms import unzip_and_rename, parse_subjects
from typing import Optional
import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed


def _process_single_subject(
    sub_dir_name: str,
    input_dir: Path,
    output_dir: Path,
    temp_dir: Path,
    misc_dir: Optional[Path],
    bids_mapping: dict,
    dcm2niix_path: str,
    error_log_file: Path,
):
    """Process a single subject: convert DICOMs and organize into BIDS. Designed to run in a worker process."""
    subject_id = sub_dir_name.split('-')[1]
    subject_input_dir = input_dir / sub_dir_name / "study"
    subject_temp_dir = temp_dir / f"sub-{subject_id}"
    subject_temp_dir.mkdir(parents=True, exist_ok=True)

    # Run dcm2niix
    print(f"[sub-{subject_id}] Running dcm2niix...")
    cmd = [
        str(dcm2niix_path),
        "-f", "%d_%s",
        "-p", "y",
        "-z", "y",
        "-o", str(subject_temp_dir),
        str(subject_input_dir)
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        error_message = f"""
--------------------------------------------------
Timestamp: {datetime.datetime.now().isoformat()}
Subject: {sub_dir_name}
Command: {' '.join(e.cmd)}
Exit Code: {e.returncode}
Stderr:
{e.stderr}
--------------------------------------------------
"""
        with open(error_log_file, "a") as f:
            f.write(error_message)
        print(f"[sub-{subject_id}] !!! WARNING: dcm2niix failed. See {error_log_file} for details.")
        return subject_id, False

    # Organize into BIDS
    warnings = []
    for file in sorted(subject_temp_dir.iterdir()):
        if file.suffix not in [".nii", ".gz", ".json"]:
            continue

        target_path = None
        for modality, mappings in bids_mapping.items():
            for pattern, bids_name in mappings.items():
                match = re.match(pattern, file.name, re.IGNORECASE)
                if match:
                    groups = match.groups()
                    try:
                        formatted_bids_name = bids_name.format(*groups, run=groups[0])
                    except IndexError:
                        formatted_bids_name = bids_name

                    sub_bids_dir = output_dir / f"sub-{subject_id}" / modality
                    sub_bids_dir.mkdir(parents=True, exist_ok=True)

                    target_name = f"sub-{subject_id}_{formatted_bids_name}{file.suffix}"
                    if file.suffix == ".gz":
                        target_name = f"sub-{subject_id}_{formatted_bids_name}.nii.gz"
                        target_name = target_name.replace(".nii.nii.gz", ".nii.gz")

                    target_path = sub_bids_dir / target_name
                    break
            if target_path:
                break

        if target_path:
            shutil.move(file, target_path)
        elif misc_dir:
            warnings.append(file.name)
            misc_subject_dir = misc_dir / f"sub-{subject_id}"
            misc_subject_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(file, misc_subject_dir / file.name)

    if warnings:
        print(f"[sub-{subject_id}] {len(warnings)} files moved to misc (no BIDS mapping): {', '.join(warnings[:3])}...")

    print(f"[sub-{subject_id}] Done.")
    return subject_id, True


class DicomToBidsConverter:
    """
    Converts a raw DICOM dataset to BIDS format using a configurable mapping.
    Can operate on a directory of unzipped DICOMs or a directory of zipped archives.
    """

    def __init__(self, mapping_file: str = "bids_mapping.json"):
        self.dcm2niix_path = self._get_dcm2niix()
        with open(mapping_file, 'r') as f:
            self.bids_mapping = json.load(f)

    def _get_dcm2niix(self) -> Path:
        """
        Checks for dcm2niix and downloads it if not present.
        Returns the path to the executable.
        """
        # Check if dcm2niix is available on the system PATH first
        system_path = shutil.which("dcm2niix")
        if system_path:
            print(f"Using system dcm2niix: {system_path}")
            return Path(system_path)

        dcm2niix_dir = Path("dcm2niix")
        if dcm2niix_dir.exists():
            for f in dcm2niix_dir.iterdir():
                if f.name.startswith("dcm2niix") and os.access(f, os.X_OK):
                    return f.resolve()

        print("dcm2niix not found, downloading...")
        dcm2niix_dir.mkdir(exist_ok=True)

        if sys.platform.startswith('linux'):
            url = "https://github.com/rordenlab/dcm2niix/releases/latest/download/dcm2niix_lnx.zip"
            zip_path = dcm2niix_dir / "dcm2niix_lnx.zip"
        elif sys.platform.startswith('darwin'):
            url = "https://github.com/rordenlab/dcm2niix/releases/latest/download/dcm2niix_mac.zip"
            zip_path = dcm2niix_dir / "dcm2niix_mac.zip"
        else: # Assuming Windows
            url = "https://github.com/rordenlab/dcm2niix/releases/latest/download/dcm2niix_win.zip"
            zip_path = dcm2niix_dir / "dcm2niix_win.zip"

        try:
            with requests.get(url, stream=True) as r:
                r.raise_for_status()
                with open(zip_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            print("Download successful.")
            shutil.unpack_archive(zip_path, dcm2niix_dir)
            zip_path.unlink()
        except requests.exceptions.RequestException as e:
            print(f"Error downloading dcm2niix: {e}")
            sys.exit(1)
        except (shutil.ReadError, FileNotFoundError) as e:
            print(f"Error unpacking dcm2niix: {e}. The download may be corrupt.")
            sys.exit(1)


        for f in dcm2niix_dir.iterdir():
            if f.name.startswith("dcm2niix") and not f.name.endswith(".zip"):
                 # Make executable on Unix-like systems
                if sys.platform.startswith('linux') or sys.platform.startswith('darwin'):
                    f.chmod(f.stat().st_mode | 0o111)
                return f.resolve()

        raise FileNotFoundError("dcm2niix executable not found after download.")

    def run(
        self,
        output_dir: str,
        subjects: str = "all",
        input_dir: Optional[str] = None,
        zip_dir: Optional[str] = None,
        misc_dir: Optional[str] = None,
        zero_padding: int = 2,
        workers: int = 4,
    ):
        """
        Runs the DICOM to BIDS conversion.

        Args:
            output_dir (str): The root directory for the BIDS output.
            subjects (str, optional): A comma-separated list or range(s) of subject IDs. Defaults to "all".
            input_dir (str, optional): Path to a directory with pre-unzipped subject folders (e.g., sub-001).
            zip_dir (str, optional): Path to a directory with zipped subject archives.
            misc_dir (str, optional): A separate directory to store non-BIDS compliant files.
            zero_padding (int, optional): The number of leading zeros for the subject ID. Defaults to 2.
            workers (int, optional): Number of parallel workers for conversion. Defaults to 4.
        """
        if not input_dir and not zip_dir:
            print("Error: You must provide either --input-dir or --zip-dir.")
            sys.exit(1)
        if input_dir and zip_dir:
            print("Error: You can only provide one of --input-dir or --zip-dir.")
            sys.exit(1)

        self.output_dir = Path(output_dir).resolve()
        self.temp_dir = self.output_dir / "tmp"
        self.misc_dir = Path(misc_dir) if misc_dir else None

        # Create a unique, timestamped log file in a 'logs' directory
        log_dir = Path("./logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.error_log_file = log_dir / f"conversion_{timestamp}.log"

        self.output_dir.mkdir(parents=True, exist_ok=True)

        raw_dicom_dir = None
        try:
            if zip_dir:
                # Create a temporary directory to hold the unzipped raw DICOMs
                raw_dicom_dir = self.output_dir / "tmp_dicom"
                print(f"Unzipping archives from {zip_dir} to temporary directory {raw_dicom_dir}...")
                unzip_and_rename(zip_dir, str(raw_dicom_dir), subjects=subjects, zero_padding=zero_padding)
                self.input_dir = raw_dicom_dir
            elif input_dir:
                self.input_dir = Path(input_dir).resolve()
            else:
                # This case is handled by the initial check, but keeps linters happy
                return

            subject_list = []
            if subjects == "all":
                subject_list = sorted([d.name for d in self.input_dir.iterdir() if d.is_dir() and d.name.startswith("sub-")])
            else:
                parsed_subjects = parse_subjects(str(subjects))
                subject_list = [f"sub-{s.strip().zfill(zero_padding)}" for s in parsed_subjects]

            print(f"Processing {len(subject_list)} subjects with {workers} workers...")

            if workers <= 1:
                # Serial processing
                for sub_dir_name in subject_list:
                    _process_single_subject(
                        sub_dir_name, self.input_dir, self.output_dir, self.temp_dir,
                        self.misc_dir, self.bids_mapping, str(self.dcm2niix_path),
                        self.error_log_file,
                    )
            else:
                # Parallel processing
                with ProcessPoolExecutor(max_workers=workers) as executor:
                    futures = {
                        executor.submit(
                            _process_single_subject,
                            sub_dir_name, self.input_dir, self.output_dir, self.temp_dir,
                            self.misc_dir, self.bids_mapping, str(self.dcm2niix_path),
                            self.error_log_file,
                        ): sub_dir_name
                        for sub_dir_name in subject_list
                    }
                    for future in as_completed(futures):
                        sub_dir_name = futures[future]
                        try:
                            subject_id, success = future.result()
                        except Exception as e:
                            print(f"!!! ERROR processing {sub_dir_name}: {e}")

            print("--- Conversion complete ---")

        except KeyboardInterrupt:
            print("\n--- User interrupted. Cleaning up temporary files. ---")
            sys.exit(130)  # Standard exit code for Ctrl+C

        finally:
            # This block will always run, ensuring cleanup happens
            if self.temp_dir.exists():
                print("Cleaning up temporary directory...")
                shutil.rmtree(self.temp_dir)

            if raw_dicom_dir and raw_dicom_dir.exists():
                print(f"Cleaning up temporary raw DICOM directory {raw_dicom_dir}...")
                shutil.rmtree(raw_dicom_dir)


if __name__ == "__main__":
    fire.Fire(DicomToBidsConverter)
