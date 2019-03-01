# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from typing import Optional, List, Dict, Tuple, Deque, Any, Union, Callable
from collections import defaultdict, deque
import numpy as np
from scipy import stats
import cma
from . import base
from . import mutations
from .base import registry
# families of optimizers
# pylint: disable=unused-wildcard-import,wildcard-import, too-many-lines
from .differentialevolution import *
from .oneshot import *
from .recastlib import *


# # # # # optimizers # # # # #


class _OnePlusOne(base.Optimizer):
    """Simple but sometimes powerful optimization algorithm.

    We use the one-fifth adaptation rule, going back to Schumer and Steiglitz (1968).
    It was independently rediscovered by Devroye (1972) and Rechenberg (1973).
    We use asynchronous updates, so that the 1+1 can actually be parallel and even
    performs quite well in such a context - this is naturally close to 1+lambda.
    """

    def __init__(self, dimension: int, budget: Optional[int] = None, num_workers: int = 1) -> None:
        super().__init__(dimension, budget=budget, num_workers=num_workers)
        self._parameters = ParametrizedOnePlusOne()
        self._mutations: Dict[str, Callable[[base.ArrayLike], base.ArrayLike]] = {
            "discrete": mutations.discrete_mutation,
            "fastga": mutations.doerr_discrete_mutation,
            "doublefastga": mutations.doubledoerr_discrete_mutation,
            "portfolio": mutations.portfolio_discrete_mutation}
        self._sigma: float = 1

    def _internal_ask(self) -> base.ArrayLike:
        # pylint: disable=too-many-return-statements, too-many-branches
        noise_handling = self._parameters.noise_handling
        if not self._num_ask:
            return np.zeros(self.dimension)
        # for noisy version
        if noise_handling is not None:
            limit = (.05 if isinstance(noise_handling, str) else noise_handling[1]) * len(self.archive) ** 3
            strategy = noise_handling if isinstance(noise_handling, str) else noise_handling[0]
            if self._num_ask <= limit:
                if strategy in ["cubic", "random"]:
                    idx = np.random.choice(len(self.archive))
                    return np.frombuffer(list(self.archive.bytesdict.keys())[idx])
                elif strategy == "optimistic":
                    return self.current_bests["optimistic"].x
        # crossover
        if self._parameters.crossover and self._num_ask % 2 == 1 and len(self.archive) > 2:
            return mutations.crossover(self.current_bests["pessimistic"].x,
                                       mutations.get_roulette(self.archive, num=2))
        # mutating
        mutation = self._parameters.mutation
        if mutation == "gaussian":  # standard case
            return self.current_bests["pessimistic"].x + self._sigma * np.random.normal(0, 1, self.dimension)
        elif mutation == "cauchy":
            return self.current_bests["pessimistic"].x + self._sigma * np.random.standard_cauchy(self.dimension)
        elif mutation == "crossover":
            if self._num_ask % 2 == 0 or len(self.archive) < 3:
                return mutations.portfolio_discrete_mutation(self.current_bests["pessimistic"].x)
            else:
                return mutations.crossover(self.current_bests["pessimistic"].x,
                                           mutations.get_roulette(self.archive, num=2))
        else:
            return self._mutations[mutation](self.current_bests["pessimistic"].x)

    def _internal_tell(self, x: base.ArrayLike, value: float) -> None:
        # only used for cauchy and gaussian
        self._sigma *= 2. if value <= self.current_bests["pessimistic"].mean else .84


class ParametrizedOnePlusOne(base.ParametrizedFamily):
    """Simple but sometimes powerfull class of optimization algorithm.
    We use asynchronous updates, so that the 1+1 can actually be parallel and even
    performs quite well in such a context - this is naturally close to 1+lambda.

    Parameters
    ----------
    noise_handling: str or Tuple[str, float]
        method for handling the noise. The name can be either "random" (a random point
        is reevaluated regularly) or "optimistic" (the best optimistic point is reevaluated
        regularly, optimism in front of uncertainty). A coefficient can also be provided
        to tune the regularity of these reevaluations (default .05)
    mutation: str
        One of the available mutations from:
        - "gaussian": standard mutation by adding a Gaussian random variable (with progressive
        widening) to the best pessimistic point
        - "cauchy": same as Gaussian but with a Cauchy distribution.
        - "discrete": TODO
        - "fastga": FastGA mutations from the current best
        - "doublefastga": double-FastGA mutations from the current best (Doerr et al, Fast Genetic Algorithms, 2017)
        - "portfolio": Random number of mutated bits (called niform mixing in
           Dang & Lehre "Self-adaptation of Mutation Rates in Non-elitist Population", 2016)
    crossover: bool
        whether to add a genetic crossover step every other iteration.

    Notes
    -----
    For the noisy case, we use the one-fifth adaptation rule,
    going back to Schumer and Steiglitz (1968).
    It was independently rediscovered by Devroye (1972) and Rechenberg (1973).
    """

    _optimizer_class = _OnePlusOne

    def __init__(self, *, noise_handling: Optional[Union[str, Tuple[str, float]]] = None,
                 mutation: str = "gaussian", crossover: bool = False) -> None:
        if noise_handling is not None:
            if isinstance(noise_handling, str):
                assert noise_handling in ["random", "optimistic"], f"Unkwnown noise handling: '{noise_handling}'"
            else:
                assert isinstance(noise_handling, tuple), "noise_handling must be a string or  a tuple of type (strategy, factor)"
                assert noise_handling[1] > 0., "the factor must be a float greater than 0"
                assert noise_handling[0] in ["random", "optimistic"], f"Unkwnown noise handling: '{noise_handling}'"
        assert mutation in ["gaussian", "cauchy", "discrete", "fastga", "doublefastga", "portfolio"], f"Unkwnown mutation: '{mutation}'"
        self.noise_handling = noise_handling
        self.mutation = mutation
        self.crossover = crossover
        super().__init__()


