#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = = = =
   =   opsi client daemon (opsiclientd)    =
   = = = = = = = = = = = = = = = = = = = = =
   
   opsiclientd is part of the desktop management solution opsi
   (open pc server integration) http://www.opsi.org
   
   Copyright (C) 2008 uib GmbH
   
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

__version__ = '0.5.7'

# Imports
import os, sys, threading, time, json, urllib, base64, socket, re, shutil, filecmp
import copy as pycopy
from OpenSSL import SSL

if (os.name == 'posix'):
	from signal import *
	import getopt
	# We need a faked win32serviceutil class
	class win32serviceutil:
		ServiceFramework = object

if (os.name == 'nt'):
	import win32serviceutil, win32service
	from ctypes import *

# Twisted imports
from twisted.internet import defer, threads, reactor
from OPSI.web2 import resource, stream, server, http, responsecode, static
from OPSI.web2.channel.http import HTTPFactory
from twisted.python.failure import Failure

# OPSI imports
from OPSI.Logger import *
from OPSI.Util import *
from OPSI import Tools
from OPSI import System
from OPSI.Backend.Backend import BackendIOError
from OPSI.Backend.File import File
from OPSI.Backend.JSONRPC import JSONRPCBackend
from OPSI.Backend.File31 import File31Backend
from OPSI.Backend.Offline import OfflineBackend
from OPSI.Backend.BackendManager import BackendManager

# Create logger instance
logger = Logger()
logger.setLogFormat('[%l] [%D]   %M     (%F|%N)')

# Possible event types
EVENT_TYPE_PRODUCT_SYNC_COMPLETED = 'product sync completed'
EVENT_TYPE_DAEMON_STARTUP = 'daemon startup'
EVENT_TYPE_DAEMON_SHUTDOWN = 'daemon shutdown'
EVENT_TYPE_GUI_STARTUP = 'gui startup'
EVENT_TYPE_PANIC = 'panic event'
EVENT_TYPE_PROCESS_ACTION_REQUESTS = 'process action requests'
EVENT_TYPE_TIMER = 'timer'
EVENT_TYPE_CUSTOM = 'custom'

# Message translation
def _(msg):
	return msg



'''
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
=                                             EXEPTIONS                                               =
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
=                                                                                                     =
=                                         Exception classes.                                          =
=                                                                                                     =
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
'''
class opsiclientdError(Exception):
	""" Base class for opsiclientd exceptions. """
	
	ExceptionShortDescription = "Opsiclientd error"
	
	def __init__(self, message = None):
		self.message = message
	
	def __str__(self):
		return str(self.message)
	
	def complete_message(self):
		if self.message:
			return "%s: %s" % (self.ExceptionShortDescription, self.message)
		else:
			return "%s" % self.ExceptionShortDescription


class CanceledByUserError(opsiclientdError):
	""" Exception raised if user cancels operation. """
	ExceptionShortDescription = "Canceled by user error"





'''
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
=                                               EVENTS                                                =
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
=                                                                                                     =
=                          Classes needed for creating and handling events.                           =
=                                                                                                     =
=  The main event class is "Event", the derived classes are:                                          =
=     DaemonStartupEvent:         This event is triggered on opsiclientd statup                       =
=     DaemonShutdownEvent:        This event is triggered on opsiclientd shutdown                     =
=     ProcessActionRequestEvent:  If this event is triggered action request are processed             =
=     TimerEvent:                 This event is triggered every x seconds                             =
=                                                                                                     =
=  The class "EventListener" is an base class for classes which should handle events                  =
=                                                                                                     =
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
'''

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                            EVENT                                                  -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class Event(threading.Thread):
	def __init__(self, type, name, **kwargs):
		threading.Thread.__init__(self)
		
		if not type in (EVENT_TYPE_PRODUCT_SYNC_COMPLETED, EVENT_TYPE_DAEMON_STARTUP, EVENT_TYPE_DAEMON_SHUTDOWN, EVENT_TYPE_GUI_STARTUP,
				EVENT_TYPE_TIMER, EVENT_TYPE_PROCESS_ACTION_REQUESTS, EVENT_TYPE_CUSTOM, EVENT_TYPE_PANIC):
			raise TypeError("Unknown event type '%s'" % type)
		if not name:
			raise TypeError("Name not given")
		
		self.__dict__.update(kwargs)
		self._type = type
		self._name = name
		self._occured = 0
		self._eventListeners = []
		
		logger.setLogFormat('[%l] [%D] [event ' + str(self._name) + ']   %M  (%F|%N)', object=self)
		
		self.message = str(self.__dict__.get('message', ''))
		
		self.maxRepetitions = int(self.__dict__.get('maxRepetitions', -1))
		# wait <activationDelay> seconds before event gets active
		self.activationDelay = int(self.__dict__.get('activationDelay', 0))
		# wait <notificationDelay> seconds before event is fired
		self.notificationDelay = int(self.__dict__.get('notificationDelay', 0))
		self.warningTime = int(self.__dict__.get('warningTime', 0))
		
		# wql
		self.wql = str(self.__dict__.get('wql', ''))
		self.wqlResult = None
		#if self._type is EVENT_TYPE_CUSTOM and not self.wql:
		#	raise Exception("Custom event needs wql param")
		if (not self._type is EVENT_TYPE_CUSTOM) and self.wql:
			logger.error("Ignoring wql param because event type is '%s'" % self._type)
			self.wql = ''
		
		self.userCancelable = bool(self.__dict__.get('userCancelable', False))
		self.blockLogin = bool(self.__dict__.get('blockLogin', False))
		self.logoffCurrentUser = bool(self.__dict__.get('logoffCurrentUser', False))
		self.lockWorkstation = bool(self.__dict__.get('lockWorkstation', False))
		self.getConfigFromService = bool(self.__dict__.get('getConfigFromService', True))
		self.updateConfigFile = bool(self.__dict__.get('updateConfigFile', True))
		self.writeLogToService = bool(self.__dict__.get('writeLogToService', True))
		self.updateActionProcessor = bool(self.__dict__.get('updateActionProcessor', True))
		
		self.eventNotifierCommand = str(self.__dict__.get('eventNotifierCommand'))
		
		self.eventNotifierDesktop = str(self.__dict__.get('eventNotifierDesktop', 'current'))
		if not self.eventNotifierDesktop in ('winlogon', 'default', 'current'):
			logger.error("Bad value '%s' for eventNotifierDesktop" % self.eventNotifierDesktop)
			self.eventNotifierDesktop = 'current'
		
		self.actionNotifierCommand = str(self.__dict__.get('actionNotifierCommand'))
		
		self.actionNotifierDesktop = str(self.__dict__.get('actionNotifierDesktop', 'current'))
		if not self.actionNotifierDesktop in ('winlogon', 'default', 'current'):
			logger.error("Bad value '%s' for actionNotifierDesktop" % self.actionNotifierDesktop)
			self.actionNotifierDesktop = 'current'
		
		self.actionProcessorCommand = str(self.__dict__.get('actionProcessorCommand'))
		
		self.actionProcessorDesktop = str(self.__dict__.get('actionProcessorDesktop', 'current'))
		if not self.actionProcessorDesktop in ('winlogon', 'default', 'current'):
			logger.error("Bad value '%s' for actionProcessorDesktop" % self.actionProcessorDesktop)
			self.actionProcessorDesktop = 'current'
		
		self.serviceOptions = self.__dict__.get('serviceOptions', {})
		
		self.cacheProducts = bool(self.__dict__.get('cacheProducts', False))
		self.cacheMaxBandwidth = int(self.__dict__.get('cacheMaxBandwidth', 0))
		self.requiresCachedProducts = bool(self.__dict__.get('requiresCachedProducts', False))
		self.syncConfig = bool(self.__dict__.get('syncConfig', False))
		self.useCachedConfig = bool(self.__dict__.get('useCachedConfig', False))
		
	def __str__(self):
		return "<event: %s>" % self._name
	
	def getType(self):
		return self._type
	
	def getName(self):
		return self._name
	
	def activate(self):
		return
	
	def run(self):
		try:
			while (self.maxRepetitions < 0) or (self._occured <= self.maxRepetitions):
				if (self.activationDelay > 0):
					logger.debug("Waiting %d seconds before activation of event '%s'" % (self.activationDelay, self))
					time.sleep(self.activationDelay)
				logger.info("Activating event '%s'" % self)
				self.activate()
				logger.info("Event '%s' occured" % self)
				if (self.notificationDelay > 0):
					logger.debug("Waiting %d seconds before firing event '%s'" % (self.notificationDelay, self))
					time.sleep(self.notificationDelay)
				self.fire()
			logger.info("Event '%s' now deactivated after %d occurrences" % (self, self._occured))
		except Exception, e:
			logger.error("Failure in event '%s': %s" % (self, e))
			logger.logException(e)
		
	def addEventListener(self, eventListener):
		if not isinstance(eventListener, EventListener):
			raise TypeError("Failed to add event listener, got class %s, need class EventListener" % eventListener.__class__)
		
		for l in self._eventListeners:
			if (l == eventListener):
				return
		
		self._eventListeners.append(eventListener)
		
	def fire(self):
		class ProcessEventThread(threading.Thread):
			def __init__(self, eventListener, event):
				threading.Thread.__init__(self)
				self._eventListener = eventListener
				self._event = event
			
			def run(self):
				try:
					self._eventListener.processEvent(self._event)
				except Exception, e:
					logger.logException(e)
		
		logger.notice("Firing event '%s'" % self)
		self._occured += 1
		for l in self._eventListeners:
			# Create a new thread for each event listener
			ProcessEventThread(l, self).start()


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                            PANIC EVENT                                            -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class PanicEvent(Event):
	def __init__(self, name):
		Event.__init__(self, EVENT_TYPE_PANIC, name)
		self.maxRepetitions = -1
		self.message = 'Panic event'
		self.activationDelay = 0
		self.notificationDelay = 0
		self.warningTime = 0
		self.userCancelable = False
		self.blockLogin = False
		self.logoffCurrentUser = False
		self.lockWorkstation = False
		self.getConfigFromService = False
		self.updateConfigFile = False
		self.writeLogToService = False
		self.updateActionProcessor = False
		self.eventNotifierCommand = None
		self.actionNotifierCommand = None
		self.actionProcessorDesktop = 'winlogon'
		self.serviceOptions = {}
	
	def activate(self):
		e = threading.Event()
		e.wait()

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                        SYNC COMPLETED EVENT                                       -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ProductSyncCompletedEvent(Event):
	def __init__(self, name, **kwargs):
		Event.__init__(self, EVENT_TYPE_PRODUCT_SYNC_COMPLETED, name, **kwargs)
	
	def activate(self):
		e = threading.Event()
		e.wait()

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                        DAEMON STARTUP EVENT                                       -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class DaemonStartupEvent(Event):
	def __init__(self, name, **kwargs):
		Event.__init__(self, EVENT_TYPE_DAEMON_STARTUP, name, **kwargs)
		self.maxRepetitions = 0
	
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                       DAEMON SHUTDOWN EVENT                                       -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class DaemonShutdownEvent(Event):
	def __init__(self, name, **kwargs):
		Event.__init__(self, EVENT_TYPE_DAEMON_SHUTDOWN, name, **kwargs)
		self.maxRepetitions = 0
	
	def activate(self):
		e = threading.Event()
		e.wait()

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                         GUI STARTUP EVENT                                         -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class GUIStartupEvent(Event):
	def __init__(self, name, **kwargs):
		Event.__init__(self, EVENT_TYPE_GUI_STARTUP, name, **kwargs)
		self.maxRepetitions = 0
		self.processName = None
		if   (os.name == 'nt') and (sys.getwindowsversion()[0] == 5):
			self.processName = 'winlogon.exe'
		elif (os.name == 'nt') and (sys.getwindowsversion()[0] == 6):
			self.processName = 'LogonUI.exe'
		if self.processName:
			self.wql = "SELECT * FROM __InstanceCreationEvent WITHIN 5 WHERE TargetInstance ISA 'Win32_Process' AND TargetInstance.Name = '%s'" % self.processName
		
	def activate(self):
		if self.wql:
			(wmi, pythoncom) = (None, None)
			while True:
				try:
					import wmi, pythoncom
					break
				except Exception, e:
					logger.warning("Failed to import: %s, retrying in 2 seconds" % e)
					sleep(2)
			pythoncom.CoInitialize()
			try:
				c = wmi.WMI()
				watcher = c.watch_for(raw_wql=self.wql, wmi_class='')
				if self.processName and System.getPid(self.processName):
					logger.info("Process '%s' is running on activation of event %s => firing" % (self.processName, self))
					return
				logger.info("watching for wql: %s" % self.wql)
				self.wqlResult = watcher()
				logger.info("got wmi object: %s" % self.wqlResult)
			except Exception, e:
				logger.error("Failed to activate event '%s': %s" % (self, e))
				pythoncom.CoUninitialize()
				raise
			pythoncom.CoUninitialize()
		else:
			# Not yet supported
			return
		
	
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                   PROCESS ACTION REQUESTS EVENT                                   -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ProcessActionRequestEvent(Event):
	def __init__(self, name, **kwargs):
		Event.__init__(self, EVENT_TYPE_PROCESS_ACTION_REQUESTS, name, **kwargs)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                            TIMER EVENT                                            -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class TimerEvent(Event):
	def __init__(self, name, **kwargs):
		Event.__init__(self, EVENT_TYPE_TIMER, name, **kwargs)
	
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                           CUSTOM EVENT                                            -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class CustomEvent(Event):
	def __init__(self, name, **kwargs):
		Event.__init__(self, EVENT_TYPE_CUSTOM, name, **kwargs)
	
	def activate(self):
		if self.wql:
			(wmi, pythoncom) = (None, None)
			while True:
				try:
					import wmi, pythoncom
					break
				except Exception, e:
					logger.warning("Failed to import: %s, retrying in 5 seconds" % e)
					sleep(5)
			pythoncom.CoInitialize()
			try:
				while True:
					try:
						import wmi
						break
					except Exception, e:
						logger.warning("Failed to import wmi: %s, retrying in 5 seconds" % e)
						sleep(5)
				c = wmi.WMI()
				logger.info("watching for wql: %s" % self.wql)
				watcher = c.watch_for(raw_wql=self.wql, wmi_class='')
				self.wqlResult = watcher()
				logger.info("got wmi object: %s" % self.wqlResult)
			except Exception, e:
				pythoncom.CoUninitialize()
				logger.error("Failed to activate event '%s': %s" % (self, e))
				raise
			pythoncom.CoUninitialize()
		else:
			# Not yet supported
			e = threading.Event()
			e.wait()
	
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                          EVENT LISTENER                                           -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class EventListener(object):
	def __init__(self):
		logger.debug("EventListener initiated")
	
	def processEvent(event):
		logger.warning("%s: processEvent() not implemented" % self)







