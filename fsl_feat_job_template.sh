#!/bin/bash
#SBATCH --job-name=fsl_feat
#SBATCH --account=def-ACCOUNT
#SBATCH --time=12:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --output=logs/fsl_feat_%A_%a.out

set -euo pipefail

# Required environment variables:
#   MANIFEST_CSV  CSV from `fsl_feat_pipeline.py discover-runs`
#   CONFIG_JSON   FEAT config JSON
#   PIPELINE_DIR  checkout containing fsl_feat_pipeline.py
#
# Optional:
#   ROW_ID        override SLURM_ARRAY_TASK_ID
#   FSL_MODULE    module name to load, e.g. fsl/6.0.7
#   PYTHON_MODULE module name to load
#   PYTHON_BIN    python executable

if [[ -n "${FSL_MODULE:-}" ]]; then
  module load "${FSL_MODULE}"
fi
if [[ -n "${PYTHON_MODULE:-}" ]]; then
  module load "${PYTHON_MODULE}"
fi

MANIFEST_CSV="${MANIFEST_CSV:?Set MANIFEST_CSV}"
CONFIG_JSON="${CONFIG_JSON:?Set CONFIG_JSON}"
PIPELINE_DIR="${PIPELINE_DIR:?Set PIPELINE_DIR}"
PYTHON_BIN="${PYTHON_BIN:-python}"
ROW_ID="${ROW_ID:-${SLURM_ARRAY_TASK_ID:?Set ROW_ID or submit as a SLURM array}}"

if [[ -z "${SLURM_TMPDIR:-}" ]]; then
  echo "ERROR: this script must run inside a SLURM compute allocation with SLURM_TMPDIR set." >&2
  exit 2
fi

work_dir="${SLURM_TMPDIR}/fsl_feat_${ROW_ID}"
mkdir -p "${work_dir}"
mkdir -p logs

cd "${PIPELINE_DIR}"

srun --cpu-bind=cores --hint=nomultithread \
  "${PYTHON_BIN}" fsl_feat_pipeline.py run-feat-row \
  --manifest-csv "${MANIFEST_CSV}" \
  --config-json "${CONFIG_JSON}" \
  --row-id "${ROW_ID}" \
  --work-dir "${work_dir}"

srun --cpu-bind=cores --hint=nomultithread \
  "${PYTHON_BIN}" fsl_feat_pipeline.py summarize \
  --manifest-csv "${MANIFEST_CSV}" \
  --output-csv "${MANIFEST_CSV%.csv}.status.csv"
