
#!/bin/python 

import numpy as np
import pandas as pd 
#import matplotlib
#%matplotlib inline
#import matplotlib.pyplot as plt
#import seaborn as sns
#plt.rcParams["font.family"] = "Times New Roman"
#plt.rcParams["mathtext.fontset"] = "stix"

from pathlib import Path
import lmfit as lmf
import scipy.interpolate as scpint 
import dask.distributed as distributed
import os
import time



def reduced_chi2(expected, model, sigma_exp, ddof=1):
    return (np.power((model-expected)/sigma_exp,2)).sum()/(sigma_exp.shape[0]-ddof)

def unique_arr(arr):
    return (np.unique(arr).shape[0] == arr.shape[0])

def probfitness_func(rchi2):
    """
    I forget what this is for?
    """
    if rchi2 < 1.0:
        fitness = 1/np.power((1/rchi2-1),2)
    else:
        fitness = 1/np.power((rchi2-1), 2)
            
    return fitness  

def invert_x2(rchi2):
    return 1/rchi2
def invert_absx2(rchi2):
    return 1/abs(1-rchi2)

def interpolate2exp(row, expQ):
    interp_Iq = scpint.splrep(row.index.values, row.values, s=0)
    #print(f'{expQ}')
    modI_expQ = scpint.splev(expQ, interp_Iq, der=0)
    return pd.Series(index=expQ, data=modI_expQ)

  
def _residual_lmf(pars, I, data=None, sigma=None):
    """
    Residual function for lmfit for the ensemble fits
    """
    parvals = pars.valuesdict()
    c = parvals['c']
    b = parvals['b']
    wkeys = list(parvals.keys())[2:]
    wparms = [parvals[ky] for ky in wkeys]
    I=I.reshape(-1,len(wkeys))
    #print(I[:,0].shape,data.shape)
    model = c*(np.array([wparms[n]*I[:,n] for n in range(I.shape[1])]).sum(axis=0)) + b
    
    #print(model.shape)
    if np.all(data) == None:
        return model
    if np.all(sigma) == None:
        return (data-model)
    else:
        return (data-model)/sigma
    
    
def gen_modelparams(ens_size, param_dict={})->None:
    """
    param_dict: for evaluating the model after the fitting with optimal parameters
    """
    pars=lmf.Parameters()
    if len(param_dict.keys())==0.0:
        pars.add_many(("c",4.0, True, 1e-12, np.inf),
                            ("b",1e-4, True, -np.inf, np.inf))
        
        const_expr="1.0" ## constraint expression
        
        for nw in range(1, ens_size+1,1):
            pars.add(f"w{nw}",value=(1.0/ens_size+0.1), min=1e-12, max=1.0, vary=True)
            
            if nw == (ens_size):
                pars.add(f"w{nw}", min=1e-12, max=1.0, expr=const_expr, vary=False)
                break
            const_expr+=f"-w{nw}"
    else:
        pars = lmf.Parameters()
        for ky in param_dict.keys():
            pars.add(ky, value=param_dict[ky])
            
    return pars
    
    
def fitness(set_data, expdata, ens_size):
    """
    Perform the fit to the experimental data
    Save the fit parameters and the chi2
    """
    fit_time_start = time.time()
        
    mpars = gen_modelparams(ens_size)
    ## check if self.experiment has error values:
    if ("Error" in expdata.columns):
        sigmaI = expdata['Error'].values
    else:
        sigmaI = None
            
    minimize_fit = lmf.minimize(_residual_lmf, mpars,
                                    method='Differential Evolution',
                                    args=(set_data, ),
                                    kws={'data':expdata.iloc[:,1].values,
                                       'sigma':sigmaI},
                                    )
        
    ## X2 is not the fitness here, the weight in choose_parents is so should be adjusted accordingly
    ## 
    #self.gen_fitness[self.curr_gen, data_index]  = minimize_fit.redchi
    result = {'success':minimize_fit.success, 'nfev':minimize_fit.nfev, 'eval_time':(time.time() - fit_time_start), 
                  'chi2':minimize_fit.redchi, 'aic':minimize_fit.aic, 'params':minimize_fit.params.valuesdict(),}
        
    return result

