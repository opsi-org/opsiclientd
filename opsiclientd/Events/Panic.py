# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0
"""
Panic events are used to react to problems.
"""

from __future__ import absolute_import

from opsiclientd.Events.Basic import Event, EventGenerator
from opsiclientd.EventConfiguration import EventConfig

__all__ = ['PanicEvent', 'PanicEventConfig', 'PanicEventGenerator']


class PanicEventConfig(EventConfig): # pylint: disable=too-many-instance-attributes
	def setConfig(self, conf):
		EventConfig.setConfig(self, conf)
		self.maxRepetitions = -1
		self.actionMessage = 'Panic event'
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
		self.eventNotifierCommand = None
		self.actionNotifierCommand = None
		self.shutdownNotifierCommand = None
		self.actionProcessorDesktop = 'winlogon'


class PanicEventGenerator(EventGenerator):

	def createEvent(self, eventInfo={}): # pylint: disable=dangerous-default-value
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None

		return PanicEvent(eventConfig=eventConfig, eventInfo=eventInfo)


class PanicEvent(Event): # pylint: disable=too-few-public-methods
	pass
