
from pathlib import Path
import json

def _read_json_input(config_file="./config.json"):
    """
    Function to read a json file for the inputs of the genetic algorithm:
    mapping function to change dict keys to 
    Should include:
    experimental data to read in 
    directory of the files if not in working directory
    scattering data file: PDBFILENAME SCATTERINGFILENAME [...Structural Parameters...]
    Genetic Algorithm:
    1. number of iterations (n_iter) 
    2. number of generations (n_gen) 
    3. Ensemble Size or list of ensemble sizes (ens_size) 
    4. fraction of structures to use in the ensembles (ens_split) 
    5. crossover probability (co_prob) 
    6. mutation probabaility (mut_prob)  
    7. cutoff weight for validation (self.cut_weight)
    8. Evaluation of Fitness (standard or inv_absolute)
    9. Run evaluation step in parallel (parallel) (if parallel = False: Nedler-Mead instead of DiffEv)
    10. what type of algorithm to use the weights (default is Differential Evolution )
    
    """
    
    with open(config_file ,mode='r') as cfile:
        cfile_params = json.load(cfile)
    
    ga_input_list = []
    ga_param_ndx = 2
    cfile_keys = list(cfile_params.keys())
    for nens, ens_size in enumerate(range(2, cfile_params['max_ensemble_size']+1, 1)):
        
        ga_input_list.append(cfile_params[cfile_keys[ga_param_ndx+nens]])


    return cfile_params['files'], ga_input_list

if __name__=="__main__":

    #with open("testing_read.json", mode='w', encoding='utf-8') as testjson:
    #    json.dump({"testing":[1,2,3,4]}, testjson)

    config_file1 = Path("config_test.json")
    if config_file1.exists():
        print(f"config file, {config_file1}, exists. Reading config file")
        config_filelist, config_ga_input = _read_json_input(config_file1)

    else:
        print(f"config file, {config_file1}, does not exist")

    
    print(config_ga_input)