class GAEnsembleOpt:
    
    def __init__(self, data, exp_data,
                 ens_size=2, n_gen=100, n_iter=1000,
                 ens_split=0.85, co_prob=0.5, mut_prob=0.15,
                 method="prob", rank_prob=0.8, invabsx2=False,
                 elitism=True, parallel=True):
        
        
        self.ens_size = ens_size
        self.n_gen = n_gen
        self.n_iter = n_iter
        self.curr_gen = 0
        self.method = method
        self.rankprob = rank_prob
        self.invabsx2 = invabsx2 ## use the inverted x2 as the fitness with the absolute value of 1-X^2


        ## Definitions of the data to fit and 
        self.data = data ## data should be in (nq, nConf) dataframe
        self.experiment = exp_data.astype('float') ## should be a dataframe
        self.indices = np.arange(0, data.shape[1], 1)
        self.interp_data = self.data.T.apply(interpolate2exp,
                                               axis=1,
                                               expQ = self.experiment['Q'].values,
                                               ) ## Will Return (nConf, nq) dataframe
        
        ## Eventually need to change if any of the general parameters are changed
        remainder = (data.shape[1]*ens_split)%self.ens_size
        if remainder != 0:
            self.n_ens = int((int(data.shape[1]*ens_split)-remainder)/self.ens_size)
            self.pool_size = int(data.shape[1]*ens_split-remainder)
        else:
            self.n_ens = int(data.shape[1]*ens_split/self.ens_size)
            self.pool_size = int(data.shape[1]*ens_split)
        
        ## must be even to divide into parents
        if (self.n_ens%2)==1:
            self.n_ens-=1
            self.pool_size-=self.ens_size
        
        #self.ens_indices = np.zeros((self.n_ens,self.ens_size))
        print(self.data.shape[1], self.pool_size)
        self.mut_indices = np.zeros((self.data.shape[1]-self.pool_size,1))
        
        ## class attribute for the ensemble fitting 
        self.cut_weight = 1e-6
        
        ## class attributes for the ga algorithm
        self.parents = np.zeros((self.n_ens, self.ens_size)) # set of indices ...
        self.parent_pairs = np.zeros((int(self.n_ens/2),2,self.ens_size))
        self.elitism=elitism
        self.elite_child = [] ## for elitism 
        self.children = np.zeros((self.n_ens, self.ens_size)) # set of indices ...
                                 
        self.gen_fitness = np.zeros((self.n_gen, self.n_ens))
        self.gen_rchi2 = np.zeros((self.n_gen, self.n_ens))
        self.gen_aic = np.zeros((self.n_gen, self.n_ens))
        
        self.fitness_check = np.ones((self.n_ens, self.n_gen)) ## checks to see if the fit produces proper weights
        self.p_crossover = co_prob
        self.p_mutate = mut_prob
        
        ##convergence criteria
        self.gen_converged = False
        self.iter_converged = False
        
        self.fitness_saturation = 0 ## count how many generations have the same minimum 
        self.pbest_rchi2 = {'chi2':0, 'aic':0, 'fitness':0,
                            'ensemble':[0]*self.n_gen, 'gen_found':0,
                            'fit_pars':{}} ## previous best aic
        
        ## start at aic -np.inf ==> RelLikelihood=0, same with rchi2
        self.cbest_rchi2 = {'chi2':np.inf, 'aic':np.inf, 'fitness':0, 'ensemble':[0]*self.n_gen, 'gen_found':0, 'fit_pars':{}} ## current best aic 
        self.citbest_rchi2 = self.pbest_rchi2
        self.itbest_rchi2 = [dict() for n in range(self.n_iter)] 
        

        ## average time to calculate the , total time spent doing the fitness calculation,
        ## time spent evaluating, time for validation, time updating for parents, crossovers, mutation
        ## fitness total ~= evaluation time
        self.individual_fitness_time = np.zeros((self.n_ens,1))
        self.time_log={'fitness_ave':0.0, 'fitness_total':0.0, 'evaluation':0.0, 'validation':0.0, 
                       'parents':0.0, 'crossover':0.0, 'mutation':0.0}

        ## Parallel Options
        ## Fraction of CPUs we want to use? Maybe better to use a localcluster outside of the 

        self.parallel = parallel 
        
   
    def randomcol_indices(self):
        """
        randomize the column selections from the data
        """
        return np.random.choice(np.arange(0, self.data.shape[1], 1), self.pool_size, replace=False).reshape(-1,self.ens_size)    
    
    
    def evaluate(self, client):
        """
        Fit each of the parents to the experimental data
        Evaluate the fitness from the fits 
        
        For Loop can be parallelized with multiprocess?
        """
        eval_time_start = time.time()
        ensemble_scattering_parents = np.rollaxis(self.interp_data.values[self.parents,:], 2, 1)
        
        
        mfit_array = {}
        if self.parallel:
            #with distributed.LocalCluster(n_workers=self.cpus,
            #                  processes=True,
            #                  threads_per_worker=1,
            #                 ) as cluster, distributed.Client(cluster) as client:
                
            fitmap = client.map(fitness, ensemble_scattering_parents, expdata = self.experiment, ens_size=self.ens_size)
            fitmap_seq = distributed.as_completed(fitmap)
                
            for nfit, fit in enumerate(fitmap_seq):
                mfit_array.update({nfit:fit.result()})
        else:
            for nfit, ens_data in enumerate(ensemble_scattering_parents):
                #print(datindex)
                mfit_array.update(self.fitness(ens_data, self.experiment))

        self.time_log['evaluation'] = time.time()-eval_time_start
        ##print(self.pars.valuesdict(), mfit_array[0]['params'])
        self.gen_paramfit = pd.DataFrame(index=list(mfit_array[0]['params'].keys()),
                                         columns=np.arange(0,self.n_ens)).fillna(0.0)
        
        for data_index in list(mfit_array.keys()):
            self.gen_rchi2[self.curr_gen, data_index] = mfit_array[data_index]['chi2']
            self.gen_aic[self.curr_gen, data_index] = mfit_array[data_index]['aic']
            self.gen_paramfit.loc[list(mfit_array[0]['params'].keys()), data_index] = list(mfit_array[data_index]['params'].values())
            self.individual_fitness_time[data_index] = mfit_array[data_index]['eval_time']

        if self.method == "prob":
            if (not self.invabsx2): ## if invabsx2 is False, use the standard inversion
                x2weight = np.apply_along_axis(invert_x2, 1,
                                           self.gen_rchi2[self.curr_gen,:].reshape(-1,1))
                self.gen_fitness[self.curr_gen, :] = x2weight.flatten()
            else: ## else use the absolute value so the X^2 converges to 1 (may be helpful in data with high error)
                x2weight = np.apply_along_axis(invert_absx2, 1,
                                               self.gen_rchi2[self.curr_gen,:].reshape(-1,1))
                self.gen_fitness[self.curr_gen, :] = x2weight.flatten()
        
        elif self.method == "rank":
            self.gen_fitness[self.curr_gen, :] = self.gen_rchi2[self.curr_gen, :]
        
        elif self.method == "prob_div":
            x2weight = np.apply_along_axis(invert_x2, 1,
                                           self.gen_rchi2[self.curr_gen,:].reshape(-1,1))
            self.gen_fitness[self.curr_gen, :] = x2weight.flatten()
            
        elif self.method == "rank_div":
            self.gen_fitness[self.curr_gen, :] = self.gen_rchi2[self.curr_gen, :]

        self.time_log['evaluation'] = time.time()-eval_time_start
        
        
    def validate_and_update(self):
        
        """
        validate the fits and choose the best, unique solutions to save?
        ## if the diversity methods are chosen, need to save the best solutions for propagation
        in which case
        """
        validate_time_start = time.time()
        
        valid_solutions = ~np.any(self.gen_paramfit.iloc[2:,:]<1e-6,axis=0)
        unique_ensembles = np.apply_along_axis(unique_arr, 1, self.parents)
        
        vu_indices = np.where(valid_solutions&unique_ensembles)[0]
        vu_parents = self.parents[valid_solutions&unique_ensembles]
        
        vu_aic = self.gen_aic[self.curr_gen, valid_solutions&unique_ensembles]
        vu_chi2 = self.gen_rchi2[self.curr_gen, valid_solutions&unique_ensembles]
        vu_fitness = self.gen_fitness[self.curr_gen, valid_solutions&unique_ensembles]
        
        ## remove duplicate parents
        ### Check sizes to make sure their are valid solutions. If no valid solutions,
        ### race condition met and start a new iteration. 
        unique_sol, unq_solut_ndx  = np.unique(vu_parents, axis=0, return_index=True)
        if len(unq_solut_ndx) == 0.0:
            print('no valid solutions found')

        self.unique_solutions = unique_sol
        self.n_valid_unique_solutions = self.unique_solutions.shape[0]
        
        ## Structure check? 
        
        ##current best valid solutions
        #rel_rchi2 = selfself.cbest_rchi2
        fitmax_index = np.where(vu_fitness[unq_solut_ndx] == vu_fitness[unq_solut_ndx].max())[0]
        vufitmax=unq_solut_ndx[fitmax_index]
        ##{ 'chi2':0,'fitness', 'ensemble':[0]*self.n_gen, 'gen_found':0, 'fit_pars':{}}
        
        if vu_fitness.max() > self.cbest_rchi2['fitness']:
            
            print(f"Fitness updated from {self.cbest_rchi2['fitness']} to {vu_fitness[unq_solut_ndx].max()}")
            
            self.pbest_rchi2 = self.cbest_rchi2
            #self.cbest_aic['aic'] = vu_aic[unq_solut_ndx].min()
            self.cbest_rchi2['chi2'] = vu_chi2[vufitmax]
            self.cbest_rchi2['aic'] = vu_aic[vufitmax]
            self.cbest_rchi2['fitness'] = vu_fitness[vufitmax]
            self.cbest_rchi2['ensemble'] = vu_parents[vufitmax]
            self.cbest_rchi2['gen_found'] = self.curr_gen
            #print(self.gen_paramfit.T[valid_solutions&unique_ensembles].iloc[vufitmax])
            self.cbest_rchi2['fit_pars'] = self.gen_paramfit.T[valid_solutions&unique_ensembles].iloc[vufitmax].to_dict('list')
            ## convert dict entries to floats not lists
            for key in list(self.cbest_rchi2['fit_pars'].keys()):
                self.cbest_rchi2['fit_pars'][key] = self.cbest_rchi2['fit_pars'][key][0]
            self.fitness_saturation = 0
            
        else:
            self.fitness_saturation += 1
            
        ## Update the best over the iteration
        if vu_fitness.max() > self.citbest_rchi2['fitness']:
            
            #print(f"Fitness updated from {self.citbest_rchi2['fitness']['fitness']} to {vu_fitness[unq_solut_ndx].max()}")
            
            #self.cbest_aic['aic'] = vu_aic[unq_solut_ndx].min()
            self.citbest_rchi2['chi2'] = vu_chi2[vufitmax]
            self.citbest_rchi2['aic'] = vu_aic[vufitmax]
            self.citbest_rchi2['fitness'] = vu_fitness[vufitmax]
            self.citbest_rchi2['ensemble'] = vu_parents[vufitmax]
            self.citbest_rchi2['gen_found'] = self.curr_gen
            #print(self.gen_paramfit.T[valid_solutions&unique_ensembles].iloc[vufitmax])
            self.citbest_rchi2['fit_pars'] = self.gen_paramfit.T[valid_solutions&unique_ensembles].iloc[vufitmax].to_dict('list')
            ## convert dict entries to floats not lists
            for key in list(self.cbest_rchi2['fit_pars'].keys()):
                self.citbest_rchi2['fit_pars'][key] = self.citbest_rchi2['fit_pars'][key][0]
            self.itbest_rchi2[self.curr_iter] = self.citbest_rchi2

        self.time_log['validation'] = time.time()-validate_time_start
    
    def choose_parents(self):
        """
        choose parents for the next generation
        """
        parents_time_start = time.time()
        if self.method == "prob": 
            ## check if parents have duplicate indices in the ensemble 
            unique_ensembles = np.apply_along_axis(unique_arr, 1, self.parents)
            weight_ndx = np.arange(0,self.n_ens,1)
            x2weight = self.gen_fitness[self.curr_gen,:]
            
            if np.any(~unique_ensembles):
                #print("parent is non unique: removing them from the list ")
                nonunq_ensembles = np.where(~unique_ensembles)[0]
                weight_ndx = np.delete(weight_ndx, nonunq_ensembles)
                x2weight = np.delete(x2weight, nonunq_ensembles)
            
            x2weight_norm = x2weight/x2weight.sum()
            
            if self.elitism:
                max_fitness_parent = np.where(x2weight==x2weight.max())[0]
                self.elite_child = weight_ndx[max_fitness_parent[0]] ## saving the index of the top fitness  
                        
            parent_indices = np.random.choice(weight_ndx,
                                              self.n_ens,
                                              p=x2weight_norm)
            
            parents_check = self.parents[parent_indices]
            #unq_func = lambda arr: (np.unique(arr).shape[0] == arr.shape[0])
            unique_ensembles = np.apply_along_axis(unique_arr, 1, parents_check)
            if np.any(~unique_ensembles):
                #print(parents_check)
                nonunq_ensembles = np.where(~unique_ensembles)[0]
                #print("parent is non unique")
                print(parents_check[nonunq_ensembles])
                
                #for nq_ndx in nonunq_ensembles:
                
            
            self.parent_pairs = self.parents[parent_indices.reshape(-1,2)] 
        
        self.time_log['parents'] = time.time() -  parents_time_start
        
        #elif self.method == "rank":
            #sort_index = 
            #rank_choose = 
        #elif self.method == "rank-div":
        #    pass
        
        ## check to make sure the ensemble is unique, i.e there are no duplicates pairings
        
    
    def crossover(self):
        
        """
        crossover the parent indices for the next generation
        Always do the cross over i.e. [A,B],[C,D] ==> [A,C],[B,D] 
        if ndx is == ens_size children == parents
        """
        crossover_time_start = time.time()
        
        copy_parent_pairs = self.parent_pairs
        for pnumb, ens_pair in enumerate(self.parent_pairs):
            co_ndx = 0
            for pi in range(self.ens_size):
                rcheck = np.random.rand()
                #print(pi,rcheck)
                if rcheck > self.p_crossover:
                    co_ndx=pi
                    break;
                else:
                    continue
            ndx_check = (pi==(self.ens_size-1))
            co_check = (co_ndx==0)
            if ndx_check and co_check:
                ## if each index fails the check to cross over, parents become children i.e. no crossover
                ## continue onto the next set of parents 
                continue
            #print(ens_pair)
            parent1_copy = ens_pair[0]
            parent2_copy = ens_pair[1]
            #print(parent1_copy, parent2_copy)
            psel1 = parent1_copy[co_ndx+1:]
            psel2 = parent2_copy[:-(co_ndx+1)]
            
            parent1_copy[co_ndx+1:]=psel2
            parent2_copy[:-(co_ndx+1)]=psel1
            
            ### checks to see if the new parents are unique, i.e. each element in the array is singular
            p1_check = ((np.unique(parent1_copy).shape[0] != parent1_copy.shape[0]))
            p2_check = ((np.unique(parent2_copy).shape[0] != parent2_copy.shape[0]))
            
            ## if either p1_check or p2_check is true: continue on
            ## count the checks if a certain amount of checks fail for this generation,
            ## pool is either saturated or a optimal set of conformations has been found
            ## else crossover
            if p1_check or p2_check:
                print("crossed parents are not unique: continuing")
                continue
            else:
                ## crossover
                copy_parent_pairs[pnumb]= [parent1_copy, parent2_copy]
        
        ## after all crossovers are done, children are created. 
        self.children = copy_parent_pairs.reshape(-1,self.ens_size)
        self.time_log['crossover'] = time.time() - crossover_time_start
    
    def mutation(self):
        """
        mutate the children after crossover
        """

        mutate_time_start = time.time()
        
        children_copy = self.children
        for nch, child in enumerate(self.children):
            
            for elem, chindx in enumerate(child):
                mut_check = np.random.rand()
            
                if mut_check <= self.p_mutate:
                    
                    child_copy = child
                    child_copy[elem] = np.random.choice(self.mut_indices.shape[0],1)[0]
                    child_check = ((np.unique(child_copy).shape[0]) != child.shape[0])
                    if child_check:
                        print("child is not unique: continuing")
                        continue
                    else:
                        children_copy[nch] = child_copy
                        continue ## only one mutation per child
                    
        self.children=children_copy

        self.time_log['mutation'] = time.time() - mutate_time_start
        
    
    def check_genconvergence(self, citer):
        
        ## check 1: maximal generations 
        if self.curr_gen == self.n_gen:
            print("Reached the maximal number of generations: Moving On to the next Iteration")
            self.gen_converged = True
            return None
        
        
        ## check 2:
        if (not self.elitism):
            nconverge = 100 
        else:
            ## give more chances for the elitist function to be exchanged
            nconverge = self.n_gen/2.0
            
        #if self.fitness_saturation>nconverge:
        #    print(f"The fitness function has had the same value,{self.cbest_rchi2['fitness']}, over {nconverge} times.")
        #    print(f"Generation has most likely converged to a set ensemble. Moving onto iteration{citer+1}")
        #    self.gen_converged = True
            
        #    return None
        pass
        ## check 3: ## 
        
            
    def check_iterconvergence(self):
        pass
        
    def wipe_generation(self):
        pass
    
    def evolve(self, dask_client):
        
        ##evaluate the 
        self.curr_iter = 0
        for it in np.arange(0, self.n_iter, 1):
            
            self.curr_iter = it
            self.citbest_rchi2 = {'chi2':0, 'aic':0, 'fitness':0, 'ensemble':[0]*self.n_gen, 'gen_found':0, 'fit_pars':{}}
            ## initialize the parents and mutation indices
            rcols = self.randomcol_indices()
            self.parents = self.indices[rcols] ## parents, evovling 
            
            ## How to check if the 
            check_indices = [not (m in self.parents.flatten()) for m in self.indices]
            self.mut_indices = self.indices
            
            self.curr_gen=0
            
            while (not self.gen_converged):
                
            #for cg in np.arange(0,self.n_gen,1):
                ## update parents from the children of the previous generation
                ## children become parents in the end
                if self.curr_gen>0:
                    self.parents = self.children
                
                print(f"Current Generation: {self.curr_gen}")
                ## evaluate parents
                self.evaluate(dask_client)
                self.validate_and_update()
                
                ## choose parents 
                self.choose_parents()
                
                ## make children
                self.crossover()
                self.mutation()
                
                ## check convergence if not reached
                self.curr_gen+=1
                self.check_genconvergence(it)
                self.time_log['fitness_ave'] = self.individual_fitness_time.mean()
                
                
            ## clean up and save the best fits and ensembles for the generation, before moving on 
            #self.validate_and_update()
            self.gen_converged = False
            
    def evaluate_bestfit(self):
        bestpars = gen_modelparams(self.ens_size, self.cbest_rchi2['fit_pars'])
        best_model = _residual_lmf(bestpars,
                                        self.data[self.cbest_rchi2['ensemble'][0]].values.T)
        return best_model 
    
    def _write_bestmodel(self, foutname: Path = Path('./'), err=True):
        #print(self.data.index.values.shape, self.evaluate_bestfit().shape)
        bmdf = pd.DataFrame(columns=['q', 'intensity'],
                             data=np.vstack([self.data.index.values, self.evaluate_bestfit()]).T
                            )
        if err:
            bmdf['error'] = bmdf['intensity']*0.04

        bmdf.to_csv(f'{foutname}/best_model_EnsmebleSize{self.ens_size}.csv', float_format='%E', sep=' ', index=None, columns=None)

        return None
    
    def _write_parameterfile(self, pfile_name, pfile_path: Path = Path('./')):
        """
        Write out the best fits for the all the iterations of the genetic algorithm in order of chi^2
        Required parameters to save:
        Fit parameters to regenerate best models
        quality of fit: chi^2 , aic
        pdbname associated with the fits
        Useful information:
        

        """

        return None


