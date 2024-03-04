# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
Events that get active once a system shuts down or restarts.
"""

import time

import psutil
from opsicommon.logging import logger

from opsiclientd.Config import OPSI_SETUP_USER_NAME
from opsiclientd.Events.Basic import Event
from opsiclientd.Events.Windows.SensLogon import SensLogonEventGenerator
from opsiclientd.Events.Windows.WMI import WMIEventConfig

__all__ = ["UserLoginEvent", "UserLoginEventConfig", "UserLoginEventGenerator"]


class UserLoginEventConfig(WMIEventConfig):
	def setConfig(self, conf):
		WMIEventConfig.setConfig(self, conf)
		self.blockLogin = False
		self.logoffCurrentUser = False
		self.lockWorkstation = False


class UserLoginEventGenerator(SensLogonEventGenerator):
	def __init__(self, opsiclientd, eventConfig):
		SensLogonEventGenerator.__init__(self, opsiclientd, eventConfig)

	def callback(self, eventType, *args):
		logger.debug("UserLoginEventGenerator event callback: eventType '%s', args: %s", eventType, args)
		if self._opsiclientd.is_stopping():
			return

		if args[0].split("\\")[-1] == OPSI_SETUP_USER_NAME:
			logger.info("Login of user %s detected, no UserLoginAction will be fired.", args[0])
			return

		if eventType == "Logon":
			logger.notice("User login detected: %s", args[0])
			self._eventsOccured += 1
			self.fireEvent(self.createEvent(eventInfo={"User": args[0]}))
			if (self._generatorConfig.maxRepetitions > 0) and (self._eventsOccured > self._generatorConfig.maxRepetitions):
				self.stop()

	def createEvent(self, eventInfo={}):
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None

		return UserLoginEvent(eventConfig=eventConfig, eventInfo=eventInfo)


class UserLoginEvent(Event):
	pass


class LoginDetector(SensLogonEventGenerator):
	def __init__(self, opsiclientd, eventConfig):
		SensLogonEventGenerator.__init__(self, opsiclientd, eventConfig)

	def callback(self, eventType, *args):
		logger.info("LoginDetector triggered. eventType: '%s', args: %s", eventType, args)
		if self._opsiclientd.is_stopping() or args[0].split("\\")[-1] == OPSI_SETUP_USER_NAME:
			return
		if eventType == "Logon":
			logger.notice("User login detected: %s", args[0])
			self._wait_for_explorer()
			self._opsiclientd.updateMOTD()

	def _wait_for_explorer(self):
		for _ in range(12):
			if "explorer.exe" in (p.name() for p in psutil.process_iter()):
				logger.info("Finished waiting for explorer.exe to start")
				return
			logger.debug("Waiting for explorer.exe to start")
			time.sleep(5)
		raise RuntimeError("Timeout while waiting for explorer.exe to start")

	def createEvent(self, eventInfo={}):
		logger.debug("createEvent triggered for LoginDetector - should never occur")
		return None
