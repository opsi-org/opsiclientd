# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
Events that get active once a system shuts down or restarts.
"""

from opsiclientd.Events.Basic import Event, EventGenerator
from opsiclientd.Events.Windows.WMI import WMIEventConfig

__all__ = [
	'SystemShutdownEvent', 'SystemShutdownEventConfig',
	'SystemShutdownEventGenerator'
]


class SystemShutdownEventConfig(WMIEventConfig):
	def setConfig(self, conf):
		WMIEventConfig.setConfig(self, conf)
		self.maxRepetitions = 0


class SystemShutdownEventGenerator(EventGenerator):
	pass


class SystemShutdownEvent(Event): # pylint: disable=too-few-public-methods
	pass
