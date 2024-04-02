# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
Processing action requests.
"""

from __future__ import annotations

from opsiclientd.EventConfiguration import EventConfig
from opsiclientd.Events.Basic import Event, EventGenerator

__all__ = ["ProcessActionRequestsEvent", "ProcessActionRequestsEventConfig", "ProcessActionRequestsEventGenerator"]


class ProcessActionRequestsEventConfig(EventConfig):
	pass


class ProcessActionRequestsEventGenerator(EventGenerator):
	def createEvent(self, eventInfo: dict[str, str | list[str]] | None = None) -> ProcessActionRequestsEvent | None:
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None

		return ProcessActionRequestsEvent(eventConfig=eventConfig, eventInfo=eventInfo)


class ProcessActionRequestsEvent(Event):
	pass
