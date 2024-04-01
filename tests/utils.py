# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
utils
"""

import os
from contextlib import contextmanager
from typing import Generator

import pytest

from opsiclientd.Config import Config


@pytest.fixture
def opsiclientd_url() -> str:
	return "https://localhost:4441"


@pytest.fixture
def opsiclientd_auth() -> tuple[str, str]:
	config = Config()
	config.readConfigFile()
	return (config.get("global", "host_id"), config.get("global", "opsi_host_key"))


@contextmanager
def change_dir(path) -> Generator[None, None, None]:
	old_dir = os.getcwd()
	os.chdir(path)
	try:
		yield
	finally:
		os.chdir(old_dir)


def load_config_file(config_file: str) -> None:
	config = Config()
	config.set("global", "config_file", config_file)
	config.readConfigFile()


@pytest.fixture
def default_config() -> None:
	load_config_file("tests/data/opsiclientd.conf")