def _read_json_input():
    """
    Function to read a json file for the inputs of the genetic algorithm
    Should include 
    """
    pass 

def _read_SANSFiles(local_dir, fname_regex):
    """
    Read in the sans files 
    This may be part of the GA object soon? Why have 
    """
    sans_files = Path(f'{path2sans}/{local_dir}').glob(f'{fname_regex}')
    
    sans_files_names = pd.Series(sans_files).astype(str).str.split('/', expand=True).iloc[:,-1]

    scatteringdf = pd.DataFrame(index=np.linspace(0.0,0.5,501),
                                          columns=sans_files_names.index)
    
    for nn, file in sans_files_names.items():
    
        sansdf = pd.read_csv(f'{path2sans}/{local_dir}/{file}', delim_whitespace=True,
                                usecols=[0,1], skiprows=6, header=None, names=['q','I'])
        scatteringdf.loc[:,nn] = sansdf['I'].values
    
    return scatteringdf


if __name__=="__main__":

    path2sans = Path('/Users/9cq/Documents/Projects/Bilbo-MD_SANS/For_Sharique')
    exp_etfoxidized = pd.read_csv(f'{path2sans}/For_Alan/SANS-etf-oxidized.fit', delim_whitespace=True, header=None, skiprows=1,
                             names=['Q','I(Q)','Error','dq'])
    exp_etfoxidized_rebinned = pd.read_csv(f'{path2sans}/SANS_ETF_OXI_rebinned.dat',
                                       delim_whitespace=True, header=None, 
                                         names=['Q','I(Q)','Error'])
    exp_etfoxidized_rebinned['I(Q)'] = exp_etfoxidized_rebinned['I(Q)'] + 0.00013
    exp_etfoxidized_smoothed= pd.read_csv(f'{path2sans}/smoothed_ETF_OXI_3mgL.dat',
                                       delim_whitespace=True, header=None, 
                                         names=['Q','I(Q)','Error'])
    exp_etfoxidized_smoothed['I(Q)'] = exp_etfoxidized_smoothed['I(Q)'] + 0.00013


    ## Changed to local path or like MultiFOXS a txt file of paths to scattering intensities
    ## 
    
    ensemble_scatteringdf = _read_SANSFiles('fit', '*_nofad_EXHModel.dat')

    exp_qmax_ndx = np.where(exp_etfoxidized['Q']<0.35)[0][-1]
    GA2_HDX = GAEnsembleOpt(ensemble_scatteringdf,
                            exp_etfoxidized_smoothed.iloc[1:exp_qmax_ndx],
                            ens_size=2, n_gen=1, n_iter=1, ens_split=1.0,
                            mut_prob=0.1,elitism=False, invabsx2=True, parallel=True,
                            )
    with distributed.LocalCluster(n_workers=int(0.4*os.cpu_count()),
                              processes=True,
                              threads_per_worker=1,
                             ) as cluster, distributed.Client(cluster) as client:
        GA2_HDX.evolve(dask_client=client)
    print(GA2_HDX.time_log)
    print(GA2_HDX.cbest_rchi2)
    GA2_HDX._write_bestmodel()

