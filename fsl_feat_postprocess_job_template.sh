#!/bin/bash
#SBATCH --job-name=fsl_feat_post
#SBATCH --account=def-ACCOUNT
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --output=logs/fsl_feat_post_%j.out

set -euo pipefail

# Required:
#   MANIFEST_CSV
#   PIPELINE_DIR
#   QC_ROOT
#
# Optional:
#   ROI_CONFIG_JSON
#   ROI_OUTPUT_ROOT
#   STATUS_CSV
#   MNI_GRAY_PRIOR
#   MNI_GRAY_MASK_OUTPUT
#   FSL_MODULE
#   PYTHON_MODULES
#   PYTHON_BIN

if [[ -n "${FSL_MODULE:-}" ]]; then
  module load "${FSL_MODULE}"
fi
if [[ -n "${PYTHON_MODULES:-}" ]]; then
  module load ${PYTHON_MODULES}
fi

MANIFEST_CSV="${MANIFEST_CSV:?Set MANIFEST_CSV}"
PIPELINE_DIR="${PIPELINE_DIR:?Set PIPELINE_DIR}"
QC_ROOT="${QC_ROOT:?Set QC_ROOT}"
STATUS_CSV="${STATUS_CSV:-${MANIFEST_CSV%.csv}.status.csv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "${PIPELINE_DIR}"
mkdir -p logs "$(dirname "${STATUS_CSV}")" "${QC_ROOT}"

if [[ -n "${MNI_GRAY_PRIOR:-}" && -n "${MNI_GRAY_MASK_OUTPUT:-}" ]]; then
  mkdir -p "$(dirname "${MNI_GRAY_MASK_OUTPUT}")"
  if [[ ! -f "${MNI_GRAY_MASK_OUTPUT}" ]]; then
    fslmaths "${MNI_GRAY_PRIOR}" -thr "${MNI_GRAY_THRESHOLD:-0.2}" -bin "${MNI_GRAY_MASK_OUTPUT}"
  fi
fi

srun --cpu-bind=cores --hint=nomultithread \
  "${PYTHON_BIN}" fsl_feat_pipeline.py summarize \
  --manifest-csv "${MANIFEST_CSV}" \
  --output-csv "${STATUS_CSV}"

srun --cpu-bind=cores --hint=nomultithread \
  "${PYTHON_BIN}" fsl_feat_pipeline.py make-qc \
  --manifest-csv "${MANIFEST_CSV}" \
  --output-root "${QC_ROOT}"

if [[ -n "${ROI_CONFIG_JSON:-}" && -n "${ROI_OUTPUT_ROOT:-}" ]]; then
  srun --cpu-bind=cores --hint=nomultithread \
    "${PYTHON_BIN}" fsl_feat_pipeline.py build-roi-masks \
    --manifest-csv "${MANIFEST_CSV}" \
    --roi-config-json "${ROI_CONFIG_JSON}" \
    --output-root "${ROI_OUTPUT_ROOT}"
fi

