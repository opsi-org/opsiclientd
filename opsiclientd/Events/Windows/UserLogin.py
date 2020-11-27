# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org
# Copyright (C) 2010-2019 uib GmbH <info@uib.de>

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
Events that get active once a system shuts down or restarts.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:author: Erol Ueluekmen <e.ueluekmen@uib.de>
:author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU Affero General Public License version 3
"""

from __future__ import absolute_import

import sys

from OPSI.Logger import Logger
from OPSI import System

from opsiclientd.Events.Basic import Event
from opsiclientd.Events.Windows.SensLogon import SensLogonEventGenerator
from opsiclientd.Events.Windows.WMI import WMIEventConfig

__all__ = [
	'UserLoginEvent', 'UserLoginEventConfig', 'UserLoginEventGenerator'
]

logger = Logger()


class UserLoginEventConfig(WMIEventConfig):
	def setConfig(self, conf):
		WMIEventConfig.setConfig(self, conf)
		self.blockLogin = False
		self.logoffCurrentUser = False
		self.lockWorkstation = False


class UserLoginEventGenerator(SensLogonEventGenerator):
	def __init__(self, eventConfig):
		SensLogonEventGenerator.__init__(self, eventConfig)

	def callback(self, eventType, *args):
		logger.debug(u"UserLoginEventGenerator event callback: eventType '%s', args: %s" % (eventType, args))
		if sys.getwindowsversion().major >= 6:
			# Try to find out, if the Login is from the WindowManager
			# (Win8 Bugfix for UserLoginScripts)
			sessionIds = None
			sessionId = None
			sessionData = None

			sessionIds = System.getUserSessionIds(args[0])
			if sessionIds:
				sessionId = sessionIds[0]
				sessionData = System.getSessionInformation(sessionId)
				if sessionData.get(u'LogonDomain', '') == u'Window Manager':
					logger.notice(u"Windows Manager Login detected, no UserLoginAction will be fired.")
					return

		if eventType == 'Logon':
			logger.notice(u"User login detected: %s" % args[0])
			self._eventsOccured += 1
			self.fireEvent(self.createEvent(eventInfo={'User': args[0]}))
			if (self._generatorConfig.maxRepetitions > 0) and (self._eventsOccured > self._generatorConfig.maxRepetitions):
				self.stop()

	def createEvent(self, eventInfo={}):
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None

		return UserLoginEvent(eventConfig=eventConfig, eventInfo=eventInfo)


class UserLoginEvent(Event):
	pass
