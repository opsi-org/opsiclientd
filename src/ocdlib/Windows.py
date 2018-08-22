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
import time
import win32serviceutil
import win32service
import win32com.server.policy
import win32com.client

from OPSI.Logger import Logger, LOG_NONE, LOG_DEBUG
from OPSI.Types import forceBool, forceUnicode
from OPSI import System

from ocdlib.Opsiclientd import Opsiclientd

__all__ = ('OpsiclientdInit', )

# from Sens.h
SENSGUID_PUBLISHER = "{5fee1bd6-5b9b-11d1-8dd2-00aa004abd5e}"
SENSGUID_EVENTCLASS_LOGON = "{d5978630-5b9f-11d1-8dd2-00aa004abd5e}"

# from EventSys.h
PROGID_EventSystem = "EventSystem.EventSystem"
PROGID_EventSubscription = "EventSystem.EventSubscription"

IID_ISensLogon = "{d597bab3-5b9f-11d1-8dd2-00aa004abd5e}"

logger = Logger()

wmi = None
pythoncom = None
importWmiAndPythoncomLock = threading.Lock()


def importWmiAndPythoncom(importWmi=True, importPythoncom=True):
	global wmi
	global pythoncom
	if importWmi and not pythoncom:
		importPythoncom = True

	if not ((wmi or not importWmi) and (pythoncom or not importPythoncom)):
		logger.info(u"Need to import wmi / pythoncom")
		with importWmiAndPythoncomLock:
			while not ((wmi or not importWmi) and (pythoncom or not importPythoncom)):
				try:
					if not pythoncom and importPythoncom:
						logger.debug(u"Importing pythoncom")
						import pythoncom

					if not wmi and importWmi:
						logger.debug(u"Importing wmi")
						pythoncom.CoInitialize()
						try:
							import wmi
						finally:
							pythoncom.CoUninitialize()
				except Exception as importError:
					logger.warning(u"Failed to import: {}, retrying in 2 seconds", forceUnicode(importError))
					time.sleep(2)

	return (wmi, pythoncom)


class OpsiclientdInit(object):
	def __init__(self):
		logger.debug(u"OpsiclientdInit")
		win32serviceutil.HandleCommandLine(OpsiclientdServiceFramework)


class OpsiclientdServiceFramework(win32serviceutil.ServiceFramework):
	_svc_name_ = "opsiclientd"
	_svc_display_name_ = "opsiclientd"
	_svc_description_ = "opsi client daemon"

	def __init__(self, args):
		"""
		Initialize service and create stop event
		"""
		self.opsiclientd = None
		sys.stdout = logger.getStdout()
		sys.stderr = logger.getStderr()
		logger.setConsoleLevel(LOG_NONE)

		logger.debug(u"OpsiclientdServiceFramework initiating")
		win32serviceutil.ServiceFramework.__init__(self, args)
		self._stopEvent = threading.Event()
		logger.debug(u"OpsiclientdServiceFramework initiated")

	def ReportServiceStatus(self, serviceStatus, waitHint=5000, win32ExitCode=0, svcExitCode=0):
		# Wrapping because ReportServiceStatus sometimes lets windows
		# report a crash of opsiclientd (python 2.6.5) invalid handle
		try:
			logger.debug('Reporting service status: {}', serviceStatus)
			win32serviceutil.ServiceFramework.ReportServiceStatus(
				self,
				serviceStatus,
				waitHint=waitHint,
				win32ExitCode=win32ExitCode,
				svcExitCode=svcExitCode
			)
		except Exception as reportStatusError:
			logger.error(u"Failed to report service status {0}: {1}", serviceStatus, forceUnicode(reportStatusError))

	def SvcInterrogate(self):
		logger.debug(u"OpsiclientdServiceFramework SvcInterrogate")
		# Assume we are running, and everyone is happy.
		self.ReportServiceStatus(win32service.SERVICE_RUNNING)

	def SvcStop(self):
		"""
		Gets called from windows to stop service
		"""
		logger.debug(u"OpsiclientdServiceFramework SvcStop")
		# Write to event log
		self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
		# Fire stop event to stop blocking self._stopEvent.wait()
		self._stopEvent.set()

	def SvcShutdown(self):
		"""
		Gets called from windows on system shutdown
		"""
		logger.debug(u"OpsiclientdServiceFramework SvcShutdown")
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
		startTime = time.time()

		try:
			try:
				try:
					debugLogFile = os.path.join(System.getSystemDrive(), 'opsi.org', 'log', 'opsiclientd.log')
					if logger.getLogFile() is None:
						logger.setLogFile(debugLogFile)
					logger.setFileLevel(LOG_DEBUG)

					logger.log(1, u"Logger initialized", raiseException=True)
				except Exception as serviceRunError:
					try:
						error = str(serviceRunError)
					except Exception:
						error = 'unkown error'

					with open(debugLogFile, "a+") as f:
						f.write("Failed to initialize logger: %s\r\n" % error)
			except Exception:
				pass

			logger.debug(u"OpsiclientdServiceFramework SvcDoRun")

			# Write to event log
			self.ReportServiceStatus(win32service.SERVICE_START_PENDING)

			windowsVersion = sys.getwindowsversion()
			if windowsVersion[0] == 5:  # NT5: XP
				self.opsiclientd = OpsiclientdNT5()
			elif windowsVersion[0] == 6:  # NT6: Vista / Windows7 and later
				if windowsVersion[1] >= 3:  # Windows8.1 or newer
					self.opsiclientd = OpsiclientdNT63()
				else:
					self.opsiclientd = OpsiclientdNT6()
			else:
				raise Exception(u"Running windows version not supported")

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
		except Exception, e:
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
				logger.info(u"Failed to initiate shutdown: {}", forceUnicode(shutdownError))
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
				logger.info(u"Failed to initiate reboot: {}", forceUnicode(rebootError))
				time.sleep(1)


class OpsiclientdNT6(OpsiclientdNT):
	def __init__(self):
		OpsiclientdNT.__init__(self)


class OpsiclientdNT63(OpsiclientdNT):
	"OpsiclientdNT for Windows NT 6.3 - Windows 8.1"

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
