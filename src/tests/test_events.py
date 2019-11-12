# -*- coding: utf-8 -*-

from ocdlib.Events.Configs import getEventConfigs


def testGettingEventConfiguration(config, configFile):
	"""
	Testing if event configuration can be read from an config file.

	No check if the data is correct.
	"""
	config.set('global', 'config_file', configFile)
	config.readConfigFile()

	configs = getEventConfigs()

	assert configs.keys(), 'no event configurations read'
	assert configs
