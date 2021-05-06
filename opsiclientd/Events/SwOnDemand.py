# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
Software On Demand events.

Usually triggered by the kiosk client on the client.
"""

from __future__ import absolute_import

from opsiclientd.Events.Basic import Event, EventGenerator
from opsiclientd.EventConfiguration import EventConfig

__all__ = [
	'SwOnDemandEvent', 'SwOnDemandEventConfig', 'SwOnDemandEventGenerator'
]


class SwOnDemandEventConfig(EventConfig):
	pass


class SwOnDemandEventGenerator(EventGenerator):
	def __init__(self, opsiclientd, eventConfig):
		EventGenerator.__init__(self, opsiclientd, eventConfig)

	def createEvent(self, eventInfo={}): # pylint: disable=dangerous-default-value
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None

		return SwOnDemandEvent(eventConfig=eventConfig, eventInfo=eventInfo)


class SwOnDemandEvent(Event): # pylint: disable=too-few-public-methods
	pass