OnePlusOne = ParametrizedOnePlusOne().with_name("OnePlusOne", register=True)
NoisyOnePlusOne = ParametrizedOnePlusOne(noise_handling="random").with_name("NoisyOnePlusOne", register=True)
OptimisticNoisyOnePlusOne = ParametrizedOnePlusOne(noise_handling="optimistic").with_name("OptimisticNoisyOnePlusOne", register=True)
DiscreteOnePlusOne = ParametrizedOnePlusOne(mutation="discrete").with_name("DiscreteOnePlusOne", register=True)
OptimisticDiscreteOnePlusOne = ParametrizedOnePlusOne(
    noise_handling="optimistic", mutation="discrete").with_name("OptimisticDiscreteOnePlusOne", register=True)
NoisyDiscreteOnePlusOne = ParametrizedOnePlusOne(
    noise_handling=("random", 1.), mutation="discrete").with_name("NoisyDiscreteOnePlusOne", register=True)
DoubleFastGADiscreteOnePlusOne = ParametrizedOnePlusOne(mutation="doublefastga").with_name("DoubleFastGADiscreteOnePlusOne", register=True)
FastGADiscreteOnePlusOne = ParametrizedOnePlusOne(
    mutation="fastga").with_name("FastGADiscreteOnePlusOne", register=True)
DoubleFastGAOptimisticNoisyDiscreteOnePlusOne = ParametrizedOnePlusOne(
    noise_handling="optimistic", mutation="doublefastga").with_name("DoubleFastGAOptimisticNoisyDiscreteOnePlusOne", register=True)
FastGAOptimisticNoisyDiscreteOnePlusOne = ParametrizedOnePlusOne(
    noise_handling="optimistic", mutation="fastga").with_name("FastGAOptimisticNoisyDiscreteOnePlusOne", register=True)
FastGANoisyDiscreteOnePlusOne = ParametrizedOnePlusOne(
    noise_handling="random", mutation="fastga").with_name("FastGANoisyDiscreteOnePlusOne", register=True)
PortfolioDiscreteOnePlusOne = ParametrizedOnePlusOne(mutation="portfolio").with_name("PortfolioDiscreteOnePlusOne", register=True)
PortfolioOptimisticNoisyDiscreteOnePlusOne = ParametrizedOnePlusOne(
    noise_handling="optimistic", mutation="portfolio").with_name("PortfolioOptimisticNoisyDiscreteOnePlusOne", register=True)
PortfolioNoisyDiscreteOnePlusOne = ParametrizedOnePlusOne(
    noise_handling="random", mutation="portfolio").with_name("PortfolioNoisyDiscreteOnePlusOne", register=True)
CauchyOnePlusOne = ParametrizedOnePlusOne(mutation="cauchy").with_name("CauchyOnePlusOne", register=True)
RecombiningOptimisticNoisyDiscreteOnePlusOne = ParametrizedOnePlusOne(
    crossover=True, mutation="discrete", noise_handling="optimistic").with_name(
        "RecombiningOptimisticNoisyDiscreteOnePlusOne", register=True)
RecombiningPortfolioOptimisticNoisyDiscreteOnePlusOne = ParametrizedOnePlusOne(
    crossover=True, mutation="portfolio", noise_handling="optimistic").with_name(
        "RecombiningPortfolioOptimisticNoisyDiscreteOnePlusOne", register=True)


@registry.register
class CMA(base.Optimizer):
    def __init__(self, dimension: int, budget: Optional[int] = None, num_workers: int = 1) -> None:
        super().__init__(dimension, budget=budget, num_workers=num_workers)
        self.es: Optional[cma.CMAEvolutionStrategy] = None
        popsize = max(num_workers, 4 + int(3 * np.log(dimension)))
        # delay initialization to ease implementation of variants
        self._cma_init: Dict[str, Any] = {"x0": [0.] * dimension, "sigma0": 1., "inopts": {"popsize": popsize}}
        self.listx: List[base.ArrayLike] = []
        self.listy: List[float] = []
        self.to_be_asked: Deque[np.ndarray] = deque()

    def _internal_ask(self) -> base.ArrayLike:
        if self.es is None:
            self.es = cma.CMAEvolutionStrategy(**self._cma_init)
        if not self.to_be_asked:
            self.to_be_asked.extend(self.es.ask())
        return self.to_be_asked.popleft()

    def _internal_tell(self, x: base.ArrayLike, value: float) -> None:
        if self.es is None:
            self.es = cma.CMAEvolutionStrategy(**self._cma_init)
        self.listx += [x]
        self.listy += [value]
        if len(self.listx) >= self.es.popsize:
            try:
                self.es.tell(self.listx, self.listy)
            except RuntimeError:
                pass
            else:
                self.listx = []
                self.listy = []

    def _internal_provide_recommendation(self) -> base.ArrayLike:
        if self.es is None:
            return RuntimeError("Either ask or tell method should have been called before")
        return self.es.result.xbest


@registry.register
class MicroCMA(CMA):

    def __init__(self, dimension: int, budget: Optional[int] = None, num_workers: int = 1) -> None:
        super().__init__(dimension, budget=budget, num_workers=num_workers)
        self._cma_init["sigma0"] = 1e-6


