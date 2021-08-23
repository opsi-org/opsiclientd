# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
Events for when a sync is completed.
"""

from opsiclientd.Events.Basic import Event, EventGenerator
from opsiclientd.EventConfiguration import EventConfig

__all__ = [
	'SyncCompletedEvent', 'SyncCompletedEventConfig',
	'SyncCompletedEventGenerator'
]


class SyncCompletedEventConfig(EventConfig):
	pass


class SyncCompletedEventGenerator(EventGenerator):

	def createEvent(self, eventInfo={}): # pylint: disable=dangerous-default-value
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None

		return SyncCompletedEvent(eventConfig=eventConfig, eventInfo=eventInfo)


class SyncCompletedEvent(Event): # pylint: disable=too-few-public-methods
	pass
