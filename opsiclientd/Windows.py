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
Functionality to work on Windows.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:author: Erol Ueluekmen <e.ueluekmen@uib.de>
:license: GNU Affero General Public License version 3
"""

import os
import sys
import threading
import tempfile
import time
import psutil
import win32con
import win32gui
import win32service
import win32serviceutil
import win32com.server.policy
import win32com.client
import win32api
import win32security
import ntsecuritycon
import win32process
import servicemanager

import opsicommon.logging
from opsicommon.logging import logger, logging_config, LOG_NONE, LOG_DEBUG, LOG_ERROR
from OPSI.Types import forceBool, forceUnicode
from OPSI import System

from opsiclientd.Opsiclientd import Opsiclientd, OpsiclientdInit

# from Sens.h
SENSGUID_PUBLISHER = "{5fee1bd6-5b9b-11d1-8dd2-00aa004abd5e}"
SENSGUID_EVENTCLASS_LOGON = "{d5978630-5b9f-11d1-8dd2-00aa004abd5e}"

# from EventSys.h
PROGID_EventSystem = "EventSystem.EventSystem"
PROGID_EventSubscription = "EventSystem.EventSubscription"

IID_ISensLogon = "{d597bab3-5b9f-11d1-8dd2-00aa004abd5e}"

#logger = Logger()

import wmi
import pythoncom

def importWmiAndPythoncom(importWmi=True, importPythoncom=True):
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


def run_as_system(command):
	currentProcess = win32api.OpenProcess(win32con.MAXIMUM_ALLOWED, False, os.getpid())
	currentProcessToken = win32security.OpenProcessToken(currentProcess, win32con.MAXIMUM_ALLOWED)
	duplicatedCurrentProcessToken = win32security.DuplicateTokenEx(
		ExistingToken=currentProcessToken,
		DesiredAccess=win32con.MAXIMUM_ALLOWED,
		ImpersonationLevel=win32security.SecurityImpersonation,
		TokenType=ntsecuritycon.TokenImpersonation,
		TokenAttributes=None
	)
	id = win32security.LookupPrivilegeValue(None, win32security.SE_DEBUG_NAME)
	newprivs = [(id, win32security.SE_PRIVILEGE_ENABLED)]
	win32security.AdjustTokenPrivileges(duplicatedCurrentProcessToken, False, newprivs)

	win32security.SetThreadToken(win32api.GetCurrentThread(), duplicatedCurrentProcessToken)

	currentProcessToken = win32security.OpenThreadToken(win32api.GetCurrentThread(), win32con.MAXIMUM_ALLOWED, False)
	sessionId = win32security.GetTokenInformation(currentProcessToken, ntsecuritycon.TokenSessionId)
	
	pid = None
	for proc in psutil.process_iter():
		try:
			if proc.name() == "lsass.exe":
				pid = proc.pid
				break
		except psutil.AccessDenied:
			pass
	if not pid:
		raise RuntimeError("Failed to get pid of lsass.exe")
	
	lsassProcess = win32api.OpenProcess(win32con.MAXIMUM_ALLOWED, False, pid)
	lsassProcessToken = win32security.OpenProcessToken(
		lsassProcess,
		win32con.MAXIMUM_ALLOWED
	)

	systemToken = win32security.DuplicateTokenEx(
		ExistingToken=lsassProcessToken,
		DesiredAccess=win32con.MAXIMUM_ALLOWED,
		ImpersonationLevel=win32security.SecurityImpersonation,
		TokenType=ntsecuritycon.TokenImpersonation,
		TokenAttributes=None
	)
	
	privs = win32security.GetTokenInformation(systemToken, ntsecuritycon.TokenPrivileges)
	newprivs = []
	# enable all privileges
	for privtuple in privs:
		newprivs.append((privtuple[0], win32security.SE_PRIVILEGE_ENABLED))
	privs = tuple(newprivs)
	win32security.AdjustTokenPrivileges(systemToken, False, newprivs) 
	
	win32security.SetThreadToken(win32api.GetCurrentThread(), systemToken)
	
	hToken = win32security.DuplicateTokenEx(
		ExistingToken=lsassProcessToken,
		DesiredAccess=win32con.MAXIMUM_ALLOWED,
		ImpersonationLevel=win32security.SecurityImpersonation,
		TokenType=ntsecuritycon.TokenPrimary,
		TokenAttributes=None
	)
	win32security.SetTokenInformation(hToken, ntsecuritycon.TokenSessionId, sessionId)
	
	privs = win32security.GetTokenInformation(hToken, ntsecuritycon.TokenPrivileges)
	newprivs = []
	# enable all privileges
	for privtuple in privs:
		newprivs.append((privtuple[0], win32security.SE_PRIVILEGE_ENABLED))
	privs = tuple(newprivs)
	win32security.AdjustTokenPrivileges(hToken, False, newprivs) 

	s = win32process.STARTUPINFO()
	dwCreationFlags = win32con.CREATE_NEW_CONSOLE
	(hProcess, hThread, dwProcessId, dwThreadId) = win32process.CreateProcessAsUser(
		hToken, None, command, None, None, 1, dwCreationFlags, None, None, s)

class OpsiclientdWindowsInit(OpsiclientdInit):
	def __init__(self):
		try:
			super().__init__()
			parent = psutil.Process(os.getpid()).parent()
			# https://stackoverflow.com/questions/25770873/python-windows-service-pyinstaller-executables-error-1053
			#if os.environ.get("USERNAME", "$").endswith("$") and len(sys.argv) == 1:
			if parent and parent.name() == "services.exe":
				self.init_logging()
				with opsicommon.logging.log_context({'instance', 'opsiclientd'}):
					logger.essential("opsiclientd service start")
					#logger.debug(os.environ)
					servicemanager.Initialize()
					servicemanager.PrepareToHostSingle(OpsiclientdService)
					servicemanager.StartServiceCtrlDispatcher()
			else:
				if any(arg in sys.argv[1:] for arg in ("install", "update", "remove", "start", "stop", "restart")):
					win32serviceutil.HandleCommandLine(OpsiclientdService)
				else:
					if not "--elevated" in sys.argv:
						command = " ".join(sys.argv) + " --elevated"
						return run_as_system(command)
					
					sys.argv.remove("--elevated")
					options = self.parser.parse_args()
					self.init_logging(stderr_level=options.logLevel, log_filter=options.logFilter)
					with opsicommon.logging.log_context({'instance', 'opsiclientd'}):
						logger.notice("Running as user: %s", win32api.GetUserName())
						if parent:
							logger.notice("Parent process: %s (%s)", parent.name(), parent.pid)
						logger.debug(os.environ)
						opsiclientd = opsiclientd_factory()
						try:
							opsiclientd.start()
							while True:
								time.sleep(1)
						except KeyboardInterrupt:
							logger.essential("KeyboardInterrupt #1 -> stop")
							opsiclientd.stop()
							try:
								opsiclientd.join(15)
							except KeyboardInterrupt:
								logger.essential("KeyboardInterrupt #2 -> kill process")
								psutil.Process(os.getpid()).kill()
		except Exception as exc:
			logger.critical(exc, exc_info=True)

		
class OpsiclientdService(win32serviceutil.ServiceFramework):
	_svc_name_ = "opsiclientd"
	_svc_display_name_ = "opsiclientd"
	_svc_description_ = "opsi client daemon"

	def __init__(self, args):
		"""
		Initialize service and create stop event
		"""
		self.opsiclientd = None
		try:
			logging_config(stderr_level=LOG_NONE)
			
			logger.debug("OpsiclientdService initiating")
			win32serviceutil.ServiceFramework.__init__(self, args)
			self._stopEvent = threading.Event()
			logger.debug("OpsiclientdService initiated")
		except Exception as exc:
			logger.logException(exc)
			raise

	def ReportServiceStatus(self, serviceStatus, waitHint=5000, win32ExitCode=0, svcExitCode=0):
		# Wrapping because ReportServiceStatus sometimes lets windows
		# report a crash of opsiclientd (python 2.6.5) invalid handle
		try:
			logger.debug('Reporting service status: %s', serviceStatus)
			win32serviceutil.ServiceFramework.ReportServiceStatus(
				self,
				serviceStatus,
				waitHint=waitHint,
				win32ExitCode=win32ExitCode,
				svcExitCode=svcExitCode
			)
		except Exception as exc:
			logger.error("Failed to report service status %s: %s", serviceStatus, reportStatusError)

	def SvcInterrogate(self):
		logger.notice("Handling interrogate request")
		# Assume we are running, and everyone is happy.
		self.ReportServiceStatus(win32service.SERVICE_RUNNING)

	def SvcStop(self):
		"""
		Gets called from windows to stop service
		"""
		logger.notice("Handling stop request")
		# Write to event log
		self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
		# Fire stop event to stop blocking self._stopEvent.wait()
		self._stopEvent.set()

	def SvcShutdown(self):
		"""
		Gets called from windows on system shutdown
		"""
		logger.notice("Handling shutdown request")
		# Write to event log
		self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
		if self.opsiclientd:
			self.opsiclientd.systemShutdownInitiated()
		# Fire stop event to stop blocking self._stopEvent.wait()
		self._stopEvent.set()

	def SvcRun(self):
		"""
		Gets called from windows to start service
		"""
		try:
			logger.notice("Handling start request")
			startTime = time.time()
			
			# Write to event log
			self.ReportServiceStatus(win32service.SERVICE_START_PENDING)

			self.opsiclientd = opsiclientd_factory()
			
			# Write to event log
			self.ReportServiceStatus(win32service.SERVICE_RUNNING)
			logger.debug(u"Took %0.2f seconds to report service running status" % (time.time() - startTime))

			self.opsiclientd.start()

			# Wait for stop event
			self._stopEvent.wait()

			# Shutdown opsiclientd
			self.opsiclientd.stop()
			self.opsiclientd.join(15)

			logger.notice(u"opsiclientd stopped")
			for thread in threading.enumerate():
				logger.notice(u"Running thread after stop: %s" % thread)
		except Exception as e:
			logger.critical(u"opsiclientd crash")
			logger.logException(e)


class OpsiclientdNT(Opsiclientd):
	def __init__(self):
		Opsiclientd.__init__(self)

	def shutdownMachine(self):
		self._isShutdownTriggered = True
		self.clearShutdownRequest()
		System.shutdown(3)

	def rebootMachine(self):
		self._isRebootTriggered = True
		self.clearRebootRequest()
		System.reboot(3)

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
				logger.notice(u"Shutdown initiated")
				break
			except Exception as shutdownError:
				# Device not ready?
				logger.info(u"Failed to initiate shutdown: %s", forceUnicode(shutdownError))
				time.sleep(1)


class RebootThread(threading.Thread):
	def __init__(self):
		threading.Thread.__init__(self)

	def run(self):
		while True:
			try:
				System.reboot(0)
				logger.notice(u"Reboot initiated")
				break
			except Exception as rebootError:
				# Device not ready?
				logger.info(u"Failed to initiate reboot: %s", forceUnicode(rebootError))
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
