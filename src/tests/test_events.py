# -*- coding: utf-8 -*-

import ocdlib.Events as Events


def testGettingEventConfiguration(config, configFile):
	"""
	Testing if event configuration can be read from an config file.

	No check if the data is correct.
	"""
	config.set('global', 'config_file', configFile)
	config.readConfigFile()

	configs = Events.getEventConfigs()

	assert configs.keys(), 'no event configurations read'
	assert configs
