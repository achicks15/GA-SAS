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

## This is an example SLURM submission script on the CADES cluster at Oak Ridge National Laboratory to run a Pepsi-SANS calculation over a large number of PDBs
## RGBIN is an environment variable passed during submission
## sbatch --export=ALL,RGBIN=25.0 
## RGBIN is the RGBIN from the Bilbo-MD Sampling

cd $SLURM_SUBMIT_DIR

## This is a simple case where the non-exchangeable hydrogens in chain B are 51% deutereted. 

mkdir -p fit_sans_d2o_75D 

for snap in {15500..115000..500}
do
pdbid=step1_pdbreader${RGBIN}_1_${snap}.pdb ## Should have chain identifiers in the PDB to match --deuterated flags in Pepsi-SANS
~/Pepsi-SANS $pdbid -o fit_sans_d2o_75D/step1${RGBIN}_${snap}_Uniform.dat -n 25 -ms 0.5 -ns 501 --d2o 0.75 --deuterated B --deut 0.51 

done
