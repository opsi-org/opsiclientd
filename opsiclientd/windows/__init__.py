# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

import time
import threading
import win32com.client # pylint: disable=import-error
import win32com.server.policy # pylint: disable=import-error

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


def start_pty(shell="powershell.exe", lines=30, columns=120):
	logger.notice("Starting %s (%d/%d)", shell, lines, columns)
	try:
		# Import of winpty may sometimes fail because of problems with the needed dll.
		# Therefore we do not import at toplevel
		from winpty import PtyProcess # pylint: disable=import-error,import-outside-toplevel
	except ImportError as err:
		logger.error("Failed to start pty: %s", err, exc_info=True)
		raise
	process = PtyProcess.spawn(shell, dimensions=(lines, columns))

	def read(length: int):
		return process.read(length).encode("utf-8")

	def write(data: bytes):
		return process.write(data.decode("utf-8"))

	def stop():
		process.close()

	return (read, write, stop)
