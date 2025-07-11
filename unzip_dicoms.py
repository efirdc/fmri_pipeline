import os
import zipfile
import shutil
import fire
from typing import List, Union, Tuple

def parse_subjects(subjects_str: str) -> List[str]:
    """
    Parses a subject string, handling ranges and comma-separated values.
    e.g., "01,03-05" -> ["01", "03", "04", "05"]
    """
    subjects = []
    parts = subjects_str.split(',')
    for part in parts:
        part = part.strip()
        if '-' in part:
            start, end = part.split('-')
            try:
                start_num, end_num = int(start), int(end)
                for i in range(start_num, end_num + 1):
                    subjects.append(str(i))
            except ValueError:
                print(f"Warning: Invalid range '{part}', skipping.")
        else:
            try:
                int(part) # check if it's a valid number
                subjects.append(part)
            except ValueError:
                print(f"Warning: Invalid subject ID '{part}', skipping.")
    return subjects

def unzip_and_rename(
    input_dir: str,
    output_dir: str,
    subjects: Union[str, int, List[Union[str, int]], Tuple[Union[str, int], ...]] = "all",
    zero_padding: int = 2,
):
    """
    Unzips archives and renames the extracted folders.

    Args:
        input_dir (str): Directory containing the zipped DICOM files.
        output_dir (str): Directory to extract the files to.
        subjects (str or list, optional): A single subject ID, a list of subject IDs,
                                          or 'all' to process all subjects. Defaults to "all".
        zero_padding (int, optional): The number of leading zeros for the subject ID. Defaults to 2.
    """
    os.makedirs(output_dir, exist_ok=True)

    subjects_to_process = []
    if subjects != "all":
        # Handle the different ways fire can pass arguments
        if isinstance(subjects, (list, tuple)):
            subjects_str = ",".join(map(str, subjects))
        else:
            subjects_str = str(subjects)
        subjects_to_process = parse_subjects(subjects_str)

    for filename in sorted(os.listdir(input_dir)):
        if filename.endswith(".zip"):
            try:
                subject_id = filename.split('_')[1].split('.')[0]
            except IndexError:
                print(f"Warning: Could not extract subject ID from {filename}. Skipping.")
                continue

            # Filter subjects if a list is provided
            if subjects_to_process and subject_id not in subjects_to_process:
                continue

            zip_path = os.path.join(input_dir, filename)
            print(f"Processing {zip_path}...")

            # Extract the zip file
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(output_dir)

            # --- Renaming logic ---
            base_name = os.path.splitext(filename)[0]
            try:
                subject_id = base_name.split('_')[1]
            except IndexError:
                print(f"Warning: Could not extract subject ID from {filename}. Skipping.")
                continue

            original_folder_path = os.path.join(output_dir, base_name)
            new_folder_name = f"sub-{subject_id.zfill(zero_padding)}"
            new_folder_path = os.path.join(output_dir, new_folder_name)

            if os.path.isdir(original_folder_path):
                print(f"Renaming {original_folder_path} to {new_folder_path}")
                shutil.move(original_folder_path, new_folder_path)
            else:
                print(f"Warning: Expected extracted folder {original_folder_path} not found.")

if __name__ == "__main__":
    fire.Fire(unzip_and_rename)
    print("Processing complete.") 