'''
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
=                                            CONTROL PIPES                                            =
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
=                                                                                                     =
=             These classes are used to create named pipes for remote procedure calls                 =
=                                                                                                     =
=  The class "ControlPipe" is the base class for a named pipe which handles remote procedure calls    =
=     PosixControlPipe implements a control pipe for posix operating systems                          =
=     NTControlPipe implements a control pipe for windows operating systems                           =
=  The class "ControlPipeFactory" selects the right implementation for the running os                 =
=                                                                                                     =
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
'''

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                        CONTROL PIPE                                               -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ControlPipe(threading.Thread):
	def __init__(self, opsiclientd):
		logger.setLogFormat('[%l] [%D] [control pipe]   %M     (%F|%N)', object=self)
		threading.Thread.__init__(self)
		self._opsiclientd = opsiclientd
		self._pipe = None
		self._pipeName = ""
		self._bufferSize = 4096
		self._running = False
		
	def stop(self):
		self._running = False
	
	def isRunning(self):
		return self._running
	
	def executeRpc(self, rpc):
		result = { 'id': 1, 'error': None, 'result': None }
		try:
			rpc = json.read(rpc)
			if not rpc.get('id'):
				raise Exception('No id defined!')
			result['id'] = rpc['id']
			if not rpc.get('method'):
				raise Exception('No method defined!')
			
			method = rpc.get('method')
			params = rpc.get('params')
			logger.info("RPC method: '%s' params: '%s'" % (method, params))
			
			# Execute method
			start = time.time()
			result['result'] = self._opsiclientd.executePipeRpc(method, params)
			logger.debug('Got result...')
			duration = round(time.time() - start, 3)
			logger.info('Took %0.3fs to process %s(%s)' % (duration, method, str(params)[1:-1]))
		except Exception, e:
			logger.error(e)
			result['error'] = { 'class': e.__class__.__name__, 'message': str(e) }
		return json.write(result)
		
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                     POSIX CONTROL PIPE                                            -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class PosixControlPipe(ControlPipe):
	def __init__(self, opsiclientd):
		ControlPipe.__init__(self, opsiclientd)
		self._pipeName = "/var/run/opsiclientd/fifo"
	
	def createPipe(self):
		logger.debug2("Creating pipe %s" % self._pipeName)
		if not os.path.exists( os.path.dirname(self._pipeName) ):
			os.mkdir( os.path.dirname(self._pipeName) )
		if os.path.exists(self._pipeName):
			os.unlink(self._pipeName)
		os.mkfifo(self._pipeName)
		logger.debug2("Pipe %s created" % self._pipeName)
	
	def run(self):
		self._running = True
		try:
			self.createPipe()
			while self._running:
				try:
					logger.debug2("Opening named pipe %s" % self._pipeName)
					self._pipe = os.open(self._pipeName, os.O_RDONLY)
					logger.debug2("Reading from pipe %s" % self._pipeName)
					rpc = os.read(self._pipe, self._bufferSize)
					os.close(self._pipe)
					if not rpc:
						logger.error("No rpc from pipe")
						continue
					logger.debug("Received rpc from pipe '%s'" % rpc)
					result = self.executeRpc(rpc)
					logger.debug2("Opening named pipe %s" % self._pipeName)
					timeout = 3
					ta = 0.0
					while (ta < timeout):
						try:
							self._pipe = os.open(self._pipeName, os.O_WRONLY | os.O_NONBLOCK)
							break
						except Exception, e:
							if not hasattr(e, 'errno') or (e.errno != 6):
								raise
							time.sleep(0.01)
							ta += 0.01
					if (ta >= timeout):
						logger.error("Failed to write to pipe (timed out after %d seconds)" % timeout)
						continue
					logger.debug2("Writing to pipe")
					written = os.write(self._pipe, result)
					logger.debug2("Number of bytes written: %d" % written)
					if (len(result) != written):
						logger.error("Failed to write all bytes to pipe (%d/%d)" % (written, len(result)))
				
				except Exception, e:
					logger.error("Pipe IO error: %s" % e)
				try:
					os.close(self._pipe)
				except:
					pass
		except Exception, e:
			logger.logException(e)
		logger.notice("ControlPipe exiting")
		if os.path.exists(self._pipeName):
			os.unlink(self._pipeName)
		self._running = False
		
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                     NT CONTROL PIPE CONNECTION                                    -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class NTControlPipeConnection(threading.Thread):
	def __init__(self, ntControlPipe, pipe, bufferSize):
		logger.setLogFormat('[%l] [%D] [control pipe]   %M     (%F|%N)', object=self)
		threading.Thread.__init__(self)
		self._ntControlPipe = ntControlPipe
		self._pipe = pipe
		self._bufferSize = bufferSize
		logger.debug("NTControlPipeConnection initiated")
		
	def run(self):
		self._running = True
		try:
			chBuf = create_string_buffer(self._bufferSize)
			cbRead = c_ulong(0)
			while self._running:
				logger.debug("Reading fom pipe")
				fReadSuccess = windll.kernel32.ReadFile(self._pipe, chBuf, self._bufferSize, byref(cbRead), None)
				if ((fReadSuccess == 1) or (cbRead.value != 0)):
					logger.info("Received rpc from pipe '%s'" % chBuf.value)
					result =  "%s\0" % self._ntControlPipe.executeRpc(chBuf.value)
					cbWritten = c_ulong(0)
					logger.debug("Writing to pipe")
					fWriteSuccess = windll.kernel32.WriteFile(
									self._pipe,
									c_char_p(result),
									len(result),
									byref(cbWritten),
									None )
					logger.debug("Number of bytes written: %d" % cbWritten.value)
					if not fWriteSuccess:
						logger.error("Could not reply to the client's request from the pipe")
						break
					if (len(result) != cbWritten.value):
						logger.error("Failed to write all bytes to pipe (%d/%d)" % (cbWritten.value, len(result)))
						break
					break
				else:
					logger.error("Failed to read from pipe")
					break
			
			windll.kernel32.FlushFileBuffers(self._pipe)
			windll.kernel32.DisconnectNamedPipe(self._pipe)
			windll.kernel32.CloseHandle(self._pipe)
		except Exception, e:
			logger.error("NTControlPipeConnection error: %s" % e)
		logger.debug("NTControlPipeConnection exiting")
		self._running = False

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                          NT CONTROL PIPE                                          -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class NTControlPipe(ControlPipe):
	
	def __init__(self, opsiclientd):
		threading.Thread.__init__(self)
		ControlPipe.__init__(self, opsiclientd)
		self._pipeName = "\\\\.\\pipe\\opsiclientd"
		
	def createPipe(self):
		logger.info("Creating pipe %s" % self._pipeName)
		PIPE_ACCESS_DUPLEX = 0x3
		PIPE_TYPE_MESSAGE = 0x4
		PIPE_READMODE_MESSAGE = 0x2
		PIPE_WAIT = 0
		PIPE_UNLIMITED_INSTANCES = 255
		NMPWAIT_USE_DEFAULT_WAIT = 0
		INVALID_HANDLE_VALUE = -1
		self._pipe = windll.kernel32.CreateNamedPipeA(
					self._pipeName,
					PIPE_ACCESS_DUPLEX,
					PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT,
					PIPE_UNLIMITED_INSTANCES,
					self._bufferSize,
					self._bufferSize,
					NMPWAIT_USE_DEFAULT_WAIT,
					None )
		if (self._pipe == INVALID_HANDLE_VALUE):
			raise Exception("Failed to create named pipe")
		logger.debug("Pipe %s created" % self._pipeName)
	
	def run(self):
		ERROR_PIPE_CONNECTED = 535
		self._running = True
		try:
			while self._running:
				self.createPipe()
				logger.debug("Connecting to named pipe %s" % self._pipeName)
				# This call is blocking until a client connects
				fConnected = windll.kernel32.ConnectNamedPipe(self._pipe, None)
				if ((fConnected == 0) and (windll.kernel32.GetLastError() == ERROR_PIPE_CONNECTED)):
					fConnected = 1
				if (fConnected == 1):
					logger.debug("Connected to named pipe %s" % self._pipeName)
					logger.debug("Creating NTControlPipeConnection")
					cpc = NTControlPipeConnection(self, self._pipe, self._bufferSize)
					cpc.start()
					logger.debug("NTControlPipeConnection thread started")
				else:
					logger.error("Failed to connect to pipe")
					windll.kernel32.CloseHandle(self._pipe)
		except Exception, e:
			logger.logException(e)
		logger.notice("ControlPipe exiting")
		self._running = False

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                     CONTROL PIPE FACTORY                                          -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
def ControlPipeFactory(opsiclientd):
	if (os.name == 'posix'):
		return PosixControlPipe(opsiclientd)
	if (os.name == 'nt'):
		return NTControlPipe(opsiclientd)
	else:
		raise NotImplemented("Unsupported operating system %s" % os.name)








'''
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
=                                            CONTROL SERVER                                           =
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
=                                                                                                     =
=      These classes are used to create a https service which executes remote procedure calls         =
=                                                                                                     =
=                                                                                                     =
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
'''

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                            SSL CONTEXT                                            -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class SSLContext:
	def __init__(self, sslServerKeyFile, sslServerCertFile):
		self._sslServerKeyFile = sslServerKeyFile
		self._sslServerCertFile = sslServerCertFile
		
	def getContext(self):
		''' Create an SSL context. '''
		
		# Test if server certificate and key file exist.
		if not os.path.isfile(self._sslServerKeyFile):
			raise Exception("Server key file '%s' does not exist!" % self._sslServerKeyFile)
			
		if not os.path.isfile(self._sslServerCertFile):
			raise Exception("Server certificate file '%s' does not exist!" % self._sslServerCertFile)
		
		# Create and return ssl context
		context = SSL.Context(SSL.SSLv23_METHOD)
		context.use_privatekey_file(self._sslServerKeyFile)
		context.use_certificate_file(self._sslServerCertFile)
		return context

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                    CONTROL SERVER RESOURCE ROOT                                   -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ControlServerResourceRoot(resource.Resource):
	addSlash = True
	def render(self, request):
		''' Process GET request. '''
		return http.Response(stream="<html><head><title>opsiclientd</title></head><body></body></html>")
	
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                 CONTROL SERVER RESOURCE JSON RPC                                  -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ControlServerResourceJsonRpc(resource.Resource):
	def __init__(self, opsiclientd):
		logger.setLogFormat('[%l] [%D] [control server]   %M     (%F|%N)', object=self)
		resource.Resource.__init__(self)
		self._opsiclientd = opsiclientd
		
	def getChild(self, name, request):
		''' Get the child resource for the requested path. '''
		if not name:
			return self
		return resource.Resource.getChild(self, name, request)
	
	def http_POST(self, request):
		''' Process POST request. '''
		logger.info("ControlServerResourceJsonRpc: processing POST request")
		worker = ControlServerJsonRpcWorker(request, self._opsiclientd, method = 'POST')
		return worker.process()
		
	def http_GET(self, request):
		''' Process GET request. '''
		logger.info("ControlServerResourceJsonRpc: processing GET request")
		worker = ControlServerJsonRpcWorker(request, self._opsiclientd, method = 'GET')
		return worker.process()

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                 CONTROL SERVER RESOURCE INTERFACE                                 -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ControlServerResourceInterface(ControlServerResourceJsonRpc):
	def __init__(self, opsiclientd):
		logger.setLogFormat('[%l] [%D] [control server]   %M     (%F|%N)', object=self)
		ControlServerResourceJsonRpc.__init__(self, opsiclientd)
	
	def http_POST(self, request):
		''' Process POST request. '''
		logger.info("ControlServerResourceInterface: processing POST request")
		worker = ControlServerJsonInterfaceWorker(request, self._opsiclientd, method = 'POST')
		return worker.process()
		
	def http_GET(self, request):
		''' Process GET request. '''
		logger.info("ControlServerResourceInterface: processing GET request")
		worker = ControlServerJsonInterfaceWorker(request, self._opsiclientd, method = 'GET')
		return worker.process()

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                           JSON RPC WORKER                                         -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class JsonRpcWorker(object):
	def __init__(self, request, opsiclientd, method = 'POST'):
		self.request = request
		self._opsiclientd = opsiclientd
		self.method = method
		self.session = None
		self.response = http.Response( code = responsecode.OK )
		self.rpc = {"id": None, "method": None, "params": []}
		self.result = {"id": None, "result": None, "error": None}
		
	def process(self):
		try:
			self.deferred = defer.Deferred()
			self.deferred.addCallback(self._getQuery)
			self.deferred.addCallback(self._getRpc)
			self.deferred.addCallback(self._authenticate)
			self.deferred.addCallback(self._executeRpc)
			# Convert ints to strings to prevent problems with delphi libraries
			self.deferred.addCallback(self._returnResponse)
			self.deferred.addErrback(self._errback)
			self.deferred.callback(None)
			return self.deferred
		except Exception, e:
			return self._errback(e)
	
	def _allIntsToString(self, obj):
		if ( type(obj) == type([]) ):
			for i in range( len(obj) ):
				obj[i] = self._allIntsToString(obj[i])
		
		elif ( type(obj) == type({}) ):
			for (key, value) in obj.items():
				obj[key] = self._allIntsToString(value)
		elif ( type(obj) == type(1) ):
			obj = str(obj)
		return obj
	
	def _handlePostData(self, chunk):
		logger.debug2("_handlePostData %s" % chunk)
		self.query += chunk
	
	def _returnResponse(self, result):
		self.result['result'] = self._allIntsToString(self.result['result'])
		jsonResult = ''
		try:
			jsonResult = json.write( self.result )
		except Exception, e:
			logger.critical(e)
		self.response.stream = stream.IByteStream(jsonResult)
		return self.response
	
	def _errback(self, failure):
		if (self.response.code == responsecode.OK):
			# Do not overwrite responsecodes set earlier
			self.response.code = responsecode.INTERNAL_SERVER_ERROR
		
		if isinstance(failure, Failure):
			if not self.result['error']:
				self.result['error'] = failure.getErrorMessage()
			try:
				failure.raiseException()
			except Exception, e:
				logger.logException(e)
		else:
			if not self.result['error']:
				self.result['error'] = str(failure)
		logger.error("Failed to process rpc: %s" % self.result['error'])
		return self._returnResponse(None)
	
	def _getQuery(self, result):
		self.query = ''
		if (self.method == 'GET'):
			self.query = urllib.unquote( self.request.querystring )
		elif (self.method == 'POST'):
			# Returning deferred needed for chaining
			d = stream.readStream(self.request.stream, self._handlePostData)
			d.addErrback(self._errback)
			return d
		
	def _getRpc(self, result):
		if not self.query:
			raise Exception('Got no query')
		
		try:
			# Deserialize json-object
			self.rpc = json.read(self.query)
			if not self.rpc.get('id'):
				raise Exception('No id defined!')
			self.result['id'] = self.rpc['id']
			if not self.rpc.get('method'):
				raise Exception('No method defined!')
		except Exception, e:
			e = str(e)
			logger.warning("Failed to get rpc from query '%s': %s" % 
					(self.query, e) )
			# Bad request
			self.response.code = responsecode.BAD_REQUEST
			self.result['error'] = e
			raise
		
		logger.info('Got json-rpc request: %s' % self.rpc)
	
	def _executeRpc(self, result):
		''' Execute json remote procedure call. '''
		d = threads.deferToThread(self._realRpc)
		d.addErrback(self._errback)
		return d
	
	def _realRpc(self):
		self.result['result'] = None
		
	def _authenticate(self, result):
		''' This function tries to authenticate a user.
		    Raises an exception on authentication failure. '''
		
		try:
			(user, password) = ('', '')
			logger.debug("Trying to get username and password from Authorization header")
			auth = self.request.headers.getHeader('Authorization')
			if auth:
				logger.debug("Authorization header found (type: %s)" % auth[0])
				try:
					encoded = auth[1]
					(user, password) = base64.decodestring(encoded).split(':')
					logger.confidential("Client supplied username '%s' and password '%s'" % (user, password))
				except Exception:
					raise Exception("Bad Authorization header from '%s'" % self.request.remoteAddr.host)
			
			logger.notice( "Authorization request from %s@%s" % (user, self.request.remoteAddr.host) )
			if not user:
				user = socket.getfqdn()
			if not password:
				raise Exception("Cannot authenticate, no password given")
			
			self._opsiclientd.authenticate(user, password)
			
		except Exception, e:
			# Forbidden
			#logger.logException(e)
			logger.error("Forbidden: %s" % str(e))
			self.response.code = responsecode.UNAUTHORIZED
			self.response.headers.setHeader('www-authenticate', [('basic', { 'realm': 'OPSI Client Service' } )])
			#self.result['error'] = str(e)
			raise

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                   CONTROL SERVER JSON RPC WORKER                                  -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ControlServerJsonRpcWorker(JsonRpcWorker):
	def __init__(self, request, opsiclientd, method = 'POST'):
		JsonRpcWorker.__init__(self, request, opsiclientd, method)
		logger.setLogFormat('[%l] [%D] [control server]   %M     (%F|%N)', object=self)
	
	def _realRpc(self):
		method = self.rpc.get('method')
		params = self.rpc.get('params')
		logger.info("RPC method: '%s' params: '%s'" % (method, params))
		
		try:
			# Execute method
			start = time.time()
			self.result['result'] = self._opsiclientd.executeServerRpc(method, params)
		except Exception, e:
			logger.logException(e)
			self.result['error'] = { 'class': e.__class__.__name__, 'message': str(e) }
			self.result['result'] = None
			return
		
		logger.debug('Got result...')
		duration = round(time.time() - start, 3)
		logger.debug('Took %0.3fs to process %s(%s)' % (duration, method, str(params)[1:-1]))

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                       JSON INTERFACE WORKER                                       -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ControlServerJsonInterfaceWorker(ControlServerJsonRpcWorker):
	xhtml = """
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"
	"http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
	
<html xmlns="http://www.w3.org/1999/xhtml">
	<head>
		<title>opsi client interface</title>
		<style>
		input, select {
			background-color: #fafafa;
			border-color: #abb1ef;
			border-width: 1px;
			border-style: solid;
			font-family: verdana, arial;
			font-size: 12px;
			width: 280px;
		}
		.json {
			background-color: #fafafa;
			border-color: #abb1ef;
			border-width: 1px;
			border-style: dashed;
			font-family: verdana, arial;
			font-size: 11px;
			padding: 10px;
			color: #555555;
		}
		.json_key {
			color: #9e445a;
		}
		.json_label {
			color: #abb1ef;
			margin-top: 20px;
			margin-bottom: 5px;
			font-family: verdana, arial;
			font-size: 11px;
		}
		.title {
			color: #555555; 
			font-size: 20px; 
			font-weight: bolder; 
			letter-spacing: 5px;
		}
		.button {
			background-color: #fafafa;
			border: none;
			margin-top: 20px;
			color: #9e445a;
			font-weight: bolder;
		}
		.box {
			background-color: #fafafa;
			border-color: #555555;
			border-width: 2px;
			border-style: solid;
			padding: 20px;
			margin: 30px;
			font-family: verdana, arial;
			font-size: 12px;
		}
		</style>
		<script type="text/javascript">
			var parameters = new Array();
			var method = '';
			var params = '';
			var id = '"id": 1';
%s
			function selectFunction(select) {
				method = select.value;
				tbody = document.getElementById('tbody');
				var button;
				var json;
				for (i=tbody.childNodes.length-1; i>=0; i--) {
					if (tbody.childNodes[i].id == 'tr_method') {
					}
					else if (tbody.childNodes[i].id == 'tr_submit') {
						button = tbody.childNodes[i];
						tbody.removeChild(button);
					}
					else if (tbody.childNodes[i].id == 'tr_json') {
						json = tbody.childNodes[i];
						tbody.removeChild(json);
					}
					else {
						tbody.removeChild(tbody.childNodes[i]);
					}
				}

				for (i=0; i < parameters[select.value].length; i++) {
					tr = document.createElement("tr");
					td1 = document.createElement("td");
					text = document.createTextNode(parameters[select.value][i] + ":");
					td1.appendChild(text);
					td2 = document.createElement("td");
					input = document.createElement("input");
					input.setAttribute('onchange', 'jsonString()');
					input.setAttribute('type', 'text');
					td2.appendChild(input);
					tr.appendChild(td1);
					tr.appendChild(td2);
					tbody.appendChild(tr)
				}
				tbody.appendChild(json)
				tbody.appendChild(button)
				
				jsonString();
			}
			
			function onSubmit() {
				var json = '{ "id": 1, "method": ';
				json += document.getElementById('json_method').firstChild.data;
				json += ', "params": ';
				json += document.getElementById('json_params').firstChild.data;
				json += ' }';
				window.location.href = '?' + json;
				return false;
			}
			
			function jsonString() {
				span = document.getElementById('json_method');
				for (i=span.childNodes.length-1; i>=0; i--) {
					span.removeChild(span.childNodes[i])
				}
				span.appendChild(document.createTextNode('"' + method + '"'));
				
				span = document.getElementById('json_params');
				for (i=span.childNodes.length-1; i>=0; i--) {
					span.removeChild(span.childNodes[i])
				}
				params = '['
				inputs = document.getElementsByTagName('input');
				for (i=0; i<inputs.length; i++) {
					if (inputs[i].id != 'submit') {
						if (inputs[i].value == '') {
							i = inputs.length;
						}
						else {
							if (i>0) {
								params += ', ';
							}
							params += inputs[i].value.replace(/\\\/g, '\\\\\\\\');
						}
					}
				}
				span.appendChild(document.createTextNode(params + ']'));
			}
		</script>
	</head>
	<body onload="selectFunction(document.getElementById('select'))">
		<div class="title">opsi client interface</div>
		<form action="cgi" method="post" onsubmit="return onSubmit()">
			<table class="box">
			<tbody id="tbody">
				<tr id="tr_method">
					<td style="width: 120px;">Method:</td>
					<td style="width: 280px;">
						<select id="select" onchange="selectFunction(this)" name="method">
%s
						</select>
					</td>
				</tr>
				<tr id="tr_json">
					<td colspan="2">
						<div class="json_label">
							resulting json remote procedure call:
						</div>
						<div class="json">
							{&nbsp;"<font class="json_key">method</font>": <span id="json_method"></span>,<br />
							&nbsp;&nbsp;&nbsp;"<font class="json_key">params</font>": <span id="json_params">[]</span>,<br />
							&nbsp;&nbsp;&nbsp;"<font class="json_key">id</font>": 1 }
						</div>
					</td>
				</tr>
				<tr id="tr_submit">
					<td align="center" colspan="2">
						<input value="Execute" id="submit" class="button" type="submit" />
					</td>
				</tr>
			</tbody>
			</table>
		</form>
		<div>
			<div class="json_label">
				json-rpc result
			</div>
			<div class="json">
				<pre>%s</pre>
			</div>
		</div>
	</body>
</html>"""

	def __init__(self, request, opsiconfd, method = 'POST'):
		ControlServerJsonRpcWorker.__init__(self, request, opsiconfd, method)
	
	def _returnResponse(self, result):
		js = ''
		sel = ''
		for f in self._opsiclientd.getPossibleMethods():
			js += "\t\t\tparameters['%s'] = new Array();\r\n" % (f['name'])
			for p in range(len(f['params'])):
				js += "\t\t\tparameters['%s'][%s]='%s';\r\n" % (f['name'], p, f['params'][p])
			if (f['name'] == self.rpc['method']):
				sel += '\t\t\t\t\t\t\t<option selected>%s</option>\r\n' % f['name']
			else:
				sel += '\t\t\t\t\t\t\t<option>%s</option>\r\n' % f['name']
		
		self.response.stream = stream.IByteStream(self.xhtml % (js, sel, Tools.jsonObjToHtml(self.result)))
		return self.response
	
	def _errback(self, failure):
		if (self.response.code == responsecode.OK):
			# Do not overwrite responsecodes set earlier
			self.response.code = responsecode.INTERNAL_SERVER_ERROR
		
		if isinstance(failure, Failure):
			if not self.result['error']:
				self.result['error'] = failure.getErrorMessage()
			try:
				failure.raiseException()
			except Exception, e:
				logger.logException(e)
		else:
			if not self.result['error']:
				self.result['error'] = str(failure)
		logger.error("Failed to process rpc: %s" % self.result['error'])
		return self._returnResponse(None)




# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                        CACHED CONFIG SERVICE                                      -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

class CacheService(threading.Thread):
	def __init__(self, opsiclientd):
		threading.Thread.__init__(self)
		logger.setLogFormat('[%l] [%D] [cache service]   %M     (%F|%N)', object=self)
		self._opsiclientd = opsiclientd
		self._storageDir = self._opsiclientd._config['cache_service']['storage_dir']
		self._cacheBackendBaseDir  = os.path.join(self._storageDir, 'cache_backend')
		self._workBackendBaseDir   = os.path.join(self._storageDir, 'work_backend')
		self._productCacheDir = os.path.join(self._storageDir, 'install')
		self._productIds = []
		self._stateFile = os.path.join(self._storageDir, 'sync_state')
		self._initiated = False
		self._state = {
			'product':  {},
			'config':   {}
		}
		self._syncConfigRequested = False
		self._cacheProductsRequested = False
		self._syncConfigEnded = threading.Event()
		self._cacheProductsEnded = threading.Event()
		self._currentProductProgressObserver = None
		self._overallProductProgressObserver = None
		self._currentConfigProgressObserver = None
		self._overallConfigProgressObserver = None
		self._running = False
	
	def setCurrentProductProgressObserver(self, currentProductProgressObserver):
		self._currentProductProgressObserver = currentProductProgressObserver
	
	def setOverallProductProgressObserver(self, overallProductProgressObserver):
		self._overallProductProgressObserver = overallProductProgressObserver
	
	def setCurrentConfigProgressObserver(self, currentConfigProgressObserver):
		self._currentConfigProgressObserver = currentConfigProgressObserver
	
	def setOverallConfigProgressObserver(self, overallConfigProgressObserver):
		self._overallConfigProgressObserver = overallConfigProgressObserver
	
	def stop(self):
		self._running = False
	
	def isRunning(self):
		return self._running
	
	def init(self):
		if self._initiated:
			logger.info("Initializing cache service: already initalized")
			return
		logger.notice("Initializing cache service")
		serverId = self._opsiclientd.getConfigValue('config_service', 'server_id')
		if not serverId:
			raise Exception("Failed to initialize CacheService config_service.server_id not known")
		
		self._cacheBackendArgs = {
			'logDir':                     os.path.join(self._cacheBackendBaseDir, 'logs'),
			'pckeyFile':                  os.path.join(self._cacheBackendBaseDir, 'pckeys'),
			'passwdFile':                 os.path.join(self._cacheBackendBaseDir, 'passwd'),
			'groupsFile':                 os.path.join(self._cacheBackendBaseDir, 'clientgroups.ini'),
			'licensesFile':               os.path.join(self._cacheBackendBaseDir, 'licenses.ini'),
			'clientConfigDir':            os.path.join(self._cacheBackendBaseDir, 'clients'),
			'clientTemplatesDir':         os.path.join(self._cacheBackendBaseDir, 'templates'),
			'defaultClientTemplateFile':  os.path.join(self._cacheBackendBaseDir, 'templates', 'pcproto.ini'),
			'globalConfigFile':           os.path.join(self._cacheBackendBaseDir, 'global.ini'),
			'depotConfigDir':             os.path.join(self._cacheBackendBaseDir, 'depots'),
			'productLockFile':            os.path.join(self._cacheBackendBaseDir, 'depots', 'product.locks'),
			'auditInfoDir':               os.path.join(self._cacheBackendBaseDir, 'audit'),
			'serverId':                   serverId
		}
		self._workBackendArgs = {
			'logDir':                     os.path.join(self._workBackendBaseDir, 'logs'),
			'pckeyFile':                  os.path.join(self._workBackendBaseDir, 'pckeys'),
			'passwdFile':                 os.path.join(self._workBackendBaseDir, 'passwd'),
			'groupsFile':                 os.path.join(self._workBackendBaseDir, 'clientgroups.ini'),
			'licensesFile':               os.path.join(self._workBackendBaseDir, 'licenses.ini'),
			'clientConfigDir':            os.path.join(self._workBackendBaseDir, 'clients'),
			'clientTemplatesDir':         os.path.join(self._workBackendBaseDir, 'templates'),
			'defaultClientTemplateFile':  os.path.join(self._workBackendBaseDir, 'templates', 'pcproto.ini'),
			'globalConfigFile':           os.path.join(self._workBackendBaseDir, 'global.ini'),
			'depotConfigDir':             os.path.join(self._workBackendBaseDir, 'depots'),
			'productLockFile':            os.path.join(self._workBackendBaseDir, 'depots', 'product.locks'),
			'auditInfoDir':               os.path.join(self._workBackendBaseDir, 'audit'),
			'serverId':                   serverId
		}
		
		self._hostId = self._opsiclientd.getConfigValue('global', 'host_id')
		self._opsiHostKey = self._opsiclientd.getConfigValue('global', 'opsi_host_key')
		self._address = self._opsiclientd.getConfigValue('config_service', 'url')
		
		logger.debug("Using hostId: %s" % self._hostId)
		logger.debug("Using depot address: %s" % self._address)
		logger.debug("Using storage dir: %s" % self._storageDir)
		logger.debug("Using cache backend base dir: %s" % self._cacheBackendBaseDir)
		logger.debug("Using work backend base dir: %s" % self._workBackendBaseDir)
		
		if not os.path.isdir(self._storageDir):
			os.mkdir(self._storageDir)
		if not os.path.isdir(self._cacheBackendBaseDir):
			os.mkdir(self._cacheBackendBaseDir)
		if not os.path.isdir(self._workBackendBaseDir):
			os.mkdir(self._workBackendBaseDir)
		
		logger.info("Creating remote backend")
		self._remoteBackend = JSONRPCBackend(address = self._address, username = self._hostId, password = self._opsiHostKey, args = { 'connectOnInit': False })
		
		logger.info("Creating cache backend")
		self._cacheBackend = File31Backend(args = self._cacheBackendArgs)
		logger.setLogFormat('[%l] [%D] [cache service]   %M     (%F|%N)', object = self._cacheBackend)
		self._cacheBackend.createOpsiBase()
		#self._cacheBackend = BackendManager(backend = self._cacheBackend, authRequired = False, configFile = self._opsiclientd.getConfigValue('cache_service', 'backend_manager_config'))
		
		logger.info("Creating work backend")
		self._workBackend = File31Backend(args = self._workBackendArgs)
		logger.setLogFormat('[%l] [%D] [cache service]   %M     (%F|%N)', object = self._workBackend)
		self._workBackend.createOpsiBase()
		#self._workBackend = BackendManager(backend = self._workBackend, authRequired = False, configFile = self._opsiclientd.getConfigValue('cache_service', 'backend_manager_config'))
		
		logger.info("Creating offline backend")
		self._offlineBackend = OfflineBackend(
					args = {
						'remoteBackend':        self._remoteBackend,
						'cacheBackend':         self._cacheBackend,
						'workBackend':          self._workBackend,
						'storageDir':           self._storageDir
					} )
		logger.setLogFormat('[%l] [%D] [cache service]   %M     (%F|%N)', object = self._offlineBackend)
		self._backend = BackendManager(backend = self._offlineBackend, authRequired = False, configFile = self._opsiclientd.getConfigValue('cache_service', 'backend_manager_config'))
		logger.setLogFormat('[%l] [%D] [cache service]   %M     (%F|%N)', object = self._backend)
		
		# TODO: url
		self._repository = getRepository(	#url        = self._opsiclientd.getConfigValue('depot_server', 'url'),
							url          = 'webdavs://%s:4447/opsi-depot' % self._opsiclientd.getConfigValue('depot_server', 'depot_id'),
							username     = self._hostId,
							password     = self._opsiHostKey)
		self.readStateFile()
		
		self._initiated = True
	
	def getConfigSyncCompleted(self):
		if not self._initiated:
			logger.info("CacheService not initiated")
			return False
		if not self._state['config']:
			logger.info("Config not synced")
			return False
		if not self._state['config'].get('sync_completed'):
			logger.debug("Config sync not completed: %s" % self._state['config'])
			return False
		logger.debug("Config sync completed on '%s'" % self._state['config']['sync_completed'])
		return True
		
	def getProductSyncCompleted(self):
		if not self._initiated:
			logger.info("CacheService not initiated")
			return False
		if not self._state['product']:
			logger.info("No products cached")
			return False
		productSyncCompleted = True
		for (productId, state) in self._state['product'].items():
			if state.get('sync_completed'):
				logger.debug("Product '%s': sync completed" % productId)
			else:
				productSyncCompleted = False
				logger.debug("Product '%s': sync not completed" % productId)
		return productSyncCompleted
		
	def readStateFile(self):
		logger.notice("Reading cache service state file '%s'" % self._stateFile)
		if not os.path.exists(self._stateFile):
			logger.warning("Cache service state file '%s' not found" % self._stateFile)
			return
		self._state = {
			'product':  {},
			'config':   {}
		}
		ini = File().readIniFile(self._stateFile)
		for section in ini.sections():
			for (k, v) in ini.items(section):
				if (section.lower() == 'config'):
					self._state['config'][k] = v
				elif section.lower().startswith('product_'):
					productId = section.split('_', 1)[1].lower().strip()
					if not self._state['product'].has_key(productId):
						self._state['product'][productId] = {}
					self._state['product'][productId][k] = v
		logger.debug("CacheService state is now:\n%s" % Tools.objectToBeautifiedText(self._state))
		
	def writeStateFile(self):
		logger.notice("Writing cache service state file '%s'" % self._stateFile)
		f = open(self._stateFile, 'w')
		f.close()
		ini = File().readIniFile(self._stateFile)
		ini.add_section('config')
		for (k, v) in self._state['config'].items():
			ini.set('config', k, str(v))
		for (productId, values) in self._state['product'].items():
			section = 'product_%s' % productId.lower()
			ini.add_section(section)
			for (k, v) in self._state['product'][productId].items():
				ini.set(section, k, str(v))
		File().writeIniFile(self._stateFile, ini)
		
	def cacheProducts(self, productIds, maxBandwidth=0, waitForEnding=False):
		if not self._initiated:
			raise Exception("Cannot cache products: not initiated")
		self._productIds = productIds
		self._cacheProductsRequested = True
		self._cacheProductsEnded.clear()
		self._repository.setMaxBandwidth(maxBandwidth)
		if waitForEnding:
			self._cacheProductsEnded = threading.Event()
			self._cacheProductsEnded.wait()
			for productId in self._productIds:
				if self._state['product'][productId]['sync_failed']:
					return False
			return True
	
	def syncConfig(self, productIds, waitForEnding=False):
		if not self._initiated:
			raise Exception("Cannot sync config: not initiated")
		self._productIds = productIds
		self._syncConfigRequested = True
		self._syncConfigEnded.clear()
		if waitForEnding:
			self._syncConfigEnded = threading.Event()
			self._syncConfigEnded.wait()
			return bool(self._state['config']['sync_failed'])
	
	def workWithLocalConfig(self):
		if not self._initiated:
			raise Exception("Cannot work on local config: not initiated")
		if not self.getConfigSyncCompleted():
			raise Exception("Cannot work on local config: sync not completed")
		self._offlineBackend._workLocalOnly(True)
	
	def run(self):
		self._running = True
		while self._running:
			try:
				if self._syncConfigRequested:
					self._syncConfigRequested = False
					
					try:
						logger.notice("Syncing config (products: %s)" % ', '.join(self._productIds))
						if not self._initiated:
							raise Exception("Cannot sync config: not initiated")
						
						self._remoteBackend.possibleMethods = []
						self._remoteBackend._connect()
						modules = self._remoteBackend.getOpsiInformation_hash()['modules']
						if not modules.get('vpn'):
							raise Exception("Cannot sync config: VPN module currently disabled")
						
						if not modules.get('valid'):
							raise Exception("Cannot sync config: modules file invalid")
						
						if (modules.get('expires', '') != 'never') and (time.mktime(time.strptime(modules.get('expires', '2000-01-01'), "%Y-%m-%d")) - time.time() <= 0):
							raise Exception("Cannot sync config: modules file signature expired")
						
						logger.info("Verifying modules file signature")
						import base64, md5, twisted.conch.ssh.keys
						publicKey = twisted.conch.ssh.keys.getPublicKeyObject(data = base64.decodestring('AAAAB3NzaC1yc2EAAAADAQABAAABAQCAD/I79Jd0eKwwfuVwh5B2z+S8aV0C5suItJa18RrYip+d4P0ogzqoCfOoVWtDojY96FDYv+2d73LsoOckHCnuh55GA0mtuVMWdXNZIE8Avt/RzbEoYGo/H0weuga7I8PuQNC/nyS8w3W8TH4pt+ZCjZZoX8S+IizWCYwfqYoYTMLgB0i+6TCAfJj3mNgCrDZkQ24+rOFS4a8RrjamEz/b81noWl9IntllK1hySkR+LbulfTGALHgHkDUlk0OSu+zBPw/hcDSOMiDQvvHfmR4quGyLPbQ2FOVm1TzE0bQPR+Bhx4V8Eo2kNYstG2eJELrz7J1TJI0rCjpB+FQjYPsP'))
						data = ''
						mks = modules.keys()
						mks.sort()
						for module in mks:
							if module in ('valid', 'signature'):
								continue
							val = modules[module]
							if (val == False): val = 'no'
							if (val == True):  val = 'yes'
							data += module.lower().strip() + ' = ' + val + '\r\n'
						if not bool(publicKey.verify(md5.new(data).digest(), [ long(modules['signature']) ])):
							raise Exception("Cannot sync config: modules file invalid")
						logger.info("Modules file signature verified")
						
						self._state['config'] = {
							'sync_started':    time.time(),
							'sync_completed':  '',
							'sync_failed':     ''
						}
						depotId = self._opsiclientd.getConfigValue('depot_server', 'depot_id')
						
						logger.notice("Executing cached method calls")
						self._offlineBackend._writebackCache(currentProgressObserver = self._currentConfigProgressObserver)
						
						logger.notice("Building config cache")
						self._offlineBackend._buildCache(
								serverIds  = [ None ],
								depotIds   = [ depotId ],
								clientIds  = [ self._hostId ],
								groupIds   = [ None ],
								productIds = self._productIds,
								currentProgressObserver = self._currentConfigProgressObserver,
								overallProgressObserver = self._overallConfigProgressObserver )
						self._state['config']['sync_completed'] = time.time()
						
						logger.notice("Config synced")
					except Exception, e:
						logger.logException(e)
						logger.error("Failed to sync config: %s" % e)
						self._state['config']['sync_failed'] = str(e)
					self.writeStateFile()
					self._syncConfigEnded.set()
				
				if self._cacheProductsRequested:
					self._cacheProductsRequested = False
					
					try:
						logger.notice("Caching products: %s" % ', '.join(self._productIds))
						if not self._initiated:
							raise Exception("Cannot cache products: not initiated")
						
						self._remoteBackend.possibleMethods = []
						self._remoteBackend._connect()
						modules = self._remoteBackend.getOpsiInformation_hash()['modules']
						if not modules.get('vpn'):
							raise Exception("Cannot cache config: VPN module currently disabled")
						
						if not modules.get('valid'):
							raise Exception("Cannot cache config: modules file invalid")
						
						if (modules.get('expires', '') != 'never') and (time.mktime(time.strptime(modules.get('expires', '2000-01-01'), "%Y-%m-%d")) - time.time() <= 0):
							raise Exception("Cannot sync config: modules file signature expired")
						
						logger.info("Verifying modules file signature")
						import base64, md5, twisted.conch.ssh.keys
						publicKey = twisted.conch.ssh.keys.getPublicKeyObject(data = base64.decodestring('AAAAB3NzaC1yc2EAAAADAQABAAABAQCAD/I79Jd0eKwwfuVwh5B2z+S8aV0C5suItJa18RrYip+d4P0ogzqoCfOoVWtDojY96FDYv+2d73LsoOckHCnuh55GA0mtuVMWdXNZIE8Avt/RzbEoYGo/H0weuga7I8PuQNC/nyS8w3W8TH4pt+ZCjZZoX8S+IizWCYwfqYoYTMLgB0i+6TCAfJj3mNgCrDZkQ24+rOFS4a8RrjamEz/b81noWl9IntllK1hySkR+LbulfTGALHgHkDUlk0OSu+zBPw/hcDSOMiDQvvHfmR4quGyLPbQ2FOVm1TzE0bQPR+Bhx4V8Eo2kNYstG2eJELrz7J1TJI0rCjpB+FQjYPsP'))
						data = ''
						mks = modules.keys()
						mks.sort()
						for module in mks:
							if module in ('valid', 'signature'):
								continue
							val = modules[module]
							if (val == False): val = 'no'
							if (val == True):  val = 'yes'
							data += module.lower().strip() + ' = ' + val + '\r\n'
						if not bool(publicKey.verify(md5.new(data).digest(), [ long(modules['signature']) ])):
							raise Exception("Cannot cache config: modules file invalid")
						logger.info("Modules file signature verified")
						
						logger.info("Synchronizing %d product(s):" % len(self._productIds))
						for productId in self._productIds:
							logger.info("   %s" % productId)
						
						overallProgressSubject = ProgressSubject(id = 'sync_products_overall', type = 'product_sync', end = len(self._productIds))
						overallProgressSubject.setMessage( _('Synchronizing products') )
						if self._overallProductProgressObserver: overallProgressSubject.attachObserver(self._overallProductProgressObserver)
						
						for productId in self._productIds:
							logger.notice("Syncing files of product '%s'" % productId)
							if not self._state['product'].has_key(productId):
								self._state['product'][productId] = {
									'sync_started':    time.time(),
								}
							self._state['product'][productId]['sync_completed'] = ''
							self._state['product'][productId]['sync_failed'] = ''
							self.writeStateFile()
							try:
								self._productSynchronizer = DepotToLocalDirectorySychronizer(
									self._repository,
									self._productCacheDir,
									[ productId ]
								)
								self._productSynchronizer.synchronize(self._currentProductProgressObserver)
								self._state['product'][productId]['sync_completed'] = time.time()
								logger.notice("Product '%s' synced" % productId)
							except Exception, e:
								logger.error("Failed to sync product '%s': %s" % (productId, e))
								self._state['product'][productId]['sync_failed'] = str(e)
							self.writeStateFile()
							overallProgressSubject.addToState(1)
						
						if self._overallProductProgressObserver: overallProgressSubject.detachObserver(self._overallProductProgressObserver)
						
						for productId in self._productIds:
							if self._state['product'][productId]['sync_failed']:
								raise Exception(self._state['product'][productId]['sync_failed'])
						
						logger.notice("All products cached: %s" % ', '.join(self._productIds))
						for event in self._opsiclientd.getEvents(EVENT_TYPE_PRODUCT_SYNC_COMPLETED):
							event.fire()
					
					except Exception, e:
						logger.logException(e)
						logger.error("Failed to cache products: %s" % e)
					self.writeStateFile()
					self._cacheProductsEnded.set()
					
					
					
				time.sleep(3)
			except Exception, e:
				logger.logException(e)
		
	def reset(self):
		if os.path.exists(self._storageDir):
			shutil.rmtree(self._storageDir)
		self._initiated = False
		self.init()
		
	def processRpc(self, method, params):
		if not self._initiated:
			raise Exception("Cache service not initiated")
		return eval('self._backend.%s(*params)' % method)
	
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                              CACHED CONFIG SERVICE RESOURCE JSON RPC                              -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class CacheServiceResourceJsonRpc(resource.Resource):
	def __init__(self, opsiclientd):
		logger.setLogFormat('[%l] [%D] [cached cfg server]   %M     (%F|%N)', object=self)
		resource.Resource.__init__(self)
		self._opsiclientd = opsiclientd
		
	def getChild(self, name, request):
		''' Get the child resource for the requested path. '''
		if not name:
			return self
		return resource.Resource.getChild(self, name, request)
	
	def http_POST(self, request):
		''' Process POST request. '''
		logger.info("CacheServiceResourceJsonRpc: processing POST request")
		worker = CacheServiceJsonRpcWorker(request, self._opsiclientd, method = 'POST')
		return worker.process()
		
	def http_GET(self, request):
		''' Process GET request. '''
		logger.info("CacheServiceResourceJsonRpc: processing GET request")
		worker = CacheServiceJsonRpcWorker(request, self._opsiclientd, method = 'GET')
		return worker.process()


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                               CACHED CONFIG SERVICE JSON RPC WORKER                               -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class CacheServiceJsonRpcWorker(JsonRpcWorker):
	def __init__(self, request, opsiclientd, method = 'POST'):
		JsonRpcWorker.__init__(self, request, opsiclientd, method)
		logger.setLogFormat('[%l] [%D] [cached cfg server]   %M     (%F|%N)', object=self)
	
	def _realRpc(self):
		method = self.rpc.get('method')
		params = self.rpc.get('params')
		logger.info("RPC method: '%s' params: '%s'" % (method, params))
		
		try:
			# Execute method
			start = time.time()
			self.result['result'] = self._opsiclientd._cacheService.processRpc(method, params)
		except Exception, e:
			logger.logException(e)
			self.result['error'] = { 'class': e.__class__.__name__, 'message': str(e) }
			self.result['result'] = None
			return
		
		logger.debug('Got result...')
		duration = round(time.time() - start, 3)
		logger.debug('Took %0.3fs to process %s(%s)' % (duration, method, str(params)[1:-1]))


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                           CONTROL SERVER                                          -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ControlServer(threading.Thread):
	def __init__(self, opsiclientd, httpsPort, sslServerKeyFile, sslServerCertFile, staticDir=None):
		logger.setLogFormat('[%l] [%D] [control server]   %M     (%F|%N)', object=self)
		threading.Thread.__init__(self)
		self._opsiclientd = opsiclientd
		self._httpsPort = httpsPort
		self._sslServerKeyFile = sslServerKeyFile
		self._sslServerCertFile = sslServerCertFile
		self._staticDir = staticDir
		self._root = None
		self._running = False
		logger.info("ControlServer initiated")
		
	def run(self):
		self._running = True
		try:
			logger.info("creating root resource")
			self.createRoot()
			self._site = server.Site(self._root)
			reactor.listenSSL(
				self._httpsPort,
				HTTPFactory(self._site),
				SSLContext(self._sslServerKeyFile, self._sslServerCertFile) )
			logger.notice("Control server is accepting HTTPS requests on port %d" % self._httpsPort)
			if not reactor.running:
				reactor.run(installSignalHandlers=0)
			
		except Exception, e:
			logger.logException(e)
		logger.notice("Control server exiting")
		self._running = False
	
	def stop(self):
		if reactor and reactor.running:
			reactor.stop()
		self._running = False
		
	def createRoot(self):
		if self._staticDir:
			if os.path.isdir(self._staticDir):
				self._root = static.File(self._staticDir)
			else:
				logger.error("Cannot add static content '/': directory '%s' does not exist." % self._staticDir)
		if not self._root:
			self._root = ControlServerResourceRoot()
		self._root.putChild("opsiclientd", ControlServerResourceJsonRpc(self._opsiclientd))
		self._root.putChild("interface", ControlServerResourceInterface(self._opsiclientd))
		self._root.putChild("rpc", CacheServiceResourceJsonRpc(self._opsiclientd))









