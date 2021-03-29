# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0

from opsiclientd.Events.Utilities.Configs import getEventConfigs

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
