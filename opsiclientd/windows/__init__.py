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

import time
import threading
import win32com.client # pylint: disable=import-error

from opsicommon.logging import logger

# pyright: reportMissingImports=false

# from Sens.h
SENSGUID_PUBLISHER = "{5fee1bd6-5b9b-11d1-8dd2-00aa004abd5e}"
SENSGUID_EVENTCLASS_LOGON = "{d5978630-5b9f-11d1-8dd2-00aa004abd5e}"

# from EventSys.h
PROGID_EventSystem = "EventSystem.EventSystem" # pylint: disable=invalid-name
PROGID_EventSubscription = "EventSystem.EventSubscription" # pylint: disable=invalid-name

IID_ISensLogon = "{d597bab3-5b9f-11d1-8dd2-00aa004abd5e}" # pylint: disable=invalid-name

wmi = None # pylint: disable=invalid-name
pythoncom = None # pylint: disable=invalid-name
importWmiAndPythoncomLock = threading.Lock()

def importWmiAndPythoncom(importWmi=True, importPythoncom=True):
	global wmi # pylint: disable=global-statement,invalid-name
	global pythoncom # pylint: disable=global-statement,invalid-name
	if importWmi and not pythoncom:
		importPythoncom = True

	if not ((wmi or not importWmi) and (pythoncom or not importPythoncom)):
		logger.info("Importing wmi / pythoncom")
		with importWmiAndPythoncomLock:
			while not ((wmi or not importWmi) and (pythoncom or not importPythoncom)):
				try:
					if not pythoncom and importPythoncom:
						logger.debug("Importing pythoncom")
						import pythoncom # pylint: disable=import-error,import-outside-toplevel,redefined-outer-name

					if not wmi and importWmi:
						logger.debug("Importing wmi")
						pythoncom.CoInitialize()
						try:
							import wmi # pylint: disable=import-error,import-outside-toplevel,redefined-outer-name
						finally:
							pythoncom.CoUninitialize()
				except Exception as import_error: # pylint: disable=broad-except
					logger.warning("Failed to import: %s, retrying in 2 seconds", import_error)
					time.sleep(2)

	return (wmi, pythoncom)

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
		(_wmi, _pythoncom) = importWmiAndPythoncom(importWmi=False)

		subscription_interface = _pythoncom.WrapObject(self)

		event_system = win32com.client.Dispatch(PROGID_EventSystem)

		event_subscription = win32com.client.Dispatch(PROGID_EventSubscription)
		event_subscription.EventClassID = SENSGUID_EVENTCLASS_LOGON
		event_subscription.PublisherID = SENSGUID_PUBLISHER
		event_subscription.SubscriptionName = 'opsiclientd subscription'
		event_subscription.SubscriberInterface = subscription_interface

		event_system.Store(PROGID_EventSubscription, event_subscription)

	def Logon(self, *args): # pylint: disable=invalid-name
		logger.notice('Logon: %s', args)
		self._callback('Logon', *args)

	def Logoff(self, *args): # pylint: disable=invalid-name
		logger.notice('Logoff: %s', args)
		self._callback('Logoff', *args)

	def StartShell(self, *args): # pylint: disable=invalid-name
		logger.notice('StartShell: %s', args)
		self._callback('StartShell', *args)

	def DisplayLock(self, *args): # pylint: disable=invalid-name
		logger.notice('DisplayLock: %s', args)
		self._callback('DisplayLock', *args)

	def DisplayUnlock(self, *args): # pylint: disable=invalid-name
		logger.notice('DisplayUnlock: %s', args)
		self._callback('DisplayUnlock', *args)

	def StartScreenSaver(self, *args): # pylint: disable=invalid-name
		logger.notice('StartScreenSaver: %s', args)
		self._callback('StartScreenSaver', *args)

	def StopScreenSaver(self, *args): # pylint: disable=invalid-name
		logger.notice('StopScreenSaver: %s', args)
		self._callback('StopScreenSaver', *args)
