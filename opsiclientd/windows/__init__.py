# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2025 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0-only

"""
opsiclientd.windows
"""

import ctypes
import os
import shlex
import threading
import time
from ctypes import wintypes

if os.name == "nt":
	from ctypes import get_last_error  # type: ignore[attr-defined]
	from ctypes import WinError, windll
else:
	WinError = get_last_error = windll = None

from pathlib import Path
from types import ModuleType
from typing import Any, Callable

import win32com.client  # type: ignore[import]
import win32com.server.policy  # type: ignore[import]
from OPSI.System.Windows import createDesktop  # type: ignore[import]
from OPSI.System.Windows import (getActiveSessionId, getUserToken,
                                 terminateProcess, win32con, win32event,
                                 win32process)
from opsicommon.logging import get_logger
from opsicommon.types import (forceBool, forceInt, forceUnicode,
                              forceUnicodeLower)

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
		log = logger.notice if exitCode == 0 else logger.warning
		log("Process %d ended with exit code %d", dwProcessId, exitCode)  # type: ignore
		# Can occur with the DeviceLock software on system startup
		# -1073741502 / 0xc0000142 / STATUS_DLL_INIT_FAILED
		if exitCode == -1073741502 and attempt < max_attempts:
			logger.warning("Retrying in 10 seconds")
			time.sleep(10)
			continue
		return (None, None, None, None)
	return (None, None, None, None)


# Reparse point handling
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
GENERIC_READ = 0x80000000
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
FSCTL_GET_REPARSE_POINT = 0x000900A8
IO_REPARSE_TAG_SYMLINK = 0xA000000C
IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003  # Junction
MAXIMUM_REPARSE_DATA_BUFFER_SIZE = 16 * 1024  # 16KB
ERROR_NOT_A_REPARSE_POINT = 0x1126  # 4390
SYMLINK_FLAG_RELATIVE = 0x00000001

CreateFileW = windll.kernel32.CreateFileW
CreateFileW.restype = wintypes.HANDLE
CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]

DeviceIoControl = windll.kernel32.DeviceIoControl
DeviceIoControl.restype = wintypes.BOOL
DeviceIoControl.argtypes = [
	wintypes.HANDLE,
	wintypes.DWORD,
	wintypes.LPVOID,
	wintypes.DWORD,
	wintypes.LPVOID,
	wintypes.DWORD,
	ctypes.POINTER(wintypes.DWORD),
	ctypes.c_void_p,
]

CloseHandle = windll.kernel32.CloseHandle
CloseHandle.restype = wintypes.BOOL
CloseHandle.argtypes = [wintypes.HANDLE]


class SYMBOLIC_LINK_REPARSE_BUFFER(ctypes.Structure):
	_fields_ = [
		("SubstituteNameOffset", wintypes.USHORT),
		("SubstituteNameLength", wintypes.USHORT),
		("PrintNameOffset", wintypes.USHORT),
		("PrintNameLength", wintypes.USHORT),
		("Flags", wintypes.ULONG),
		("PathBuffer", wintypes.WCHAR * 1),
	]


class MOUNT_POINT_REPARSE_BUFFER(ctypes.Structure):
	_fields_ = [
		("SubstituteNameOffset", wintypes.USHORT),
		("SubstituteNameLength", wintypes.USHORT),
		("PrintNameOffset", wintypes.USHORT),
		("PrintNameLength", wintypes.USHORT),
		("PathBuffer", wintypes.WCHAR * 1),
	]


class GENERIC_REPARSE_BUFFER(ctypes.Structure):
	_fields_ = [("DataBuffer", wintypes.BYTE * 1)]


class REPARSE_BUFFER_UNION(ctypes.Union):
	_fields_ = [
		("SymbolicLinkReparseBuffer", SYMBOLIC_LINK_REPARSE_BUFFER),
		("MountPointReparseBuffer", MOUNT_POINT_REPARSE_BUFFER),
		("GenericReparseBuffer", GENERIC_REPARSE_BUFFER),
	]


class REPARSE_DATA_BUFFER(ctypes.Structure):
	_fields_ = [
		("ReparseTag", wintypes.ULONG),
		("ReparseDataLength", wintypes.USHORT),
		("Reserved", wintypes.USHORT),
		("ReparseBuffer", REPARSE_BUFFER_UNION),
	]


def get_link_target(link_path: str | Path) -> Path | None:
	if not isinstance(link_path, Path):
		link_path = Path(link_path)
	handle = CreateFileW(
		str(link_path), GENERIC_READ, 0, None, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS, None
	)
	if handle == INVALID_HANDLE_VALUE:
		return None

	try:
		reparse_buffer_raw = ctypes.create_string_buffer(MAXIMUM_REPARSE_DATA_BUFFER_SIZE)
		bytes_returned = wintypes.DWORD()
		success = DeviceIoControl(
			handle,
			FSCTL_GET_REPARSE_POINT,
			None,
			0,
			reparse_buffer_raw,
			MAXIMUM_REPARSE_DATA_BUFFER_SIZE,
			ctypes.byref(bytes_returned),
			None,
		)

		if not success:
			last_error = get_last_error()
			if last_error == ERROR_NOT_A_REPARSE_POINT:
				logger.debug("'%s' is not a reparse point", link_path)
				return None
			logger.warning("DeviceIoControl failed for '%s': %s", link_path, WinError(last_error))
			return None

		rdb = ctypes.cast(reparse_buffer_raw, ctypes.POINTER(REPARSE_DATA_BUFFER)).contents
		target_path = ""

		if rdb.ReparseTag == IO_REPARSE_TAG_SYMLINK:
			symlink_buffer = rdb.ReparseBuffer.SymbolicLinkReparseBuffer
			path_buffer_start_addr = ctypes.addressof(symlink_buffer) + type(symlink_buffer).PathBuffer.offset

			sub_name_addr = path_buffer_start_addr + symlink_buffer.SubstituteNameOffset
			sub_name_len_chars = symlink_buffer.SubstituteNameLength // ctypes.sizeof(wintypes.WCHAR)
			target_path = ctypes.wstring_at(sub_name_addr, sub_name_len_chars)

			if symlink_buffer.Flags & SYMLINK_FLAG_RELATIVE:
				link_dir = link_path.parent
				target_path = str((link_dir / target_path).absolute())

		elif rdb.ReparseTag == IO_REPARSE_TAG_MOUNT_POINT:
			mount_point_buffer = rdb.ReparseBuffer.MountPointReparseBuffer
			path_buffer_start_addr = ctypes.addressof(mount_point_buffer) + type(mount_point_buffer).PathBuffer.offset
			sub_name_addr = path_buffer_start_addr + mount_point_buffer.SubstituteNameOffset
			sub_name_len_chars = mount_point_buffer.SubstituteNameLength // ctypes.sizeof(wintypes.WCHAR)
			target_path = ctypes.wstring_at(sub_name_addr, sub_name_len_chars)

		else:
			logger.warning("Unsupported reparse tag %r for link '%s'", rdb.ReparseTag, link_path)
			return None

		# Strip "\??\" prefix if it leads to a drive letter path (e.g., \??\C:\...)
		if target_path.startswith("\\??\\") and len(target_path) > 4 and target_path[5] == ":" and target_path[6] == "\\":
			target_path = target_path[4:]
		return Path(target_path)

	except OSError as err:
		logger.warning("Error processing reparse point for '%s': %s", link_path, err)
		return None
	finally:
		CloseHandle(handle)
