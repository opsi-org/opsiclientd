# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

"""
Events for when a sync is completed.
"""

from __future__ import annotations

from opsiclientd.EventConfiguration import EventConfig
from opsiclientd.Events.Basic import Event, EventGenerator

__all__ = ["SyncCompletedEvent", "SyncCompletedEventConfig", "SyncCompletedEventGenerator"]


class SyncCompletedEventConfig(EventConfig):
	pass


class SyncCompletedEventGenerator(EventGenerator):
	def createEvent(self, eventInfo: dict[str, str | list[str]] | None = None) -> SyncCompletedEvent | None:
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None

		return SyncCompletedEvent(eventConfig=eventConfig, eventInfo=eventInfo)


class SyncCompletedEvent(Event):
	pass
