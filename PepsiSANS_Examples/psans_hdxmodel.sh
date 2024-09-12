#!/bin/bash

#SBATCH -N 1 
#SBATCH -n 4
#SBATCH -c 1
#SBATCH -G 0
#SBATCH --mem=0G
#SBATCH -A bsd
#SBATCH -p batch
#SBATCH -t 06:00:00
#SBATCH -o ./%j-output.txt
#SBATCH -e ./%j-output.txt
#SBATCH --mail-type=FAIL
#SBATCH --mail-user=9cq@ornl.gov

## This is an example SLURM submission script on the CADES cluster at Oak Ridge National Laboratory to run a Pepsi-SANS calculation over a large number of PDBs
## RGBIN is an environment variable passed during submission
## sbatch --export=ALL,RGBIN=25.0 
## RGBIN is the RGBIN from the Bilbo-MD Sampling

cd $SLURM_SUBMIT_DIR

module load anaconda3
source activate ~/anaconda_SCOMAP-XD/SCOMAP-XD ## Location of the CONDA environment for SCOMAP-XD

## This is a more complex example where you would use SCOMAP-XD to calculate the position of the deuterium based off the structure of the PDB
## hModel 3 uses explicit deuteration in your model for Pepsi-SANS
## SCOMAP-XD is located here: https://github.com/achicks15/SCOMAP-XD

for snap in {15500..115000..500}
do
pdbid=step1_pdbreader${RGBIN}_1_${snap}.pdb
python3 ~/anaconda_SCOMAPXD/pyscripts/deuterate.py -s 75.0 -n 1 -p step1${RGBIN}_${snap}_nofad -g "0.0/0.0" ./fit/$pdbid
~/Pepsi-SANS ./fit/Template_PDBs/step1${RGBIN}_${snap}_nofad_75-sD2O_0-0-gD2O_NEx0001.pdb -o fit_sans_d2o_75D/step1${RGBIN}_${snap}_nofad_EXHModel.dat -n 25 -ms 0.5 -ns 501 --d2o 0.75 --hModel 3

done