'''
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
=                                             OPSICLIENTD                                             =
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
=                                                                                                     =
=              These classes are used to create the main opsiclientd service / daemon                 =
=                                                                                                     =
=                                                                                                     =
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
'''
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                     SERVICE CONNECTION THREAD                                     -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ServiceConnectionThread(KillableThread):
	def __init__(self, configServiceUrl, username, password, notificationServer, statusObject):
		logger.setLogFormat('[%l] [%D] [service connection]   %M     (%F|%N)', object=self)
		KillableThread.__init__(self)
		self._configServiceUrl = configServiceUrl
		self._username = username
		self._password = password
		self._notificationServer = notificationServer
		self._statusSubject = statusObject
		self.configService = None
		self.running = False
		self.connected = False
		self.cancelled = False
		if not self._configServiceUrl:
			raise Exception("No config service url given")
	
	def getUsername(self):
		return self._username
	
	def run(self):
		try:
			logger.debug("ServiceConnectionThread started...")
			self.running = True
			self.connected = False
			self.cancelled = False
			
			tryNum = 0
			while not self.cancelled and not self.connected:
				try:
					tryNum += 1
					logger.notice("Connecting to config server '%s' #%d" % (self._configServiceUrl, tryNum))
					self._statusSubject.setMessage( _("Connecting to config server '%s' #%d") % (self._configServiceUrl, tryNum))
					if (len(self._username.split('.')) < 3):
						logger.notice("Domain missing in username %s, fetching domain from service" % self._username)
						configService = JSONRPCBackend(address = self._configServiceUrl, username = '', password = '')
						domain = configService.getDomain()
						self._username += '.' + domain
						logger.notice("Got domain '%s' from service, username expanded to '%s'" % (domain, self._username))
					self.configService = JSONRPCBackend(address = self._configServiceUrl, username = self._username, password = self._password)
					self.configService.authenticated()
					self.connected = True
					self._statusSubject.setMessage("Connected to config server '%s'" % self._configServiceUrl)
					logger.notice("Connected to config server '%s'" % self._configServiceUrl)
				except Exception, e:
					self._statusSubject.setMessage("Failed to connect to config server '%s': %s" % (self._configServiceUrl, e))
					logger.error("Failed to connect to config server '%s': %s" % (self._configServiceUrl, e))
					time.sleep(3)
			
		except Exception, e:
			logger.logException(e)
		self.running = False
	
	def stopConnectionCallback(self, choiceSubject):
		logger.notice("Connection cancelled by user")
		self.stop()
	
	def stop(self):
		logger.debug("stopping thread")
		self.cancelled = True
		time.sleep(2)
		logger.debug("running: %s, alive: %s" % (self.running, self.isAlive()))
		if self.running and self.isAlive():
			logger.debug("Terminating thread")
			self.terminate()

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                      EVENT PROCESSING THREAD                                      -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class EventProcessingThread(KillableThread):
	def __init__(self, opsiclientd, event):
		logger.setLogFormat('[%l] [%D] [event processing]   %M     (%F|%N)', object=self)
		KillableThread.__init__(self)
		
		self.opsiclientd = opsiclientd
		self.event = event
		
		self.running = False
		self.eventCancelled = False
		self.waiting = False
		self.waitCancelled = False
		
	def startNotifierApplication(self, command, desktop=''):
		if not command:
			raise ValueError("No command given")
		
		activeSessionId = System.getActiveConsoleSessionId()
		if not desktop or desktop.lower() not in ('winlogon', 'default'):
			desktop = self.opsiclientd.getCurrentActiveDesktopName()
		if not desktop or desktop.lower() not in ('winlogon', 'default'):
			desktop = 'winlogon'
		
		logger.notice("Starting notifier application in session '%s' on desktop '%s'" % (activeSessionId, desktop))
		processId = System.runCommandInSession(command = command, sessionId = activeSessionId, desktop = desktop, waitForProcessEnding=False)[2]
		time.sleep(3)
		return processId
		
	def stopNotifierApplication(self, processId):
		if not processId:
			raise ValueError("No process id given")
		
		logger.notice("Stopping notifier application")
		try:
			self.opsiclientd.closeProcessWindows(processId)
			time.sleep(3)
			System.terminateProcess(processId = processId)
		except Exception, e:
			#logger.error("Failed to stop notifier application: %s" % e)
			pass
		
	def run(self):
		try:
			logger.notice("============= EventProcessingThread for event '%s' started =============" % self.event)
			self.running = True
			self.eventCancelled = False
			self.waiting = False
			self.waitCancelled = False
			notifierApplicationPid = None
			# Store current config service url and depot url
			configServiceUrl = self.opsiclientd.getConfigValue('config_service', 'url')
			depotServerUrl = self.opsiclientd.getConfigValue('depot_server', 'url')
			depotDrive = self.opsiclientd.getConfigValue('depot_server', 'drive')
			try:
				if self.event.requiresCachedProducts:
					# Event needs cached products => initialize cache service
					self.opsiclientd._cacheService.init()
					if self.opsiclientd._cacheService.getProductSyncCompleted():
						logger.notice("Event '%s' requires cached products and product sync is done" % self.event)
						cacheDepotDir = (self.opsiclientd.getConfigValue('cache_service', 'storage_dir') + '\\install').replace('\\', '/').replace('//', '/')
						cacheDepotDrive = cacheDepotDir.split('/')[0]
						cacheDepotUrl = 'smb://localhost/noshare/' + ('/'.join(cacheDepotDir.split('/')[1:]))
						self.opsiclientd.setConfigValue('depot_server', 'url', cacheDepotUrl)
						self.opsiclientd.setConfigValue('depot_server', 'drive', cacheDepotDrive)
					else:
						logger.notice("Event '%s' requires cached products but product sync is not done, exiting" % self.event)
						self.running = False
						return
				
				if self.event.useCachedConfig:
					# Event needs cached config => initialize cache service
					self.opsiclientd._cacheService.init()
					if self.opsiclientd._cacheService.getConfigSyncCompleted():
						logger.notice("Event '%s' requires cached config and config sync is done" % self.event)
						self.opsiclientd._cacheService.workWithLocalConfig()
						cacheConfigServiceUrl = 'https://127.0.0.1:%s/rpc' % self.opsiclientd.getConfigValue('control_server', 'port')
						logger.notice("Setting config service url to cache service url '%s'" % cacheConfigServiceUrl)
						self.opsiclientd.setConfigValue('config_service', 'url', cacheConfigServiceUrl)
					else:
						logger.notice("Event '%s' requires cached config but config sync is not done, exiting" % self.event)
						self.running = False
						return
				
				self.opsiclientd.getEventSubject().setMessage(self.event.message)
				if self.event.warningTime:
					choiceSubject = ChoiceSubject(id = 'choice')
					if self.event.userCancelable:
						choiceSubject.setChoices([ 'Abort', 'Start now' ])
						choiceSubject.setCallbacks( [ self.abortEventCallback, self.startEventCallback ] )
					else:
						choiceSubject.setChoices([ 'Start now' ])
						choiceSubject.setCallbacks( [ self.startEventCallback ] )
					self.opsiclientd.getNotificationServer().addSubject(choiceSubject)
					try:
						if self.event.eventNotifierCommand:
							notifierApplicationPid = self.startNotifierApplication(
										command = self.event.eventNotifierCommand,
										desktop = self.event.eventNotifierDesktop )
							
						timeout = int(self.event.warningTime)
						while(timeout > 0) and not self.eventCancelled and not self.waitCancelled:
							self.waiting = True
							logger.info("Notifying user of event %s" % self.event)
							self.opsiclientd.getStatusSubject().setMessage("Event %s: processing will start in %d seconds" \
																% (self.event.getName(), timeout))
							timeout -= 1
							time.sleep(1)
						
						if self.eventCancelled:
							raise CanceledByUserError("cancelled by user")
					finally:
						self.waiting = False
						if notifierApplicationPid:
							self.stopNotifierApplication(notifierApplicationPid)
						self.opsiclientd.getNotificationServer().removeSubject(choiceSubject)
				
				self.opsiclientd.getStatusSubject().setMessage(_("Processing event %s") % self.event.getName())
				
				if self.event.blockLogin:
					self.opsiclientd.setBlockLogin(True)
				if self.event.logoffCurrentUser:
					System.logoffCurrentUser()
					time.sleep(15)
				elif self.event.lockWorkstation:
					System.lockWorkstation()
					time.sleep(15)
				
				if self.event.actionNotifierCommand:
					notifierApplicationPid = self.startNotifierApplication(
									command = self.event.actionNotifierCommand,
									desktop = self.event.actionNotifierDesktop )
				
				if not self.event.useCachedConfig:
					if self.event.getConfigFromService:
						self.opsiclientd.getConfigFromService()
					if self.event.updateConfigFile:
						self.opsiclientd.updateConfigFile()
					
				self.opsiclientd.processProductActionRequests(self.event)
			
			finally:
				self.opsiclientd.getEventSubject().setMessage("")
				self.opsiclientd.processShutdownRequests()
				if self.event.writeLogToService:
					self.opsiclientd.writeLogToService()
				# Disconnect has to be called, even if connect failed!
				self.opsiclientd.disconnectConfigServer()
				if notifierApplicationPid:
					self.stopNotifierApplication(notifierApplicationPid)
				if (not self.opsiclientd._rebootRequested and not self.opsiclientd._shutdownRequested) \
				    or (sys.getwindowsversion()[0] < 6):
					# Windows NT < 6 can't shutdown while pgina.dll is blocking login!
					self.opsiclientd.setBlockLogin(False)
				if self.event.useCachedConfig:
					# Set config service url back to previous url
					logger.notice("Setting config service url back to '%s'" % configServiceUrl)
					self.opsiclientd.setConfigValue('config_service', 'url', configServiceUrl)
					logger.notice("Setting depot server url back to '%s'" % depotServerUrl)
					self.opsiclientd.setConfigValue('depot_server', 'url', depotServerUrl)
					logger.notice("Setting depot drive back to '%s'" % depotDrive)
					self.opsiclientd.setConfigValue('depot_server', 'drive', depotDrive)
				
		except Exception, e:
			logger.error("Failed to process event %s: %s" % (self.event, e))
			logger.logException(e)
		
		self.running = False
		logger.notice("============= EventProcessingThread for event '%s' ended =============" % self.event)
		
	def abortEventCallback(self, choiceSubject):
		logger.notice("Event aborted by user")
		self.eventCancelled = True
	
	def startEventCallback(self, choiceSubject):
		logger.notice("Waiting cancelled by user")
		self.waitCancelled = True
	
	#def stop(self):
	#	time.sleep(5)
	#	if self.running and self.isAlive():
	#		logger.debug("Terminating thread")
	#		self.terminate()

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                            OPSICLIENTD                                            -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class Opsiclientd(EventListener, threading.Thread):
	def __init__(self):
		logger.setLogFormat('[%l] [%D] [opsiclientd]   %M     (%F|%N)', object=self)
		logger.debug("Opsiclient initiating")
		
		EventListener.__init__(self)
		threading.Thread.__init__(self) 
		
		self._setEnvironment = True
		self._startupTime = time.time()
		self._running = False
		self._configService = None
		self._configServiceException = None
		self._processingEvent = False
		self._blockLogin = True
		self._currentActiveDesktopName = None
		self._events = {}
		
		self._statusApplicationProcess = None
		
		self._statusSubject = MessageSubject('status')
		self._eventSubject = MessageSubject('event')
		self._serviceUrlSubject = MessageSubject('configServiceUrl')
		self._clientIdSubject = MessageSubject('clientId')
		self._actionProcessorInfoSubject = MessageSubject('actionProcessorInfo')
		self._opsiclientdInfoSubject = MessageSubject('opsiclientdInfo')
		self._detailSubjectProxy = MessageSubjectProxy('detail')
		self._currentProgressSubjectProxy = ProgressSubjectProxy('currentProgress')
		self._overallProgressSubjectProxy = ProgressSubjectProxy('overallProgress')
		
		self._rebootRequested = False
		self._shutdownRequested = False
		
		self._config = {
			'system': {
				'program_files_dir':      '',
			},
			'global': {
				'config_file':            'opsiclientd.conf',
				'log_file':               'opsiclientd.log',
				'log_level':              LOG_NOTICE,
				'host_id':                System.getFQDN(),
				'opsi_host_key':          '',
				'wait_before_reboot':     3,
				'wait_before_shutdown':   3,
				'wait_for_gui_timeout':   120,
			},
			'config_service': {
				'server_id':              '',
				'url':                    '',
				'connection_timeout':     10,
				'user_cancellable_after': 0,
			},
			'depot_server': {
				'depot_id':               '',
				'url':                    '',
				'drive':                  '',
			},
			'cache_service': {
				'storage_dir':            'cache_service',
				'backend_manager_config': '',
			},
			'control_server': {
				'interface':              '0.0.0.0', # TODO
				'port':                   4441,
				'ssl_server_key_file':    'opsiclientd.pem',
				'ssl_server_cert_file':   'opsiclientd.pem',
				'static_dir':             'static_html',
			},
			'notification_server': {
				'interface':              '127.0.0.1',
				'port':                   4442,
			},
			'opsiclientd_notifier': {
				'command':                '',
				'block_notifier_command': '',
			},
			'action_processor': {
				'run_as_user':            'pcpatch',
				'local_dir':              '',
				'remote_dir':             '',
				'filename':               '',
				'command':                '',
			}
		}
		
		self._possibleMethods = [
			{ 'name': 'getPossibleMethods_listOfHashes', 'params': [ ],                              'availability': ['server', 'pipe'] },
			{ 'name': 'getBlockLogin',                   'params': [ ],                              'availability': ['server', 'pipe'] },
			{ 'name': 'isRebootRequested',               'params': [ ],                              'availability': ['server', 'pipe'] },
			{ 'name': 'isShutdownRequested',             'params': [ ],                              'availability': ['server', 'pipe'] },
			{ 'name': 'getBlockLogin',                   'params': [ ],                              'availability': ['server', 'pipe'] },
			{ 'name': 'setBlockLogin',                   'params': [ 'blockLogin' ],                 'availability': ['server'] },
			{ 'name': 'runCommand',                      'params': [ 'command', '*desktop' ],        'availability': ['server'] },
			{ 'name': 'fireEvent',                       'params': [ 'name' ],                       'availability': ['server'] },
			{ 'name': 'logoffCurrentUser',               'params': [ ],                              'availability': ['server'] },
			{ 'name': 'lockWorkstation',                 'params': [ ],                              'availability': ['server'] },
			{ 'name': 'setStatusMessage',                'params': [ 'message' ],                    'availability': ['server'] },
			{ 'name': 'readLog',                         'params': [ '*type' ],                      'availability': ['server'] },
			{ 'name': 'shutdown',                        'params': [ '*wait' ],                      'availability': ['server'] },
			{ 'name': 'reboot',                          'params': [ '*wait' ],                      'availability': ['server'] },
			{ 'name': 'uptime',                          'params': [ ],                              'availability': ['server'] },
			{ 'name': 'getCurrentActiveDesktopName',     'params': [ ],                              'availability': ['server'] },
			{ 'name': 'setCurrentActiveDesktopName',     'params': [ 'desktop' ],                    'availability': ['server'] },
			{ 'name': 'setConfigValue',                  'params': [ 'section', 'option', 'value' ], 'availability': ['server'] },
			{ 'name': 'updateConfigFile',                'params': [ ],                              'availability': ['server'] },
		]
	
	def setBlockLogin(self, blockLogin):
		self._blockLogin = bool(blockLogin)
		
	def getNotificationServer(self):
		return self._notificationServer
	
	def getStatusSubject(self):
		return self._statusSubject
	
	def getEventSubject(self):
		return self._eventSubject
	
	def isRunning(self):
		return self._running
		
	
	def getConfigValue(self, section, option, raw = False):
		if not section:
			section = 'global'
		section = str(section).strip().lower()
		option = str(option).strip().lower()
		if not self._config.has_key(section):
			raise ValueError("No such config section: %s" % section)
		if not self._config[section].has_key(option):
			raise ValueError("No such config option in section '%s': %s" % (section, option))
		
		value = self._config[section][option]
		if not raw and type(value) in (unicode, str) and (value.count('%') >= 2):
			value = self.fillPlaceholders(value)
		return value
		
	def setConfigValue(self, section, option, value):
		if not section:
			section = 'global'
		
		section = str(section).strip().lower()
		option = str(option).strip().lower()
		value = value.strip()
		
		logger.info("Setting config value %s.%s" % (section, option))
		logger.debug("setConfigValue(%s, %s, %s)" % (section, option, value))
		
		if option not in ('action_processor_command') and (value == ''):
			logger.warning("Refusing to set empty value for config value '%s' of section '%s'" % (option, section))
			return
		
		if (option == 'opsi_host_key'):
			if (len(value) != 32):
				raise ValueError("Bad opsi host key, length != 32")
			logger.addConfidentialString(value)
		
		if section in ('system'):
			return
		
		if option in ('log_level', 'port', 'wait_for_gui_timeout'):
			value = int(value)
		
		if not self._config.has_key(section):
			self._config[section] = {}
		self._config[section][option] = value
		
		if   (section == 'config_service') and (option == 'url'):
			self.setConfigServiceUrl(self._config[section][option])
		elif (section == 'config_service') and option in ('connection_timeout', 'user_cancellable_after'):
			self._config[section][option] = int(self._config[section][option])
			if (self._config[section][option] < 0):
				self._config[section][option] = 0
		elif (section == 'global') and (option == 'log_level'):
			logger.setFileLevel(self._config[section][option])
		elif (section == 'global') and (option == 'log_file'):
			logger.setLogFile(self._config[section][option])
		
	def readConfigFile(self):
		''' Get settings from config file '''
		logger.notice("Trying to read config from file: '%s'" % self._config['global']['config_file'])
		
		try:
			# Read Config-File
			config = File().readIniFile(self._config['global']['config_file'], raw = True)
			
			# Read log settings early
			if config.has_section('global'):
				if config.has_option('global', 'log_level'):
					self.setConfigValue('global', 'log_level', config.get('global', 'log_level'))
				if config.has_option('global', 'log_file'):
					logFile = config.get('global', 'log_file')
					for i in (2, 1, 0):
						slf = None
						dlf = None
						try:
							slf = logFile + '.' + str(i-1)
							if (i <= 0):
								slf = logFile
							dlf = logFile + '.' + str(i)
							if os.path.exists(slf):
								if os.path.exists(dlf):
									os.unlink(dlf)
								os.rename(slf, dlf)
						except Exception, e:
							logger.error("Failed to rename %s to %s: %s" % (slf, dlf, e) )
					self.setConfigValue('global', 'log_file', logFile)
			
			# Process all sections
			for section in config.sections():
				logger.debug("Processing section '%s' in config file: '%s'" % (section, self._config['global']['config_file']))
				
				for (option, value) in config.items(section):
					option = option.lower()
					self.setConfigValue(section.lower(), option, value)
				
		except Exception, e:
			# An error occured while trying to read the config file
			logger.error("Failed to read config file '%s': %s" % (self._config['global']['config_file'], e))
			logger.logException(e)
			return
		logger.notice("Config read")
		logger.debug("Config is now:\n %s" % Tools.objectToBeautifiedText(self._config))
	
	def updateConfigFile(self):
		''' Get settings from config file '''
		logger.notice("Trying to write config to file: '%s'" % self._config['global']['config_file'])
		
		try:
			# Read config file
			self._statusSubject.setMessage( _("Updating config file") )
			config = File().readIniFile(self._config['global']['config_file'], raw = True)
			changed = False
			for (section, value) in self._config.items():
				if not type(value) is dict:
					continue
				if section in ('system'):
					continue
				if not config.has_section(section):
					config.add_section(section)
					changed = True
				for (option, value) in value.items():
					if (section == 'config_service') and option in ('host', 'port'):
						continue
					if (section == 'global') and option in ('config_file', 'host_id'):
						# Do not store these options
						continue
					value = str(value)
					if not config.has_option(section, option) or (config.get(section, option) != value):
						changed = True
						config.set(section, option, value)
			if changed:
				# Write back config file if changed
				File().writeIniFile(self._config['global']['config_file'], config)
				logger.notice("Config file '%s' written" % self._config['global']['config_file'])
			else:
				logger.notice("No need to write config file '%s', config file is up to date" % self._config['global']['config_file'])
			
		except Exception, e:
			# An error occured while trying to write the config file
			logger.error("Failed to write config file '%s': %s" % (self._config['global']['config_file'], e))
			logger.logException(e)
		
		
	def getConfigFromService(self):
		''' Get settings from service '''
		logger.notice("Getting config from service")
		try:
			self._statusSubject.setMessage(_("Getting config from service"))
			
			self.connectConfigServer()
			
			for (key, value) in self._configService.getNetworkConfig_hash(self._config['global']['host_id']).items():
				if (key.lower() == 'depotid'):
					depotId = value
					self.setConfigValue(section = 'depot_server', option = 'depot_id', value = depotId)
					self.setConfigValue(section = 'depot_server', option = 'url', value = self._configService.getDepot_hash(depotId)['depotRemoteUrl'])
				elif (key.lower() == 'depotdrive'):
					self.setConfigValue(section = 'depot_server', option = 'drive', value = value)
				else:
					logger.info("Unhandled network config key '%s'" % key)
				
			logger.notice("Got network config from service")
			
			for (key, value) in self._configService.getGeneralConfig_hash(self._config['global']['host_id']).items():
				try:
					parts = key.lower().split('.')
					if (len(parts) < 3) or (parts[0] != 'opsiclientd'):
						continue
					
					self.setConfigValue(section = parts[1], option = parts[2], value = value)
					
				except Exception, e:
					logger.error("Failed to process general config key '%s:%s': %s", (key, value, e))
			
			logger.notice("Got config from service")
			
			self._statusSubject.setMessage(_("Got config from service"))
			logger.debug("Config is now:\n %s" % Tools.objectToBeautifiedText(self._config))
		#except CanceledByUserError, e:
		#	logger.error("Failed to get config from service: %s" % e)
		#	raise
		#except Exception, e:
		#	logger.error("Failed to get config from service: %s" % e)
		#	logger.logException(e)
		except Exception, e:
			logger.error("Failed to get config from service: %s" % e)
			raise
		
	def writeLogToService(self):
		logger.notice("Writing log to service")
		try:
			if not self._configService:
				raise Exception("Not connected to config service")
			self._statusSubject.setMessage( _("Writing log to service") )
			f = open(self._config['global']['log_file'])
			data = f.read()
			data += "-------------------- submitted part of log file ends here, see the rest of log file on client --------------------\n"
			f.close()
			# Do not log jsonrpc request
			logger.setFileLevel(LOG_WARNING)
			self._configService.writeLog('clientconnect', data, self._config['global']['host_id'])
			logger.setFileLevel(self._config['global']['log_level'])
		except Exception, e:
			logger.error("Failed to write log to service: %s" % e)
	
	def fillPlaceholders(self, string, escaped=False):
		for (section, values) in self._config.items():
			if not type(values) is dict:
				continue
			for (key, value) in values.items():
				value = str(value)
				if (string.find('"%' + str(section) + '.' + str(key) + '%"') != -1) and escaped:
					if (os.name == 'posix'):
						value = value.replace('"', '\\"')
					if (os.name == 'nt'):
						value = value.replace('"', '^"')
				newString = string.replace('%' + str(section) + '.' + str(key) + '%', value)
				
				if (newString != string):
					string = self.fillPlaceholders(newString, escaped)
		return string
	
	def createEvents(self):
		self._events['panic'] = PanicEvent('panic')
		self._events['panic'].actionProcessorCommand = self.getConfigValue('action_processor', 'command', raw=True)
		
		events = {}
		for (section, options) in self._config.items():
			section = section.lower()
			if section.startswith('event_'):
				eventName = section.split('_', 1)[1]
				if not eventName:
					logger.error("No event name defined in section '%s'" % section)
					continue
				if eventName in self._events.keys():
					logger.error("Event '%s' already defined" % eventName)
					continue
				events[eventName] = {
					'active': True,
					'args':   {},
					'super':  None }
				try:
					for key in options.keys():
						if   (key.lower() == 'active'):
							events[eventName]['active'] = not options[key].lower() in ('0', 'false', 'off', 'no')
						elif (key.lower() == 'super'):
							events[eventName]['super'] = options[key]
						else:
							events[eventName]['args'][key.lower()] = options[key]
				except Exception, e:
					logger.error("Failed to parse event '%s': %s" % (eventName, e))
		
		def __inheritArgsFromSuperEvents(eventsCopy, args, superEventName):
			if not superEventName in eventsCopy.keys():
				logger.error("Event '%s': Super event '%s' not found" % (eventName, superEventName))
				return args
			superArgs = pycopy.deepcopy(eventsCopy[superEventName]['args'])
			if eventsCopy[superEventName]['super']:
				__inheritArgsFromSuperEvents(eventsCopy, superArgs, eventsCopy[superEventName]['super'])
			superArgs.update(args)
			return superArgs
		
		eventsCopy = pycopy.deepcopy(events)
		for eventName in events.keys():
			if events[eventName]['super']:
				events[eventName]['args'] = __inheritArgsFromSuperEvents(eventsCopy, events[eventName]['args'], events[eventName]['super'])
		
		for (eventName, event) in events.items():
			try:
				if not event['active']:
					logger.notice("Event '%s' is deactivated" % eventName)
					continue
				
				if not event['args'].get('type'):
					logger.error("Event '%s': event type not set" % eventName)
					continue
				
				#if not event['args'].get('action_processor_command'):
				#	event['args']['action_processor_command'] = self.getConfigValue('action_processor', 'command')
				
				args = {}
				for (key, value) in event['args'].items():
					if   (key == 'type'):
						continue
					elif (key == 'message'):
						args['message'] = value
					elif (key == 'max_repetitions'):
						args['maxRepetitions'] = int(value)
					elif (key == 'activation_delay'):
						args['activationDelay'] = int(value)
					elif (key == 'notification_delay'):
						args['notificationDelay'] = int(value)
					elif (key == 'warning_time'):
						args['warningTime'] = int(value)
					elif (key == 'wql'):
						args['wql'] = value
					elif (key == 'user_cancelable'):
						args['userCancelable'] = not value.lower() in ('0', 'false', 'off', 'no')
					elif (key == 'block_login'):
						args['blockLogin'] = not value.lower() in ('0', 'false', 'off', 'no')
					elif (key == 'lock_workstation'):
						args['lockWorkstation'] = value.lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'logoff_current_user'):
						args['logoffCurrentUser'] = value.lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'get_config_from_service'):
						args['getConfigFromService'] = not value.lower() in ('0', 'false', 'off', 'no')
					elif (key == 'update_config_file'):
						args['updateConfigFile'] = not value.lower() in ('0', 'false', 'off', 'no')
					elif (key == 'write_log_to_service'):
						args['writeLogToService'] = not value.lower() in ('0', 'false', 'off', 'no')
					elif (key == 'cache_products'):
						args['cacheProducts'] = value.lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'cache_max_bandwidth'):
						args['cacheMaxBandwidth'] = int(value)
					elif (key == 'requires_cached_products'):
						args['requiresCachedProducts'] = value.lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'sync_config'):
						args['syncConfig'] = value.lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'use_cached_config'):
						args['useCachedConfig'] = value.lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'update_action_processor'):
						args['updateActionProcessor'] = not value.lower() in ('0', 'false', 'off', 'no')
					elif (key == 'event_notifier_command'):
						args['eventNotifierCommand'] = self.fillPlaceholders(value.lower(), escaped=True)
					elif (key == 'event_notifier_desktop'):
						args['eventNotifierDesktop'] = value.lower()
					elif (key == 'action_notifier_command'):
						args['actionNotifierCommand'] = self.fillPlaceholders(value.lower(), escaped=True)
					elif (key == 'action_notifier_desktop'):
						args['actionNotifierDesktop'] = value.lower()
					elif (key == 'action_processor_command'):
						args['actionProcessorCommand'] = value.lower()
					elif (key == 'action_processor_desktop'):
						args['actionProcessorDesktop'] = value.lower()
					elif (key == 'service_options'):
						args['serviceOptions'] = eval(value)
					else:
						logger.error("Skipping unknown option '%s' in definition of event '%s'" % (key, eventName))
				
				logger.info("\nEvent '" + eventName + "' args:\n" + Tools.objectToBeautifiedText(args) + "\n")
				
				if   (event['args']['type'] == EVENT_TYPE_PRODUCT_SYNC_COMPLETED):
					self._events[eventName] = ProductSyncCompletedEvent(eventName, **args)
				elif (event['args']['type'] == EVENT_TYPE_DAEMON_STARTUP):
					self._events[eventName] = DaemonStartupEvent(eventName, **args)
				elif (event['args']['type'] == EVENT_TYPE_DAEMON_SHUTDOWN):
					self._events[eventName] = DaemonShutdownEvent(eventName, **args)
				elif (event['args']['type'] == EVENT_TYPE_GUI_STARTUP):
					self._events[eventName] = GUIStartupEvent(eventName, **args)
				elif (event['args']['type'] == EVENT_TYPE_TIMER):
					self._events[eventName] = TimerEvent(eventName, **args)
				elif (event['args']['type'] == EVENT_TYPE_CUSTOM):
					self._events[eventName] = CustomEvent(eventName, **args)
				else:
					raise ValueError("Unhandled event type '%s' in definition of event '%s'" % (event['args']['type'], eventName))
				logger.notice("%s event '%s' created" % (event['args']['type'], eventName))
				
			except Exception, e:
					logger.error("Failed to create event '%s': %s" % (eventName, e))
		
		for event in self._events.values():
			event.addEventListener(self)
			event.start()
			logger.notice("Event '%s' started" % event)
	
	def getEvents(self, eventType=''):
		events = []
		for event in self._events.values():
			if not eventType or (event.getType() == eventType):
				events.append(event)
		return events
		
	def waitForGUI(self, timeout=None):
		if not timeout:
			timeout = None
		class WaitForGUI(EventListener):
			def __init__(self, waitApp = None):
				self._waitApp = waitApp
				self._waitAppPid = None
				if self._waitApp:
					logger.info("Starting wait for GUI app")
					try:
						self._waitAppPid = System.runCommandInSession(
							command = self._waitApp,
							sessionId = None,
							desktop = 'winlogon',
							waitForProcessEnding = False)[2]
					except Exception, e:
						logger.error("Failed to start wait for GUI app: %s" % e)
				self._guiStarted = threading.Event()
				event = GUIStartupEvent("wait_for_gui")
				event.addEventListener(self)
				event.start()
			
			def processEvent(self, event):
				if self._waitAppPid:
					try:
						logger.info("Terminating wait for GUI app (pid %s)" % self._waitAppPid)
						System.terminateProcess(processId = self._waitAppPid)
					except Exception, e:
						logger.warning("Failed to terminate wait for GUI app: %s" % e)
				self._guiStarted.set()
				
			def wait(self, timeout=None):
				self._guiStarted.wait(timeout)
				if not self._guiStarted.isSet():
					logger.warning("Timed out after %d seconds while waiting for GUI" % timeout)
				
		WaitForGUI(self.getConfigValue('global', 'wait_for_gui_application')).wait(timeout)
		
	def run(self):
		self._running = True
		
		self.readConfigFile()
		
		try:
			logger.comment("Opsiclientd version: %s" % __version__)
			logger.comment("Commandline: %s" % ' '.join(sys.argv))
			logger.comment("Working directory: %s" % os.getcwd())
			logger.notice("Using host id '%s'" % self._config['global']['host_id'])
			
			self.setBlockLogin(True)
			
			self._clientIdSubject.setMessage(self._config['global']['host_id'])
			self._opsiclientdInfoSubject.setMessage("opsiclientd %s" % __version__)
			self.setActionProcessorInfo()
			
			logger.notice("Starting control pipe")
			try:
				self._controlPipe = ControlPipeFactory(self)
				self._controlPipe.start()
				logger.notice("Control pipe started")
			except Exception, e:
				logger.error("Failed to start control pipe: %s" % e)
				raise
			
			logger.notice("Starting control server")
			try:
				self._controlServer = ControlServer(
								opsiclientd       = self,
								httpsPort         = self.getConfigValue('control_server', 'port'),
								sslServerKeyFile  = self.getConfigValue('control_server', 'ssl_server_key_file'),
								sslServerCertFile = self.getConfigValue('control_server', 'ssl_server_cert_file'),
								staticDir         = self.getConfigValue('control_server', 'static_dir') )
				self._controlServer.start()
				logger.notice("Control server started")
			except Exception, e:
				logger.error("Failed to start control server: %s" % e)
				raise
			
			logger.notice("Starting cache service")
			try:
				self._cacheService = CacheService(opsiclientd = self)
				self._cacheService.start()
				logger.notice("Cache service started")
			except Exception, e:
				logger.error("Failed to start cache service: %s" % e)
				raise
			
			logger.notice("Starting notification server")
			try:
				self._notificationServer = NotificationServer(
								address  = self._config['notification_server']['interface'],
								port     = self._config['notification_server']['port'],
								subjects = [
									self._statusSubject,
									self._eventSubject,
									self._serviceUrlSubject,
									self._clientIdSubject,
									self._actionProcessorInfoSubject,
									self._opsiclientdInfoSubject,
									self._detailSubjectProxy,
									self._currentProgressSubjectProxy,
									self._overallProgressSubjectProxy ] )
				logger.setLogFormat('[%l] [%D] [notification server]   %M     (%F|%N)', object=self._notificationServer)
				logger.setLogFormat('[%l] [%D] [notification server]   %M     (%F|%N)', object=self._notificationServer.getObserver())
				self._notificationServer.start()
				logger.notice("Notification server started")
			except Exception, e:
				logger.error("Failed to start notification server: %s" % e)
				raise
			
			# Create events
			self.createEvents()
			for event in self.getEvents(EVENT_TYPE_DAEMON_STARTUP):
				event.fire()
			
			# Wait until gui starts up
			logger.notice("Waiting for gui startup (timeout: %d seconds)" % self._config['global']['wait_for_gui_timeout'])
			self.waitForGUI(timeout = self._config['global']['wait_for_gui_timeout'])
			logger.notice("Gui started")
			
			# Wait some more seconds for events to fire
			time.sleep(5)
			if not self._processingEvent:
				logger.notice("No events processing, unblocking login")
				self.setBlockLogin(False)
			
			# TODO: passive wait?
			while self._running:
				time.sleep(1)
			for event in self.getEvents(EVENT_TYPE_DAEMON_SHUTDOWN):
				event.fire()
			
		except Exception, e:
			logger.logException(e)
			self.setBlockLogin(False)
		
		self._running = False
		
	def stop(self):
		logger.notice("opsiclientd is going down")
		self.setBlockLogin(False)
		
		# Stop cache service
		if self._cacheService:
			self._cacheService.stop()
		
		# Stop control pipe thread
		if self._controlPipe:
			self._controlPipe.stop()
		
		# Stop control server thread
		if self._controlServer:
			self._controlServer.stop()
		
		# Stop notification server thread
		if self._notificationServer:
			self._notificationServer.stop()
		
		self._running = False
	
	def authenticate(self, username, password):
		if (username == self._config['global']['host_id']) and (password == self._config['global']['opsi_host_key']):
			return True
		if (os.name == 'nt'):
			if (username == 'Administrator'):
				import win32security
				# The LogonUser function will raise an Exception on logon failure
				win32security.LogonUser(username, 'None', password, win32security.LOGON32_LOGON_NETWORK, win32security.LOGON32_PROVIDER_DEFAULT)
				# No exception raised => user authenticated
				return True
		raise Exception("Invalid credentials")
		
	def setConfigServiceUrl(self, url):
		if not re.search('https?://[^/]+', url):
			raise ValueError("Bad config service url '%s'" % url)
		self._config['config_service']['url'] = url
		self._config['config_service']['host'] = self._config['config_service']['url'].split('/')[2]
		self._config['config_service']['port'] = '4447'
		if (self._config['config_service']['host'].find(':') != -1):
			(self._config['config_service']['host'], self._config['config_service']['port']) = self._config['config_service']['host'].split(':', 1)
		self._serviceUrlSubject.setMessage(self._config['config_service']['url'])
	
	def setActionProcessorInfo(self):
		self._actionProcessorInfoSubject.setMessage("")
	
	def processEvent(self, event):
		logger.notice("Processing event %s" % event)
		self._statusSubject.setMessage( _("Processing event %s") % event )
		
		if self._processingEvent and (event._type != EVENT_TYPE_PANIC):
			logger.error("Already processing event")
			return
		self._processingEvent = True
		
		eventProcessingThread = EventProcessingThread(self, event)
		eventProcessingThread.start()
		eventProcessingThread.join()
		logger.notice("Done processing event '%s'" % event)
		
		self._processingEvent = False
	
	def processProductActionRequests(self, event):
		logger.error("processProductActionRequests not implemented")
	
	def connectConfigServer(self):
		if self._configService:
			# Already connected
			return
		
		if self._configServiceException:
			# Exception will be cleared on disconnect
			raise Exception("Connect failed, will not retry")
		
		try:
			choiceSubject = ChoiceSubject(id = 'choice')
			choiceSubject.setChoices([ 'Stop connection' ])
			
			logger.debug("Creating ServiceConnectionThread")
			serviceConnectionThread = ServiceConnectionThread(
						configServiceUrl    = self.getConfigValue('config_service', 'url'),
						username            = self.getConfigValue('global', 'host_id'),
						password            = self.getConfigValue('global', 'opsi_host_key'),
						notificationServer  = self._notificationServer,
						statusObject        = self._statusSubject )
			
			choiceSubject.setCallbacks( [ serviceConnectionThread.stopConnectionCallback ] )
			
			cancellableAfter = int(self._config['config_service']['user_cancellable_after'])
			if (cancellableAfter < 1):
				self._notificationServer.addSubject(choiceSubject)
			
			timeout = int(self._config['config_service']['connection_timeout'])
			logger.info("Starting ServiceConnectionThread, timeout is %d seconds" % timeout)
			serviceConnectionThread.start()
			time.sleep(1)
			logger.debug("ServiceConnectionThread started")
			
			while serviceConnectionThread.running and (timeout > 0):
				logger.debug("Waiting for ServiceConnectionThread (timeout: %d, alive: %s) " % (timeout, serviceConnectionThread.isAlive()))
				self._detailSubjectProxy.setMessage( _('Timeout: %ds') % timeout )
				cancellableAfter -= 1
				if (cancellableAfter == 0):
					self._notificationServer.addSubject(choiceSubject)
				time.sleep(1)
				timeout -= 1
			
			self._detailSubjectProxy.setMessage('')
			self._notificationServer.removeSubject(choiceSubject)
			
			if serviceConnectionThread.cancelled:
				logger.error("ServiceConnectionThread canceled by user")
				raise CanceledByUserError("Failed to connect to config service '%s': cancelled by user" % \
							self._config['config_service']['url'] )
			elif serviceConnectionThread.running:
				logger.error("ServiceConnectionThread timed out after %d seconds" % self._config['config_service']['connection_timeout'])
				serviceConnectionThread.stop()
				raise Exception("Failed to connect to config service '%s': timed out after %d seconds" % \
							(self._config['config_service']['url'], self._config['config_service']['connection_timeout']) )
				
			if not serviceConnectionThread.connected:
				raise Exception("Failed to connect to config service '%s': reason unknown" % self._config['config_service']['url'])
			
			if (serviceConnectionThread.getUsername() != self._config['global']['host_id']):
				self._config['global']['host_id'] = serviceConnectionThread.getUsername()
				logger.info("Updated host_id to '%s'" % self._config['global']['host_id'])
			self._configService = serviceConnectionThread.configService
			self._config['config_service']['server_id'] = self._configService.getServerId(self._config['global']['host_id'])
			logger.info("Updated config_service.host_id to '%s'" % self._config['config_service']['server_id'])
			
			if self.getConfigValue('config_service', 'url').split('/')[2] not in ('127.0.0.1', 'localhost'):
				
				try:
					modules = self._configService.getOpsiInformation_hash()['modules']
					if not modules.get('vista'):
						raise Exception("Vista module currently disabled")
					
					if not modules.get('valid'):
						raise Exception("Modules file invalid")
					
					if (modules.get('expires', '') != 'never') and (time.mktime(time.strptime(modules.get('expires', '2000-01-01'), "%Y-%m-%d")) - time.time() <= 0):
						raise Exception("Modules file signature expired")
					
					logger.info("Verifying modules file signature")
					import base64, md5, twisted.conch.ssh.keys
					publicKey = twisted.conch.ssh.keys.getPublicKeyObject(data = base64.decodestring('AAAAB3NzaC1yc2EAAAADAQABAAABAQCAD/I79Jd0eKwwfuVwh5B2z+S8aV0C5suItJa18RrYip+d4P0ogzqoCfOoVWtDojY96FDYv+2d73LsoOckHCnuh55GA0mtuVMWdXNZIE8Avt/RzbEoYGo/H0weuga7I8PuQNC/nyS8w3W8TH4pt+ZCjZZoX8S+IizWCYwfqYoYTMLgB0i+6TCAfJj3mNgCrDZkQ24+rOFS4a8RrjamEz/b81noWl9IntllK1hySkR+LbulfTGALHgHkDUlk0OSu+zBPw/hcDSOMiDQvvHfmR4quGyLPbQ2FOVm1TzE0bQPR+Bhx4V8Eo2kNYstG2eJELrz7J1TJI0rCjpB+FQjYPsP'))
					data = ''
					mks = modules.keys()
					mks.sort()
					for module in mks:
						if module in ('valid', 'signature'):
							continue
						val = modules[module]
						if (val == False): val = 'no'
						if (val == True):  val = 'yes'
						data += module.lower().strip() + ' = ' + val + '\r\n'
					if not bool(publicKey.verify(md5.new(data).digest(), [ long(modules['signature']) ])):
						raise Exception("Modules file invalid")
					logger.info("Modules file signature verified")
				except Exception, e:
					logger.critical(e)
					self.writeLogToService()
					raise
		except Exception, e:
			self._configService = None
			self._configServiceException = e
			raise
		
	def disconnectConfigServer(self):
		self._configService = None
		self._configServiceException = None
	
	def getPossibleMethods(self):
		return self._possibleMethods
	
	def executeServerRpc(self, method, params=[]):
		for m in self._possibleMethods:
			if (m['name'] == method):
				if 'server' not in m['availability']:
					raise Exception("Access denied")
				break
		
		if (method == 'getPossibleMethods_listOfHashes'):
			pm = []
			for m in self._possibleMethods:
				if 'server' in m['availability']:
					pm.append(m)
			return pm
		
		return self.executeRpc(method, params)
		
	def executePipeRpc(self, method, params=[]):
		for m in self._possibleMethods:
			if (m['name'] == method):
				if 'pipe' not in m['availability']:
					raise Exception("Access denied")
				break
		
		if (method == 'getPossibleMethods_listOfHashes'):
			pm = []
			for m in self._possibleMethods:
				if 'pipe' in m['availability']:
					pm.append(m)
			return pm
		
		return self.executeRpc(method, params)
		
	def executeRpc(self, method, params=[]):
		if not params:
			params = []
		if not type(params) is list:
			params = [ params ]
			
		exists = False
		for m in self._possibleMethods:
			if (m['name'] == method):
				while (len(params) < len(m['params'])):
					params.append(None)
				exists = True
				break
		if not exists:
			raise NotImplementedError("Method '%s' not known" % method)
		
		try:
			if (method == 'getBlockLogin'):
				logger.notice("rpc getBlockLogin: blockLogin is '%s'" % self._blockLogin)
				return self._blockLogin
			
			elif (method == 'setBlockLogin'):
				self.setBlockLogin(bool(params[0]))
				logger.notice("rpc setBlockLogin: blockLogin set to '%s'" % self._blockLogin)
				if self._blockLogin:
					return "Login blocker is on"
				else:
					return "Login blocker is off"
			
			elif (method == 'runCommand'):
				if not params[0]:
					raise ValueError("No command given")
				desktop = None
				if (len(params) > 1) and params[1]:
					desktop = str(params[1])
				else:
					desktop = self.getCurrentActiveDesktopName()
				logger.notice("rpc runCommand: executing command '%s' on desktop '%s'" % (params[0], desktop))
				System.runCommandInSession(command = str(params[0]), sessionId = None, desktop = desktop, waitForProcessEnding = False)
				return "command '%s' executed" % str(params[0])
			
			elif (method == 'logoffCurrentUser'):
				logger.notice("rpc logoffCurrentUser: logging of current user now")
				System.logoffCurrentUser()
				
			elif (method == 'lockWorkstation'):
				logger.notice("rpc lockWorkstation: locking workstation now")
				System.lockWorkstation()
				
			elif (method == 'fireEvent'):
				if not params[0]:
					raise ValueError("No event name given")
				name = params[0]
				if not name in self._events.keys():
					raise ValueError("Event '%s' not in list of known events: %s" % (name, ', '.join(self._events.keys())))
				logger.notice("Firing event '%s'" % name)
				self._events[name].fire()
			
			elif (method == 'setStatusMessage'):
				message = params[0]
				if not type(message) in (str, unicode):
					message = ""
				logger.notice("rpc setStatusMessage: Setting status message to '%s'" % message)
				self._statusSubject.setMessage(message)
			
			elif (method == 'readLog'):
				logType = 'opsiclientd'
				if (len(params) > 0) and params[0]:
					logType = str(params[0])
				logger.notice("rpc readLog: reading log of type '%s'" % logType)
				if not logType in ('opsiclientd'):
					raise ValueError("Unknown log type '%s'" % logType)
				if (logType == 'opsiclientd'):
					f = open(self._config['global']['log_file'])
					data = f.read()
					f.close()
					return data
				return ""
			
			elif (method == 'shutdown'):
				wait = 0
				if (len(params) > 0) and type(params[0]) is int:
					wait = int(params[0])
				logger.notice("rpc shutdown: shutting down computer in %s seconds" % wait)
				System.shutdown(wait = wait)
			
			elif (method == 'isShutdownRequested'):
				return self._shutdownRequested
			
			elif (method == 'reboot'):
				wait = 0
				if (len(params) > 0) and type(params[0]) is int:
					wait = int(params[0])
				logger.notice("rpc reboot: rebooting computer in %s seconds" % wait)
				System.reboot(wait = wait)
			
			elif (method == 'isRebootRequested'):
				return self._rebootRequested
			
			elif (method == 'uptime'):
				uptime = int(time.time() - self._startupTime)
				logger.notice("rpc uptime: opsiclientd is running for %d seconds" % uptime)
				return uptime
			
			elif (method == 'getCurrentActiveDesktopName'):
				desktop = self.getCurrentActiveDesktopName()
				logger.notice("rpc getCurrentActiveDesktopName: current active desktop name is '%s'" % desktop)
				return desktop
			
			elif (method == 'setCurrentActiveDesktopName'):
				self._currentActiveDesktopName = str(params[0])
				logger.notice("rpc setCurrentActiveDesktopName: current active desktop name set to '%s'" % params[0])
			
			elif (method == 'setConfigValue'):
				if (len(params) < 3):
					raise ValueError("section, option or value missing")
				return self.setConfigValue(*params)
			
			elif (method == 'updateConfigFile'):
				self.updateConfigFile()
			
			else:
				raise NotImplementedError("Method '%s' not implemented" % method)
			
		except Exception, e:
			logger.logException(e)
			raise
	
	def getCurrentActiveDesktopName(self):
		if not (self._config.has_key('opsiclientd_rpc') and self._config['opsiclientd_rpc'].has_key('command')):
			raise Exception("opsiclientd_rpc command not defined")
		rpc = 'setCurrentActiveDesktopName(System.getActiveDesktopName())'
		cmd = '%s "%s"' % (self.getConfigValue('opsiclientd_rpc', 'command'), rpc)
		System.runCommandInSession(command = cmd, waitForProcessEnding = True)
		return self._currentActiveDesktopName
	
	def closeProcessWindows(self, processId):
		if not (self._config.has_key('opsiclientd_rpc') and self._config['opsiclientd_rpc'].has_key('command')):
			raise Exception("opsiclientd_rpc command not defined")
		rpc = 'exit(); System.closeProcessWindows(processId = %s)' % processId
		cmd = '%s "%s"' % (self.getConfigValue('opsiclientd_rpc', 'command'), rpc)
		System.runCommandInSession(command = cmd, waitForProcessEnding = False)
	
	def processShutdownRequests(self):
		pass
	
	
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                         OPSICLIENTD POSIX                                         -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class OpsiclientdPosix(Opsiclientd):
	def __init__(self):
		Opsiclientd.__init__(self)

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
		System.shutdown(wait = self._config['global']['wait_before_reboot'])
	
	def _rebootMachine(self):
		self._rebootRequested = True
		System.reboot(wait = self._config['global']['wait_before_reboot'])
	
	def updateActionProcessor(self):
		logger.notice("Updating action processor")
		self._statusSubject.setMessage(_("Updating action processor"))
		
		self.connectConfigServer()
		
		actionProcessorFilename = self._config['action_processor']['filename']
		
		actionProcessorLocalDir = self.getConfigValue('action_processor', 'local_dir')
		actionProcessorLocalTmpDir = actionProcessorLocalDir + '.tmp'
		actionProcessorLocalFile = os.path.join(actionProcessorLocalDir, actionProcessorFilename)
		actionProcessorLocalTmpFile = os.path.join(actionProcessorLocalTmpDir, actionProcessorFilename)
		
		actionProcessorRemoteDir = os.path.join(self._config['depot_server']['drive'], self._config['action_processor']['remote_dir'])
		actionProcessorRemoteFile = os.path.join(actionProcessorRemoteDir, actionProcessorFilename)
		
		if not os.path.exists(actionProcessorLocalFile):
			logger.notice("Action processor needs update because file '%s' not found" % actionProcessorLocalFile)
		elif ( abs(os.stat(actionProcessorLocalFile).st_mtime - os.stat(actionProcessorRemoteFile).st_mtime) > 10 ):
			logger.notice("Action processor needs update because modification time difference is more than 10 seconds")
		elif not filecmp.cmp(actionProcessorLocalFile, actionProcessorRemoteFile):
			logger.notice("Action processor needs update because file changed")
		else:
			logger.notice("Local action processor exists and seems to be up to date")
			return actionProcessorLocalFile
		
		# Update files
		logger.notice("Start copying the action processor files")
		if os.path.exists(actionProcessorLocalTmpDir):
			logger.info("Deleting dir '%s'" % actionProcessorLocalTmpDir)
			shutil.rmtree(actionProcessorLocalTmpDir)
		logger.info("Copying from '%s' to '%s'" % (actionProcessorRemoteDir, actionProcessorLocalTmpDir))
		shutil.copytree(actionProcessorRemoteDir, actionProcessorLocalTmpDir)
		
		if not os.path.exists(actionProcessorLocalTmpFile):
			raise Exception("File '%s' does not exist after copy" % actionProcessorLocalTmpFile)
		
		if os.path.exists(actionProcessorLocalDir):
			logger.info("Deleting dir '%s'" % actionProcessorLocalDir)
			shutil.rmtree(actionProcessorLocalDir)
		
		logger.info("Moving dir '%s' to '%s'" % (actionProcessorLocalTmpDir, actionProcessorLocalDir))
		shutil.move(actionProcessorLocalTmpDir, actionProcessorLocalDir)
		
		logger.notice('Local action processor successfully updated')
		
		self._configService.setProductInstallationStatus(
						'opsi-winst',
						self._config['global']['host_id'],
						'installed')
		
		self.setActionProcessorInfo()
	
	def setActionProcessorInfo(self):
		try:
			actionProcessorFilename = self.getConfigValue('action_processor', 'filename')
			actionProcessorLocalDir = self.getConfigValue('action_processor', 'local_dir')
			actionProcessorLocalFile = os.path.join(actionProcessorLocalDir, actionProcessorFilename)
			actionProcessorLocalFile = actionProcessorLocalFile
			info = System.getFileVersionInfo(actionProcessorLocalFile)
			version = info.get('FileVersion', u'')
			name = info.get('ProductName', u'')
			logger.info("Action processor name '%s', version '%s'" % (name, version))
			self._actionProcessorInfoSubject.setMessage("%s %s" % (name.encode('utf-8'), version.encode('utf-8')))
		except Exception, e:
			logger.error("Failed to set action processor info: %s" % e)
	
	def processProductActionRequests(self, event):
		self._statusSubject.setMessage(_("Getting action requests from config service"))
		
		try:
			bootmode = ''
			try:
				bootmode = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\general", "bootmode")
			except Exception, e:
				logger.warning("Failed to get bootmode from registry: %s" % e)
			
			self.connectConfigServer()
			productStates = []
			if (self._configService.getLocalBootProductStates_hash.func_code.co_argcount == 2):
				if event.serviceOptions:
					logger.warning("Service cannot handle service options in method getLocalBootProductStates_hash")
				productStates = self._configService.getLocalBootProductStates_hash(self._config['global']['host_id'])
				productStates = productStates.get(self._config['global']['host_id'], [])
			else:
				productStates = self._configService.getLocalBootProductStates_hash(self._config['global']['host_id'], event.serviceOptions)
				productStates = productStates.get(self._config['global']['host_id'], [])
			
			logger.notice("Got product action requests from configservice")
			productIds = []
			for productState in productStates:
				if (productState['actionRequest'] not in ('none', 'undefined')):
					productIds.append(productState['productId'])
					logger.notice("   [%2s] product %-20s %s" % (len(productIds), productState['productId'] + ':', productState['actionRequest']))
			
			if (len(productIds) == 0) and (bootmode == 'BKSTD'):
				logger.notice("No product action requests set")
				self._statusSubject.setMessage( _("No product action requests set") )
			
			else:
				logger.notice("Start processing action requests")
				
				if not event.useCachedConfig and event.syncConfig:
					logger.notice("Syncing config (products: %s)" % productIds)
					self._cacheService.init()
					self._statusSubject.setMessage( _("Syncing config") )
					self._cacheService.setCurrentConfigProgressObserver(self._currentProgressSubjectProxy)
					self._cacheService.setOverallConfigProgressObserver(self._overallProgressSubjectProxy)
					self._cacheService.syncConfig(productIds = productIds, waitForEnding = True)
					self._statusSubject.setMessage( _("Config synced") )
					self._currentProgressSubjectProxy.setState(0)
					self._overallProgressSubjectProxy.setState(0)
					
				# Setting some registry values before starting action
				# Mainly for action processor winst
				System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "depoturl",   self._config['depot_server']['url'])
				System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "depotdrive", self._config['depot_server']['drive'])
				System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "configurl",   "<deprecated>")
				System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "configdrive", "<deprecated>")
				System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "utilsurl",    "<deprecated>")
				System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "utilsdrive",  "<deprecated>")
				
				if event.cacheProducts:
					logger.notice("Caching products: %s (max bandwidth: %d bit/s)" % (productIds, event.cacheMaxBandwidth))
					self._cacheService.init()
					if event.cacheMaxBandwidth:
						self._statusSubject.setMessage( _("Caching products (%d kbit/s)") % (event.cacheMaxBandwidth/1000) )
					else:
						self._statusSubject.setMessage( _("Caching products") )
					self._cacheService.setCurrentProductProgressObserver(self._currentProgressSubjectProxy)
					self._cacheService.setOverallProductProgressObserver(self._overallProgressSubjectProxy)
					self._currentProgressSubjectProxy.attachObserver(self._detailSubjectProxy)
					
					try:
						if not self._cacheService.cacheProducts(productIds, maxBandwidth=event.cacheMaxBandwidth, waitForEnding=True):
							raise Exception("Failed to cache products")
					finally:
						self._detailSubjectProxy.setMessage("")
						self._currentProgressSubjectProxy.detachObserver(self._detailSubjectProxy)
					
					self._statusSubject.setMessage( _("Products cached") )
					self._currentProgressSubjectProxy.setState(0)
					self._overallProgressSubjectProxy.setState(0)
				
				if event.actionProcessorCommand:
					self._statusSubject.setMessage( _("Starting actions") )
					self.runProductActions(event)
					self._statusSubject.setMessage( _("Actions completed") )
				
		except Exception, e:
			logger.logException(e)
			logger.error("Failed to process product action requests: %s" % e)
			self._statusSubject.setMessage( _("Failed to process product action requests: %s") % e )
		
		time.sleep(3)
	
	def processShutdownRequests(self):
		self._rebootRequested = False
		self._shutdownRequested = False
		rebootRequested = 0
		try:
			rebootRequested = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "RebootRequested")
		except Exception, e:
			logger.error("Failed to get rebootRequested from registry: %s" % e)
		logger.info("rebootRequested: %s" % rebootRequested)
		if rebootRequested:
			System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "RebootRequested", 0)
			if (rebootRequested == 2):
				# Logout
				logger.notice("Logout requested, nothing to do")
				pass
			else:
				# Reboot
				self._rebootRequested = True
				self._statusSubject.setMessage(_("Rebooting machine"))
				self._rebootMachine()
		else:
			shutdownRequested = 0
			try:
				shutdownRequested = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "ShutdownRequested")
			except Exception, e:
				logger.error("Failed to get shutdownRequested from registry: %s" % e)
			logger.info("shutdownRequested: %s" % shutdownRequested)
			if shutdownRequested:
				# Shutdown
				System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "ShutdownRequested", 0)
				self._shutdownRequested = True
				self._statusSubject.setMessage(_("Shutting down machine"))
				self._shutdownMachine()
		
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                          OPSICLIENTD NT5                                          -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class OpsiclientdNT5(OpsiclientdNT):
	def __init__(self):
		OpsiclientdNT.__init__(self)
		if (sys.getwindowsversion()[1] == 0):
			# NT 5.0 / win2k
			# If reboot/shutdown is triggered while pgina.dll is
			# in function WlxInitialize the system will not reboot/shutdown
			# For this the default reboot/shutdown wait time is set to 15 seconds
			# This should be enough time for pgina to stop blocking and leave WlxInitialize
			self._config['global']['wait_before_reboot'] = 15
			self._config['global']['wait_before_shutdown'] = 15
		
	def _shutdownMachine(self):
		self._shutdownRequested = True
		# Running in thread to avoid failure of shutdown (device not ready)
		class _shutdownThread(threading.Thread):
			def __init__ (self, wait):
				threading.Thread.__init__(self)
				self.wait = wait
			
			def run(self):
				while(True):
					try:
						System.shutdown(wait = self.wait)
						logger.notice("Shutdown initiated")
						break
					except Exception, e:
						# Device not ready?
						logger.info("Failed to initiate shutdown: %s" % e)
						time.sleep(1)
			
		_shutdownThread(wait = self._config['global']['wait_before_shutdown']).start()
		
	def _rebootMachine(self):
		self._rebootRequested = True
		# Running in thread to avoid failure of reboot (device not ready)
		class _rebootThread(threading.Thread):
			def __init__ (self, wait):
				threading.Thread.__init__(self)
				self.wait = wait
			
			def run(self):
				while(True):
					try:
						System.reboot(wait = self.wait)
						logger.notice("Reboot initiated")
						break
					except Exception, e:
						# Device not ready?
						logger.info("Failed to initiate reboot: %s" % e)
						time.sleep(1)
		
		_rebootThread(wait = self._config['global']['wait_before_reboot']).start()
	
	def runProductActions(self, event):
		logger.debug("runProductActions(): running on NT5")
		
		actionProcessorDesktop = event.actionProcessorDesktop
		if not actionProcessorDesktop or actionProcessorDesktop.lower() not in ('winlogon', 'default'):
			actionProcessorDesktop = self.getCurrentActiveDesktopName()
		if not actionProcessorDesktop or actionProcessorDesktop.lower() not in ('winlogon', 'default'):
			actionProcessorDesktop = 'winlogon'
		
		depotShareMounted = False
		userCreated = False
		username = self.getConfigValue('action_processor', 'run_as_user')
		password = '$!?' + Tools.randomString(16) + '§/%'
		imp = None
		try:
			logger.notice("Creating local user '%s'" % username)
			if System.existsUser(username = username):
				System.deleteUser(username = username)
			System.createUser(username = username, password = password, groups = [ System.getAdminGroupName() ])
			userCreated = True
			
			# Impersonate
			imp = System.Impersonate(username = username, password = password, desktop = actionProcessorDesktop)
			imp.start(logonType = 'INTERACTIVE', newDesktop = True)
			
			if self.getConfigValue('depot_server', 'url').split('/')[2] not in ('127.0.0.1', 'localhost'):
				logger.notice("Mounting depot share")
				self._statusSubject.setMessage( _("Mounting depot share %s" % self.getConfigValue('depot_server', 'url')) )
				
				encryptedPassword = self._configService.getPcpatchPassword(self._config['global']['host_id'])
				pcpatchPassword = Tools.blowfishDecrypt(self._config['global']['opsi_host_key'], encryptedPassword)
				
				System.mount(self.getConfigValue('depot_server', 'url'), self.getConfigValue('depot_server', 'drive'), username="pcpatch", password=pcpatchPassword)
				depotShareMounted = True
				
				if event.updateActionProcessor:
					logger.notice("Updating action processor")
					try:
						self.updateActionProcessor()
					except Exception, e:
						logger.error("Failed to update action processor: %s" % e)
				
			logger.notice("Starting action processor as user '%s' on desktop '%s'" % (username, actionProcessorDesktop))
			self._statusSubject.setMessage( _("Starting action processor") )
			
			if self._setEnvironment:
				try:
					logger.debug("Current environment:")
					for (k, v) in os.environ.items():
						logger.debug("   %s=%s" % (k,v))
					logger.debug("Updating environment")
					hostname = os.environ['COMPUTERNAME']
					(homeDrive, homeDir) = os.environ['USERPROFILE'].split('\\')[0:2]
					# TODO: Anwendungsdaten
					os.environ['APPDATA']     = '%s\\%s\\%s\\Anwendungsdaten' % (homeDrive, homeDir, username)
					os.environ['HOMEDRIVE']   = homeDrive
					os.environ['HOMEPATH']    = '\\%s\\%s' % (homeDir, username)
					os.environ['LOGONSERVER'] = '\\\\%s' % hostname
					os.environ['SESSIONNAME'] = 'Console'
					os.environ['USERDOMAIN']  = '%s' % hostname
					os.environ['USERNAME']    = username
					os.environ['USERPROFILE'] = '%s\\%s\\%s' % (homeDrive, homeDir, username)
					logger.debug("Updated environment:")
					for (k, v) in os.environ.items():
						logger.debug("   %s=%s" % (k,v))
				except Exception, e:
					logger.error("Failed to set environment: %s" % e)
			imp.runCommand(command = self.fillPlaceholders(event.actionProcessorCommand), waitForProcessEnding = True)
			
			logger.notice("Action processor ended")
			self._statusSubject.setMessage( _("Action processor ended") )
			
		finally:
			if depotShareMounted:
				logger.notice("Unmounting depot share")
				System.umount(self.getConfigValue('depot_server', 'drive'))
			if imp:
				imp.end()
			if userCreated:
				logger.notice("Deleting local user '%s'" % username)
				System.deleteUser(username = username)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                          OPSICLIENTD NT6                                          -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class OpsiclientdNT6(OpsiclientdNT):
	def __init__(self):
		OpsiclientdNT.__init__(self)
	
	def runProductActions(self, event):
		logger.debug("runProductActions(): running on NT6")
		
		actionProcessorDesktop = event.actionProcessorDesktop
		if not actionProcessorDesktop or actionProcessorDesktop.lower() not in ('winlogon', 'default'):
			actionProcessorDesktop = self.getCurrentActiveDesktopName()
		if not actionProcessorDesktop or actionProcessorDesktop.lower() not in ('winlogon', 'default'):
			actionProcessorDesktop = 'winlogon'
		
		depotShareMounted = False
		try:
			if self.getConfigValue('depot_server', 'url').split('/')[2] not in ('127.0.0.1', 'localhost'):
				logger.notice("Mounting depot share")
				self._statusSubject.setMessage( _("Mounting depot share %s" % self.getConfigValue('depot_server', 'url')) )
				
				encryptedPassword = self._configService.getPcpatchPassword(self._config['global']['host_id'])
				pcpatchPassword = Tools.blowfishDecrypt(self._config['global']['opsi_host_key'], encryptedPassword)
				
				System.mount(self.getConfigValue('depot_server', 'url'), self.getConfigValue('depot_server', 'drive'), username="pcpatch", password=pcpatchPassword)
				depotShareMounted = True
				
				if event.updateActionProcessor:
					logger.notice("Updating action processor")
					try:
						self.updateActionProcessor()
					except Exception, e:
						logger.error("Failed to update action processor: %s" % e)
				
			activeSessionId = System.getActiveConsoleSessionId()
			logger.notice("Starting action processor in session '%s' on desktop '%s'" % (activeSessionId, actionProcessorDesktop))
			self._statusSubject.setMessage( _("Starting action processor") )
			
			System.runCommandInSession(command = self.fillPlaceholders(event.actionProcessorCommand), sessionId = activeSessionId, desktop = actionProcessorDesktop, waitForProcessEnding = True)
			
			logger.notice("Action processor ended")
			self._statusSubject.setMessage( _("Action processor ended") )
			
		finally:
			if depotShareMounted:
				logger.notice("Unmounting depot share")
				System.umount(self.getConfigValue('depot_server', 'drive'))

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                          OPSICLIENTD NT7                                          -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class OpsiclientdNT7(OpsiclientdNT):
	def __init__(self):
		OpsiclientdNT.__init__(self)
	
	def runProductActions(self, event):
		logger.debug("runProductActions(): running on NT7")
		
		actionProcessorDesktop = event.actionProcessorDesktop
		if not actionProcessorDesktop or actionProcessorDesktop.lower() not in ('winlogon', 'default'):
			actionProcessorDesktop = self.getCurrentActiveDesktopName()
		if not actionProcessorDesktop or actionProcessorDesktop.lower() not in ('winlogon', 'default'):
			actionProcessorDesktop = 'winlogon'
		
		if not (self.getConfigValue('action_processor', 'run_as_user') == 'pcpatch'):
			logger.warning("Cannot run action processor as user '%s' on nt7, running as 'pcpatch'" % self.getConfigValue('action_processor', 'run_as_user'))
		
		pcpatchPassword = ''
		
		if self.getConfigValue('depot_server', 'url').split('/')[2] not in ('127.0.0.1', 'localhost') and event.updateActionProcessor:
			logger.notice("Updating action processor")
			imp = None
			depotShareMounted = False
			try:
				imp = System.Impersonate(username = 'pcpatch', password = pcpatchPassword)
				imp.start(logonType = 'NEW_CREDENTIALS')
				
				logger.notice("Mounting depot share %s" %  self.getConfigValue('depot_server', 'url'))
				self._statusSubject.setMessage(_("Mounting depot share %s") % self.getConfigValue('depot_server', 'url'))
				
				encryptedPassword = self._configService.getPcpatchPassword(self._config['global']['host_id'])
				pcpatchPassword = Tools.blowfishDecrypt(self._config['global']['opsi_host_key'], encryptedPassword)
				
				System.mount(self.getConfigValue('depot_server', 'url'), self.getConfigValue('depot_server', 'drive'), username='pcpatch', password=pcpatchPassword)
				depotShareMounted = True
				
				self.updateActionProcessor()
			
			except Exception, e:
				logger.error("Failed to update action processor: %s" % e)
		
			if depotShareMounted:
				try:
					logger.notice("Unmounting depot share")
					System.umount(self.getConfigValue('depot_server', 'drive'))
				except:
					pass
			if imp:
				try:
					imp.end()
				except:
					pass
			
		command = '%system.program_files_dir%\\opsi.org\\preloginloader\\action_processor_starter.exe ' \
			+ '"%global.host_id%" "%global.opsi_host_key%" "%control_server.port%" ' \
			+ '"%global.log_file%" "%global.log_level%" ' \
			+ '"' + self.getConfigValue('depot_server', 'url') + '" "' + self.getConfigValue('depot_server', 'drive') + '" ' \
			+ '"pcpatch" "' + pcpatchPassword + '" ' \
			+ '"' + actionProcessorDesktop + '" "' + self.fillPlaceholders(event.actionProcessorCommand).replace('"', '\\"') + '"'
		command = self.fillPlaceholders(command)
		
		System.runCommandInSession(command = command, desktop = actionProcessorDesktop, waitForProcessEnding = True)
		
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                         OPSICLIENTD INIT                                          -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
def OpsiclientdInit():
	if (os.name == 'posix'):
		return OpsiclientdPosixInit()
	
	# if sys.platform == 'win32':
	if (os.name == 'nt'):
		return OpsiclientdNTInit()
	else:
		raise NotImplementedError("Unsupported operating system %s" % os.name)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                       OPSICLIENTD POSIX INIT                                      -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class OpsiclientdPosixInit(object):
	def __init__(self):
		logger.debug("OpsiclientdPosixInit")
		argv = sys.argv[1:]
		
		# Call signalHandler on signal SIGHUP, SIGTERM, SIGINT
		signal(SIGHUP,  self.signalHandler)
		signal(SIGTERM, self.signalHandler)
		signal(SIGINT,  self.signalHandler)
		
		# Process command line arguments
		try:
			(opts, args) = getopt.getopt(argv, "vDl:")
		
		except getopt.GetoptError:
			self.usage()
			sys.exit(1)
		
		daemon = False
		logLevel = LOG_NOTICE
		for (opt, arg) in opts:
			if   (opt == "-v"):
				print "opsiclientd version %s" % __version__
				sys.exit(0)
			if   (opt == "-D"):
				daemon = True
			if   (opt == "-l"):
				logLevel = int(arg)
		if daemon:
			logger.setConsoleLevel(LOG_NONE)
			self.daemonize()
		else:
			logger.setConsoleLevel(logLevel)
		
		# Start opsiclientd
		self._opsiclientd = OpsiclientdPosix()
		self._opsiclientd.start()
		#self._opsiclientd.join()
		while self._opsiclientd.isRunning():
			time.sleep(1)
		
	def signalHandler(self, signo, stackFrame):
		if (signo == SIGHUP):
			return
		if (signo == SIGTERM or signo == SIGINT):
			self._opsiclientd.stop()
	
	def usage(self):
		print "\nUsage: %s [-v] [-D]" % os.path.basename(sys.argv[0])
		print "Options:"
		print "  -v    Show version information and exit"
		print "  -D    Causes the server to operate as a daemon"
		print "  -l    Set log level (default: 4)"
		print "        0=nothing, 1=critical, 2=error, 3=warning, 4=notice, 5=info, 6=debug, 7=debug2, 9=confidential"
		print ""
	
	def daemonize(self):
		return
		# Fork to allow the shell to return and to call setsid
		try:
			pid = os.fork()
			if (pid > 0):
				# Parent exits
				sys.exit(0)
		except OSError, e:
			raise Exception("First fork failed: %e" % e)
		
		# Do not hinder umounts
		os.chdir("/")
		# Create a new session
		os.setsid()
		
		# Fork a second time to not remain session leader
		try:
			pid = os.fork()
			if (pid > 0):
				sys.exit(0)
		except OSError, e:
			raise Exception("Second fork failed: %e" % e)
		
		logger.setConsoleLevel(LOG_NONE)
		
		# Close standard output and standard error.
		os.close(0)
		os.close(1)
		os.close(2)
		
		# Open standard input (0)
		if (hasattr(os, "devnull")):
			os.open(os.devnull, os.O_RDWR)
		else:
			os.open("/dev/null", os.O_RDWR)
		
		# Duplicate standard input to standard output and standard error.
		os.dup2(0, 1)
		os.dup2(0, 2)
		sys.stdout = logger.getStdout()
		sys.stderr = logger.getStderr()

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
			logger.debug("OpsiclientdServiceFramework initiating")
			win32serviceutil.ServiceFramework.__init__(self, args)
			self._stopEvent = threading.Event()
			logger.debug("OpsiclientdServiceFramework initiated")
		
		def SvcStop(self):
			"""
			Gets called from windows to stop service
			"""
			logger.debug("OpsiclientdServiceFramework SvcStop")
			# Write to event log
			self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
			# Fire stop event to stop blocking self._stopEvent.wait()
			self._stopEvent.set()
			
		
		def SvcDoRun(self):
			"""
			Gets called from windows to start service
			"""
			startTime = time.time()
			logger.debug("OpsiclientdServiceFramework SvcDoRun")
			# Write to event log
			self.ReportServiceStatus(win32service.SERVICE_START_PENDING)
			
			# Start opsiclientd
			workingDirectory = os.getcwd()
			try:
				workingDirectory = os.path.dirname(System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SYSTEM\\CurrentControlSet\\Services\\opsiclientd\\PythonClass", ""))
			except Exception, e:
				logger.error("Failed to get working directory from registry: %s" % e)
			os.chdir(workingDirectory)
			
			opsiclientd = None
			if (sys.getwindowsversion()[0] == 5):
				# NT5: XP
				opsiclientd = OpsiclientdNT5()
			elif (sys.getwindowsversion()[0] == 6):
				# NT6: Vista / Windows7 beta
				if (sys.getwindowsversion()[1] >= 1):
					# Windows7 beta
					opsiclientd = OpsiclientdNT7()
				else:
					opsiclientd = OpsiclientdNT6()
			else:
				raise Exception("Running windows version not supported")
			
			opsiclientd.start()
			# Write to event log
			self.ReportServiceStatus(win32service.SERVICE_RUNNING)
			
			logger.debug("Took %0.2f seconds to report service running status" % (time.time() - startTime))
			
			# Wait for stop event
			self._stopEvent.wait()
			
			# Shutdown opsiclientd
			opsiclientd.stop()
			
			# Write to event log
			self.ReportServiceStatus(win32service.SERVICE_STOPPED)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                        OPSICLIENTD NT INIT                                        -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class OpsiclientdNTInit(object):
	def __init__(self):
		logger.debug("OpsiclientdNTInit")
		win32serviceutil.HandleCommandLine(OpsiclientdServiceFramework)
		


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                               MAIN                                                -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
if (__name__ == "__main__"):
	logger.setConsoleLevel(LOG_WARNING)
	exception = None
	
	try:
		OpsiclientdInit()
		
	except SystemExit, e:
		pass
		
	except Exception, e:
		exception = e
	
	if exception:
		logger.logException(exception)
		print >> sys.stderr, "ERROR:", str(exception)
		sys.exit(1)
	sys.exit(0)


