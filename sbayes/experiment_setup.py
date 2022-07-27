#!/usr/bin/env python3
# -*- coding: utf-8 -*-

""" Setup of the Experiment"""
import logging
import os
from pathlib import Path
from typing import Optional

from sbayes.util import set_experiment_name, PathLike
from sbayes.config.config import SBayesConfig


class Experiment:

    """sBayes experiment class. Takes care of loading and verifying the config file,
    handling paths, setting up logging...

    Attributes:
        config_file (PathLike): The path to the config_file.
        experiment_name (str): The name of the experiment run (= name of results folder)
        config (SBayesConfig): The config parsed into a python dictionary.
        path_results (Path): The path to the results folder.
        logger (logging.Logger): The logger used throughout the run of the experiment.
    """

    def __init__(
        self,
        config_file: PathLike,
        experiment_name: str = None,
        custom_settings: Optional[dict] = None,
        log: bool = True,
    ):
        # Naming and shaming
        self.experiment_name = experiment_name or set_experiment_name()

        # Initialize the logger
        self.logger = self.init_logger()

        # Load and parse the config file
        self.config = SBayesConfig.from_config_file(config_file, custom_settings)

        # Set results path
        self.path_results = self.init_results_directory(self.config, self.experiment_name)

        # Print the initial log message
        if log:
            self.log_experiment()

    def init_results_directory(self, config: SBayesConfig, experiment_name: str):
        """Create subdirectory for this experiment, add it to the logger and the return path."""
        path_results = config.results.path / experiment_name
        os.makedirs(path_results, exist_ok=True)
        self.add_logger_file(path_results)
        return path_results

    @staticmethod
    def init_logger():
        logger = logging.Logger("sbayesLogger", level=logging.DEBUG)
        logger.addHandler(logging.StreamHandler())
        return logger

    def add_logger_file(self, path_results):
        log_path = path_results / "experiment.log"
        self.logger.addHandler(logging.FileHandler(filename=log_path))

    def log_experiment(self):
        self.logger.info("Experiment: %s", self.experiment_name)
        self.logger.info("File location for results: %s", self.path_results)
