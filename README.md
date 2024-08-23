# GA-SAS
Genetic Algorithm Code for performing a Minimum Ensemble Search (MES) to optimize small angle scattering curves(SAS). The code is written all in python3, GASANS-dask.py.
The code requires pandas, numpy, scipy, lmfit, and dask modules. 

## Installing the necessary modules 
The easiest way to get the necessary modules is with an anaconda enviroment. 

## Instructions:
The GASANS-dask.py reads a JSON file, config.json, to read the location of the calculated scattering files, corresponding PDB files, and experiment scattering curves. There should be a file "structure.csv" in csv format with the names of the PDB file and corresponding calculated scattering curves, and following any structural parameters you wish to correlate to the ensemble of structures. The name of the structure file is givin in the config JSON file. "read_json_input.py" is the code to read the json input file. It is loaded in "GASANS-dask.py". 

The second set of entries in the JSON config file is the maximum size of the ensemble you wish to run " max_ensemble_size". The next entries are the parameters for each run of the genetic algorithm. If max_ensemble_size =4, you will have 3 entries for the runs of the genetic algorithm with 2,3, and 4 scattering profiles per ensemble. In each entry, you can change parameters like the number of generations, number of iterations, crossover probability, mutation probability, fitting algorithm, etc.. One parameter parallel should always be true and is handled by Dask. Dask futures can run on one processes, but can be changed to run across multiple processes for faster performance. 

### To Run:
Call GASANS-dask.py in your local directory with the properly set up config_test.json and structure.csv file. 

### Output:
GASANS-dask.py will output a csv file with the best_model parameters and the scattering curve of the best fitting model.  

## To Do:
1. Update the reader for experiment files for general reads of experimental data, Q, I(Q), $\sigma I(Q)$. 
2. Have a way to read in best_model parameters incase users want to look at the all together or recalculate. 
3. Fitting ranges for the data, qmin qmax, parameters 
4. Parameter to select the fraction of CPUs you want to parallize with. 
