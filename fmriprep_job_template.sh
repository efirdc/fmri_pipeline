#!/bin/bash
#SBATCH --time=12:00:00
#SBATCH --account=def-YOUR_ACCOUNT_HERE
#SBATCH -n 1
#SBATCH --cpus-per-task=8
#SBATCH --mem-per-cpu=8G
#SBATCH --mail-user=YOUR_EMAIL_HERE@ualberta.ca
#SBATCH --mail-type=BEGIN,END,FAIL
#SBATCH --array=SUBJECT_IDS_HERE

set -euo pipefail

raw_sub_id="${SLURM_ARRAY_TASK_ID}"
sub_id="$(printf "%03d" "${raw_sub_id}")"

module load apptainer

project="/path/to/your/project"
bids_root="${project}/bids_dataset"
output_root="${project}/fmriprep"
fmriprep_sif="${project}/fmriprep_24.1.1.sif"
license_file="${project}/license.txt"
subject_dir="${bids_root}/sub-${sub_id}"

if [[ ! -d "${subject_dir}" ]]; then
  echo "Missing BIDS subject directory: ${subject_dir}" >&2
  exit 1
fi

if [[ ! -f "${bids_root}/dataset_description.json" ]]; then
  echo "Missing BIDS root file: ${bids_root}/dataset_description.json" >&2
  exit 1
fi

if [[ ! -f "${fmriprep_sif}" ]]; then
  echo "Missing fMRIPrep image: ${fmriprep_sif}" >&2
  exit 1
fi

if [[ ! -f "${license_file}" ]]; then
  echo "Missing FreeSurfer license: ${license_file}" >&2
  exit 1
fi

mkdir -p "${SLURM_TMPDIR}/bids_input" "${SLURM_TMPDIR}/output" "${SLURM_TMPDIR}/work_dir" "${output_root}"

cp -r "${subject_dir}" "${SLURM_TMPDIR}/bids_input/"
cp "${bids_root}/dataset_description.json" "${SLURM_TMPDIR}/bids_input/"
cp "${license_file}" "${SLURM_TMPDIR}/bids_input/license.txt"

apptainer run --cleanenv \
  -B "${SLURM_TMPDIR}/bids_input:/data" \
  -B "${SLURM_TMPDIR}/output:/output" \
  -B "${SLURM_TMPDIR}/work_dir:/work" \
  "${fmriprep_sif}" \
  /data /output participant \
  --participant-label "${sub_id}" \
  --work-dir /work \
  --fs-license-file /data/license.txt \
  --output-spaces T1w MNI152NLin2009cAsym \
  --nthreads "${SLURM_CPUS_PER_TASK}" \
  --omp-nthreads "${SLURM_CPUS_PER_TASK}" \
  --stop-on-first-crash

cp -r "${SLURM_TMPDIR}/output/." "${output_root}/"