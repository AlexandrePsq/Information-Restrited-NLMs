# -*- coding: utf-8 -*-
"""
General framework regrouping various methods to perform transformations of the data.
===================================================
A Transformer instanciation requires:
    - tr: int, it is the repetition time of the fMRI image acquisition,
    - nscans: dict regrouping the number of scans for each run,
    - indexes: list of numpy arrays specifying the columns indexes for each model,
    - offset_type_dict: dict of list regrouping the offset type for each run (dict keys) and each model (in a list),
    - duration_type_dict: dict of list regrouping the duration type for each run (dict keys) and each model (in a list),
    - offset_path: string,
    - duration_path: string,
    - language: string,
    - hrf: string specifying the kind of hemodynamic response function to use to create the regressors that wil 
    be fitted to fMRI data,
    - oversampling: int, oversampling of the signal before convolution,
    - with_mean: bool specifying if we remove the mean from the data,
    - with_std: bool specifying if we divide by the standard deviation the data.

This class enables to perform a lots of transformations on a given dataset:
    - from loading and preprocessing with the process_* functions
    - to classical functions like standardization,
    - or more complex ones like make_regressor.

"""



import os
import numpy as np
import pandas as pd
from numpy import linalg as la

from sklearn.preprocessing import StandardScaler
from nistats.hemodynamic_models import compute_regressor

from utils import fetch_offsets, fetch_duration, filter_args



