# -*- coding: utf-8 -*-

import os
import mock
import pytest

from opsiclientd.Config import Config

@pytest.fixture
def opsiclient_url():
	return "https://localhost:4441"

@pytest.fixture
def config():
	testconfig = Config()
	with mock.patch('opsiclientd.Events.Utilities.Configs.config', testconfig):
		yield testconfig


@pytest.fixture
def configFile(onWindows):
	if onWindows:
		return os.path.join(os.path.dirname(__file__), '..', 'opsiclientd_data', 'windows', 'opsiclientd.conf')
	else:
		return os.path.join(os.path.dirname(__file__), '..', 'opsiclientd_data', 'linux', 'opsiclientd.conf')


@pytest.fixture
def onWindows():
	return bool(os.name == 'nt')