@registry.register
class MilliCMA(CMA):

    def __init__(self, dimension: int, budget: Optional[int] = None, num_workers: int = 1) -> None:
        super().__init__(dimension, budget=budget, num_workers=num_workers)
        self._cma_init["sigma0"] = 1e-3


@registry.register
class DiagonalCMA(CMA):

    def __init__(self, dimension: int, budget: Optional[int] = None, num_workers: int = 1) -> None:
        super().__init__(dimension, budget=budget, num_workers=num_workers)
        self._cma_init["inopts"]['CMA_diagonal'] = True


@registry.register
class EDA(base.Optimizer):
    """Test-based population-size adaptation.

    Population-size equal to lambda = 4 x dimension.
    Test by comparing the first fifth and the last fifth of the 5lambda evaluations.
    """
    # pylint: disable=too-many-instance-attributes

    def __init__(self, dimension: int, budget: Optional[int] = None, num_workers: int = 1) -> None:
        super().__init__(dimension, budget=budget, num_workers=num_workers)
        self.sigma = 1
        self.covariance = np.identity(dimension)
        self.mu = dimension
        self.llambda = 4 * dimension
        if num_workers is not None:
            self.llambda = max(self.llambda, num_workers)
        self.current_center = np.zeros(dimension)
        # Evaluated population
        self.evaluated_population: List[base.ArrayLike] = []
        self.evaluated_population_sigma: List[float] = []
        self.evaluated_population_fitness: List[float] = []
        # Unevaluated population
        self.unevaluated_population: List[base.ArrayLike] = []
        self.unevaluated_population_sigma: List[float] = []
        # Archive
        self.archive_fitness: List[float] = []

    def _internal_provide_recommendation(self) -> base.ArrayLike:  # This is NOT the naive version. We deal with noise.
        return self.current_center

    def _internal_ask(self) -> base.ArrayLike:
        mutated_sigma = self.sigma * np.exp(np.random.normal(0, 1) / np.sqrt(self.dimension))
        assert len(self.current_center) == len(self.covariance), [self.dimension, self.current_center, self.covariance]
        individual = tuple(mutated_sigma * np.random.multivariate_normal(self.current_center, self.covariance))
        self.unevaluated_population_sigma += [mutated_sigma]
        self.unevaluated_population += [tuple(individual)]
        return individual

    def _internal_tell(self, x: base.ArrayLike, value: float) -> None:
        idx = self.unevaluated_population.index(tuple(x))
        self.evaluated_population += [x]
        self.evaluated_population_fitness += [value]
        self.evaluated_population_sigma += [self.unevaluated_population_sigma[idx]]
        del self.unevaluated_population[idx]
        del self.unevaluated_population_sigma[idx]
        if len(self.evaluated_population) >= self.llambda:
            # Sorting the population.
            sorted_pop_with_sigma_and_fitness = [(i, s, f) for f, i, s in sorted(
                zip(self.evaluated_population_fitness, self.evaluated_population, self.evaluated_population_sigma))]
            self.evaluated_population = [p[0] for p in sorted_pop_with_sigma_and_fitness]
            self.covariance = .1 * np.cov(np.array(self.evaluated_population).T)
            self.evaluated_population_sigma = [p[1] for p in sorted_pop_with_sigma_and_fitness]
            self.evaluated_population_fitness = [p[2] for p in sorted_pop_with_sigma_and_fitness]
            # Computing the new parent.
            self.current_center = sum([np.asarray(self.evaluated_population[i]) for i in range(self.mu)]) / self.mu
            self.sigma = np.exp(sum([np.log(self.evaluated_population_sigma[i]) for i in range(self.mu)]) / self.mu)
            self.evaluated_population = []
            self.evaluated_population_sigma = []
            self.evaluated_population_fitness = []


@registry.register
class PCEDA(EDA):
    """Test-based population-size adaptation.

    Population-size equal to lambda = 4 x dimension.
    Test by comparing the first fifth and the last fifth of the 5lambda evaluations.
    """
    # pylint: disable=too-many-instance-attributes

    def _internal_tell(self, x: base.ArrayLike, value: float) -> None:
        self.archive_fitness += [value]
        if len(self.archive_fitness) >= 5 * self.llambda:
            first_fifth = [self.archive_fitness[i] for i in range(self.llambda)]
            last_fifth = [self.archive_fitness[i] for i in range(4*self.llambda, 5*self.llambda)]
            mean1 = sum(first_fifth) / float(self.llambda)
            std1 = np.std(first_fifth) / np.sqrt(self.llambda - 1)
            mean2 = sum(last_fifth) / float(self.llambda)
            std2 = np.std(last_fifth) / np.sqrt(self.llambda - 1)
            z = (mean1 - mean2) / (np.sqrt(std1**2 + std2**2))
            if z < 2.:
                self.mu *= 2
            else:
                self.mu = int(self.mu * 0.84)
                if self.mu < self.dimension:
                    self.mu = self.dimension
            self.llambda = 4 * self.mu
            if self.num_workers > 1:
                self.llambda = max(self.llambda, self.num_workers)
                self.mu = self.llambda // 4
            self.archive_fitness = []
        idx = self.unevaluated_population.index(tuple(x))
        self.evaluated_population += [x]
        self.evaluated_population_fitness += [value]
        self.evaluated_population_sigma += [self.unevaluated_population_sigma[idx]]
        del self.unevaluated_population[idx]
        del self.unevaluated_population_sigma[idx]
        if len(self.evaluated_population) >= self.llambda:
            # Sorting the population.
            sorted_pop_with_sigma_and_fitness = [(i, s, f) for f, i, s in sorted(
                zip(self.evaluated_population_fitness, self.evaluated_population, self.evaluated_population_sigma))]
            self.evaluated_population = [p[0] for p in sorted_pop_with_sigma_and_fitness]
            self.covariance = np.cov(np.array(self.evaluated_population).T)
            self.evaluated_population_sigma = [p[1] for p in sorted_pop_with_sigma_and_fitness]
            self.evaluated_population_fitness = [p[2] for p in sorted_pop_with_sigma_and_fitness]
            # Computing the new parent.
            self.current_center = sum([np.asarray(self.evaluated_population[i]) for i in range(self.mu)]) / self.mu
            self.sigma = np.exp(sum([np.log(self.evaluated_population_sigma[i]) for i in range(self.mu)]) / self.mu)
            self.evaluated_population = []
            self.evaluated_population_sigma = []
            self.evaluated_population_fitness = []


