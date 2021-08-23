# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
Daemon Shutdown Events
"""

from opsiclientd.Events.Basic import Event, EventGenerator
from opsiclientd.EventConfiguration import EventConfig

__all__ = [
	'DaemonShutdownEvent', 'DaemonShutdownEventConfig',
	'DaemonShutdownEventGenerator'
]


class DaemonShutdownEventConfig(EventConfig):
	def setConfig(self, conf):
		EventConfig.setConfig(self, conf)
		self.maxRepetitions = 0


class DaemonShutdownEventGenerator(EventGenerator):

	def createEvent(self, eventInfo={}): # pylint: disable=dangerous-default-value
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None

		return DaemonShutdownEvent(
			eventConfig=eventConfig,
			eventInfo=eventInfo
		)


class DaemonShutdownEvent(Event): # pylint: disable=too-few-public-methods
	pass
