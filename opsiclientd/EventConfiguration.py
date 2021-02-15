# -*- coding: utf-8 -*-

# This file is part of python-opsi.
# Copyright (C) 2013 uib GmbH <info@uib.de>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
opsiclientd - Event configuration.

:license: GNU Affero General Public License version 3
"""
from __future__ import absolute_import

import re

from OPSI.Types import forceUnicode

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
		self.shutdown = bool(conf.get('shutdown', False))
		self.reboot = bool(conf.get('reboot', False))
		self.shutdownWarningMessage = str(conf.get('shutdownWarningMessage', ''))
		self.shutdownWarningTime = int(conf.get('shutdownWarningTime', 0))
		self.shutdownWarningRepetitionTime = int(conf.get('shutdownWarningRepetitionTime', 3600))
		self.shutdownUserCancelable = int(conf.get('shutdownUserCancelable', 0))
		self.shutdownCancelCounter = int(conf.get('shutdownCancelCounter', 0))
		self.blockLogin = bool(conf.get('blockLogin', False))
		self.logoffCurrentUser = bool(conf.get('logoffCurrentUser', False))
		self.lockWorkstation = bool(conf.get('lockWorkstation', False))
		self.processShutdownRequests = bool(conf.get('processShutdownRequests', True))
		self.getConfigFromService = bool(conf.get('getConfigFromService', True))
		self.updateConfigFile = bool(conf.get('updateConfigFile', True))
		self.writeLogToService = bool(conf.get('writeLogToService', True))
		self.updateActionProcessor = bool(conf.get('updateActionProcessor', True))
		self.actionType = str(conf.get('actionType', ''))
		self.eventNotifierCommand = str(conf.get('eventNotifierCommand', ''))
		self.eventNotifierDesktop = str(conf.get('eventNotifierDesktop', 'current'))
		self.actionNotifierCommand = str(conf.get('actionNotifierCommand', ''))
		self.actionNotifierDesktop = str(conf.get('actionNotifierDesktop', 'current'))
		self.shutdownNotifierCommand = str(conf.get('shutdownNotifierCommand', ''))
		self.shutdownNotifierDesktop = str(conf.get('shutdownNotifierDesktop', 'current'))
		self.processActions = bool(conf.get('processActions', True))
		self.actionProcessorCommand = str(conf.get('actionProcessorCommand', ''))
		self.actionProcessorDesktop = str(conf.get('actionProcessorDesktop', 'current'))
		self.actionProcessorTimeout = int(conf.get('actionProcessorTimeout', 3 * 3600))
		self.actionProcessorProductIds = list(conf.get('actionProcessorProductIds', []))
		self.excludeProductGroupIds = list(conf.get('excludeProductGroupIds', []))
		self.includeProductGroupIds = list(conf.get('includeProductGroupIds', []))
		self.preActionProcessorCommand = str(conf.get('preActionProcessorCommand', ''))
		self.postActionProcessorCommand = str(conf.get('postActionProcessorCommand', ''))
		self.postEventCommand = str(conf.get('postEventCommand', ''))
		self.trustedInstallerDetection = bool(conf.get('trustedInstallerDetection', True))
		self.cacheProducts = bool(conf.get('cacheProducts', False))
		self.cacheMaxBandwidth = int(conf.get('cacheMaxBandwidth', 0))
		self.cacheDynamicBandwidth = bool(conf.get('cacheDynamicBandwidth', True))
		self.useCachedProducts = bool(conf.get('useCachedProducts', False))
		self.syncConfigToServer = bool(conf.get('syncConfigToServer', False))
		self.syncConfigFromServer = bool(conf.get('syncConfigFromServer', False))
		self.postSyncConfigToServer = bool(conf.get('postSyncConfigToServer', False))
		self.postSyncConfigFromServer = bool(conf.get('postSyncConfigFromServer', False))
		self.useCachedConfig = bool(conf.get('useCachedConfig', False))
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
