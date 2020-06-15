# -*- coding: utf-8 -*-

import os
import mock
import pytest

from opsiclientd.Config import ConfigImplementation


@pytest.fixture
def config():
	testconfig = ConfigImplementation()
	with mock.patch('opsiclientd.Events.Utilities.Configs.config', testconfig):
		yield testconfig


@pytest.fixture
def configFile(onWindows):
	if onWindows:
		return os.path.join(os.path.dirname(__file__), '..', 'windows', 'opsiclientd.conf')
	else:
		return os.path.join(os.path.dirname(__file__), '..', 'linux', 'opsiclientd.conf')


@pytest.fixture
def onWindows():
	return bool(os.name == 'nt')
