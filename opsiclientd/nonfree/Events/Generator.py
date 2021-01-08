# -*- coding: utf-8 -*-

# ocdlibnonfree is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org

# Copyright (C) 2015-2019 uib GmbH
# http://www.uib.de/
# All rights reserved.
"""
Non-free event generators.

:copyright:	uib GmbH <info@uib.de>
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
