# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
Timer events get active after a specified time.
"""

from opsiclientd.EventConfiguration import EventConfig
from opsiclientd.Events.Basic import Event, EventGenerator

__all__ = ["TimerEvent", "TimerEventConfig", "TimerEventGenerator"]


class TimerEventConfig(EventConfig):
	pass


class TimerEventGenerator(EventGenerator):
	def createEvent(self, eventInfo={}):
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None

		return TimerEvent(eventConfig=eventConfig, eventInfo=eventInfo)


class TimerEvent(Event):
	pass
