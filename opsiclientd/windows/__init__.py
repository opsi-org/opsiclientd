# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
opsiclientd.windows
"""

import threading
import time
from typing import Any

import win32com.client  # type: ignore[import]
import win32com.server.policy  # type: ignore[import]
from OPSI.System.Windows import (  # type: ignore[import]
	createDesktop,
	getActiveSessionId,
	getUserToken,
	terminateProcess,
	win32con,
	win32event,
	win32process,
)
from opsicommon.logging import get_logger
from opsicommon.types import forceBool, forceInt, forceUnicode, forceUnicodeLower

from opsiclientd.Config import OPSI_SETUP_USER_NAME

# pyright: reportMissingImports=false

# from Sens.h
SENSGUID_PUBLISHER = "{5fee1bd6-5b9b-11d1-8dd2-00aa004abd5e}"
SENSGUID_EVENTCLASS_LOGON = "{d5978630-5b9f-11d1-8dd2-00aa004abd5e}"

# from EventSys.h
PROGID_EventSystem = "EventSystem.EventSystem"
PROGID_EventSubscription = "EventSystem.EventSubscription"

IID_ISensLogon = "{d597bab3-5b9f-11d1-8dd2-00aa004abd5e}"

wmi = None  # type: ignore[var-annotated]
pythoncom = None  # type: ignore[var-annotated]
importWmiAndPythoncomLock = threading.Lock()

logger = get_logger("opsiclientd")


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
						import pythoncom  # type: ignore[import]

					if not wmi and importWmi:
						logger.debug("Importing wmi")
						pythoncom.CoInitialize()
						try:
							import wmi  # type: ignore[import]
						finally:
							pythoncom.CoUninitialize()
				except Exception as import_error:
					logger.warning("Failed to import: %s, retrying in 2 seconds", import_error)
					time.sleep(2)

	return (wmi, pythoncom)


class SensLogon(win32com.server.policy.DesignatedWrapPolicy):
	_com_interfaces_ = [IID_ISensLogon]
	_public_methods_ = ["Logon", "Logoff", "StartShell", "DisplayLock", "DisplayUnlock", "StartScreenSaver", "StopScreenSaver"]

	def __init__(self, callback):
		self._wrap_(self)
		self._callback = callback

	def subscribe(self):
		(_wmi, _pythoncom) = importWmiAndPythoncom(importWmi=False)
		pythoncom.CoInitialize()

		subscription_interface = _pythoncom.WrapObject(self)

		event_system = win32com.client.Dispatch(PROGID_EventSystem)

		event_subscription = win32com.client.Dispatch(PROGID_EventSubscription)
		event_subscription.EventClassID = SENSGUID_EVENTCLASS_LOGON
		event_subscription.PublisherID = SENSGUID_PUBLISHER
		event_subscription.SubscriptionName = "opsiclientd subscription"
		event_subscription.SubscriberInterface = subscription_interface

		event_system.Store(PROGID_EventSubscription, event_subscription)

	def Logon(self, *args):
		logger.notice("Logon: %s", args)
		self._callback("Logon", *args)

	def Logoff(self, *args):
		logger.notice("Logoff: %s", args)
		self._callback("Logoff", *args)

	def StartShell(self, *args):
		logger.notice("StartShell: %s", args)
		self._callback("StartShell", *args)

	def DisplayLock(self, *args):
		logger.notice("DisplayLock: %s", args)
		self._callback("DisplayLock", *args)

	def DisplayUnlock(self, *args):
		logger.notice("DisplayUnlock: %s", args)
		self._callback("DisplayUnlock", *args)

	def StartScreenSaver(self, *args):
		logger.notice("StartScreenSaver: %s", args)
		self._callback("StartScreenSaver", *args)

	def StopScreenSaver(self, *args):
		logger.notice("StopScreenSaver: %s", args)
		self._callback("StopScreenSaver", *args)


def start_pty(shell="powershell.exe", lines=30, columns=120):
	logger.notice("Starting %s (%d/%d)", shell, lines, columns)
	try:
		# Import of winpty may sometimes fail because of problems with the needed dll.
		# Therefore we do not import at toplevel
		from winpty import PtyProcess  # type: ignore[import]
	except ImportError as err:
		logger.error("Failed to start pty: %s", err, exc_info=True)
		raise
	process = PtyProcess.spawn(shell, dimensions=(lines, columns))

	def read(length: int):
		return process.read(length).encode("utf-8")

	def write(data: bytes):
		return process.write(data.decode("utf-8"))

	return (process.pid, read, write, process.setwinsize, process.close)


def runCommandInSession(
	command,
	sessionId=None,
	desktop="default",
	duplicateFrom="winlogon.exe",
	waitForProcessEnding=True,
	timeoutSeconds=0,
	noWindow=False,
	shell=True,
	max_attempts=6,
):
	"""
	put command arguments in double, not single, quotes.
	"""
	command = forceUnicode(command)
	if sessionId is not None:
		sessionId = forceInt(sessionId)

	desktop = forceUnicodeLower(desktop)
	if desktop.find("\\") == -1:
		desktop = "winsta0\\" + desktop

	duplicateFrom = forceUnicode(duplicateFrom)
	waitForProcessEnding = forceBool(waitForProcessEnding)
	timeoutSeconds = forceInt(timeoutSeconds)

	logger.debug("Session id given: %s", sessionId)
	if sessionId is None or (sessionId < 0):
		logger.debug("No session id given, running in active session")
		sessionId = getActiveSessionId()

	if desktop.split("\\")[-1] not in ("default", "winlogon"):
		logger.info("Creating new desktop '%s'", desktop.split("\\")[-1])
		try:
			createDesktop(desktop.split("\\")[-1])
		except Exception as err:
			logger.warning(err)

	userToken = getUserToken(sessionId, duplicateFrom)

	dwCreationFlags = win32con.NORMAL_PRIORITY_CLASS
	if noWindow:
		dwCreationFlags |= win32con.CREATE_NO_WINDOW

	sti = win32process.STARTUPINFO()
	sti.lpDesktop = desktop

	for attempt in range(1, max_attempts + 1):
		logger.notice("Executing: '%s' in session '%s' on desktop '%s'", command, sessionId, desktop)
		(hProcess, hThread, dwProcessId, dwThreadId) = win32process.CreateProcessAsUser(
			userToken, None, command, None, None, 1, dwCreationFlags, None, None, sti
		)

		logger.info("Process startet, pid: %d", dwProcessId)
		if not waitForProcessEnding:
			return (hProcess, hThread, dwProcessId, dwThreadId)

		logger.info("Waiting for process ending: %d (timeout: %d seconds)", dwProcessId, timeoutSeconds)
		sec = 0.0
		while win32event.WaitForSingleObject(hProcess, timeoutSeconds):
			if timeoutSeconds > 0:
				if sec >= timeoutSeconds:
					terminateProcess(processId=dwProcessId)
					raise RuntimeError(f"Timed out after {sec} seconds while waiting for process {dwProcessId}")
				sec += 0.1
			time.sleep(0.1)

		exitCode = win32process.GetExitCodeProcess(hProcess)
		log = logger.notice
		if exitCode != 0:
			log = logger.warning
		log("Process %d ended with exit code %d", dwProcessId, exitCode)
		# Can occur with the DeviceLock software on system startup
		# -1073741502 / 0xc0000142 / STATUS_DLL_INIT_FAILED
		if exitCode == -1073741502 and attempt < max_attempts:
			logger.warning("Retrying in 10 seconds")
			time.sleep(10)
			continue
		return (None, None, None, None)


class LoginDetector(threading.Thread):
	def __init__(self, opsiclientd: Any) -> None:
		self._opsiclientd = opsiclientd
		self._sensLogon = SensLogon(self.callback)
		self._sensLogon.subscribe()
		self._stopped = False

	def callback(self, eventType, *args):
		logger.devel("LoginDetector triggered. eventType: '%s', args: %s", eventType, args)
		if self._opsiclientd.is_stopping():
			return

		if args[0].split("\\")[-1] == OPSI_SETUP_USER_NAME:
			logger.info("Login of user %s detected, no UserLoginAction will be fired.", args[0])
			return

		if eventType == "Logon":
			logger.notice("User login detected: %s", args[0])
			self._opsiclientd.updateMOTD()

	def run(self) -> None:
		while not self._stopped:
			time.sleep(0.5)

	def stop(self) -> None:
		self._stopped = True
