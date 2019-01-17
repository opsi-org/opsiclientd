# -*- coding: utf-8 -*-

import os
import mock
import pytest

from ocdlib.Config import ConfigImplementation


@pytest.fixture
def config():
	testconfig = ConfigImplementation()
	with mock.patch('ocdlib.Events.config', testconfig):
		yield testconfig


@pytest.fixture
def configFile():
	return os.path.join(os.path.dirname(__file__), '..', 'windows', 'opsiclientd.conf')
