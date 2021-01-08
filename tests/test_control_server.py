# -*- coding: utf-8 -*-

import opsiclientd.ControlServer as OCS
from opsiclientd.Events.Utilities.Configs import getEventConfigs
from opsiclientd.Events.Utilities.Generators import createEventGenerators

import pytest


@pytest.fixture
def preparedConfig(config, configFile):
	config.set('global', 'config_file', configFile)
	yield config


def testFiringEvent(preparedConfig):
	preparedConfig.readConfigFile()

	createEventGenerators(None)
	getEventConfigs()

	controlServer = OCS.OpsiclientdRpcInterface(None)
	controlServer.fireEvent('on_demand')


def testFiringUnknownEventRaisesError(preparedConfig):
	preparedConfig.readConfigFile()

	controlServer = OCS.OpsiclientdRpcInterface(None)
	with pytest.raises(ValueError):
		controlServer.fireEvent('foobar')


def testGUIStartupEventOnlyOnWindows(preparedConfig, onWindows):
	preparedConfig.readConfigFile()

	createEventGenerators(None)
	configs = getEventConfigs()

	assert configs
	if onWindows:
		assert 'gui_startup' in configs
