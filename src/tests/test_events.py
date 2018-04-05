# -*- coding: utf-8 -*-

import mock
import os

import pytest

from ocdlib.Config import ConfigImplementation
import ocdlib.Events as Events


@pytest.fixture
def config():
	testconfig = ConfigImplementation()
	with mock.patch('ocdlib.Events.config', testconfig):
		yield testconfig


@pytest.fixture
def configFile():
	return os.path.join(os.path.dirname(__file__), '..', 'windows', 'opsiclientd.conf')


def testGettingEventConfiguration(config, defaultConfigFile):
	"""
	Testing if event configuration can be read from an config file.

	No check if the data is correct.
	"""
	config.set('global', 'config_file', defaultConfigFile)
	config.readConfigFile()

	configs = Events.getEventConfigs()

	assert configs.keys(), 'no event configurations read'
	assert configs
