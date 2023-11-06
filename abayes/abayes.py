from __future__ import annotations

from typing import Optional, List, Union, Tuple, Dict
import numpy as np
import pandas as pd
from jinja2 import Environment, PackageLoader
from jinja2.exceptions import TemplateNotFound
from pathlib import Path
from functools import cached_property
from hashlib import md5
import json
import os

import arviz as az
import cmdstanpy as csp

from .templates.distributions import LIKELIHOODS
from ._globals import CACHE_LOCATION, ROOT

__all__ = [
    "ABayes",
    "DEFAULT_PRIORS",
]

DEFAULT_PRIORS = {"mu": "normal(0, 1)", "sigma": "normal(0, 1)"}

ENVIRONMENT = Environment(loader=PackageLoader("abayes"))

VectorTypes = Union[List, np.ndarray]
DataTypes = Union[Dict[str, VectorTypes], Tuple[VectorTypes, ...]]

class ABayes(object):
    """The main A/B testing class.

    This class initializes a ABayes object instance, given a specified
    likelihood function and a set of priors.

    Parameters
    ----------

    Returns
    -------
    """

    def __init__(self, likelihood: str = "normal", priors: Priors = DEFAULT_PRIORS, seed: int = None, force_compile: Optiona[bool] = None) -> None:
        self._likelihood = likelihood
        self._priors = priors
        self.model : csp.CmdStanModel = self.compile(force=force_compile)
        self._fit: csp.CmdStanMCMC = None

    likelihood = property(lambda self: self._likelihood)
    priors = property(lambda self: self._priors)
    cmdstan_mcmc = property(lambda self: self._fit)

    def fit(self, data: DataTypes, **cmdstanpy_kwargs) -> ABayes:
        if not hasattr(data, "__iter__"):
            raise ValueError("Data passed to MiniAb.fit must be an iterable.")
        if isinstance(data, Dict):
            y1, y2 = data.values()
        else:
            y1, y2 = data
        y = np.hstack([y1, y2])
        _j = [1] * len(y1) + [2] * len(y2)
        clean_data = {"N": len(y1) + len(y2), "j": _j, "y": y}
        self._fit = self.model.sample(data=clean_data, **cmdstanpy_kwargs, show_console=True)
        return self

    def compile(self, force: bool = False) -> CmdStanModel:
        stan_file = self._hash() + ".stan"
        if force or stan_file not in os.listdir(CACHE_LOCATION):
            stan_file_path = str(CACHE_LOCATION) + "/" + stan_file
            with open(stan_file_path, "w") as f:
                f.write(self._render_model())
            return csp.CmdStanModel(stan_file=stan_file_path)
        else:
            return csp.CmdStanModel(exe_file=str(CACHE_LOCATION) + "/" + self._hash())

    def _render_model(self) -> str:
        try:
            template = ENVIRONMENT.get_template("distributions/" + self._likelihood.lower() + ".stan")
        except TemplateNotFound:
            raise ValueError(f"Cannot build model for likelihood {self._likelihood}.\n"
                             f"Likelihoods available are {LIKELIHOODS}.")

        rendered = template.render(priors=self.priors)
        return rendered
        
    @property
    def inference_data(self):
        self._check_fit_exists()
        return az.from_cmdstanpy(self.cmdstan_mcmc)
    
    @cached_property
    def draws(self) -> np.ndarray:
        self._check_fit_exists()
        return self._fit.stan_variables()

    @cached_property
    def summary(self) -> pd.DataFrame:
        self._check_fit_exists()
        variables = ["mu", "mu_diff"]
        if self._likelihood == "normal":
            variables += ["sigma", "sigma_diff"]
        if self._likelihood == "bernoulli":
            variables += ["mu_prob", "mu_prob_diff"]
        inference_data = self.inference_data
        return az.summary(inference_data, var_names=variables)

    def _hash(self):
        return md5(json.dumps(tuple((self.priors, self.likelihood))).encode("utf-8")).hexdigest()

    def _check_fit_exists(self) -> Union[None, Exception]:
        if self._fit is None:
            raise AttributeError("The model has not been fit yet.")
        else:
            return True


