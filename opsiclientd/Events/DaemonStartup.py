# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0
"""
Daemon Startup Events
"""

from __future__ import absolute_import

from opsiclientd.Events.Basic import Event, EventGenerator
from opsiclientd.EventConfiguration import EventConfig

__all__ = [
	'DaemonStartupEvent', 'DaemonStartupEventConfig',
	'DaemonStartupEventGenerator'
]


class DaemonStartupEventConfig(EventConfig):
	def setConfig(self, conf):
		EventConfig.setConfig(self, conf)
		self.maxRepetitions = 0


class DaemonStartupEventGenerator(EventGenerator):

	def createEvent(self, eventInfo={}): # pylint: disable=dangerous-default-value
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None

		return DaemonStartupEvent(eventConfig=eventConfig, eventInfo=eventInfo)


class DaemonStartupEvent(Event): # pylint: disable=too-few-public-methods
	pass
