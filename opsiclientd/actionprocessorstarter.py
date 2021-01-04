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
:copyright: uib GmbH <info@uib.de>
:license: GNU Affero General Public License version 3
"""

import gettext
import locale
import os
import sys

import opsicommon.logging
from opsicommon.logging import logger, LOG_NONE
from OPSI.Backend.JSONRPC import JSONRPCBackend
from OPSI import System

from opsiclientd import __version__, DEFAULT_STDERR_LOG_FORMAT, DEFAULT_FILE_LOG_FORMAT


def runAsTest(command, username, password, maxWait=120000):
	try:
		import ctypes
		from ctypes import POINTER
		from ctypes.wintypes import HANDLE, LPVOID, WORD, DWORD, BOOL


		LPSTR = ctypes.c_char_p
		LPBYTE = LPSTR
		LPHANDLE = POINTER(HANDLE)
		LPDWORD = POINTER(DWORD)

		NULL = 0
		TRUE = 1
		FALSE = 0

		ERROR_BROKEN_PIPE = 109
		INVALID_HANDLE_VALUE = -1
		HANDLE_FLAG_INHERIT = 0x0001
		DUPLICATE_SAME_ACCESS = 0x00000002
		INFINITE = 0xFFFFFFFF
		WAIT_FAILED = 0xFFFFFFFF
		STARTF_USESTDHANDLES = 0x0100
		CREATE_NO_WINDOW = 0x08000000
		STARTF_USESHOWWINDOW = 0x00000001
		SW_HIDE = 0


		class PROCESS_INFORMATION(ctypes.Structure):
			_pack_ = 1
			_fields_ = [
				('hProcess',    HANDLE),
				('hThread',     HANDLE),
				('dwProcessId', DWORD),
				('dwThreadId',  DWORD),
			]


		class STARTUPINFO(ctypes.Structure):
			_pack_ = 1
			_fields_ = [
				('cb',              DWORD),
				('lpReserved',      DWORD),     # LPSTR
				('lpDesktop',       LPSTR),
				('lpTitle',         LPSTR),
				('dwX',             DWORD),
				('dwY',             DWORD),
				('dwXSize',         DWORD),
				('dwYSize',         DWORD),
				('dwXCountChars',   DWORD),
				('dwYCountChars',   DWORD),
				('dwFillAttribute', DWORD),
				('dwFlags',         DWORD),
				('wShowWindow',     WORD),
				('cbReserved2',     WORD),
				('lpReserved2',     DWORD),     # LPBYTE
				('hStdInput',       DWORD),
				('hStdOutput',      DWORD),
				('hStdError',       DWORD),
			]


		class SECURITY_ATTRIBUTES(ctypes.Structure):
			_fields_ = [("nLength", DWORD),
						("lpSecurityDescriptor", LPVOID),
						("bInheritHandle", BOOL)]

		LPSECURITY_ATTRIBUTES = POINTER(SECURITY_ATTRIBUTES)

		GetLastError = ctypes.windll.kernel32.GetLastError
		GetLastError.argtypes = []
		GetLastError.restype = DWORD

		CloseHandle = ctypes.windll.kernel32.CloseHandle
		CloseHandle.argtypes = [HANDLE]
		CloseHandle.restype = BOOL

		CreatePipe = ctypes.windll.kernel32.CreatePipe
		CreatePipe.argtypes = [POINTER(HANDLE), POINTER(HANDLE),
							LPSECURITY_ATTRIBUTES, DWORD]
		CreatePipe.restype = BOOL

		SetHandleInformation = ctypes.windll.kernel32.SetHandleInformation
		SetHandleInformation.argtypes = [HANDLE, DWORD, DWORD]
		SetHandleInformation.restype = BOOL

		DuplicateHandle = ctypes.windll.kernel32.DuplicateHandle
		DuplicateHandle.argtypes = [HANDLE, HANDLE, HANDLE, LPHANDLE,
									DWORD, BOOL, DWORD]
		DuplicateHandle.restype = BOOL

		GetCurrentProcess = ctypes.windll.kernel32.GetCurrentProcess
		GetCurrentProcess.argtypes = []
		GetCurrentProcess.restype = HANDLE

		WaitForSingleObject = ctypes.windll.kernel32.WaitForSingleObject
		WaitForSingleObject.argtypes = [HANDLE, DWORD]
		WaitForSingleObject.restype = DWORD

		ReadFile = ctypes.windll.kernel32.ReadFile
		ReadFile.argtypes = [HANDLE, LPVOID, DWORD, LPDWORD, LPVOID]
		ReadFile.restype = BOOL


		def create_pipe():
			saAttr = SECURITY_ATTRIBUTES()
			saAttr.nLength = ctypes.sizeof(saAttr)
			saAttr.bInheritHandle = True
			saAttr.lpSecurityDescriptor = None

			handles = HANDLE(), HANDLE()
			if not CreatePipe(ctypes.byref(handles[0]),
							ctypes.byref(handles[1]), ctypes.byref(saAttr), 0):
				raise ctypes.WinError()
			if not SetHandleInformation(handles[0], HANDLE_FLAG_INHERIT, 0):
				raise ctypes.WinError()

			return handles[0].value, handles[1].value


		def read_pipe(handle):
			result = ''
			# Allocate the output buffer
			data = ctypes.create_string_buffer(4096)
			while True:
				bytesRead = DWORD(0)
				if not ReadFile(handle, data, 4096,
								ctypes.byref(bytesRead), None):
					le = GetLastError()
					if le == ERROR_BROKEN_PIPE:
						break
					else:
						raise ctypes.WinError()
				s = data.value[0:bytesRead.value]
				result += s.decode('utf_8', 'replace')
			return result


		def CreateProcessWithLogonW(lpUsername=None, lpDomain=None,
									lpPassword=None, dwLogonFlags=0,
									lpApplicationName=None, lpCommandLine=None,
									dwCreationFlags=0, lpEnvironment=None,
									lpCurrentDirectory=None, lpStartupInfo=None):
			if not lpUsername:
				lpUsername = NULL
			else:
				lpUsername = ctypes.c_wchar_p(lpUsername)
			if not lpDomain:
				lpDomain = NULL
			else:
				lpDomain = ctypes.c_wchar_p(lpDomain)
			if not lpPassword:
				lpPassword = NULL
			else:
				lpPassword = ctypes.c_wchar_p(lpPassword)
			if not lpApplicationName:
				lpApplicationName = NULL
			else:
				lpApplicationName = ctypes.c_wchar_p(lpApplicationName)
			if not lpCommandLine:
				lpCommandLine = NULL
			else:
				lpCommandLine = ctypes.create_unicode_buffer(lpCommandLine)
			if not lpEnvironment:
				lpEnvironment = NULL
			else:
				lpEnvironment = ctypes.c_wchar_p(lpEnvironment)
			if not lpCurrentDirectory:
				lpCurrentDirectory = NULL
			else:
				lpCurrentDirectory = ctypes.c_wchar_p(lpCurrentDirectory)

			if not lpStartupInfo:
				p_hstdout, c_hstdout = create_pipe()
				p_hstderr, c_hstderr = create_pipe()

				lpStartupInfo = STARTUPINFO()
				lpStartupInfo.cb = ctypes.sizeof(STARTUPINFO)
				lpStartupInfo.lpReserved = 0
				lpStartupInfo.lpDesktop = 0
				lpStartupInfo.lpTitle = 0
				lpStartupInfo.dwFlags = STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW
				lpStartupInfo.cbReserved2 = 0
				lpStartupInfo.lpReserved2 = 0
				lpStartupInfo.hStdOutput = c_hstdout
				lpStartupInfo.hStdError = c_hstderr
				lpStartupInfo.wShowWindow = SW_HIDE

			lpProcessInformation = PROCESS_INFORMATION()
			lpProcessInformation.hProcess = INVALID_HANDLE_VALUE
			lpProcessInformation.hThread = INVALID_HANDLE_VALUE
			lpProcessInformation.dwProcessId = 0
			lpProcessInformation.dwThreadId = 0

			if not ctypes.windll.advapi32.CreateProcessWithLogonW(
					lpUsername, lpDomain, lpPassword, dwLogonFlags, lpApplicationName,
					ctypes.byref(lpCommandLine), dwCreationFlags, lpEnvironment,
					lpCurrentDirectory, ctypes.byref(lpStartupInfo),
					ctypes.byref(lpProcessInformation)):

				raise ctypes.WinError()

			res = WaitForSingleObject(lpProcessInformation.hProcess, INFINITE)
			if res == WAIT_FAILED:
				raise ctypes.WinError()

			CloseHandle(c_hstdout)
			out = read_pipe(p_hstdout)
			CloseHandle(p_hstdout)
			CloseHandle(c_hstderr)
			err = read_pipe(p_hstderr)
			CloseHandle(p_hstderr)
			return out, err
		
		CreateProcessWithLogonW(username, None, password, 0, command, command)
	except Exception as e:
		logger.error(e, exc_info=True)
		raise

def runAsTest2(command, username, password, maxWait=120000):
	try:
		import os
		import msvcrt
		import win32security
		import win32con
		import win32pipe
		import win32process
		import win32api
		import win32net
		import win32file
		import win32event
		import win32profile
		import win32service

		#user_info = self.opsiclientd.createOpsiSetupAdmin()

		GENERIC_ACCESS = win32con.GENERIC_READ | win32con.GENERIC_WRITE | win32con.GENERIC_EXECUTE | win32con.GENERIC_ALL

		WINSTA_ALL = (win32con.WINSTA_ACCESSCLIPBOARD  | win32con.WINSTA_ACCESSGLOBALATOMS | \
		win32con.WINSTA_CREATEDESKTOP    | win32con.WINSTA_ENUMDESKTOPS      | \
		win32con.WINSTA_ENUMERATE        | win32con.WINSTA_EXITWINDOWS       | \
		win32con.WINSTA_READATTRIBUTES   | win32con.WINSTA_READSCREEN        | \
		win32con.WINSTA_WRITEATTRIBUTES  | win32con.DELETE                   | \
		win32con.READ_CONTROL            | win32con.WRITE_DAC                | \
		win32con.WRITE_OWNER)

		DESKTOP_ALL = (win32con.DESKTOP_CREATEMENU      | win32con.DESKTOP_CREATEWINDOW  | \
		win32con.DESKTOP_ENUMERATE       | win32con.DESKTOP_HOOKCONTROL   | \
		win32con.DESKTOP_JOURNALPLAYBACK | win32con.DESKTOP_JOURNALRECORD | \
		win32con.DESKTOP_READOBJECTS     | win32con.DESKTOP_SWITCHDESKTOP | \
		win32con.DESKTOP_WRITEOBJECTS    | win32con.DELETE                | \
		win32con.READ_CONTROL            | win32con.WRITE_DAC             | \
		win32con.WRITE_OWNER)

		# maxWait = Maximum execution time in ms
		userSid = win32security.LookupAccountName(None, username)[0]
		# Login as domain user and create new session
		userToken = win32security.LogonUser(username, None, password,
											win32con.LOGON32_LOGON_INTERACTIVE,
											win32con.LOGON32_PROVIDER_DEFAULT)
		rc = win32api.GetLastError()
		if userToken is None or rc != 0:
			raise Exception(f"LogonUser failed with error {rc}")
		profileDir = win32profile.GetUserProfileDirectory(userToken)
		tokenUser = win32security.GetTokenInformation(userToken, win32security.TokenUser)

		# Set access rights to window station
		hWinSta = win32service.OpenWindowStation("winsta0", False, win32con.READ_CONTROL | win32con.WRITE_DAC )
		# Get security descriptor by winsta0-handle
		secDescWinSta = win32security.GetUserObjectSecurity(hWinSta, win32security.OWNER_SECURITY_INFORMATION
																		| win32security.DACL_SECURITY_INFORMATION
																		| win32con.GROUP_SECURITY_INFORMATION)
		# Get DACL from security descriptor
		daclWinSta = secDescWinSta.GetSecurityDescriptorDacl()
		if daclWinSta is None:
			# Create DACL if not exisiting
			daclWinSta = win32security.ACL()
		# Add ACEs to DACL for specific user group
		daclWinSta.AddAccessAllowedAce(win32security.ACL_REVISION_DS, GENERIC_ACCESS, userSid)
		daclWinSta.AddAccessAllowedAce(win32security.ACL_REVISION_DS, WINSTA_ALL, userSid)
		# Set modified DACL for winsta0
		win32security.SetSecurityInfo(hWinSta, win32security.SE_WINDOW_OBJECT, win32security.DACL_SECURITY_INFORMATION,
										None, None, daclWinSta, None)

		# Set access rights to desktop
		hDesktop = win32service.OpenDesktop("default", 0, False, win32con.READ_CONTROL
																	| win32con.WRITE_DAC
																	| win32con.DESKTOP_WRITEOBJECTS
																	| win32con.DESKTOP_READOBJECTS)
		# Get security descriptor by desktop-handle
		secDescDesktop = win32security.GetUserObjectSecurity(hDesktop, win32security.OWNER_SECURITY_INFORMATION
																		| win32security.DACL_SECURITY_INFORMATION
																		| win32con.GROUP_SECURITY_INFORMATION )
		# Get DACL from security descriptor
		daclDesktop = secDescDesktop.GetSecurityDescriptorDacl()
		if daclDesktop is None:
			#create DACL if not exisiting
			daclDesktop = win32security.ACL()
		# Add ACEs to DACL for specific user group
		daclDesktop.AddAccessAllowedAce(win32security.ACL_REVISION_DS, GENERIC_ACCESS, userSid)
		daclDesktop.AddAccessAllowedAce(win32security.ACL_REVISION_DS, DESKTOP_ALL, userSid)
		# Set modified DACL for desktop
		win32security.SetSecurityInfo(hDesktop, win32security.SE_WINDOW_OBJECT, win32security.DACL_SECURITY_INFORMATION,
										None, None, daclDesktop, None)

		# Setup stdin, stdOut and stderr
		secAttrs = win32security.SECURITY_ATTRIBUTES()
		secAttrs.bInheritHandle = 1
		stdOutRd, stdOutWr = win32pipe.CreatePipe(secAttrs, 0)
		stdErrRd, stdErrWr = win32pipe.CreatePipe(secAttrs, 0)

		ppid = win32api.GetCurrentProcess()
		tmp = win32api.DuplicateHandle(ppid, stdOutRd, ppid, 0, 0, win32con.DUPLICATE_SAME_ACCESS)
		win32file.CloseHandle(stdOutRd)
		stdOutRd = tmp

		environment = win32profile.CreateEnvironmentBlock(userToken, False)

		startupInfo = win32process.STARTUPINFO()
		startupInfo.dwFlags = win32con.STARTF_USESTDHANDLES
		startupInfo.hStdOutput = stdOutWr
		startupInfo.hStdError = stdErrWr

		#win32security.ImpersonateLoggedOnUser(userToken)

		#System.mount(depotRemoteUrl, depotDrive, username=depotServerUsername, password=depotServerPassword)

		hPrc = win32process.CreateProcessAsUser(
								userToken,
								None,               # appName
								command,            # commandLine
								None,               # processAttributes
								None,               # threadAttributes
								1,                  # bInheritHandles
								win32process.CREATE_NEW_CONSOLE, # dwCreationFlags
								environment,        # newEnvironment
								profileDir,         # currentDirectory
								startupInfo)[0]

		win32file.CloseHandle(stdErrWr)
		win32file.CloseHandle(stdOutWr)
		win32security.RevertToSelf()

		# Wait for process to complete
		stdOutBuf = os.fdopen(msvcrt.open_osfhandle(stdOutRd, 0), "rb")
		stdErrBuf = os.fdopen(msvcrt.open_osfhandle(stdErrRd, 0), "rb")
		win32event.WaitForSingleObject(hPrc, maxWait)
		stdOut = stdOutBuf.read()
		stdErr = stdErrBuf.read()
		rc = win32process.GetExitCodeProcess(hPrc)

		logger.notice(rc)
		logger.notice(stdOut.decode("utf-8"))
		logger.notice(stdErr.decode("utf-8"))
	except Exception as e:
		logger.error(e, exc_info=True)
		raise

def main():
	if len(sys.argv) != 17:
		print(
			f"Usage: {os.path.basename(sys.argv[0])} <hostId> <hostKey> <controlServerPort>"
			" <logFile> <logLevel> <depotRemoteUrl> <depotDrive> <depotServerUsername> <depotServerPassword>"
			" <sessionId> <actionProcessorDesktop> <actionProcessorCommand> <actionProcessorTimeout>"
			" <runAsUser> <runAsPassword> <createEnvironment>"
		)
		sys.exit(1)

	(
		hostId, hostKey, controlServerPort, logFile, logLevel, depotRemoteUrl,
		depotDrive, depotServerUsername, depotServerPassword, sessionId,
		actionProcessorDesktop, actionProcessorCommand, actionProcessorTimeout,
		runAsUser, runAsPassword, createEnvironment
	) = sys.argv[1:]

	if hostKey:
		logger.addConfidentialString(hostKey)
	if depotServerPassword:
		logger.addConfidentialString(depotServerPassword)
	if runAsPassword:
		logger.addConfidentialString(runAsPassword)

	opsicommon.logging.init_logging(
		stderr_level=LOG_NONE,
		stderr_format=DEFAULT_STDERR_LOG_FORMAT,
		log_file=logFile,
		file_level=int(logLevel),
		file_format=DEFAULT_FILE_LOG_FORMAT
	)
	
	with opsicommon.logging.log_context({'instance' : os.path.basename(sys.argv[0])}):
		logger.debug(
			"Called with arguments: %s",
			', '.join((
				hostId, hostKey, controlServerPort, logFile, logLevel, depotRemoteUrl,
				depotDrive, depotServerUsername, depotServerPassword, sessionId,
				actionProcessorDesktop, actionProcessorCommand, actionProcessorTimeout,
				runAsUser, runAsPassword, createEnvironment
			))
		)
		
		try:
			lang = locale.getdefaultlocale()[0].split('_')[0]
			localeDir = os.path.join(os.path.dirname(sys.argv[0]), 'locale')
			translation = gettext.translation('opsiclientd', localeDir, [lang])
			_ = translation.gettext
		except Exception as error:
			logger.debug("Failed to load locale for %s from %s: %s", lang, localeDir, error)
			
			def _(string):
				return string

		if runAsUser:
			return runAsTest("C:\\Windows\\System32\\cmd.exe", runAsUser, runAsPassword, maxWait=120000)
		
		if runAsUser and createEnvironment.lower() in ('yes', 'true', '1'):
			createEnvironment = True
		else:
			createEnvironment = False
		actionProcessorTimeout = int(actionProcessorTimeout)
		imp = None
		depotShareMounted = False
		be = None

		try:
			be = JSONRPCBackend(username=hostId, password=hostKey, address=f"https://localhost:{controlServerPort}/opsiclientd")

			if runAsUser:
				logger.info("Impersonating user '%s'", runAsUser)
				imp = System.Impersonate(username=runAsUser, password=runAsPassword, desktop=actionProcessorDesktop)
				imp.start(logonType="INTERACTIVE", newDesktop=False, createEnvironment=createEnvironment)
			else:
				logger.info("Impersonating network account '%s'", depotServerUsername)
				imp = System.Impersonate(username=depotServerUsername, password=depotServerPassword, desktop=actionProcessorDesktop)
				imp.start(logonType="NEW_CREDENTIALS")

			if depotRemoteUrl.split('/')[2] not in ("127.0.0.1", "localhost"):
				logger.notice("Mounting depot share %s", depotRemoteUrl)
				be.setStatusMessage(sessionId, _("Mounting depot share %s") % depotRemoteUrl)

				if runAsUser:
					System.mount(depotRemoteUrl, depotDrive, username=depotServerUsername, password=depotServerPassword)
				else:
					System.mount(depotRemoteUrl, depotDrive)
				depotShareMounted = True

			logger.notice("Starting action processor")
			be.setStatusMessage(sessionId, _("Action processor is running"))

			imp.runCommand(actionProcessorCommand, timeoutSeconds=actionProcessorTimeout)

			logger.notice("Action processor ended")
			be.setStatusMessage(sessionId, _("Action processor ended"))
		except Exception as e:
			logger.logException(e)
			error = f"Failed to process action requests: {e}"
			if be:
				try:
					be.setStatusMessage(sessionId, error)
				except:
					pass
			logger.error(error)

		if depotShareMounted:
			try:
				logger.notice("Unmounting depot share")
				System.umount(depotDrive)
			except:
				pass
		if imp:
			try:
				imp.end()
			except:
				pass

		if be:
			try:
				be.backend_exit()
			except:
				pass
