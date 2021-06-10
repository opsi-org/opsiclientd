# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
Events that get active once a system shuts down or restarts.
"""

from __future__ import absolute_import

import sys
import time

from OPSI import System
from OPSI.Logger import Logger

from opsiclientd.Events.Basic import Event, EventGenerator
from opsiclientd.EventConfiguration import EventConfig

__all__ = [
	'GUIStartupEvent', 'GUIStartupEventConfig', 'GUIStartupEventGenerator'
]

logger = Logger()


class GUIStartupEventConfig(EventConfig):
	def setConfig(self, conf):
		EventConfig.setConfig(self, conf)
		self.maxRepetitions = 0
		self.processNames = []


class GUIStartupEventGenerator(EventGenerator):
	def __init__(self, opsiclientd, eventConfig):
		EventGenerator.__init__(self, opsiclientd, eventConfig)
		self.guiProcessNames = []

	def createEvent(self, eventInfo={}): # pylint: disable=dangerous-default-value
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None

		return GUIStartupEvent(eventConfig=eventConfig, eventInfo=eventInfo)

	def getNextEvent(self):
		# TODO: Implement on linux and darwin
		for _ in range(10):
			time.sleep(1)
		return self.createEvent()
		# while not self._stopped:
		# 	for guiProcessName in self.guiProcessNames:
		# 		logger.debug("Checking if process '%s' running", guiProcessName)
		# 		if System.getPid(guiProcessName):
		# 			logger.debug("Process '%s' is running", guiProcessName)
		# 			return self.createEvent()
		# 	for _i in range(3):
		# 		if self._stopped:
		# 			break
		# 		time.sleep(1)

class GUIStartupEvent(Event): # pylint: disable=too-few-public-methods
	pass