@registry.register
class MPCEDA(EDA):
    """Test-based population-size adaptation.

    Population-size equal to lambda = 4 x dimension.
    Test by comparing the first fifth and the last fifth of the 5lambda evaluations.
    """
    # pylint: disable=too-many-instance-attributes

    def _internal_tell(self, x: base.ArrayLike, value: float) -> None:
        self.archive_fitness += [value]
        if len(self.archive_fitness) >= 5 * self.llambda:
            first_fifth = [self.archive_fitness[i] for i in range(self.llambda)]
            last_fifth = [self.archive_fitness[i] for i in range(4*self.llambda, 5*self.llambda)]
            mean1 = sum(first_fifth) / float(self.llambda)
            std1 = np.std(first_fifth) / np.sqrt(self.llambda - 1)
            mean2 = sum(last_fifth) / float(self.llambda)
            std2 = np.std(last_fifth) / np.sqrt(self.llambda - 1)
            z = (mean1 - mean2) / (np.sqrt(std1**2 + std2**2))
            if z < 2.:
                self.mu *= 2
            else:
                self.mu = int(self.mu * 0.84)
                if self.mu < self.dimension:
                    self.mu = self.dimension
            self.llambda = 4 * self.mu
            if self.num_workers > 1:
                self.llambda = max(self.llambda, self.num_workers)
                self.mu = self.llambda // 4
            self.archive_fitness = []
        idx = self.unevaluated_population.index(tuple(x))
        self.evaluated_population += [x]
        self.evaluated_population_fitness += [value]
        self.evaluated_population_sigma += [self.unevaluated_population_sigma[idx]]
        del self.unevaluated_population[idx]
        del self.unevaluated_population_sigma[idx]
        if len(self.evaluated_population) >= self.llambda:
            # Sorting the population.
            sorted_pop_with_sigma_and_fitness = [(i, s, f) for f, i, s in sorted(
                zip(self.evaluated_population_fitness, self.evaluated_population, self.evaluated_population_sigma))]
            self.evaluated_population = [p[0] for p in sorted_pop_with_sigma_and_fitness]
            self.covariance *= .9
            self.covariance += .1 * np.cov(np.array(self.evaluated_population).T)
            self.evaluated_population_sigma = [p[1] for p in sorted_pop_with_sigma_and_fitness]
            self.evaluated_population_fitness = [p[2] for p in sorted_pop_with_sigma_and_fitness]
            # Computing the new parent.
            self.current_center = sum([np.asarray(self.evaluated_population[i]) for i in range(self.mu)]) / self.mu
            self.sigma = np.exp(sum([np.log(self.evaluated_population_sigma[i]) for i in range(self.mu)]) / self.mu)
            self.evaluated_population = []
            self.evaluated_population_sigma = []
            self.evaluated_population_fitness = []


@registry.register
class MEDA(EDA):
    """Test-based population-size adaptation.

    Population-size equal to lambda = 4 x dimension.
    Test by comparing the first fifth and the last fifth of the 5lambda evaluations.
    """
    # pylint: disable=too-many-instance-attributes

    def _internal_tell(self, x: base.ArrayLike, value: float) -> None:
        idx = self.unevaluated_population.index(tuple(x))
        self.evaluated_population += [x]
        self.evaluated_population_fitness += [value]
        self.evaluated_population_sigma += [self.unevaluated_population_sigma[idx]]
        del self.unevaluated_population[idx]
        del self.unevaluated_population_sigma[idx]
        if len(self.evaluated_population) >= self.llambda:
            # Sorting the population.
            sorted_pop_with_sigma_and_fitness = [(i, s, f) for f, i, s in sorted(
                zip(self.evaluated_population_fitness, self.evaluated_population, self.evaluated_population_sigma))]
            self.evaluated_population = [p[0] for p in sorted_pop_with_sigma_and_fitness]
            self.covariance *= .9
            self.covariance += .1 * np.cov(np.array(self.evaluated_population).T)
            self.evaluated_population_sigma = [p[1] for p in sorted_pop_with_sigma_and_fitness]
            self.evaluated_population_fitness = [p[2] for p in sorted_pop_with_sigma_and_fitness]
            # Computing the new parent.
            self.current_center = sum([np.asarray(self.evaluated_population[i]) for i in range(self.mu)]) / self.mu
            self.sigma = np.exp(sum([np.log(self.evaluated_population_sigma[i]) for i in range(self.mu)]) / self.mu)
            self.evaluated_population = []
            self.evaluated_population_sigma = []
            self.evaluated_population_fitness = []


