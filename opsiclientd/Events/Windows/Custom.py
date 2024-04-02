# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
Windows-specific Custom event.
"""

from __future__ import annotations

from opsiclientd.Events.Basic import Event
from opsiclientd.Events.Windows.WMI import WMIEventConfig, WMIEventGenerator

__all__ = ["CustomEvent", "CustomEventConfig", "CustomEventGenerator"]


class CustomEventConfig(WMIEventConfig):
	pass


class CustomEventGenerator(WMIEventGenerator):
	def createEvent(self, eventInfo: dict[str, str | list[str]] | None = None) -> CustomEvent | None:
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None

		return CustomEvent(eventConfig=eventConfig, eventInfo=eventInfo)


class CustomEvent(Event):
	pass
