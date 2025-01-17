"""
Sampling strategies for training
"""
import copy
import torch
import random
import numpy as np 
from collections import defaultdict
from abc import ABC, abstractmethod

from kgpy import utils


class Sampler(ABC):
    """
    Abstract base class for implementing samplers
    """
    def __init__(self, triplets, batch_size, num_ents, device, inverse):
        self.bs = batch_size
        self.triplets = triplets
        self.num_ents = num_ents
        self.inverse = inverse
        self.device = device

        self._build_index()
        self.keys = list(self.index.keys())


    def __iter__(self):
        """
        Number of samples so far in epoch
        """
        self.trip_iter = 0
        return self
    

    def reset(self):
        """
        Reset iter to 0 at beginning of epoch
        """
        self.trip_iter = 0
        self._shuffle()

        return self


    @abstractmethod
    def _shuffle(self):
        """
        Shuffle training samples
        """
        pass


    @abstractmethod
    def _increment_iter(self):
        """
        Increment the iterator by batch size. Constrain to be len(_) at max
        """
        pass

    
    def _build_index(self):
        """
        Create self.index mapping.

        self.index contains 2 types of mappings:
            - All possible head entities for statement (_, relation, tail)
            - All possible tail entities for statement (head, relation, _)
        
        These are stored in self.index in form of:
            - For head mapping -> ("head", relation, tail)
            - For tail mapping -> ("tail", relation, head)
        
        The value for each key is a list of possible entities (e.g. [1, 67, 32]) 
        
        Returns:
        --------
        None
        """
        self.index = defaultdict(list)

        for t in self.triplets:
            if self.inverse:
                self.index[(t[1], t[0])].append(t[2])
            else:
                self.index[("head", t[1], t[2])].append(t[0])
                self.index[("tail", t[1], t[0])].append(t[2])

        # Remove duplicates
        for k, v in self.index.items():
            self.index[k] = list(set(v))


    def _get_labels(self, samples):
        """
        Get the label arrays for the corresponding batch of samples

        Parameters:
        -----------
            samples: Tensor
                2D Tensor of batches

        Returns:
        --------
        Tensor
            Size of (samples, num_ents). 
            Entry = 1 when possible head/tail else 0
        """
        y = torch.zeros(samples.shape[0], self.num_ents, dtype=torch.float16, device=self.device)

        for i, x in enumerate(samples):
            lbls = self.index[tuple(x)]
            y[i, lbls] = 1

        return y



#################################################################################
#
# Different Samplers
#
#################################################################################


class One_to_K(Sampler):
    """
    Standard sampler that produces k corrupted samples for each training sample.

    Does so by randomly corupting either the head or the tail of the sample

    Parameters:
    -----------
        triplets: list
            List of triplets. Each entry is a tuple of form (head, relation, tail)
        batch_size: int
            Train batch size
        num_ents: int
            Total number of entities in dataset
        num_negative: int
            Number of corrupted samples to produce per training procedure
    """
    def __init__(self, triplets, batch_size, num_ents, device, num_negative=1, inverse=False):
        super(One_to_K, self).__init__(triplets, batch_size, num_ents, device, inverse)

        self.num_negative = num_negative        
        self._shuffle()


    def __len__(self):
        """
        Total Number of batches
        """
        return len(self.triplets) // self.bs


    def _increment_iter(self):
        """
        Increment the iterator by batch size. Constrain to be len(keys) at max
        """
        self.trip_iter = min(self.trip_iter + self.bs, len(self.triplets))


    def _shuffle(self):
        """
        Shuffle samples
        """
        np.random.shuffle(self.triplets)

    
    def _sample_negative(self, samples):
        """
        Samples `self.num_negative` triplets for each training sample in batch

        Do so by randomly replacing either the head or the tail with another entitiy

        Parameters:
        -----------
            samples: list 
                triplets to corrupt 

        Returns:
        --------
        list
            Corrupted Triplets
        """
        corrupted_triplets = []

        for _ in range(self.num_negative):
            for i, t in enumerate(samples):
            
                new_triplet = copy.deepcopy(t)
                head_tail = random.choice([0, 2])
                new_triplet[head_tail] = utils.randint_exclude(0, self.num_ents, t[head_tail])
                
                corrupted_triplets.append(new_triplet)

        corrupted_triplets = torch.stack(corrupted_triplets, dim=0).to(self.device).long()

        # TODO: This makes sense for margin loss but for BCE there is no need to have a comparison for each sample
        # samples = samples.repeat(self.num_negative, 1)

        return corrupted_triplets


    def __next__(self):
        """
        Grab next batch of samples

        Returns:
        -------
        tuple (list, list)
            triplets in batch, corrupted samples for batch
        """
        if self.trip_iter >= len(self.triplets)-1:
            raise StopIteration

        # Collect next self.bs samples & labels
        batch_samples = self.triplets[self.trip_iter: min(self.trip_iter + self.bs, len(self.triplets))]
        batch_samples = torch.Tensor([list(x) for x in batch_samples]).to(self.device).long()
        neg_samples   = self._sample_negative(batch_samples)   
        
        self._increment_iter()

        return batch_samples, neg_samples



class One_to_N(Sampler):
    """
    For each of (?, r, t) and (h, r, ?) we sample each possible ent

    Parameters:
    -----------
        triplets: list
            List of triplets. Each entry is a tuple of form (head, relation, tail)
        batch_size: int
            Train batch size
        num_ents: int
            Total number of entities in dataset
    """
    def __init__(self, triplets, batch_size, num_ents, device, inverse=False):
        super(One_to_N, self).__init__(triplets, batch_size, num_ents, device, inverse)
        self._shuffle()


    def __len__(self):
        return len(self.index) // self.bs


    def _increment_iter(self):
        """
        Increment the iterator by batch size. Constrain to be len(keys) at max
        """
        self.trip_iter = min(self.trip_iter + self.bs, len(self.keys))


    def _shuffle(self):
        """
        Shuffle keys for both indices
        """
        np.random.shuffle(self.keys)


    def __next__(self):
        """
        Grab next batch of samples

        Returns:
        -------
        tuple
            indices, lbls, trip type - head/tail (optional)
        """
        if self.trip_iter >= len(self.keys)-1:
            raise StopIteration

        # Collect next self.bs samples
        batch_samples = self.keys[self.trip_iter: min(self.trip_iter + self.bs, len(self.keys))]
        batch_samples = np.array([list(x) for x in batch_samples])

        self._increment_iter()

        if self.inverse:
            # batch_ix  = torch.Tensor(batch_samples.astype(np.float)).to(self.device).long()
            batch_ix  = torch.Tensor(batch_samples).to(self.device).long()
            batch_lbls = self._get_labels(batch_samples)

            return batch_ix, batch_lbls 
        else:
            # Split by type of trip and ent/rel indices
            trip_type = batch_samples[:, 0]
            batch_ix  = torch.Tensor(batch_samples[:, 1:].astype(np.float)).to(self.device).long()
            batch_lbls = self._get_labels(batch_samples)  

            return batch_ix, batch_lbls, trip_type

