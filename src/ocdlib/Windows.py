# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = = = =
   =   ocdlib.Windows                      =
   = = = = = = = = = = = = = = = = = = = = =

   opsiclientd is part of the desktop management solution opsi
   (open pc server integration) http://www.opsi.org

   Copyright (C) 2010 uib GmbH

   http://www.uib.de/

   All rights reserved.

   This program is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License version 2 as
   published by the Free Software Foundation.

   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.

   You should have received a copy of the GNU General Public License
   along with this program; if not, write to the Free Software
   Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

   @copyright:	uib GmbH <info@uib.de>
   @author: Jan Schneider <j.schneider@uib.de>
   @license: GNU General Public License version 2
"""

import sys
import threading
import time
import win32serviceutil
import win32service
import win32com.server.policy
import win32com.client
from ctypes import *

from OPSI.Logger import Logger, LOG_NONE, LOG_DEBUG
from OPSI.Types import forceBool, forceUnicode
from OPSI import System

from ocdlib.Opsiclientd import Opsiclientd

logger = Logger()

wmi = None
pythoncom = None

importWmiAndPythoncomLock = threading.Lock()
def importWmiAndPythoncom(importWmi = True, importPythoncom = True):
	global wmi
	global pythoncom
	if importWmi and not pythoncom:
		importPythoncom = True
	if not ((wmi or not importWmi) and (pythoncom or not importPythoncom)):
		logger.info(u"Need to import wmi / pythoncom")
		importWmiAndPythoncomLock.acquire()
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
			except Exception, e:
				logger.warning(u"Failed to import: %s, retrying in 2 seconds" % forceUnicode(e))
				time.sleep(2)
		importWmiAndPythoncomLock.release()

	return (wmi, pythoncom)


# from Sens.h
SENSGUID_PUBLISHER = "{5fee1bd6-5b9b-11d1-8dd2-00aa004abd5e}"
SENSGUID_EVENTCLASS_LOGON = "{d5978630-5b9f-11d1-8dd2-00aa004abd5e}"

# from EventSys.h
PROGID_EventSystem = "EventSystem.EventSystem"
PROGID_EventSubscription = "EventSystem.EventSubscription"

IID_ISensLogon = "{d597bab3-5b9f-11d1-8dd2-00aa004abd5e}"


class SensLogon(win32com.server.policy.DesignatedWrapPolicy):
	_com_interfaces_=[IID_ISensLogon]
	_public_methods_=[
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
		(wmi, pythoncom) = importWmiAndPythoncom(importWmi = False)

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


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                   OPSICLIENTD SERVICE FRAMEWORK                                   -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class OpsiclientdServiceFramework(win32serviceutil.ServiceFramework):
	_svc_name_ = "opsiclientd"
	_svc_display_name_ = "opsiclientd"
	_svc_description_ = "opsi client daemon"
	#_svc_deps_ = ['Eventlog', 'winmgmt']

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

	def ReportServiceStatus(self, serviceStatus, waitHint = 5000, win32ExitCode = 0, svcExitCode = 0):
		# Wrapping because ReportServiceStatus sometimes lets windows report a crash of opsiclientd (python 2.6.5)
		# invalid handle ...
		try:
			logger.debug('Reporting service status: {status}'.format(status=serviceStatus))
			win32serviceutil.ServiceFramework.ReportServiceStatus(
				self, serviceStatus, waitHint = waitHint, win32ExitCode = win32ExitCode, svcExitCode = svcExitCode)
		except Exception as e:
			logger.error(u"Failed to report service status %s: %s" % (serviceStatus, forceUnicode(e)))

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
		try:
			startTime = time.time()

			try:
				debugLogFile = u"c:\\tmp\\opsiclientd.log"
				try:
					if logger.getLogFile() is None:
						logger.setLogFile(debugLogFile)
					logger.setFileLevel(LOG_DEBUG)

					logger.log(1, u"Logger initialized", raiseException=True)
				except Exception as e:
					try:
						error = str(e)
					except Exception:
						error = 'unkown error'

					with open(debugLogFile, "a+") as f:
						f.write("Failed to initialize logger: %s\r\n" % error)
			except Exception:
				pass

			logger.debug(u"OpsiclientdServiceFramework SvcDoRun")

			# Write to event log
			self.ReportServiceStatus(win32service.SERVICE_START_PENDING)

			if (sys.getwindowsversion()[0] == 5):
				# NT5: XP
				self.opsiclientd = OpsiclientdNT5()

			elif (sys.getwindowsversion()[0] == 6):
				# NT6: Vista / Windows7
				if (sys.getwindowsversion()[1] >= 1):
					# Windows7
					self.opsiclientd = OpsiclientdNT61()
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

		# This call sometimes produces an error in eventlog (invalid handle)
		#self.ReportServiceStatus(win32service.SERVICE_STOPPED)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                        OPSICLIENTD NT INIT                                        -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class OpsiclientdInit(object):
	def __init__(self):
		logger.debug(u"OpsiclientdInit")
		win32serviceutil.HandleCommandLine(OpsiclientdServiceFramework)



# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                          OPSICLIENTD NT                                           -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
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
		rebootRequested = 0
		try:
			rebootRequested = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "RebootRequested")
		except Exception, e:
			logger.warning(u"Failed to get rebootRequested from registry: %s" % forceUnicode(e))
		logger.info(u"rebootRequested: %s" % rebootRequested)
		if (rebootRequested == 2):
			# Logout
			logger.info(u"Logout requested")
			self.clearRebootRequest()
			return False
		return forceBool(rebootRequested)

	def isShutdownRequested(self):
		shutdownRequested = 0
		try:
			shutdownRequested = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "ShutdownRequested")
		except Exception, e:
			logger.warning(u"Failed to get shutdownRequested from registry: %s" % forceUnicode(e))
		logger.info(u"shutdownRequested: %s" % shutdownRequested)
		return forceBool(shutdownRequested)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                          OPSICLIENTD NT5                                          -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class OpsiclientdNT5(OpsiclientdNT):
	def __init__(self):
		OpsiclientdNT.__init__(self)

	def shutdownMachine(self):
		self._isShutdownTriggered = True
		System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "ShutdownRequested", 0)
		# Running in thread to avoid failure of shutdown (device not ready)
		class _shutdownThread(threading.Thread):
			def __init__(self):
				threading.Thread.__init__(self)

			def run(self):
				while(True):
					try:
						System.shutdown(0)
						logger.notice(u"Shutdown initiated")
						break
					except Exception, e:
						# Device not ready?
						logger.info(u"Failed to initiate shutdown: %s" % forceUnicode(e))
						time.sleep(1)

		_shutdownThread().start()

	def rebootMachine(self):
		self._isRebootTriggered = True
		System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "RebootRequested", 0)
		# Running in thread to avoid failure of reboot (device not ready)
		class _rebootThread(threading.Thread):
			def __init__(self):
				threading.Thread.__init__(self)

			def run(self):
				while(True):
					try:
						System.reboot(0)
						logger.notice(u"Reboot initiated")
						break;
					except Exception, e:
						# Device not ready?
						logger.info(u"Failed to initiate reboot: %s" % forceUnicode(e))
						time.sleep(1)

		_rebootThread().start()

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                          OPSICLIENTD NT6                                          -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class OpsiclientdNT6(OpsiclientdNT):
	def __init__(self):
		OpsiclientdNT.__init__(self)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                          OPSICLIENTD NT61                                         -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class OpsiclientdNT61(OpsiclientdNT):
	def __init__(self):
		OpsiclientdNT.__init__(self)
