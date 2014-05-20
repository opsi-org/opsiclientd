#! /usr/bin/env python
# -*- coding: utf-8 -*-

import mock
import os
import unittest

from ocdlib.Config import ConfigImplementation
import ocdlib.Events as Events
import ocdlib.ControlServer as OCS


# TODO: test ControlServer fire event


class ControlServerFiringEventTestCase(unittest.TestCase):
	def setUp(self):
		self.temporaryConfig = ConfigImplementation()
		self.configPatcher = mock.patch('ocdlib.Events.config', self.temporaryConfig)
		self.configPatcher.start()

	def tearDown(self):
		self.configPatcher.stop()
		del self.temporaryConfig

	def testFiringUnknownEventRaisesError(self):
		defaultConfigFile = os.path.join(os.path.dirname(__file__), '..', 'windows', 'opsiclientd.conf')
		self.temporaryConfig.set('global', 'config_file', defaultConfigFile)
		self.temporaryConfig.readConfigFile()

		controlServer = OCS.OpsiclientdRpcInterface(None)
		self.assertRaises(ValueError, controlServer.fireEvent, 'foobar')


if __name__ == '__main__':
	unittest.main()
