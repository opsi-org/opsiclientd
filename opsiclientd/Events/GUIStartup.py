# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
Events that get active once a system shuts down or restarts.
"""

import time
import psutil

from OPSI.Logger import Logger

from opsiclientd.SystemCheck import RUNNING_ON_DARWIN, RUNNING_ON_LINUX, RUNNING_ON_WINDOWS
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

class GUIStartupEventGenerator(EventGenerator):
	def __init__(self, opsiclientd, eventConfig):
		EventGenerator.__init__(self, opsiclientd, eventConfig)
		self.gui_process_names = []
		if RUNNING_ON_WINDOWS:
			self.gui_process_names = ["LogonUI.exe", "Explorer.exe"]
		elif RUNNING_ON_LINUX:
			self.gui_process_names = ["Xorg", "Xwayland"]
		elif RUNNING_ON_DARWIN:
			self.gui_process_names = ["WindowServer"]


	def createEvent(self, eventInfo={}): # pylint: disable=dangerous-default-value
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None

		return GUIStartupEvent(eventConfig=eventConfig, eventInfo=eventInfo)

	def getNextEvent(self):
		gui_process_names_lower = [n.lower() for n in self.gui_process_names]
		while not self._stopped:
			for proc in psutil.process_iter():
				try:
					if proc.name().lower() in [n.lower() for n in gui_process_names_lower]:
						logger.debug("Process '%s' is running", proc.name())
						return self.createEvent()
				except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
					pass
			for _i in range(3):
				if self._stopped:
					break
				time.sleep(1)

class GUIStartupEvent(Event): # pylint: disable=too-few-public-methods
	pass
