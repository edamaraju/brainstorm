#!/usr/bin/env python
# coding=utf-8
from __future__ import division, print_function, unicode_literals
from datetime import datetime
import math
import numpy as np
import sys
from brainstorm.randomness import Seedable
from brainstorm.utils import IteratorValidationError

def progress_bar(maximum, prefix='[',
                 bar='====1====2====3====4====5====6====7====8====9====0',
                 suffix='] Took: {0}\n'):
    i = 0
    start_time = datetime.utcnow()
    out = prefix
    while i < len(bar):
        progress = yield out
        j = math.trunc(progress / maximum * len(bar))
        out = bar[i: j]
        i = j
    elapsed_str = str(datetime.utcnow() - start_time)[: -5]
    yield out + suffix.format(elapsed_str)


def silence():
    while True:
        _ = yield ''


class DataIterator(object):

    def __init__(self, data_names):
        self.data_names = data_names

    def __call__(self, handler, verbose=False):
        pass


class AddGaussianNoise(DataIterator):
    """
    Adds Gaussian noise to data generated by another iterator.

    Supports usage of different means and standard deviations for different
    named data items.
    """

    def __init__(self, iter, std_dict, mean_dict=None):
        """
        :param iter: any DataIterator to which noise is to be added
        :param std_dict: specifies the standard deviation of noise added to
        each named data item
        :param mean_dict: specifies the mean of noise added to each named
        data item
        """
        super(AddGaussianNoise, self).__init__(iter.data_names)
        if mean_dict is not None:
            assert set(mean_dict.keys()) == set(std_dict.keys()), \
                "means and standard deviations must be provided for " \
                "the same data names"
        for key in std_dict.keys():
            assert key in iter.data.keys(), "key {} is not present in " \
                                            "iterator. Available keys: {" \
                                            "}".format(key, iter.data.keys())
        self.mean_dict = {} if mean_dict is None else mean_dict
        self.std_dict = std_dict
        self.iter = iter

    def __call__(self, handler, verbose=False):
        for data in self.iter(handler, verbose=verbose):
            for key in self.std_dict.keys():
                noise = handler.zeros(data[key].shape)
                mean = self.mean_dict.get(key, 0.0)
                std = self.std_dict.get(key)
                handler.fill_gaussian(mean=mean, std=std, out=noise)
                handler.add_tt(data[key], noise, out=noise)
                data[key] = noise
            yield data


class Undivided(DataIterator):
    """
    Processes the data in one block (only one iteration).
    """

    def __init__(self, **named_data):
        """
        :param named_data: named arrays with 3+ dimensions ('T', 'B', ...)
        :type named_data: dict[str, ndarray]
        """
        super(Undivided, self).__init__(named_data.keys())
        _ = _assert_correct_data_format(named_data)
        self.data = named_data
        self.total_size = int(sum(d.size for d in self.data.values()))

    def __call__(self, handler, verbose=False):
        yield self.data


class Online(DataIterator, Seedable):
    """
    Online (one sample at a time) iterator for inputs and targets.
    """

    def __init__(self, shuffle=True, verbose=None, seed=None, **named_data):
        Seedable.__init__(self, seed=seed)
        DataIterator.__init__(self, named_data.keys())
        self.nr_sequences = _assert_correct_data_format(named_data)
        self.data = named_data
        self.shuffle = shuffle
        self.verbose = verbose
        self.sample_size = int(sum(d.shape[0] * np.prod(d.shape[2:])
                                   for d in self.data.values()))

    def __call__(self, handler, verbose=False):
        if (self.verbose is None and verbose) or self.verbose:
            p_bar = progress_bar(self.nr_sequences)
        else:
            p_bar = silence()

        print(next(p_bar), end='')
        sys.stdout.flush()
        indices = np.arange(self.nr_sequences)
        if self.shuffle:
            self.rnd.shuffle(indices)
        for i, idx in enumerate(indices):
            data = {k: v[:, idx: idx + 1]
                    for k, v in self.data.items()}
            yield data
            print(p_bar.send(i + 1), end='')
            sys.stdout.flush()


class Minibatches(DataIterator, Seedable):
    """
    Minibatch iterator for inputs and targets.

    Only randomizes the order of minibatches, doesn't shuffle between
    minibatches.
    """

    def __init__(self, batch_size=10, shuffle=True, verbose=None,
                 seed=None, **named_data):
        Seedable.__init__(self, seed=seed)
        DataIterator.__init__(self, named_data.keys())
        self.nr_sequences = _assert_correct_data_format(named_data)
        self.data = named_data
        self.shuffle = shuffle
        self.verbose = verbose
        self.batch_size = batch_size
        self.sample_size = int(sum(d.shape[0] * np.prod(d.shape[2:]) * batch_size
                                   for d in self.data.values()))

    def __call__(self, handler, verbose=False):
        if (self.verbose is None and verbose) or self.verbose:
            p_bar = progress_bar(self.nr_sequences)
        else:
            p_bar = silence()

        print(next(p_bar), end='')
        sys.stdout.flush()
        indices = np.arange(
            int(math.ceil(self.nr_sequences / self.batch_size)))
        if self.shuffle:
            self.rnd.shuffle(indices)
        for i, idx in enumerate(indices):
            chunk = (slice(None),
                     slice(idx * self.batch_size, (idx + 1) * self.batch_size))

            data = {k: v[chunk] for k, v in self.data.items()}
            yield data
            print(p_bar.send((i + 1) * self.batch_size), end='')
            sys.stdout.flush()


def _assert_correct_data_format(named_data):
    nr_sequences = {}
    for name, data in named_data.items():
        if not hasattr(data, 'shape'):
            raise IteratorValidationError(
                "{} has a wrong type. (no shape attribute)".format(name)
            )
        if len(data.shape) < 3:
            raise IteratorValidationError(
                'All inputs have to have at least 3 dimensions, where the '
                'first two are time_size and batch_size.')
        nr_sequences[name] = data.shape[1]

    if min(nr_sequences.values()) != max(nr_sequences.values()):
        raise IteratorValidationError(
            'The number of sequences of all inputs must be equal, but got {}'
                .format(nr_sequences))

    return min(nr_sequences.values())
