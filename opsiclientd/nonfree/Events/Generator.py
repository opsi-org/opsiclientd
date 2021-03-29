# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# License: opsi source available license 1.0
"""
Non-free event generators.
"""

import threading

from opsiclientd.Events.Basic import Event, EventGenerator

__all__ = ['CustomEvent', 'CustomEventGenerator']


class CustomEventGenerator(EventGenerator):
	def createEvent(self, eventInfo={}): # pylint: disable=dangerous-default-value
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None

		return CustomEvent(eventConfig=eventConfig, eventInfo=eventInfo)

	def getNextEvent(self):
		self._event = threading.Event()
		if self._generatorConfig.interval > 0:
			self._event.wait(self._generatorConfig.interval)
			if self._stopped:
				return None
			return self.createEvent()
		self._event.wait()
		return None


class CustomEvent(Event): # pylint: disable=too-few-public-methods
	pass
