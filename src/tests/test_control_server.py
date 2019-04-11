#! /usr/bin/env python
# -*- coding: utf-8 -*-

import os

import ocdlib.Events as Events
import ocdlib.ControlServer as OCS

import pytest


@pytest.fixture
def preparedConfig(config, configFile):
	config.set('global', 'config_file', configFile)
	yield config


def testFiringEvent(preparedConfig):
	preparedConfig.readConfigFile()

	Events.createEventGenerators()
	Events.getEventConfigs()

	controlServer = OCS.OpsiclientdRpcInterface(None)
	controlServer.fireEvent('on_demand')


def testFiringUnknownEventRaisesError(preparedConfig):
	preparedConfig.readConfigFile()

	controlServer = OCS.OpsiclientdRpcInterface(None)
	with pytest.raises(ValueError):
		controlServer.fireEvent('foobar')


@pytest.mark.parametrize("on_windows", [os.name == 'nt'])
def testGUIStartupEventOnlyOnWindows(preparedConfig, on_windows):
	preparedConfig.readConfigFile()

	Events.createEventGenerators()
	configs = Events.getEventConfigs()

	assert configs
	if on_windows:
		assert 'gui_startup' in configs
