# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
"""
Non-free event generators.
"""

from opsiclientd.Events.Basic import Event, EventGenerator

__all__ = ["CustomEvent", "CustomEventGenerator"]


class CustomEventGenerator(EventGenerator):
	def createEvent(self, eventInfo={}):
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None

		return CustomEvent(eventConfig=eventConfig, eventInfo=eventInfo)


class CustomEvent(Event):
	pass
