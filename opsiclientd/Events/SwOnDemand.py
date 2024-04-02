# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
Software On Demand events.

Usually triggered by the kiosk client on the client.
"""

from __future__ import annotations

from opsiclientd.EventConfiguration import EventConfig
from opsiclientd.Events.Basic import Event, EventGenerator

__all__ = ["SwOnDemandEvent", "SwOnDemandEventConfig", "SwOnDemandEventGenerator"]


class SwOnDemandEventConfig(EventConfig):
	pass


class SwOnDemandEventGenerator(EventGenerator):
	def __init__(self, opsiclientd, eventConfig):
		EventGenerator.__init__(self, opsiclientd, eventConfig)

	def createEvent(self, eventInfo: dict[str, str | list[str]] | None = None) -> SwOnDemandEvent | None:
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None

		return SwOnDemandEvent(eventConfig=eventConfig, eventInfo=eventInfo)


class SwOnDemandEvent(Event):
	pass
