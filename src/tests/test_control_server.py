#! /usr/bin/env python
# -*- coding: utf-8 -*-

import mock
import os
import unittest

from ocdlib.Config import ConfigImplementation
import ocdlib.Events as Events
import ocdlib.ControlServer as OCS
import ocdlib.SystemCheck as sc


# TODO: test ControlServer fire event


class ControlServerFiringEventTestCase(unittest.TestCase):
	def setUp(self):
		self.temporaryConfig = ConfigImplementation()
		self.configPatcher = mock.patch('ocdlib.Events.config', self.temporaryConfig)
		self.configPatcher.start()

		if os.name == 'nt':
			self.defaultConfigFile = os.path.join(os.path.dirname(__file__), '..', 'windows', 'opsiclientd.conf')
		else:
			self.defaultConfigFile = os.path.join(os.path.dirname(__file__), '..', 'linux', 'opsiclientd.conf')

		self.temporaryConfig.set('global', 'config_file', self.defaultConfigFile)

	def tearDown(self):
		self.configPatcher.stop()
		del self.temporaryConfig
		del self.defaultConfigFile

	def testFiringEvent(self):
		self.temporaryConfig.readConfigFile()

		Events.createEventGenerators()
		configs = Events.getEventConfigs()

		controlServer = OCS.OpsiclientdRpcInterface(None)
		controlServer.fireEvent('on_demand')

	def testFiringUnknownEventRaisesError(self):
		self.temporaryConfig.readConfigFile()

		controlServer = OCS.OpsiclientdRpcInterface(None)
		self.assertRaises(ValueError, controlServer.fireEvent, 'foobar')


	def testGUIStartupEventOnlyOnWindows(self):
		self.temporaryConfig.readConfigFile()

		Events.createEventGenerators()
		configs = Events.getEventConfigs()

		self.assertTrue(configs)
		expected = False
		if sc.RUNNING_ON_WINDOWS:
			expected = True

		self.assertEquals(expected, 'gui_startup' in configs)


if __name__ == '__main__':
	unittest.main()
