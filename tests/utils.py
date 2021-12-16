# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

import os
import pytest
import tempfile
import configparser
from contextlib import contextmanager
import shutil

from opsiclientd.Config import Config


@pytest.fixture
def opsiclient_url():
	return "https://localhost:4441"


@pytest.fixture
def opsiclientd_auth():
	config = Config()
	return (config.get("global", "host_id"), config.get("global", "opsi_host_key"))

	#conf = configparser.ConfigParser()
	#conf.read(configFile)
	#return (conf.get("global", "host_id"), conf.get("global", "opsi_host_key"))


@pytest.fixture
def onWindows():
	return os.name == 'nt'


@contextmanager
def workInTemporaryDirectory(tempDir=None):
	"""
	Creates a temporary folder to work in. Deletes the folder afterwards.
	:param tempDir: use the given dir as temporary directory. Will not be deleted if given.
	"""

	temporary_folder = tempDir or tempfile.mkdtemp()
	with cd(temporary_folder):
		yield temporary_folder

	if not tempDir and os.path.exists(temporary_folder):
		shutil.rmtree(temporary_folder)

@contextmanager
def cd(path):
	old_dir = os.getcwd()
	os.chdir(path)
	yield
	os.chdir(old_dir)

def load_config_file(config_file):
	config = Config()
	config.set("global", "config_file", config_file)
	config.readConfigFile()

@pytest.fixture(autouse=True)
def default_config():
	load_config_file("tests/data/opsiclientd.conf")