@registry.register
class TBPSA(base.Optimizer):
    """Test-based population-size adaptation.

    Population-size equal to lambda = 4 x dimension.
    Test by comparing the first fifth and the last fifth of the 5lambda evaluations.
    """
    # pylint: disable=too-many-instance-attributes

    def __init__(self, dimension: int, budget: Optional[int] = None, num_workers: int = 1) -> None:
        super().__init__(dimension, budget=budget, num_workers=num_workers)
        self.sigma = 1
        self.mu = dimension
        self.llambda = 4 * dimension
        if num_workers is not None:
            self.llambda = max(self.llambda, num_workers)
        self.current_center = np.zeros(dimension)
        # Evaluated population
        self.evaluated_population: List[base.ArrayLike] = []
        self.evaluated_population_sigma: List[float] = []
        self.evaluated_population_fitness: List[float] = []
        # Unevaluated population
        self.unevaluated_population: List[base.ArrayLike] = []
        self.unevaluated_population_sigma: List[float] = []
        # Archive
        self.archive_fitness: List[float] = []

    def _internal_provide_recommendation(self) -> base.ArrayLike:  # This is NOT the naive version. We deal with noise.
        return self.current_center

    def _internal_ask(self) -> base.ArrayLike:
        mutated_sigma = self.sigma * np.exp(np.random.normal(0, 1) / np.sqrt(self.dimension))
        individual = tuple(self.current_center + mutated_sigma * np.random.normal(0, 1, self.dimension))
        self.unevaluated_population_sigma += [mutated_sigma]
        self.unevaluated_population += [tuple(individual)]
        return individual

    def _internal_tell(self, x: base.ArrayLike, value: float) -> None:
        self.archive_fitness += [value]
        if len(self.archive_fitness) >= 5 * self.llambda:
            first_fifth = [self.archive_fitness[i] for i in range(self.llambda)]
            last_fifth = [self.archive_fitness[i] for i in range(4*self.llambda, 5*self.llambda)]
            mean1 = sum(first_fifth) / float(self.llambda)
            std1 = np.std(first_fifth) / np.sqrt(self.llambda - 1)
            mean2 = sum(last_fifth) / float(self.llambda)
            std2 = np.std(last_fifth) / np.sqrt(self.llambda - 1)
            z = (mean1 - mean2) / (np.sqrt(std1**2 + std2**2))
            if z < 2.:
                self.mu *= 2
            else:
                self.mu = int(self.mu * 0.84)
                if self.mu < self.dimension:
                    self.mu = self.dimension
            self.llambda = 4 * self.mu
            if self.num_workers > 1:
                self.llambda = max(self.llambda, self.num_workers)
                self.mu = self.llambda // 4
            self.archive_fitness = []
        idx = self.unevaluated_population.index(tuple(x))
        self.evaluated_population += [x]
        self.evaluated_population_fitness += [value]
        self.evaluated_population_sigma += [self.unevaluated_population_sigma[idx]]
        del self.unevaluated_population[idx]
        del self.unevaluated_population_sigma[idx]
        if len(self.evaluated_population) >= self.llambda:
            # Sorting the population.
            sorted_pop_with_sigma_and_fitness = [(i, s, f) for f, i, s in sorted(
                zip(self.evaluated_population_fitness, self.evaluated_population, self.evaluated_population_sigma))]
            self.evaluated_population = [p[0] for p in sorted_pop_with_sigma_and_fitness]
            self.evaluated_population_sigma = [p[1] for p in sorted_pop_with_sigma_and_fitness]
            self.evaluated_population_fitness = [p[2] for p in sorted_pop_with_sigma_and_fitness]
            # Computing the new parent.
            self.current_center = sum([np.asarray(self.evaluated_population[i]) for i in range(self.mu)]) / self.mu
            self.sigma = np.exp(sum([np.log(self.evaluated_population_sigma[i]) for i in range(self.mu)]) / self.mu)
            self.evaluated_population = []
            self.evaluated_population_sigma = []
            self.evaluated_population_fitness = []


@registry.register
class NaiveTBPSA(TBPSA):

    def _internal_provide_recommendation(self) -> base.ArrayLike:
        return self.current_bests["optimistic"].x


@registry.register
class NoisyBandit(base.Optimizer):
    """UCB.

    This is upper confidence bound (adapted to minimization),
      with very poor parametrization; in particular, the logarithmic term is set to zero.
    Infinite arms: we add one arm when #trials >= #arms ** 3."""

    def _internal_ask(self) -> base.ArrayLike:
        if 20 * self._num_ask >= len(self.archive) ** 3:
            return np.random.normal(0, 1, self.dimension)
        if np.random.choice([True, False]):
            # numpy does not accept choice on list of tuples, must choose index instead
            idx = np.random.choice(len(self.archive))
            return np.frombuffer(list(self.archive.bytesdict.keys())[idx])
        return self.current_bests["optimistic"].x


