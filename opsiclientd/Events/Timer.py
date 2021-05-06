# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
Timer events get active after a specified time.
"""

from __future__ import absolute_import

import threading

from opsiclientd.Events.Basic import Event, EventGenerator
from opsiclientd.EventConfiguration import EventConfig

__all__ = ['TimerEvent', 'TimerEventConfig', 'TimerEventGenerator']


class TimerEventConfig(EventConfig):
	pass


class TimerEventGenerator(EventGenerator):

	def getNextEvent(self):
		self._event = threading.Event()
		if self._generatorConfig.interval > 0:
			self._event.wait(self._generatorConfig.interval)
			if self._stopped:
				return None
			return self.createEvent()
		self._event.wait()
		return None

	def createEvent(self, eventInfo={}): # pylint: disable=dangerous-default-value
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None

		return TimerEvent(eventConfig=eventConfig, eventInfo=eventInfo)


class TimerEvent(Event): # pylint: disable=too-few-public-methods
	pass
