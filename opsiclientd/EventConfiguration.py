# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
opsiclientd - Event configuration.
"""

from __future__ import absolute_import
import re
from OPSI.Types import forceUnicode, forceBool
from opsicommon.logging import log_context
from .State import State

state = State()

class EventConfig: # pylint: disable=too-many-instance-attributes

	def __init__(self, eventId, **kwargs):
		if not eventId:
			raise TypeError("Event id not given")
		self._id = str(eventId) # pylint: disable=invalid-name

		# Setting context here only succeeds if id is set
		with log_context({'instance', f'event config {self._id}'}):
			self.setConfig(kwargs)

	def setConfig(self, conf): # pylint: disable=too-many-statements
		self.name = str(conf.get('name', self._id.split('{')[0]))
		self.preconditions = dict(conf.get('preconditions', {}))
		self.actionMessage = str(conf.get('actionMessage', ''))
		self.maxRepetitions = int(conf.get('maxRepetitions', -1))
		# wait <activationDelay> seconds before event gets active
		self.activationDelay = int(conf.get('activationDelay', 0))
		# wait <notificationDelay> seconds before event is fired
		self.notificationDelay = int(conf.get('notificationDelay', 0))
		self.interval = int(conf.get('interval', -1))
		self.actionWarningTime = int(conf.get('actionWarningTime', 0))
		self.actionUserCancelable = int(conf.get('actionUserCancelable', 0))
		self.shutdown = forceBool(conf.get('shutdown', False))
		self.reboot = forceBool(conf.get('reboot', False))
		self.shutdownWarningMessage = str(conf.get('shutdownWarningMessage', ''))
		self.shutdownWarningTime = int(conf.get('shutdownWarningTime', 0))
		self.shutdownWarningRepetitionTime = int(conf.get('shutdownWarningRepetitionTime', 3600))
		self.shutdownUserSelectableTime = forceBool(conf.get('shutdownUserSelectableTime', False))
		self.shutdownWarningTimeAfterTimeSelect = int(conf.get('shutdownWarningTimeAfterTimeSelect', -1))  # pylint: disable=invalid-name
		if self.shutdownWarningTimeAfterTimeSelect == -1:
			self.shutdownWarningTimeAfterTimeSelect = self.shutdownWarningTime
		self.shutdownUserCancelable = int(conf.get('shutdownUserCancelable', 0))
		self.shutdownCancelCounter = int(conf.get('shutdownCancelCounter', 0))
		self.blockLogin = forceBool(conf.get('blockLogin', False))
		self.logoffCurrentUser = forceBool(conf.get('logoffCurrentUser', False))
		self.lockWorkstation = forceBool(conf.get('lockWorkstation', False))
		self.processShutdownRequests = forceBool(conf.get('processShutdownRequests', True))
		self.getConfigFromService = forceBool(conf.get('getConfigFromService', True))
		self.updateConfigFile = forceBool(conf.get('updateConfigFile', True))
		self.writeLogToService = forceBool(conf.get('writeLogToService', True))
		self.updateActionProcessor = forceBool(conf.get('updateActionProcessor', True))
		self.actionType = str(conf.get('actionType', ''))
		self.eventNotifierCommand = str(conf.get('eventNotifierCommand', ''))
		self.eventNotifierDesktop = str(conf.get('eventNotifierDesktop', 'current'))
		self.actionNotifierCommand = str(conf.get('actionNotifierCommand', ''))
		self.actionNotifierDesktop = str(conf.get('actionNotifierDesktop', 'current'))
		self.shutdownNotifierCommand = str(conf.get('shutdownNotifierCommand', ''))
		self.shutdownNotifierDesktop = str(conf.get('shutdownNotifierDesktop', 'current'))
		self.processActions = forceBool(conf.get('processActions', True))
		self.actionProcessorCommand = str(conf.get('actionProcessorCommand', ''))
		self.actionProcessorDesktop = str(conf.get('actionProcessorDesktop', 'current'))
		self.actionProcessorTimeout = int(conf.get('actionProcessorTimeout', 3 * 3600))
		self.actionProcessorProductIds = list(conf.get('actionProcessorProductIds', []))
		self.depotProtocol = str(conf.get('depotProtocol', ''))
		self.excludeProductGroupIds = list(conf.get('excludeProductGroupIds', []))
		self.includeProductGroupIds = list(conf.get('includeProductGroupIds', []))
		self.preActionProcessorCommand = str(conf.get('preActionProcessorCommand', ''))
		self.postActionProcessorCommand = str(conf.get('postActionProcessorCommand', ''))
		self.postEventCommand = str(conf.get('postEventCommand', ''))
		self.trustedInstallerDetection = forceBool(conf.get('trustedInstallerDetection', True))
		self.cacheProducts = forceBool(conf.get('cacheProducts', False))
		self.cacheMaxBandwidth = int(conf.get('cacheMaxBandwidth', 0))
		self.cacheDynamicBandwidth = forceBool(conf.get('cacheDynamicBandwidth', True))
		self.useCachedProducts = forceBool(conf.get('useCachedProducts', False))
		self.syncConfigToServer = forceBool(conf.get('syncConfigToServer', False))
		self.syncConfigFromServer = forceBool(conf.get('syncConfigFromServer', False))
		self.useCachedConfig = forceBool(conf.get('useCachedConfig', False))
		self.workingWindow = str(conf.get('workingWindow', ''))

	def getConfig(self):
		config = {}
		for key, value in self.__dict__.items():
			if not key.startswith('_'):
				config[key] = value

		return config

	def __str__(self):
		return f"<{self.__class__.__name__} {self._id}>"

	__repr__ = __str__

	def getId(self):
		return self._id

	def getName(self):
		return self.name

	def getActionMessage(self):
		return self._replacePlaceholdersInMessage(self.actionMessage)

	def getShutdownWarningMessage(self):
		return self._replacePlaceholdersInMessage(self.shutdownWarningMessage)

	def _replacePlaceholdersInMessage(self, message):
		def toUnderscore(value):
			s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', value)
			return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

		for key, value in self.__dict__.items():
			if 'message' in key.lower():
				continue

			message = message.replace(f'%{key}%', str(value))
			message = message.replace(f'%{toUnderscore(key)}%', str(value))

		while True:
			match = re.search('(%state.[^%]+%)', message)
			if not match:
				break
			name = match.group(1).replace('%state.', '')[:-1]
			message = message.replace(match.group(1), forceUnicode(state.get(name)))

		return message