@registry.register
class PSO(base.Optimizer):
    """Partially following SPSO2011. However, no randomization of the population order.
    """
    # pylint: disable=too-many-instance-attributes

    def __init__(self, dimension: int, budget: Optional[int] = None, num_workers: int = 1) -> None:
        super().__init__(dimension, budget=budget, num_workers=num_workers)
        self.llambda = max(40, num_workers)
        self.pop: List[base.ArrayLike] = []
        self.pop_speed: List[base.ArrayLike] = []
        self.pop_best: List[base.ArrayLike] = []
        self.pop_best_fitness: List[Optional[float]] = []
        self.pop_fitness: List[Optional[float]] = []
        self.pso_best: Optional[base.ArrayLike] = None
        self.pso_best_fitness = float("inf")
        self.locations: Dict[Tuple[float, ...], List[int]] = defaultdict(list)
        self.index = -1
        self.omega = 0.5 / np.log(2.)
        self.phip = 0.5 + np.log(2.)
        self.phig = 0.5 + np.log(2.)
        self.eps = 1e-10
        self.queue = deque(range(self.llambda))

    def _internal_ask(self) -> base.ArrayLike:
        self.index += 1
        if self.index == 0:
            self.pso_best = None
            self.pso_best_fitness = float("inf")
            for i in range(self.llambda):
                guy = np.random.uniform(0., 1., self.dimension)
                self.pop += [guy]
                self.pop_best += [guy]
                self.pop_speed += [np.random.uniform(-1., 1., self.dimension)]
                self.pop_best_fitness += [float("inf")]
                self.pop_fitness += [None]
        # Focusing on the right guy in the population.
        if not self.queue:
            raise RuntimeError("Queue is empty, you tried to ask more than population size")
        location = self.queue[0]  # don't remove just yet
        # First, the initialization.
        if self.pop_fitness[location] is None:  # This guy is not evaluated.
            assert self.pop[location] is not None
            guy = tuple(self.to_real(self.pop[location]))
            self.locations[guy] += [location]
            self.queue.popleft()  # only remove at the last minute (safer for checkpointing)
            return guy
        # We are in a standard case.
        # Speed mutation.
        for i in range(self.dimension):
            rp = np.random.uniform(0., 1.)
            rg = np.random.uniform(0., 1.)
            self.pop_speed[location][i] = (  # type: ignore
                self.omega * self.pop_speed[location][i]
                + self.phip * rp * (self.pop_best[location][i]-self.pop[location][i])
                + self.phig * rg * (self.pso_best[i] - self.pop[location][i])  # type: ignore
            )
        # Particle mutation.
        self.pop[location] += self.pop_speed[location]
        self.pop[location] = [max(0.+self.eps, min(1.-self.eps, x_)) for x_ in self.pop[location]]
        guy = tuple(self.to_real(self.pop[location]))
        self.locations[guy] += [location]
        self.queue.popleft()  # only remove at the last minute (safer for checkpointing)
        return guy

    def _internal_provide_recommendation(self) -> base.ArrayLike:
        return tuple(self.to_real(self.pso_best))

    def _internal_tell(self, x: base.ArrayLike, value: float) -> None:
        x = tuple(x)
        assert self.locations[x]
        location = self.locations[x][0]
        point = tuple(self.to_real(self.pop[location]))
        assert x == point, str(x) + f"{x} vs {point}     {self.pop}"
        self.pop_fitness[location] = value
        if value < self.pso_best_fitness:
            assert max(self.pop[location]) < 1., str(self.pop[location])
            assert min(self.pop[location]) > 0., str(self.pop[location])
            self.pso_best = [s for s in self.pop[location]]
            self.pso_best_fitness = value
        if value < self.pop_best_fitness[location]:  # type: ignore
            self.pop_best[location] = [s for s in self.pop[location]]
            self.pop_best_fitness[location] = value
        del self.locations[x][0]
        self.queue.append(location)  # update when everything is well done (safer for checkpointing)

    @staticmethod
    def to_real(x: base.ArrayLike) -> base.ArrayLike:
        output = stats.norm.ppf(x)
        assert not any(x for x in np.isnan(output)), f"Encountered NaN value {output}"
        return output


