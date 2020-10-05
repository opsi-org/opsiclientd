# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org
# Copyright (C) 2010-2018 uib GmbH <info@uib.de>

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
:copyright: uib GmbH <info@uib.de>
:license: GNU Affero General Public License version 3
"""

import os
import sys
import time
import threading
import subprocess
import win32com.server.policy
import win32com.client

import opsicommon.logging
from opsicommon.logging import logger, logging_config, LOG_NONE, LOG_DEBUG, LOG_ERROR
from OPSI.Types import forceBool, forceUnicode
from OPSI import System

from opsiclientd.Opsiclientd import Opsiclientd
from opsiclientd import config

# from Sens.h
SENSGUID_PUBLISHER = "{5fee1bd6-5b9b-11d1-8dd2-00aa004abd5e}"
SENSGUID_EVENTCLASS_LOGON = "{d5978630-5b9f-11d1-8dd2-00aa004abd5e}"

# from EventSys.h
PROGID_EventSystem = "EventSystem.EventSystem"
PROGID_EventSubscription = "EventSystem.EventSubscription"

IID_ISensLogon = "{d597bab3-5b9f-11d1-8dd2-00aa004abd5e}"

wmi = None
pythoncom = None
importWmiAndPythoncomLock = threading.Lock()
def importWmiAndPythoncom(importWmi=True, importPythoncom=True):
	global wmi
	global pythoncom
	if importWmi and not pythoncom:
		importPythoncom = True

	if not ((wmi or not importWmi) and (pythoncom or not importPythoncom)):
		logger.info("Importing wmi / pythoncom")
		with importWmiAndPythoncomLock:
			while not ((wmi or not importWmi) and (pythoncom or not importPythoncom)):
				try:
					if not pythoncom and importPythoncom:
						logger.debug("Importing pythoncom")
						import pythoncom

					if not wmi and importWmi:
						logger.debug("Importing wmi")
						pythoncom.CoInitialize()
						try:
							import wmi
						finally:
							pythoncom.CoUninitialize()
				except Exception as importError:
					logger.warning("Failed to import: %s, retrying in 2 seconds", importError)
					time.sleep(2)

	return (wmi, pythoncom)

def opsiclientd_factory():
	windowsVersion = sys.getwindowsversion()
	if windowsVersion.major == 5:  # NT5: XP
		return OpsiclientdNT5()
	elif windowsVersion.major >= 6:  # NT6: Vista / Windows7 and later
		if windowsVersion.minor >= 3:  # Windows8.1 or newer
			return OpsiclientdNT63()
		else:
			return OpsiclientdNT6()
	raise Exception(f"Windows version {windowsVersion} not supported")


class OpsiclientdNT(Opsiclientd):
	def __init__(self):
		Opsiclientd.__init__(self)

	def suspendBitlocker(self):
		logger.notice("Suspending bitlocker for one reboot if active")
		try:
			result = System.execute(
				"powershell.exe -ExecutionPolicy Bypass -Command 'Get-BitLockerVolume | Suspend-BitLocker -RebootCount 1'",
				captureStderr=True,
				waitForEnding=True
			)
			logger.info(result)
		except Exception as e:
			logger.debug("Failed to suspend bitlocker: %s", e)
	
	def rebootMachine(self, waitSeconds=3):
		if config.get('global', 'suspend_bitlocker_on_reboot'):
			self.suspendBitlocker()
		super().rebootMachine(waitSeconds)

	def clearRebootRequest(self):
		System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "RebootRequested", 0)

	def clearShutdownRequest(self):
		System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "ShutdownRequested", 0)

	def isRebootRequested(self):
		try:
			rebootRequested = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "RebootRequested")
		except Exception as error:
			logger.warning(u"Failed to get RebootRequested from registry: {0}".format(forceUnicode(error)))
			rebootRequested = 0

		logger.notice(u"Reboot request in Registry: {0}".format(rebootRequested))
		if rebootRequested == 2:
			# Logout
			logger.info(u"Logout requested")
			self.clearRebootRequest()
			return False

		return forceBool(rebootRequested)

	def isShutdownRequested(self):
		try:
			shutdownRequested = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "ShutdownRequested")
		except Exception as error:
			logger.warning(u"Failed to get shutdownRequested from registry: {0}".format(forceUnicode(error)))
			shutdownRequested = 0

		logger.notice(u"Shutdown request in Registry: {0}".format(shutdownRequested))
		return forceBool(shutdownRequested)


class OpsiclientdNT5(OpsiclientdNT):
	def __init__(self):
		OpsiclientdNT.__init__(self)

	def shutdownMachine(self):
		self._isShutdownTriggered = True
		System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "ShutdownRequested", 0)

		# Running in thread to avoid failure of shutdown (device not ready)
		ShutdownThread().start()

	def rebootMachine(self):
		self._isRebootTriggered = True
		System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "RebootRequested", 0)

		# Running in thread to avoid failure of reboot (device not ready)
		RebootThread().start()


class ShutdownThread(threading.Thread):
	def __init__(self):
		threading.Thread.__init__(self)

	def run(self):
		while True:
			try:
				System.shutdown(0)
				logger.notice("Shutdown initiated")
				break
			except Exception as e:
				# Device not ready?
				logger.info("Failed to initiate shutdown: %s", e)
				time.sleep(1)


class RebootThread(threading.Thread):
	def __init__(self):
		threading.Thread.__init__(self)

	def run(self):
		while True:
			try:
				System.reboot(0)
				logger.notice("Reboot initiated")
				break
			except Exception as e:
				# Device not ready?
				logger.info("Failed to initiate reboot: %s", e)
				time.sleep(1)


class OpsiclientdNT6(OpsiclientdNT):
	def __init__(self):
		OpsiclientdNT.__init__(self)


class OpsiclientdNT63(OpsiclientdNT):
	"OpsiclientdNT for Windows NT 6.3 - Windows >= 8.1"

	def rebootMachine(self):
		self._isRebootTriggered = True
		self.clearRebootRequest()
		logger.debug("Sleeping 3 seconds before reboot to avoid hanging.")
		for _ in range(10):
			time.sleep(0.3)
		logger.debug("Finished sleeping.")
		System.reboot(3)


class SensLogon(win32com.server.policy.DesignatedWrapPolicy):
	_com_interfaces_ = [IID_ISensLogon]
	_public_methods_ = [
		'Logon',
		'Logoff',
		'StartShell',
		'DisplayLock',
		'DisplayUnlock',
		'StartScreenSaver',
		'StopScreenSaver'
	]

	def __init__(self, callback):
		self._wrap_(self)
		self._callback = callback

	def subscribe(self):
		(wmi, pythoncom) = importWmiAndPythoncom(importWmi=False)

		subscription_interface = pythoncom.WrapObject(self)

		event_system = win32com.client.Dispatch(PROGID_EventSystem)

		event_subscription = win32com.client.Dispatch(PROGID_EventSubscription)
		event_subscription.EventClassID = SENSGUID_EVENTCLASS_LOGON
		event_subscription.PublisherID = SENSGUID_PUBLISHER
		event_subscription.SubscriptionName = 'opsiclientd subscription'
		event_subscription.SubscriberInterface = subscription_interface

		event_system.Store(PROGID_EventSubscription, event_subscription)

	def Logon(self, *args):
		logger.notice(u'Logon : %s' % [args])
		self._callback('Logon', *args)

	def Logoff(self, *args):
		logger.notice(u'Logoff : %s' % [args])
		self._callback('Logoff', *args)

	def StartShell(self, *args):
		logger.notice(u'StartShell : %s' % [args])
		self._callback('StartShell', *args)

	def DisplayLock(self, *args):
		logger.notice(u'DisplayLock : %s' % [args])
		self._callback('DisplayLock', *args)

	def DisplayUnlock(self, *args):
		logger.notice(u'DisplayUnlock : %s' % [args])
		self._callback('DisplayUnlock', *args)

	def StartScreenSaver(self, *args):
		logger.notice(u'StartScreenSaver : %s' % [args])
		self._callback('StartScreenSaver', *args)

	def StopScreenSaver(self, *args):
		logger.notice(u'StopScreenSaver : %s' % [args])
		self._callback('StopScreenSaver', *args)
