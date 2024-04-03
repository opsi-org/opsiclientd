# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

"""
Events that get active once a system shuts down or restarts.
"""

from typing import Any

from opsiclientd.Events.Basic import Event, EventGenerator
from opsiclientd.Events.Windows.WMI import WMIEventConfig

__all__ = ["SystemShutdownEvent", "SystemShutdownEventConfig", "SystemShutdownEventGenerator"]


class SystemShutdownEventConfig(WMIEventConfig):
	def setConfig(self, conf: dict[str, Any]) -> None:
		WMIEventConfig.setConfig(self, conf)
		self.maxRepetitions = 0


class SystemShutdownEventGenerator(EventGenerator):
	pass


class SystemShutdownEvent(Event):
	pass
