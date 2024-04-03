# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
opsiclientd.windows
"""

import shlex
import threading
import time
from types import ModuleType
from typing import Any, Callable

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
						import pythoncom  # type: ignore[import]

					if not wmi and importWmi and pythoncom:
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

	def __init__(self, callback: Callable) -> None:
		self._wrap_(self)  # type: ignore[attr-defined]
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


def start_pty(shell: str = "powershell.exe", lines: int = 30, columns: int = 120) -> tuple[int, Callable, Callable, Callable, Callable]:
	logger.notice("Starting %s (%d/%d)", shell, lines, columns)
	try:
		# Import of winpty may sometimes fail because of problems with the needed dll.
		# Therefore we do not import at toplevel
		from winpty import PtyProcess  # type: ignore[import]
	except ImportError as err:
		logger.error("Failed to start pty: %s", err, exc_info=True)
		raise
	process = PtyProcess.spawn(shell, dimensions=(lines, columns))

	def read(length: int) -> bytes:
		return process.read(length).encode("utf-8")

	def write(data: bytes) -> int:
		return process.write(data.decode("utf-8"))

	return (process.pid, read, write, process.setwinsize, process.close)


def runCommandInSession(
	command: str | list[str],
	sessionId: int | None = None,
	desktop: str | None = "default",
	duplicateFrom: str = "winlogon.exe",
	waitForProcessEnding: bool = True,
	timeoutSeconds: int = 0,
	noWindow: bool = False,
	shell: bool = True,
	max_attempts: int = 6,
) -> tuple[int | None, int | None, int | None, int | None]:
	"""
	put command arguments in double, not single, quotes.
	"""
	if isinstance(command, list):
		command = shlex.join(command)

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
	return (None, None, None, None)
