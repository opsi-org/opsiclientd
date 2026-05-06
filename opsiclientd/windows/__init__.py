# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2026 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0-only

"""
opsiclientd.windows
"""

import threading
import time
from types import ModuleType
from typing import Any, Callable

import win32com.client
import win32com.server.policy
from opsi.logging import get_logger

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

logger = get_logger()


def importWmiAndPythoncom(importWmi: bool = True, importPythoncom: bool = True) -> tuple[ModuleType | None, ModuleType | None]:
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

					if not wmi and importWmi and pythoncom:
						logger.debug("Importing wmi")
						pythoncom.CoInitialize()
						try:
							import wmi  # ty: ignore[unresolved-import]
						finally:
							pythoncom.CoUninitialize()
				except Exception as import_error:
					logger.warning("Failed to import: %s, retrying in 2 seconds", import_error)
					time.sleep(2)

	return (wmi, pythoncom)


class SensLogon(win32com.server.policy.DesignatedWrapPolicy):
	_com_interfaces_ = [IID_ISensLogon]
	_public_methods_ = ["Logon", "Logoff", "StartShell", "DisplayLock", "DisplayUnlock", "StartScreenSaver", "StopScreenSaver"]

	def __init__(self, callback: Callable) -> None:
		self._wrap_(self)  # ty: ignore[unresolved-attribute]
		self._callback = callback

	def subscribe(self) -> None:
		(_wmi, _pythoncom) = importWmiAndPythoncom(importWmi=False)
		assert _pythoncom

		subscription_interface = _pythoncom.WrapObject(self)

		event_system = win32com.client.Dispatch(PROGID_EventSystem)

		event_subscription = win32com.client.Dispatch(PROGID_EventSubscription)
		event_subscription.EventClassID = SENSGUID_EVENTCLASS_LOGON
		event_subscription.PublisherID = SENSGUID_PUBLISHER
		event_subscription.SubscriptionName = "opsiclientd subscription"
		event_subscription.SubscriberInterface = subscription_interface

		event_system.Store(PROGID_EventSubscription, event_subscription)

	def Logon(self, *args: Any) -> None:
		logger.notice("Logon: %s", args)
		self._callback("Logon", *args)

	def Logoff(self, *args: Any) -> None:
		logger.notice("Logoff: %s", args)
		self._callback("Logoff", *args)

	def StartShell(self, *args: Any) -> None:
		logger.notice("StartShell: %s", args)
		self._callback("StartShell", *args)

	def DisplayLock(self, *args: Any) -> None:
		logger.notice("DisplayLock: %s", args)
		self._callback("DisplayLock", *args)

	def DisplayUnlock(self, *args: Any) -> None:
		logger.notice("DisplayUnlock: %s", args)
		self._callback("DisplayUnlock", *args)

	def StartScreenSaver(self, *args: Any) -> None:
		logger.notice("StartScreenSaver: %s", args)
		self._callback("StartScreenSaver", *args)

	def StopScreenSaver(self, *args: Any) -> None:
		logger.notice("StopScreenSaver: %s", args)
		self._callback("StopScreenSaver", *args)
