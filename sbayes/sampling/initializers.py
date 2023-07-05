import logging
from collections import defaultdict
import random

import numpy as np
from numpy.typing import NDArray

from sbayes.load_data import Data
from sbayes.model import Model, update_weights
from sbayes.sampling.conditionals import sample_source_from_prior
from sbayes.sampling.counts import recalculate_feature_counts
from sbayes.sampling.operators import ObjectSelector, GibbsSampleSource
from sbayes.sampling.state import Sample
from sbayes.util import get_neighbours, normalize

USE_SKLEARN = False
if USE_SKLEARN:
    from sklearn.cluster import DBSCAN, KMeans
else:
    DBSCAN = KMeans = None


class SbayesInitializer:

    def __init__(
        self,
        model: Model,
        data: Data,
        initial_size: int,
        logger: logging.Logger = None,
    ):
        self.model = model
        self.data = data

        # Data
        self.features = data.features.values
        self.applicable_states = data.features.states
        self.n_states_by_feature = np.sum(data.features.states, axis=-1)
        self.n_features = self.features.shape[1]
        self.n_states = self.features.shape[2]
        self.n_sites = self.features.shape[0]

        # Locations and network
        self.adj_mat = data.network.adj_mat

        # Clustering
        self.n_clusters = model.n_clusters
        self.min_size = model.min_size
        self.max_size = model.max_size
        self.initial_size = initial_size

        # Confounders and sources
        self.confounders = model.confounders
        self.n_sources = 1 + len(self.confounders)
        self.n_groups = self.get_groups_per_confounder()

        if logger is None:
            import logging
            self.logger = logging.getLogger()
        else:
            self.logger = logger

    def get_groups_per_confounder(self):
        n_groups = dict()
        for k, v in self.confounders.items():
            n_groups[k] = v.n_groups
        return n_groups

    def generate_sample(self, c: int = 0) -> Sample:
        """Generate initial Sample object (clusters, weights, cluster_effect, confounding_effects)
        Kwargs:
            c: index of the MCMC chain
        Returns:
            The generated initial Sample
        """

        # Clusters
        initial_clusters = self.generate_initial_clusters(c)

        # Weights
        initial_weights = self.generate_initial_weights()

        # Confounding effects
        initial_confounding_effects = dict()
        for conf_name in self.confounders:
            initial_confounding_effects[conf_name] = self.generate_initial_confounding_effect(conf_name)

        if self.model.sample_source:
            initial_source = np.empty((self.n_sites, self.n_features, self.n_sources), dtype=bool)
        else:
            initial_source = None

        sample = Sample.from_numpy_arrays(
            clusters=initial_clusters,
            weights=initial_weights,
            confounding_effects=initial_confounding_effects,
            confounders=self.data.confounders,
            source=initial_source,
            feature_counts={'clusters': np.zeros((self.n_clusters, self.n_features, self.n_states)),
                            **{conf: np.zeros((n_groups, self.n_features, self.n_states))
                               for conf, n_groups in self.n_groups.items()}},
            chain=c,
        )

        assert ~np.any(np.isnan(initial_weights)), initial_weights

        # Generate the initial source using a Gibbs sampling step
        sample.everything_changed()

        source = sample_source_from_prior(sample)
        source[self.data.features.na_values] = 0
        sample.source.set_value(source)
        recalculate_feature_counts(self.features, sample)

        w = update_weights(sample, caching=False)
        s = sample.source.value
        assert np.all(s <= (w > 0)), np.max(w)

        full_source_operator = GibbsSampleSource(
            weight=1,
            model_by_chain=defaultdict(lambda: self.model),
            sample_from_prior=False,
            object_selector=ObjectSelector.ALL,
        )
        source = full_source_operator.function(sample)[0].source.value
        sample.source.set_value(source)
        recalculate_feature_counts(self.features, sample)

        sample.everything_changed()
        return sample

    class ClusterError(Exception):
        pass

    def generate_initial_clusters(self, c : int = 0):
        return self.grow_random_clusters()
        # return self.generate_kmeans_clusters()

    # def generate_kmeans_clusters(self):
    #     features = self.data.features.values.shape
    #     n_objects, n_features, n_states = features
    #
    #     k = self.n_clusters
    #     kmeans = KMeans(n_clusters=k)
    #     kmeans.fit(self.data.features.values.reshape(n_objects, n_features*n_states))
    #     centroids = kmeans.cluster_centers_
    #     p = centroids.reshape((k, n_features, n_states))
    #     print(p)
    #     exit()

    def generate_dbscan_clusters(self):
        return

    def grow_random_clusters(self) -> NDArray[bool]:  # (n_clusters, n_sites)
        """Generate initial clusters by growing through random grow-steps up to self.min_size."""

        # If there are no clusters in the model, return empty matrix
        if self.n_clusters == 0:
            return np.zeros((self.n_clusters, self.n_sites), bool)

        occupied = np.zeros(self.n_sites, bool)
        initial_clusters = np.zeros((self.n_clusters, self.n_sites), bool)

        # A: Grow the remaining clusters
        # With many clusters new ones can get stuck due to unfavourable seeds.
        # We perform several attempts to initialize the clusters.
        attempts = 0
        max_attempts = 1000
        n_initialized = 0

        while True:
            for i in range(n_initialized, self.n_clusters):
                try:
                    initial_size = self.initial_size
                    cl, in_cl = self.grow_cluster_of_size_k(k=initial_size, already_in_cluster=occupied)

                except self.ClusterError:
                    # Rerun: Error might be due to an unfavourable seed
                    if attempts < max_attempts:
                        attempts += 1
                        if attempts % 10 == 0 and self.initial_size > 3:
                            self.initial_size -= 1
                            self.logger.warning(f"Reduced 'initial_size' to {self.initial_size} after "
                                                f"{attempts} unsuccessful initialization attempts.")
                        break
                    # Seems there is not enough sites to grow n_clusters of size k
                    else:
                        raise ValueError(f"Failed to add additional cluster. Try fewer clusters "
                                         f"or set initial_sample to None.")

                initial_clusters[i, :] = cl
                # n_initialized += 1
            else:  # No break -> no cluster exception
                return initial_clusters

    def grow_cluster_of_size_k(self, k, already_in_cluster=None):
        """ This function grows a cluster of size k excluding any of the sites in <already_in_cluster>.
        Args:
            k (int): The size of the cluster, i.e. the number of sites in the cluster
            already_in_cluster (np.array): All sites already assigned to a cluster (boolean)

        Returns:
            np.array: The newly grown cluster (boolean).
            np.array: all sites already assigned to a cluster (boolean).

        """
        if already_in_cluster is None:
            already_in_cluster = np.zeros(self.n_sites, bool)

        # Initialize the cluster
        cluster = np.zeros(self.n_sites, bool)

        # Find all sites that are occupied by a cluster and those that are still free
        sites_occupied = np.nonzero(already_in_cluster)[0]
        sites_free = list(set(range(self.n_sites)) - set(sites_occupied))

        # Take a random free site and use it as seed for the new cluster
        try:
            i = random.sample(sites_free, 1)[0]
            cluster[i] = already_in_cluster[i] = 1
        except ValueError:
            raise self.ClusterError

        # Grow the cluster if possible
        for _ in range(k - 1):
            neighbours = get_neighbours(cluster, already_in_cluster, self.adj_mat)
            if not np.any(neighbours):
                raise self.ClusterError

            # Add a neighbour to the cluster
            site_new = random.choice(list(neighbours.nonzero()[0]))
            cluster[site_new] = already_in_cluster[site_new] = 1

        return cluster, already_in_cluster

    def generate_initial_weights(self):
        """This function generates initial weights for the Bayesian additive mixture model, either by
        A) proposing them (randomly) from scratch
        B) using the last sample of a previous run of the MCMC
        Weights are in log-space and not normalized.

        Returns:
            np.array: weights for cluster_effect and each of the i confounding_effects
        """
        return normalize(np.ones((self.n_features, self.n_sources)))

    def generate_initial_confounding_effect(self, conf: str):
        """This function generates initial state probabilities for each group in confounding effect [i], either by
        A) using the MLE
        B) using the last sample of a previous run of the MCMC
        Probabilities are in log-space and not normalized.
        Args:
            conf: The confounding effect [i]
        Returns:
            np.array: probabilities for states in each group of confounding effect [i]
                shape (n_groups, n_features, max(n_states))
        """

        n_groups = self.n_groups[conf]
        groups = self.confounders[conf].group_assignment

        initial_confounding_effect = np.zeros((n_groups, self.n_features, self.features.shape[2]))

        for g in range(n_groups):

            idx = groups[g].nonzero()[0]
            features_group = self.features[idx, :, :]

            sites_per_state = np.nansum(features_group, axis=0)

            # Compute the MLE for each state and each group in the confounding effect
            # Some groups have only NAs for some features, resulting in a non-defined MLE
            # other groups have only a single state, resulting in an MLE including 1.
            # To avoid both, we add 1 to all applicable states of each feature,
            # which gives a well-defined initial confounding effect, slightly nudged away from the MLE

            sites_per_state[np.isnan(sites_per_state)] = 0
            sites_per_state[self.applicable_states] += 1

            state_sums = np.sum(sites_per_state, axis=1)
            p_group = sites_per_state / state_sums[:, np.newaxis]
            initial_confounding_effect[g, :, :] = p_group

        return initial_confounding_effect


# Cluster initialization functions


def grow_random_cluster(data: Data, ) -> NDArray:
    ...
