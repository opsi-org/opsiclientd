# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.

"""
Non-free event generators.
"""

from __future__ import annotations

from opsiclientd.Events.Basic import Event, EventGenerator

__all__ = ["CustomEvent", "CustomEventGenerator"]


class CustomEventGenerator(EventGenerator):
	def createEvent(self, eventInfo: dict[str, str | list[str]] | None = None) -> CustomEvent | None:
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None

		return CustomEvent(eventConfig=eventConfig, eventInfo=eventInfo)


class CustomEvent(Event):
	pass
