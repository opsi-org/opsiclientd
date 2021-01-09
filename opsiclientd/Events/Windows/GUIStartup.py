# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org
# Copyright (C) 2010-2019 uib GmbH <info@uib.de>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
Events that get active once a system shuts down or restarts.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:author: Erol Ueluekmen <e.ueluekmen@uib.de>
:author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU Affero General Public License version 3
"""

from __future__ import absolute_import

import sys
import time

from OPSI import System
from OPSI.Logger import Logger

from opsiclientd.Events.Basic import Event, EventGenerator
from opsiclientd.Events.Windows.WMI import WMIEventConfig

__all__ = [
	'GUIStartupEvent', 'GUIStartupEventConfig', 'GUIStartupEventGenerator'
]

logger = Logger()


class GUIStartupEventConfig(WMIEventConfig):
	def setConfig(self, conf):
		WMIEventConfig.setConfig(self, conf)
		self.maxRepetitions = 0
		self.processNames = []


class GUIStartupEventGenerator(EventGenerator):
	def __init__(self, opsiclientd, eventConfig):
		EventGenerator.__init__(self, opsiclientd, eventConfig)
		if sys.getwindowsversion().major == 5: # pylint: disable=no-member
			self.guiProcessNames = ['winlogon.exe']
		elif sys.getwindowsversion().major >= 6: # pylint: disable=no-member
			self.guiProcessNames = ['LogonUI.exe', 'Explorer.exe']
		else:
			raise Exception('Windows version unsupported')

	def createEvent(self, eventInfo={}): # pylint: disable=dangerous-default-value
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None

		return GUIStartupEvent(eventConfig=eventConfig, eventInfo=eventInfo)

	def getNextEvent(self):
		while not self._stopped:
			for guiProcessName in self.guiProcessNames:
				logger.debug("Checking if process '%s' running", guiProcessName)
				if System.getPid(guiProcessName):
					logger.debug("Process '%s' is running", guiProcessName)
					return self.createEvent()
			for _i in range(3):
				if self._stopped:
					break
				time.sleep(1)


class GUIStartupEvent(Event): # pylint: disable=too-few-public-methods
	pass
