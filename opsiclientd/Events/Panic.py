# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

"""
Panic events are used to react to problems.
"""

from __future__ import annotations

from typing import Any

from opsiclientd.EventConfiguration import EventConfig
from opsiclientd.Events.Basic import Event, EventGenerator

__all__ = ["PanicEvent", "PanicEventConfig", "PanicEventGenerator"]


class PanicEventConfig(EventConfig):
	def setConfig(self, conf: dict[str, Any]) -> None:
		EventConfig.setConfig(self, conf)
		self.maxRepetitions = -1
		self.actionMessage = "Panic event"
		self.activationDelay = 0
		self.notificationDelay = 0
		self.actionWarningTime = 0
		self.actionUserCancelable = False
		self.blockLogin = False
		self.logoffCurrentUser = False
		self.lockWorkstation = False
		self.getConfigFromService = False
		self.updateConfigFile = False
		self.writeLogToService = False
		self.updateActionProcessor = False
		self.eventNotifierCommand: str | None = None
		self.actionNotifierCommand: str | None = None
		self.shutdownNotifierCommand: str | None = None
		self.actionProcessorDesktop = "winlogon"


class PanicEventGenerator(EventGenerator):
	def createEvent(self, eventInfo: dict[str, str | list[str]] | None = None) -> PanicEvent | None:
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None

		return PanicEvent(eventConfig=eventConfig, eventInfo=eventInfo)


class PanicEvent(Event):
	pass
