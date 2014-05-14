#! /usr/bin/env python
# -*- coding: utf-8 -*-

import mock
import os
import unittest

from ocdlib.Config import ConfigImplementation
import ocdlib.Events as Events


class EventTestCase(unittest.TestCase):
    def setUp(self):
        self.temporaryConfig = ConfigImplementation()
        self.configPatcher = mock.patch('ocdlib.Events.config', self.temporaryConfig)
        self.configPatcher.start()

    def tearDown(self):
    	self.configPatcher.stop()
        del self.temporaryConfig

    def testGettingEventConfiguration(self):
    	"""
    	Testing if event configuration can be read from an config file.

    	No check if the data is correct.
    	"""
    	defaultConfigFile = os.path.join(os.path.dirname(__file__), '..', 'windows', 'opsiclientd.conf')
    	self.temporaryConfig.set('global', 'config_file', defaultConfigFile)
    	self.temporaryConfig.readConfigFile()

        configs = Events.getEventConfigs()

        self.assertTrue(configs.keys(), 'no event configurations read')
        self.assertTrue(configs)


if __name__ == '__main__':
    unittest.main()
