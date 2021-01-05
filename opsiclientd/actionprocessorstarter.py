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
		import win32ts
		import win32gui
		import ntsecuritycon

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

		session_id = win32ts.ProcessIdToSessionId(os.getpid())
		logger.notice("session_id-> %s", session_id)

		hDesktop = win32service.GetThreadDesktop(win32api.GetCurrentThreadId())
		curr_desktop_name = win32service.GetUserObjectInformation(hDesktop, win32con.UOI_NAME)
		logger.notice("curr_desktop_name-> %s", curr_desktop_name)

		window_list = hDesktop.EnumDesktopWindows()
		for window in window_list:
			logger.notice("window-> %s", win32gui.GetWindowText(window))
		
		hWinSta = win32service.GetProcessWindowStation()
		desktop_list = hWinSta.EnumDesktops()
		for desk in desktop_list:
			logger.notice("desktop-> %s", desk)
			#desk_name = win32service.GetUserObjectInformation(desk, win32con.UOI_NAME)
			#logger.notice("desktop-> %s", desk_name)
		

		startupInfo1 = win32process.STARTUPINFO()
		startupInfo1.lpDesktop = 'winsta0\\winlogon'

		"""
		procInfo = win32process.CreateProcess(
			None,
			command,
			None,
			None,
			True,
			win32con.CREATE_NEW_CONSOLE,
			None,
			None,
			startupInfo1
		)
		"""

		# maxWait = Maximum execution time in ms
		userSid = win32security.LookupAccountName(None, username)[0]
		logger.notice("userSid-> %s", userSid)

		# Login as domain user and create new session
		userToken = win32security.LogonUser(username, None, password,
											win32con.LOGON32_LOGON_INTERACTIVE,
											win32con.LOGON32_PROVIDER_DEFAULT)
		rc = win32api.GetLastError()
		if userToken is None or rc != 0:
			raise Exception(f"LogonUser failed with error {rc}")

		try:
			profileDir = win32profile.GetUserProfileDirectory(userToken)
			tokenUser = win32security.GetTokenInformation(userToken, win32security.TokenUser)

			profile = win32profile.LoadUserProfile(userToken, {"UserName": username})
			try:
				# Set access rights to window station
				#hWinSta = win32service.OpenWindowStation("winsta0", False, win32con.READ_CONTROL | win32con.WRITE_DAC )
				#hWinSta.SetProcessWindowStation()
				
				# Get security descriptor by winsta0-handle
				secDescWinSta = win32security.GetUserObjectSecurity(hWinSta, win32security.OWNER_SECURITY_INFORMATION
																				| win32security.DACL_SECURITY_INFORMATION
																				| win32con.GROUP_SECURITY_INFORMATION)
				# Get DACL from security descriptor
				daclWinSta = secDescWinSta.GetSecurityDescriptorDacl()
				if daclWinSta is None:
					logger.notice("CREATE DACL WINSTA")
					# Create DACL if not exisiting
					daclWinSta = win32security.ACL()
				
				ace_count = daclWinSta.GetAceCount()
				logger.notice("winsta ace_count: %s", ace_count)
				for i in range(0, ace_count):
					arev, aaccess, ausersid = daclWinSta.GetAce(i)
					auser, agroup, atype  = win32security.LookupAccountSid('', ausersid)
					logger.notice("winsta ace-> %s - %s - %s - %s - %s - %s", ausersid, auser, agroup, atype, arev, aaccess)
				
				# Add ACEs to DACL for specific user group
				daclWinSta.AddAccessAllowedAce(win32security.ACL_REVISION_DS, GENERIC_ACCESS, userSid)
				daclWinSta.AddAccessAllowedAce(win32security.ACL_REVISION_DS, WINSTA_ALL, userSid)
				# Set modified DACL for winsta0
				win32security.SetSecurityInfo(hWinSta, win32security.SE_WINDOW_OBJECT, win32security.DACL_SECURITY_INFORMATION,
												None, None, daclWinSta, None)
				

				#############################
				secDescWinSta = win32security.GetUserObjectSecurity(hWinSta, win32security.OWNER_SECURITY_INFORMATION
																				| win32security.DACL_SECURITY_INFORMATION
																				| win32con.GROUP_SECURITY_INFORMATION)
				daclWinSta = secDescWinSta.GetSecurityDescriptorDacl()
				ace_count = daclWinSta.GetAceCount()
				logger.notice("new winsta ace_count: %s", ace_count)
				for i in range(0, ace_count):
					arev, aaccess, ausersid = daclWinSta.GetAce(i)
					auser, agroup, atype  = win32security.LookupAccountSid('', ausersid)
					logger.notice("new winsta ace-> %s - %s - %s - %s - %s - %s", ausersid, auser, agroup, atype, arev, aaccess)
				#############################

				# Set access rights to desktop
				#hDesktop = win32service.OpenDesktop("winlogon", 0, False, win32con.READ_CONTROL
				#															| win32con.WRITE_DAC
				#															| win32con.DESKTOP_WRITEOBJECTS
				#															| win32con.DESKTOP_READOBJECTS)
				# Get security descriptor by desktop-handle
				secDescDesktop = win32security.GetUserObjectSecurity(hDesktop, win32security.OWNER_SECURITY_INFORMATION
																				| win32security.DACL_SECURITY_INFORMATION
																				| win32con.GROUP_SECURITY_INFORMATION )
				# Get DACL from security descriptor
				daclDesktop = secDescDesktop.GetSecurityDescriptorDacl()
				if daclDesktop is None:
					logger.notice("CREATE DACL DESKTOP")
					#create DACL if not exisiting
					daclDesktop = win32security.ACL()
				
				ace_count = daclDesktop.GetAceCount()
				logger.notice("desktop ace_count: %s", ace_count)
				for i in range(0, ace_count):
					arev, aaccess, ausersid = daclDesktop.GetAce(i)
					auser, agroup, atype  = win32security.LookupAccountSid('', ausersid)
					logger.notice("desktop ace-> %s - %s - %s - %s - %s - %s", ausersid, auser, agroup, atype, arev, aaccess)

				# Add ACEs to DACL for specific user group
				daclDesktop.AddAccessAllowedAce(win32security.ACL_REVISION_DS, GENERIC_ACCESS, userSid)
				daclDesktop.AddAccessAllowedAce(win32security.ACL_REVISION_DS, DESKTOP_ALL, userSid)
				# Set modified DACL for desktop
				win32security.SetSecurityInfo(hDesktop, win32security.SE_WINDOW_OBJECT, win32security.DACL_SECURITY_INFORMATION,
												None, None, daclDesktop, None)


				##############################
				secDescDesktop = win32security.GetUserObjectSecurity(hDesktop, win32security.OWNER_SECURITY_INFORMATION
																				| win32security.DACL_SECURITY_INFORMATION
																				| win32con.GROUP_SECURITY_INFORMATION )
				# Get DACL from security descriptor
				daclDesktop = secDescDesktop.GetSecurityDescriptorDacl()
				ace_count = daclDesktop.GetAceCount()
				logger.notice("new desktop ace_count: %s", ace_count)
				for i in range(0, ace_count):
					arev, aaccess, ausersid = daclDesktop.GetAce(i)
					auser, agroup, atype  = win32security.LookupAccountSid('', ausersid)
					logger.notice("new desktop ace-> %s - %s - %s - %s - %s - %s", ausersid, auser, agroup, atype, arev, aaccess)
				##############################

				# Setup stdin, stdOut and stderr
				"""
				secAttrs = win32security.SECURITY_ATTRIBUTES()
				secAttrs.bInheritHandle = 1
				stdOutRd, stdOutWr = win32pipe.CreatePipe(secAttrs, 0)
				stdErrRd, stdErrWr = win32pipe.CreatePipe(secAttrs, 0)

				ppid = win32api.GetCurrentProcess()
				tmp = win32api.DuplicateHandle(ppid, stdOutRd, ppid, 0, 0, win32con.DUPLICATE_SAME_ACCESS)
				win32file.CloseHandle(stdOutRd)
				stdOutRd = tmp
				"""
				environment = win32profile.CreateEnvironmentBlock(userToken, False)
				logger.notice("environment-> %s", environment)

				startupInfo = win32process.STARTUPINFO()

				#startupInfo.dwFlags = win32con.STARTF_USESTDHANDLES
				#startupInfo.hStdOutput = stdOutWr
				#startupInfo.hStdError = stdErrWr
				startupInfo.lpDesktop = 'winsta0\\winlogon'

				securityAttributes = win32security.SECURITY_ATTRIBUTES()
				securityAttributes.bInheritHandle = 1
				#securityAttributes = None

				#win32security.ImpersonateLoggedOnUser(userToken)

				#System.mount(depotRemoteUrl, depotDrive, username=depotServerUsername, password=depotServerPassword)

				"""
				hPToken = win32security.OpenProcessToken(
					win32api.GetCurrentProcess(),
					win32con.TOKEN_ADJUST_PRIVILEGES | win32con.TOKEN_QUERY |
					win32con.TOKEN_DUPLICATE | win32con.TOKEN_ASSIGN_PRIMARY |
					win32con.TOKEN_READ | win32con.TOKEN_WRITE
				)
				
				hUserTokenDup = win32security.DuplicateTokenEx(
					ExistingToken=hPToken,
					DesiredAccess=win32con.MAXIMUM_ALLOWED,
					ImpersonationLevel=win32security.SecurityIdentification,
					TokenType=ntsecuritycon.TokenPrimary,
					TokenAttributes=None
				)

				# Adjust Token privilege
				win32security.SetTokenInformation(hUserTokenDup, ntsecuritycon.TokenSessionId, sessionId)
				win32security.AdjustTokenPrivileges(hUserTokenDup, 0, newPrivileges)
				"""

				userTokenDup = win32security.DuplicateTokenEx(
					ExistingToken=userToken,
					DesiredAccess=win32con.MAXIMUM_ALLOWED,
					ImpersonationLevel=win32security.SecurityIdentification,
					TokenType=ntsecuritycon.TokenPrimary,
					TokenAttributes=None
				)

				newPrivileges = []
				for priv in (
					win32security.SE_CREATE_TOKEN_NAME,
					win32security.SE_ASSIGNPRIMARYTOKEN_NAME,
					win32security.SE_LOCK_MEMORY_NAME,
					win32security.SE_INCREASE_QUOTA_NAME,
					win32security.SE_UNSOLICITED_INPUT_NAME,
					win32security.SE_MACHINE_ACCOUNT_NAME,
					win32security.SE_TCB_NAME,
					win32security.SE_SECURITY_NAME,
					win32security.SE_TAKE_OWNERSHIP_NAME,
					win32security.SE_LOAD_DRIVER_NAME,
					win32security.SE_SYSTEM_PROFILE_NAME,
					win32security.SE_SYSTEMTIME_NAME,
					win32security.SE_PROF_SINGLE_PROCESS_NAME,
					win32security.SE_INC_BASE_PRIORITY_NAME,
					win32security.SE_CREATE_PAGEFILE_NAME,
					win32security.SE_CREATE_PERMANENT_NAME,
					win32security.SE_BACKUP_NAME,
					win32security.SE_RESTORE_NAME,
					win32security.SE_SHUTDOWN_NAME,
					win32security.SE_DEBUG_NAME,
					win32security.SE_AUDIT_NAME,
					win32security.SE_SYSTEM_ENVIRONMENT_NAME,
					win32security.SE_CHANGE_NOTIFY_NAME,
					win32security.SE_REMOTE_SHUTDOWN_NAME,
					win32security.SE_UNDOCK_NAME,
					win32security.SE_SYNC_AGENT_NAME,
					win32security.SE_ENABLE_DELEGATION_NAME,
					win32security.SE_MANAGE_VOLUME_NAME
				):

					priv_id = win32security.LookupPrivilegeValue(None, win32security.SE_DEBUG_NAME)
					newPrivileges.append((priv_id, priv))
				win32security.AdjustTokenPrivileges(userTokenDup, 0, newPrivileges)

				(hProcess, hThread, dwProcessId, dwThreadId) = win32process.CreateProcessAsUser(
										userTokenDup,
										None,               # appName
										command,            # commandLine
										securityAttributes,               # processAttributes
										securityAttributes,               # threadAttributes
										1,                  # bInheritHandles
										win32process.CREATE_NEW_CONSOLE, # dwCreationFlags
										environment,        # newEnvironment
										profileDir,         # currentDirectory
										startupInfo)[0]
				
				win32event.WaitForSingleObject(hProcess, 600000)

				"""
				win32file.CloseHandle(stdErrWr)
				win32file.CloseHandle(stdOutWr)
				"""

				win32security.RevertToSelf()

				"""
				# Wait for process to complete
				stdOutBuf = os.fdopen(msvcrt.open_osfhandle(stdOutRd, 0), "rb")
				stdErrBuf = os.fdopen(msvcrt.open_osfhandle(stdErrRd, 0), "rb")
				win32event.WaitForSingleObject(hPrc, maxWait)
				stdOut = stdOutBuf.read()
				stdErr = stdErrBuf.read()
				"""

				rc = win32process.GetExitCodeProcess(hPrc)
				
				logger.notice(rc)
				#logger.notice(stdOut.decode("utf-8"))
				#logger.notice(stdErr.decode("utf-8"))
			
			finally:
				win32profile.UnloadUserProfile(userToken, profile)
		finally:
			userToken.close()
	
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
			return runAsTest("cmd.exe", runAsUser, runAsPassword, maxWait=120000)
		
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
