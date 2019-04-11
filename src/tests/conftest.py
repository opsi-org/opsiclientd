# -*- coding: utf-8 -*-

import os
import mock
import pytest

from ocdlib.Config import ConfigImplementation

ON_WINDOWS = os.name == 'nt'


@pytest.fixture
def config():
	testconfig = ConfigImplementation()
	with mock.patch('ocdlib.Events.config', testconfig):
		yield testconfig


@pytest.fixture
def configFile():
	if ON_WINDOWS:
		return os.path.join(os.path.dirname(__file__), '..', 'windows', 'opsiclientd.conf')
	else:
		return os.path.join(os.path.dirname(__file__), '..', 'linux', 'opsiclientd.conf')
