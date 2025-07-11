#!/bin/bash
#SBATCH --time=15:00:00
#SBATCH --account=def-pstjacqu
#SBATCH  -n 1
#SBATCH --cpus-per-task=8
#SBATCH --mem-per-cpu=16G
#SBATCH --mail-user=efird@ualberta.ca
#SBATCH --mail-type=BEGIN
#SBATCH --mail-type=END
#SBATCH --mail-type=FAIL
#SBATCH --mail-type=REQUEUE
#SBATCH --mail-type=ALL
#SBATCH --array=1-15

sub_num=$(printf "%03d" $SLURM_ARRAY_TASK_ID)

cd
module load apptainer

project=/project/6040211/3DfMRI/

# Create directories for fMRIprep to access at runtime
mkdir $SLURM_TMPDIR/work_dir
mkdir $SLURM_TMPDIR/sub_${sub_num}_vol_out
mkdir $SLURM_TMPDIR/image
mkdir $SLURM_TMPDIR/license
mkdir -p $SLURM_TMPDIR/3DfMRI

# Copy the raw participant data
cp -r ${project}/raw_dicom/sub-${sub_num} $SLURM_TMPDIR/3DfMRI
cp ${project}/bids_dataset/dataset_description.json $SLURM_TMPDIR/3DfMRI # not sure if this is needed

# Required fMRIprep files
cp ${project}/fmriprep_24.0.0.sif $SLURM_TMPDIR/image
cp ${project}/license.txt $SLURM_TMPDIR/license


apptainer run  --cleanenv \
-B $SLURM_TMPDIR/3DfMRI:/raw \
-B $SLURM_TMPDIR/sub-${sub_num}:/output \
-B $SLURM_TMPDIR/work_dir:/work_dir \
-B $SLURM_TMPDIR/image:/image \
-B $SLURM_TMPDIR/license:/license \
$SLURM_TMPDIR/image/fmriprep_24.0.0.sif \
/raw /output participant \
--participant-label ${sub_num} \
--work-dir /work_dir \
--fs-license-file /license/license.txt \
--output-spaces T1w \
--stop-on-first-crash


cp -r $SLURM_TMPDIR/sub-${sub_num} ${project}/fmriprep/