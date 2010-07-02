# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = = = =
   =   opsiclientd.Windows                 =
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

__version__ = '4.0'

# Imports
import threading
from ctypes import *
import win32serviceutil, win32service, win32con, win32api, win32event, win32pipe, win32file, pywintypes
import win32com.server.policy
import win32com.client

# OPSI imports
from OPSI.Logger import *
from OPSI.System import *

from opsiclientd.Opsiclientd import Opsiclientd

# Get logger instance
logger = Logger()

# Globals
wmi = None
pythoncom = None


importWmiAndPythoncomLock = threading.Lock()
def importWmiAndPythoncom(importWmi = True, importPythoncom = True):
	global wmi
	global pythoncom
	if not ((wmi or not importWmi) and (pythoncom or not importPythoncom)):
		logger.info(u"Need to import wmi / pythoncom")
		importWmiAndPythoncomLock.acquire()
		while not ((wmi or not importWmi) and (pythoncom or not importPythoncom)):
			try:
				if not wmi and importWmi:
					logger.debug(u"Importing wmi")
					import wmi
				if not pythoncom and importPythoncom:
					logger.debug(u"Importing pythoncom")
					import pythoncom
			except Exception, e:
				logger.warning(u"Failed to import: %s, retrying in 2 seconds" % forceUnicode(e))
				time.sleep(2)
		importWmiAndPythoncomLock.release()


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
				win32serviceutil.ServiceFramework.ReportServiceStatus(
					self, serviceStatus, waitHint = waitHint, win32ExitCode = win32ExitCode, svcExitCode = svcExitCode)
			except Exception, e:
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
			# Fire stop event to stop blocking self._stopEvent.wait()
			self._stopEvent.set()
		
		def SvcRun(self):
			"""
			Gets called from windows to start service
			"""
			try:
				try:
					if System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SYSTEM\\CurrentControlSet\\Services\\opsiclientd", "Debug"):
						debugLogFile = "c:\\tmp\\opsiclientd.log"
						f = open(debugLogFile, "w")
						f.write(u"--- Debug log started ---\r\n")
						f.close()
						try:
							logger.setLogFile(debugLogFile)
							logger.setFileLevel(LOG_CONFIDENTIAL)
							logger.log(1, u"Logger initialized", raiseException = True)
						except Exception, e:
							error = 'unkown error'
							try:
								error = str(e)
							except:
								pass
							f = open(debugLogFile, "a+")
							f.write("Failed to initialize logger: %s\r\n" % error)
							f.close()
				except Exception, e:
					pass
				
				startTime = time.time()
				
				logger.debug(u"OpsiclientdServiceFramework SvcDoRun")
				# Write to event log
				self.ReportServiceStatus(win32service.SERVICE_START_PENDING)
				
				# Start opsiclientd
				#workingDirectory = os.getcwd()
				#try:
				#	workingDirectory = os.path.dirname(System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SYSTEM\\CurrentControlSet\\Services\\opsiclientd\\PythonClass", ""))
				#except Exception, e:
				#	logger.error(u"Failed to get working directory from registry: %s" % forceUnicode(e))
				#os.chdir(workingDirectory)
				
				if (sys.getwindowsversion()[0] == 5):
					# NT5: XP
					opsiclientd = OpsiclientdNT5()
				
				elif (sys.getwindowsversion()[0] == 6):
					# NT6: Vista / Windows7
					if (sys.getwindowsversion()[1] >= 1):
						# Windows7
						opsiclientd = OpsiclientdNT61()
					else:
						opsiclientd = OpsiclientdNT6()
				else:
					raise Exception(u"Running windows version not supported")
				
				opsiclientd.start()
				# Write to event log
				self.ReportServiceStatus(win32service.SERVICE_RUNNING)
				
				logger.debug(u"Took %0.2f seconds to report service running status" % (time.time() - startTime))
				
				# Wait for stop event
				self._stopEvent.wait()
				
				# Shutdown opsiclientd
				opsiclientd.stop()
				opsiclientd.join(15)
				
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
		self._config['system']['program_files_dir'] = System.getProgramFilesDir()
		self._config['cache_service']['storage_dir'] = '%s\\tmp\\cache_service' % System.getSystemDrive()
		self._config['cache_service']['backend_manager_config'] = self._config['system']['program_files_dir'] + '\\opsi.org\\preloginloader\\opsiclientd\\backendManager.d'
		self._config['global']['config_file'] = self._config['system']['program_files_dir'] + '\\opsi.org\\preloginloader\\opsiclientd\\opsiclientd.conf'
		
	def _shutdownMachine(self):
		self._shutdownRequested = True
		System.shutdown(3)
	
	def _rebootMachine(self):
		self._rebootRequested = True
		System.reboot(3)
	
	def processShutdownRequests(self):
		self._rebootRequested = False
		self._shutdownRequested = False
		rebootRequested = 0
		try:
			rebootRequested = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "RebootRequested")
		except Exception, e:
			logger.warning(u"Failed to get rebootRequested from registry: %s" % forceUnicode(e))
		logger.info(u"rebootRequested: %s" % rebootRequested)
		if rebootRequested:
			System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "RebootRequested", 0)
			if (rebootRequested == 2):
				# Logout
				logger.notice(u"Logout requested, nothing to do")
				pass
			else:
				# Reboot
				self._rebootRequested = True
				self._rebootMachine()
		else:
			shutdownRequested = 0
			try:
				shutdownRequested = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "ShutdownRequested")
			except Exception, e:
				logger.warning(u"Failed to get shutdownRequested from registry: %s" % forceUnicode(e))
			logger.info(u"shutdownRequested: %s" % shutdownRequested)
			if shutdownRequested:
				# Shutdown
				System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "ShutdownRequested", 0)
				self._shutdownRequested = True
				self._shutdownMachine()
	
	
	
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                          OPSICLIENTD NT5                                          -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class OpsiclientdNT5(OpsiclientdNT):
	def __init__(self):
		OpsiclientdNT.__init__(self)
		self._config['action_processor']['run_as_user'] = 'pcpatch'
		
	def _shutdownMachine(self):
		self._shutdownRequested = True
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
		
	def _rebootMachine(self):
		self._rebootRequested = True
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