@registry.register
class SPSA(base.Optimizer):
    # pylint: disable=too-many-instance-attributes
    ''' The First order SPSA algorithm as shown in [1,2,3], with implementation details
    from [4,5].

    [1] https://en.wikipedia.org/wiki/Simultaneous_perturbation_stochastic_approximation
    [2] https://www.chessprogramming.org/SPSA
    [3] Spall, James C. "Multivariate stochastic approximation using a simultaneous perturbation gradient approximation."
        IEEE transactions on automatic control 37.3 (1992): 332-341.
    [4] Section 7.5.2 in "Introduction to Stochastic Search and Optimization: Estimation, Simulation and Control" by James C. Spall.
    [5] Pushpendre Rastogi, Jingyi Zhu, James C. Spall CISS (2016).
        Efficient implementation of Enhanced Adaptive Simultaneous Perturbation Algorithms.
    '''
    no_parallelization = True

    def __init__(self, dimension: int, budget: Optional[int] = None, num_workers: int = 1) -> None:
        super().__init__(dimension, budget=budget, num_workers=num_workers)
        self._rng = np.random.RandomState(np.random.randint(2**32, dtype=np.uint32))
        self.init = True
        self.idx = 0
        self.delta = float('nan')
        self.ym: Optional[np.ndarray] = None
        self.yp: Optional[np.ndarray] = None
        self.t = np.zeros(self.dimension)
        self.avg = np.zeros(self.dimension)
        # Set A, a, c according to the practical implementation
        # guidelines in the ISSO book.
        self.A = (10 if budget is None else max(10, budget // 20))
        # TODO: We should spend first 10-20 iterations
        # to estimate the noise standard deviation and
        # then set c = standard deviation. 1e-1 is arbitrary.
        self.c = 1e-1
        # TODO: We should chose a to be inversely proportional to
        # the magnitude of gradient and propotional to (1+A)^0.602
        # we should spend some burn-in iterations to estimate the
        # magnitude of the gradient. 1e-5 is arbitrary.
        self.a = 1e-5

    def ck(self, k: int) -> float:
        'c_k determines the pertubation.'
        return self.c / (k//2 + 1)**0.101

    def ak(self, k: int) -> float:
        'a_k is the learning rate.'
        return self.a / (k//2 + 1 + self.A)**0.602

    def _internal_ask(self) -> base.ArrayLike:
        k = self.idx
        if k % 2 == 0:
            if not self.init:
                assert self.yp is not None and self.ym is not None
                self.t -= (self.ak(k) * (self.yp - self.ym) / 2 / self.ck(k)) * self.delta
                self.avg += (self.t - self.avg) / (k // 2 + 1)
            self.delta = 2 * self._rng.randint(2, size=self.dimension) - 1
            return self.t - self.ck(k) * self.delta
        return self.t + self.ck(k) * self.delta

    def _internal_tell(self, x: base.ArrayLike, value: float) -> None:
        setattr(self, ('ym' if self.idx % 2 == 0 else 'yp'), np.array(value, copy=True))
        self.idx += 1
        if self.init and self.yp is not None and self.ym is not None:
            self.init = False

    def _internal_provide_recommendation(self) -> base.ArrayLike:
        return self.avg


@registry.register
class Portfolio(base.Optimizer):
    """Passive portfolio of CMA, 2-pt DE and Scr-Hammersley."""

    def __init__(self, dimension: int, budget: Optional[int] = None, num_workers: int = 1) -> None:
        super().__init__(dimension, budget=budget, num_workers=num_workers)
        assert budget is not None
        self.optims = [CMA(dimension, budget // 3 + (budget % 3 > 0), num_workers),
                       TwoPointsDE(dimension, budget // 3 + (budget % 3 > 1), num_workers),
                       ScrHammersleySearch(dimension, budget // 3, num_workers)]
        if budget < 12 * num_workers:
            self.optims = [ScrHammersleySearch(dimension, budget, num_workers)]
        self.who_asked: Dict[Tuple[float, ...], List[int]] = defaultdict(list)

    def _internal_ask(self) -> base.ArrayLike:
        optim_index = self._num_ask % len(self.optims)
        individual = self.optims[optim_index].ask()
        self.who_asked[tuple(individual)] += [optim_index]
        return individual

    def _internal_tell(self, x: base.ArrayLike, value: float) -> None:
        tx = tuple(x)
        optim_index = self.who_asked[tx][0]
        del self.who_asked[tx][0]
        self.optims[optim_index].tell(x, value)

    def _internal_provide_recommendation(self) -> base.ArrayLike:
        return self.current_bests["pessimistic"].x


@registry.register
class ParaPortfolio(Portfolio):
    """Passive portfolio of CMA, 2-pt DE, PSO, SQP and Scr-Hammersley."""

    def __init__(self, dimension: int, budget: Optional[int] = None, num_workers: int = 1) -> None:
        super().__init__(dimension, budget=budget, num_workers=num_workers)
        assert budget is not None

        def intshare(n: int, m: int) -> Tuple[int, ...]:
            x = [n // m] * m
            i = 0
            while sum(x) < n:
                x[i] += 1
                i += 1
            return tuple(x)
        nw1, nw2, nw3, nw4 = intshare(num_workers - 1, 4)
        self.which_optim = [0] * nw1 + [1] * nw2 + [2] * nw3 + [3] + [4] * nw4
        assert len(self.which_optim) == num_workers
        #b1, b2, b3, b4, b5 = intshare(budget, 5)
        self.optims = [CMA(dimension, num_workers=nw1),
                       TwoPointsDE(dimension, num_workers=nw2),
                       PSO(dimension, num_workers=nw3),
                       SQP(dimension, 1),
                       ScrHammersleySearch(dimension, budget=(budget // len(self.which_optim)) * nw4)
                       ]
        self.who_asked: Dict[Tuple[float, ...], List[int]] = defaultdict(list)

    def _internal_ask(self) -> base.ArrayLike:
        optim_index = self.which_optim[self._num_ask % len(self.which_optim)]
        individual = self.optims[optim_index].ask()
        self.who_asked[tuple(individual)] += [optim_index]
        return individual


@registry.register
class ParaSQPCMA(ParaPortfolio):
    """Passive portfolio of CMA and many SQP."""

    def __init__(self, dimension: int, budget: Optional[int] = None, num_workers: int = 1) -> None:
        super().__init__(dimension, budget=budget, num_workers=num_workers)
        assert budget is not None
        nw = num_workers // 2
        self.which_optim = [0] * nw
        for i in range(num_workers - nw):
            self.which_optim += [i+1]
        assert len(self.which_optim) == num_workers
        #b1, b2, b3, b4, b5 = intshare(budget, 5)
        self.optims = [CMA(dimension, num_workers=nw)]
        for i in range(num_workers - nw):
            self.optims += [SQP(dimension, 1)]
            if i > 0:
                self.optims[-1].initial_guess = np.random.normal(0, 1, self.dimension)  # type: ignore
        self.who_asked: Dict[Tuple[float, ...], List[int]] = defaultdict(list)


@registry.register
class ASCMADEthird(Portfolio):
    """Algorithm selection, with CMA and Lhs-DE. Active selection at 1/3."""

    def __init__(self, dimension: int, budget: Optional[int] = None, num_workers: int = 1) -> None:
        super().__init__(dimension, budget=budget, num_workers=num_workers)
        assert budget is not None
        self.optims = [CMA(dimension, budget=None, num_workers=num_workers),
                       LhsDE(dimension, budget=None, num_workers=num_workers)]
        self.who_asked: Dict[Tuple[float, ...], List[int]] = defaultdict(list)
        self.budget_before_choosing = budget // 3
        self.best_optim = -1

    def _internal_ask(self) -> base.ArrayLike:
        if self.budget_before_choosing > 0:
            self.budget_before_choosing -= 1
            optim_index = self._num_ask % len(self.optims)
        else:
            if self.best_optim is None:
                best_value = float("inf")
                optim_index = -1
                for i, optim in enumerate(self.optims):
                    val = optim.current_bests["pessimistic"].get_estimation("pessimistic")
                    if not val > best_value:
                        optim_index = i
                        best_value = val
                self.best_optim = optim_index
            optim_index = self.best_optim
        individual = self.optims[optim_index].ask()
        self.who_asked[tuple(individual)] += [optim_index]
        return individual


@registry.register
class ASCMADEQRthird(ASCMADEthird):
    """Algorithm selection, with CMA, ScrHalton and Lhs-DE. Active selection at 1/3."""

    def __init__(self, dimension: int, budget: Optional[int] = None, num_workers: int = 1) -> None:
        super().__init__(dimension, budget=budget, num_workers=num_workers)
        self.optims = [CMA(dimension, budget=None, num_workers=num_workers),
                       LhsDE(dimension, budget=None, num_workers=num_workers),
                       ScrHaltonSearch(dimension, budget=None, num_workers=num_workers)]


@registry.register
class ASCMA2PDEthird(ASCMADEQRthird):
    """Algorithm selection, with CMA and 2pt-DE. Active selection at 1/3."""

    def __init__(self, dimension: int, budget: Optional[int] = None, num_workers: int = 1) -> None:
        super().__init__(dimension, budget=budget, num_workers=num_workers)
        self.optims = [CMA(dimension, budget=None, num_workers=num_workers),
                       TwoPointsDE(dimension, budget=None, num_workers=num_workers)]


@registry.register
class CMandAS2(ASCMADEthird):
    """Competence map, with algorithm selection in one of the cases (3 CMAs)."""

    def __init__(self, dimension: int, budget: Optional[int] = None, num_workers: int = 1) -> None:
        super().__init__(dimension, budget=budget, num_workers=num_workers)
        self.optims = [TwoPointsDE(dimension, budget=None, num_workers=num_workers)]
        assert budget is not None
        self.budget_before_choosing = 2 * budget
        if budget < 201:
            self.optims = [OnePlusOne(dimension, budget=None, num_workers=num_workers)]
        if budget > 50 * dimension or num_workers < 30:
            self.optims = [CMA(dimension, budget=None, num_workers=num_workers),
                           CMA(dimension, budget=None, num_workers=num_workers),
                           CMA(dimension, budget=None, num_workers=num_workers)]
            self.budget_before_choosing = budget // 10


@registry.register
class CMandAS(CMandAS2):
    """Competence map, with algorithm selection in one of the cases (2 CMAs)."""

    def __init__(self, dimension: int, budget: Optional[int] = None, num_workers: int = 1) -> None:
        super().__init__(dimension, budget=budget, num_workers=num_workers)
        self.optims = [TwoPointsDE(dimension, budget=None, num_workers=num_workers)]
        assert budget is not None
        self.budget_before_choosing = 2 * budget
        if budget < 201:
            self.optims = [OnePlusOne(dimension, budget=None, num_workers=num_workers)]
            self.budget_before_choosing = 2 * budget
        if budget > 50 * dimension or num_workers < 30:
            self.optims = [CMA(dimension, budget=None, num_workers=num_workers),
                           CMA(dimension, budget=None, num_workers=num_workers)]
            self.budget_before_choosing = budget // 3


@registry.register
class CM(CMandAS2):
    """Competence map, simplest."""

    def __init__(self, dimension: int, budget: Optional[int] = None, num_workers: int = 1) -> None:
        super().__init__(dimension, budget=budget, num_workers=num_workers)
        assert budget is not None
        self.optims = [TwoPointsDE(dimension, budget=None, num_workers=num_workers)]
        self.budget_before_choosing = 2 * budget
        if budget < 201:
            self.optims = [OnePlusOne(dimension, budget=None, num_workers=num_workers)]
        if budget > 50 * dimension:
            self.optims = [CMA(dimension, budget=None, num_workers=num_workers)]


@registry.register
class MultiCMA(CM):
    """Combining 3 CMAs. Exactly identical. Active selection at 1/10 of the budget."""

    def __init__(self, dimension: int, budget: Optional[int] = None, num_workers: int = 1) -> None:
        super().__init__(dimension, budget=budget, num_workers=num_workers)
        assert budget is not None
        self.optims = [CMA(dimension, budget=None, num_workers=num_workers),
                       CMA(dimension, budget=None, num_workers=num_workers),
                       CMA(dimension, budget=None, num_workers=num_workers)]
        self.budget_before_choosing = budget // 10


@registry.register
class TripleCMA(CM):
    """Combining 3 CMAs. Exactly identical. Active selection at 1/3 of the budget."""

    def __init__(self, dimension: int, budget: Optional[int] = None, num_workers: int = 1) -> None:
        super().__init__(dimension, budget=budget, num_workers=num_workers)
        assert budget is not None
        self.optims = [CMA(dimension, budget=None, num_workers=num_workers),
                       CMA(dimension, budget=None, num_workers=num_workers),
                       CMA(dimension, budget=None, num_workers=num_workers)]
        self.budget_before_choosing = budget // 3


@registry.register
class MultiScaleCMA(CM):
    """Combining 3 CMAs with different init scale. Active selection at 1/3 of the budget."""

    def __init__(self, dimension: int, budget: Optional[int] = None, num_workers: int = 1) -> None:
        super().__init__(dimension, budget=budget, num_workers=num_workers)
        self.optims = [CMA(dimension, budget=None, num_workers=num_workers),
                       MilliCMA(dimension, budget=None, num_workers=num_workers),
                       MicroCMA(dimension, budget=None, num_workers=num_workers)]
        assert budget is not None
        self.budget_before_choosing = budget // 3
