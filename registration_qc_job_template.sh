#!/bin/bash
#SBATCH --time=04:00:00
#SBATCH --account=def-YOUR_ACCOUNT_HERE
#SBATCH --cpus-per-task=1
#SBATCH --mem=16G
#SBATCH --mail-user=YOUR_EMAIL_HERE@ualberta.ca
#SBATCH --mail-type=BEGIN,END,FAIL
#SBATCH --output=logs/registration-qc-%j.out

set -euo pipefail

project="/path/to/your/analysis"
fmriprep_root="${project}/fmriprep"
qc_root="${project}/registration_qc"

cd "${project}"
module load python/3.11.5
source .venv/bin/activate

mkdir -p "${qc_root}" logs

srun --cpu-bind=cores --hint=nomultithread \
  python fmri_pipeline/registration_qc_manifest.py \
    --fmriprep-root "${fmriprep_root}" \
    --out-csv "${qc_root}/manifest.csv" \
    --one-row-csv "${qc_root}/manifest_one_row.csv" \
    --segmentation-source ribbon_or_dseg

srun --cpu-bind=cores --hint=nomultithread \
  python fmri_pipeline/registration_qc.py \
    --manifest-csv "${qc_root}/manifest.csv" \
    --out-dir "${qc_root}/outputs" \
    --slices 7 \
    --crop-margin-px 12
