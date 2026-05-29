# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2026 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0-only

"""
Events that get active once a system shuts down or restarts.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from opsi.logging import logger
from opsi.system.session import get_display_sessions

from opsiclientd.EventConfiguration import EventConfig
from opsiclientd.Events.Basic import Event, EventGenerator

if TYPE_CHECKING:
	from opsiclientd.Opsiclientd import Opsiclientd

__all__ = ["GUIStartupEvent", "GUIStartupEventConfig", "GUIStartupEventGenerator"]


class GUIStartupEventConfig(EventConfig):
	def setConfig(self, conf: dict[str, Any]) -> None:
		EventConfig.setConfig(self, conf)
		self.maxRepetitions = 0


class GUIStartupEventGenerator(EventGenerator):
	def __init__(self, opsiclientd: Opsiclientd, eventConfig: GUIStartupEventConfig) -> None:
		EventGenerator.__init__(self, opsiclientd, eventConfig)

	def createEvent(self, eventInfo: dict[str, str | list[str]] | None = None) -> GUIStartupEvent | None:
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None

		return GUIStartupEvent(eventConfig=eventConfig, eventInfo=eventInfo)

	def getNextEvent(self) -> GUIStartupEvent | None:
		while not self._stopped:
			console_sessions = [s for s in get_display_sessions() if s.is_current_console_session]
			if console_sessions:
				logger.debug("Console session found: %s", console_sessions[0])
				return self.createEvent()

			for _i in range(3):
				if self._stopped:
					break
				time.sleep(1)
		return None


class GUIStartupEvent(Event):
	pass