class Transformer(object):
    """ Perform general transformations over a set of dataframes or arrays,
    taking into account group structures.
    """
    
    
    def __init__(
        self, 
        tr, 
        nscans, 
        indexes,
        scaling_types,
        centering,
        scaling_axis,
        order,
        offset_type_dict,
        duration_type_dict, 
        offset_path, 
        duration_path, 
        language, 
        temporal_shifting,
        hrf='spm', 
        oversampling=10, 
        with_mean=True, 
        with_std=True
        ):
        """ Instanciation of Transformer class.
        Arguments:
            - tr: int
            - nscans: dict (of int)
            - indexes: list (of np.array)
            - offset_type_dict: dict (of list)
            - duration_type_dict: dict (of list)
            - offset_path: str
            - duration_path: str
            - language: str
            - hrf: str
            - oversampling: int
            - with_mean: bool
            - with_std: bool
        """
        self.tr = tr
        self.nscans = nscans
        self.hrf = hrf
        self.oversampling = oversampling
        self.with_mean=with_mean
        self.with_std=with_std
        self.indexes = indexes
        self.offset_type_dict = offset_type_dict
        self.duration_type_dict = duration_type_dict
        self.offset_path = offset_path
        self.duration_path = duration_path
        self.language = language
        self.scaling_types = scaling_types
        self.centering = centering
        self.scaling_axis = scaling_axis
        self.order = [eval(str(item)) if (item!='std' and item is not None) else item for item in order]
        self.bucket = []
        self.temporal_shifting = temporal_shifting
        
    def clean_bucket(self):
        """ Clean instance bucket."""
        self.bucket = []
    
    def scale(self, X_train, X_test):
        """ Scale the data with specific scaling function
        for the different representations coming from different models.
        Arguments:
            - X_train: list
            - X_test: list
        """
        for index, indexes in enumerate(self.indexes):
            func = getattr(self, self.scaling_types[index])
            X_train_ = [X[:,indexes] for X in X_train]
            X_test_ = [X[:,indexes] for X in X_test]
            self.bucket.append(func(**filter_args(func, {
                'X_train': X_train_,
                'X_test': X_test_,
                'centering': self.centering[index],
                'order': self.order[index],
                'scaling_axis': self.scaling_axis
            })))
        
        X_train = [pd.concat([pd.DataFrame(data['X_train'][run_index]) for data in self.bucket], axis=1).values for run_index in range(len(self.bucket[0]['X_train']))]
        X_test = [pd.concat([pd.DataFrame(data['X_test'][run_index]) for data in self.bucket], axis=1).values for run_index in range(len(self.bucket[0]['X_test']))]
        self.clean_bucket()
        return {'X_train': X_train, 'X_test': X_test}
    
    def standardize(self, X_train, X_test):
        """Standardize a train and test sets.
        Arguments:
            - X_train: list (of np.array)
            - X_test: list (of np.array)
        Returns:
            - result: dict
        """
        matrices = [*X_train, *X_test] # X_train + X_test
        for index in range(len(matrices)):
            scaler = StandardScaler(with_mean=self.with_mean, with_std=self.with_std)
            scaler.fit(matrices[index])
            matrices[index] = scaler.transform(matrices[index])
        result = {'X_train': matrices[:-len(X_test)], 'X_test': matrices[-len(X_test):]}
        return result

    def identity(self, X_train, X_test, centering=False,):
        """ Identity function.
        Arguments:
            - X_train: list
            - X_test: list
        Returns:
            - result: dict
        """
        matrices = [*X_train, *X_test] # X_train + X_test
        if centering:
            for index in range(len(matrices)):
                scaler = StandardScaler(with_mean=centering, with_std=False)
                scaler.fit(matrices[index])
                matrices[index] = scaler.transform(matrices[index])
        result = {'X_train': matrices[:-len(X_test)], 'X_test': matrices[-len(X_test):]}
        return result

    def normalize(self, X_train, X_test, order, centering=False, scaling_axis=1):
        """ Normalizing function.
        Arguments:
            - X_train: list
            - X_test: list
            - order: order of the norm (None, inf, -inf, 0, 1, -1 ,2, -2, ...)
            - centering: bool (center data)
            - scaling_axis: int (0: column-wise=performs on rows, 1: row-wise=performs on columns)
        Returns:
            - result: dict
        """
        matrices = [*X_train, *X_test] # X_train + X_test
        for index in range(len(matrices)):
            scaler = StandardScaler(with_mean=centering, with_std=False)
            scaler.fit(matrices[index])
            matrices[index] = scaler.transform(matrices[index])
            matrices[index] = matrices[index] / np.mean(la.norm(matrices[index], ord=order, axis=scaling_axis))
        result = {'X_train': matrices[:-len(X_test)], 'X_test': matrices[-len(X_test):]}
        return result
    
    def make_regressor(self, X_train, X_test, run_train, run_test):
        """ Compute the convolution with an hrf for each column of each matrix.
        Arguments:
            - X_train: list (of np.array)
            - X_test: list (of np.array)
            - run_train: list (of int)
            - run_test: list (of int)
        Returns:
            - dict
        """
        matrices_ = [*X_train, *X_test]
        runs = [*run_train, *run_test]
        matrices = [self.compute_regressor(pd.DataFrame(array[:,index]), 
                                            self.offset_type_dict['run{}'.format(runs[array_index] + 1)][i], 
                                            self.duration_type_dict['run{}'.format(runs[array_index] + 1)][i], 
                                            'run{}'.format(runs[array_index] + 1)) for array_index, array in enumerate(matrices_) for i, index in enumerate(self.indexes)]
        step = len(self.indexes)
        matrices = [np.hstack(matrices[x : x + step]) for x in range(0, len(matrices), step)]
        return {'X_train': matrices[:-len(X_test)], 'X_test': matrices[-len(X_test):], 'run_train': run_train, 'run_test': run_test}
    
    def compute_regressor(self, dataframe, offset_type, duration_type, run_index):
        """ Compute the convolution with an hrf for each column of the dataframe.
        Arguments:
            - dataframes: pd.DataFrame
            - offset_type: str
            - duration_type: str
            - run_index: str
        Returns:
            - matrix: np.array
        """
        regressors = []
        dataframe = dataframe.dropna(axis=0)
        representations = [col for col in dataframe.columns]
        offsets = fetch_offsets(offset_type, run_index, self.offset_path, self.language)
        duration = fetch_duration(duration_type, run_index, self.duration_path, default_size=len(dataframe))
        offsets += self.temporal_shifting # shift offsets by 'temporal_shifting' seconds
        for col in representations:
            conditions = np.vstack((offsets, duration, dataframe[col]))
            signal, name = compute_regressor(exp_condition=conditions,
                                    hrf_model=self.hrf,
                                    frame_times=np.arange(0.0, self.nscans[run_index] * self.tr, self.tr),
                                    oversampling=self.oversampling)
            col = str(col)
            regressors.append(pd.DataFrame(signal, columns=[col] + [col + '_' + item for item in name[1:]] ))
        matrix = pd.concat(regressors, axis=1).values
        return matrix
    
    def process_representations(self, representation_paths, models):
        """ Load and concatenate representation dataframes 
        for each run.
        Arguments:
            - representation_paths: list (of list of paths)
            - models: list (of dict)
        Returns:
            - arrays: list of length #runs (np.array of shape: #words * #features) 
        """
        arrays = []
        runs = list(zip(*representation_paths)) # list of 9 tuples (1 for each run), each tuple containing the representations for the specified models
        # e.g.: [(path2run1_model1, path2run1_model2), (path2run2_model1, path2run2_model2)]

        # Computing design-matrices
        for i in range(len(runs)):
            # to modify in case the path leads to .npy file
            merge = pd.concat([pd.read_csv(path2features)[eval(models[index]['columns_to_retrieve'])] for index, path2features in enumerate(runs[i])], axis=1) # concatenate horizontaly the read csv files of a run
            arrays.append(merge.values)
        return arrays
    
    def process_fmri_data(self, fmri_paths, masker, add_noise_to_constant=True):
        """ Load fMRI data and mask it with a given masker.
        Preprocess it to avoid NaN value when using Pearson
        Correlation coefficients in the following analysis.
        Arguments:
            - fmri_paths: list (of string)
            - masker: NiftiMasker object
        Returns:
            - data: list of length #runs (np.array of shape: #scans * #voxels) 
        """
        data = [masker.transform(f) for f in fmri_paths]
        # voxels with activation at zero at each time step generate a nan-value pearson correlation => we add a small variation to the first element
        if add_noise_to_constant:
            for run in range(len(data)):
                zero = np.zeros(data[run].shape[0])
                new = zero.copy()
                new[0] += np.random.random()/1000
                data[run] = np.apply_along_axis(lambda x: x if not np.array_equal(x, zero) else new, 0, data[run])
        return data
