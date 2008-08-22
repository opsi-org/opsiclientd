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

__version__ = '0.2.1'

# Imports
import os, sys, threading, time, json, urllib, base64, socket, re, shutil, filecmp
from OpenSSL import SSL

if (os.name == 'posix'):
	from signal import *
	# We need a faked win32serviceutil class
	class win32serviceutil:
		ServiceFramework = object

if (os.name == 'nt'):
	import win32serviceutil, win32service
	from ctypes import *

# Twisted imports
from twisted.internet import defer, threads, reactor
from twisted.web2 import resource, stream, server, http, responsecode, static
from twisted.web2.channel.http import HTTPFactory
from twisted.python.failure import Failure

# OPSI imports
from OPSI.Logger import *
from OPSI.Util import *
from OPSI import Tools
from OPSI import System
from OPSI.Backend.File import File
from OPSI.Backend.JSONRPC import JSONRPCBackend

# Create logger instance
logger = Logger()
logger.setFileFormat('[%l] [%D] %M (%F|%N)')

# Possible event types
EVENT_TYPE_DAEMON_STARTUP = 'opsiclientd start'
EVENT_TYPE_DAEMON_SHUTDOWN = 'opsiclientd shutdown'
EVENT_TYPE_PROCESS_ACTION_REQUESTS = 'process action requests'
EVENT_TYPE_TIMER = 'timer'

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
class Event(object):
	def __init__(self, type):
		if not type in (EVENT_TYPE_DAEMON_STARTUP, EVENT_TYPE_DAEMON_SHUTDOWN, EVENT_TYPE_TIMER, EVENT_TYPE_PROCESS_ACTION_REQUESTS):
			raise TypeError("Unkown event type %s" % type)
		self._type = type
		self._eventListeners = []
		logger.setFileFormat('[%l] [%D] [event ' + str(self._type) + '] %M (%F|%N)', object=self)
		
	def __str__(self):
		return "<Event %s>" % self.getType()
	
	def getType(self):
		return self._type
	
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
		
		for l in self._eventListeners:
			# Create a new thread for each event listener
			ProcessEventThread(l, self).start()

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                        DAEMON STARTUP EVENT                                       -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class DaemonStartupEvent(Event):
	def __init__(self):
		Event.__init__(self, EVENT_TYPE_DAEMON_STARTUP)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                       DAEMON SHUTDOWN EVENT                                       -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class DaemonShutdownEvent(Event):
	def __init__(self):
		Event.__init__(self, EVENT_TYPE_DAEMON_SHUTDOWN)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                   PROCESS ACTION REQUESTS EVENT                                   -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ProcessActionRequestEvent(Event):
	def __init__(self, logoffCurrentUser=False):
		self.logoffCurrentUser = logoffCurrentUser
		Event.__init__(self, EVENT_TYPE_PROCESS_ACTION_REQUESTS)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                            TIMER EVENT                                            -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class TimerEvent(Event):
	def __init__(self, interval=0):
		Event.__init__(self, EVENT_TYPE_TIMER)
		self.setInterval(interval)
	
	def __del__(self):
		if hasattr(self, '_timer') and self._timer:
			self._timer.cancel()
		
	def __str__(self):
		return "<Event %s (every %d seconds)>" % (self.getType(), self._interval)
	
	def setInterval(self, interval):
		self._interval = int(interval)
		if hasattr(self, '_timer') and self._timer:
			self._timer.cancel()
		
		if (self._interval > 0):
			self._timer = threading.Timer(self._interval, self.timerCallback)
			self._timer.start()
		logger.debug("Timer interval set to %d" % self._interval)
	
	def timerCallback(self):
		self.fire()
		self._timer = threading.Timer(self._interval, self.timerCallback)
		self._timer.start()

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
		logger.setFileFormat('[%l] [%D] [control pipe] %M (%F|%N)', object=self)
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
			logger.info('Got result...')
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
		logger.info("Creating pipe %s" % self._pipeName)
		if not os.path.exists( os.path.dirname(self._pipeName) ):
			os.mkdir( os.path.dirname(self._pipeName) )
		if os.path.exists(self._pipeName):
			os.unlink(self._pipeName)
		os.mkfifo(self._pipeName)
		logger.info("Pipe %s created" % self._pipeName)
	
	def run(self):
		self._running = Tru
		try:
			self.createPipe()
			while self._running:
				try:
					logger.info("Opening named pipe %s" % self._pipeName)
					self._pipe = os.open(self._pipeName, os.O_RDONLY)
					logger.info("Reading from pipe %s" % self._pipeName)
					rpc = os.read(self._pipe, self._bufferSize)
					os.close(self._pipe)
					if not rpc:
						logger.error("No rpc from pipe")
						continue
					logger.notice("Received rpc from pipe '%s'" % rpc)
					result = self.executeRpc(rpc)
					logger.info("Opening named pipe %s" % self._pipeName)
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
					logger.info("Writing to pipe")
					written = os.write(self._pipe, result)
					logger.info("Number of bytes written: %d" % written)
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
		logger.setFileFormat('[%l] [%D] [control pipe] %M (%F|%N)', object=self)
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
				logger.info("Reading fom pipe")
				fReadSuccess = windll.kernel32.ReadFile(self._pipe, chBuf, self._bufferSize, byref(cbRead), None)
				if ((fReadSuccess == 1) or (cbRead.value != 0)):
					logger.notice("Received rpc from pipe '%s'" % chBuf.value)
					result =  "%s\0" % self._ntControlPipe.executeRpc(chBuf.value)
					cbWritten = c_ulong(0)
					logger.info("Writing to pipe")
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
		ERROR_PIPE_CONNECTED = 535
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
		logger.info("Pipe %s created" % self._pipeName)
	
	def run(self):
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
					logger.info("Connected to named pipe %s" % self._pipeName)
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
		logger.setFileFormat('[%l] [%D] [control server] %M (%F|%N)', object=self)
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
		worker = JsonRpcWorker(request, self._opsiclientd, method = 'POST')
		return worker.process()
		
	def http_GET(self, request):
		''' Process GET request. '''
		logger.info("ControlServerResourceJsonRpc: processing GET request")
		worker = JsonRpcWorker(request, self._opsiclientd, method = 'GET')
		return worker.process()

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                 CONTROL SERVER RESOURCE INTERFACE                                 -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ControlServerResourceInterface(ControlServerResourceJsonRpc):
	def __init__(self, opsiclientd):
		logger.setFileFormat('[%l] [%D] [control server] %M (%F|%N)', object=self)
		ControlServerResourceJsonRpc.__init__(self, opsiclientd)
	
	def http_POST(self, request):
		''' Process POST request. '''
		logger.info("ControlServerResourceInterface: processing POST request")
		worker = JsonInterfaceWorker(request, self._opsiclientd, method = 'POST')
		return worker.process()
		
	def http_GET(self, request):
		''' Process GET request. '''
		logger.info("ControlServerResourceInterface: processing GET request")
		worker = JsonInterfaceWorker(request, self._opsiclientd, method = 'GET')
		return worker.process()

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                          JSON RPC WORKER                                          -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class JsonRpcWorker(object):
	def __init__(self, request, opsiclientd, method = 'POST'):
		logger.setFileFormat('[%l] [%D] [control server] %M (%F|%N)', object=self)
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
		
		logger.info('Got result...')
		duration = round(time.time() - start, 3)
		logger.info('Took %0.3fs to process %s(%s)' % (duration, method, str(params)[1:-1]))
	
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
# -                                       JSON INTERFACE WORKER                                       -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class JsonInterfaceWorker(JsonRpcWorker):
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
		JsonRpcWorker.__init__(self, request, opsiconfd, method)
	
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
# -                                           CONTROL SERVER                                          -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ControlServer(threading.Thread):
	def __init__(self, opsiclientd, httpsPort, sslServerKeyFile, sslServerCertFile, staticDir=None):
		logger.setFileFormat('[%l] [%D] [control server] %M (%F|%N)', object=self)
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
		self._root.putChild("rpc", ControlServerResourceJsonRpc(self._opsiclientd))
		self._root.putChild("interface", ControlServerResourceInterface(self._opsiclientd))




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
	def __init__(self, configServiceUrl, username, password, notificationServer, statusObject, waitBeforeConnect=0):
		logger.setFileFormat('[%l] [%D] [service connection] %M (%F|%N)', object=self)
		KillableThread.__init__(self)
		self._configServiceUrl = configServiceUrl
		self._username = username
		self._password = password
		self._notificationServer = notificationServer
		self._statusSubject = statusObject
		self._waitBeforeConnect = waitBeforeConnect
		self._choiceSubject = None
		self.configService = None
		self.running = False
		self.connected = False
		self.canceled = False
		
	def run(self):
		try:
			logger.debug("ServiceConnectionThread started...")
			self.running = True
			self.connected = False
			self.canceled = False
			
			self._choiceSubject = ChoiceSubject(id = 'stopConnecting')
			#self._choiceSubject.setMessage("Connecting to config server '%s'" % self._configServiceUrl)
			self._choiceSubject.setChoices([ 'Stop connection' ])
			self._choiceSubject.setCallbacks( [ self.stopConnectionCallback ] )
			self._notificationServer.addSubject(self._choiceSubject)
			
			timeout = int(self._waitBeforeConnect)
			while(timeout > 0) and not self.canceled:
				logger.info("Waiting for user to cancel connect")
				self._statusSubject.setMessage("Waiting for user to cancel connect (%d)" % timeout)
				timeout -= 1
				time.sleep(1)
			
			tryNum = 0
			while not self.canceled and not self.connected:
				try:
					tryNum += 1
					logger.notice("Connecting to config server '%s' #%d" % (self._configServiceUrl, tryNum))
					self._statusSubject.setMessage( _("Connecting to config server '%s' #%d") % (self._configServiceUrl, tryNum))
					self.configService = JSONRPCBackend(address = self._configServiceUrl, username = self._username, password = self._password)
					self.configService.authenticated()
					self.connected = True
					self._statusSubject.setMessage("Connected to config server '%s'" % self._configServiceUrl)
					logger.notice("Connected to config server '%s'" % self._configServiceUrl)
				except Exception, e:
					self._statusSubject.setMessage("Failed to connect to config server '%s': %s" % (self._configServiceUrl, e))
					logger.error("Failed to connect to config server '%s': %s" % (self._configServiceUrl, e))
					time.sleep(3)
			
			if self._choiceSubject:
				self._notificationServer.removeSubject(self._choiceSubject)
				self._choiceSubject = None
		except Exception, e:
			logger.logException(e)
		self.running = False
	
	def stopConnectionCallback(self, choiceSubject):
		logger.notice("Connection canceled by user")
		self.stop()
	
	def stop(self):
		if self._choiceSubject:
			self._notificationServer.removeSubject(self._choiceSubject)
		self.canceled = True
		time.sleep(2)
		if self.running and self.isAlive():
			logger.debug("Terminating thread")
			self.terminate()
		
		
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                            OPSICLIENTD                                            -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class Opsiclientd(EventListener, threading.Thread):
	def __init__(self):
		logger.setFileFormat('[%l] [%D] [opsiclientd] %M (%F|%N)', object=self)
		logger.debug("Opsiclient initiating")
		
		EventListener.__init__(self)
		threading.Thread.__init__(self) 
		
		self._startupTime = time.time()
		self._running = False
		self._configService = None
		self._daemonStartupEvent = DaemonStartupEvent()
		self._daemonStartupEvent.addEventListener(self)
		self._daemonShutdownEvent = DaemonShutdownEvent()
		self._daemonShutdownEvent.addEventListener(self)
		self._timerEvent = TimerEvent()
		self._timerEvent.addEventListener(self)
		self._processActionRequestsEvent = ProcessActionRequestEvent()
		self._processActionRequestsEvent.addEventListener(self)
		self._processingActionRequests = False
		self._blockLogin = True
		self._CurrentActiveDesktopName = None
		
		self._statusApplicationProcess = None
		
		self._statusSubject = MessageSubject('status')
		self._serviceUrlSubject = MessageSubject('configServiceUrl')
		self._clientIdSubject = MessageSubject('clientId')
		
		self._config = {
			'global': {
				'config_file':           'opsiclientd.conf',
				'log_file':              'opsiclientd.log',
				'log_level':             LOG_NOTICE,
				'host_id':               socket.getfqdn(),
				'opsi_host_key':         '',
			},
			'config_service': {
				'url':                   '',
				'connection_timeout':    30,
				'wait_before_connect':   5,
			},
			'control_server': {
				'interface':             '0.0.0.0', # TODO
				'port':                  4441,
				'ssl_server_key_file':   'opsiclientd.pem',
				'ssl_server_cert_file':  'opsiclientd.pem',
				'static_dir':            'static_html',
			},
			'notification_server': {
				'interface':             '127.0.0.1',
				'port':                  4442,
			},
			'opsiclientd_notifier': {
				'command':               '',
			},
			'action_processor': {
				'local_dir':             '',
				'remote_dir':            '',
				'filename':              '',
				'command':               '',
			},
		}
		
		self._possibleMethods = [
			{ 'name': 'getPossibleMethods_listOfHashes', 'params': [ ],                       'availability': ['server', 'pipe'] },
			{ 'name': 'getBlockLogin',                   'params': [ ],                       'availability': ['server', 'pipe'] },
			{ 'name': 'setBlockLogin',                   'params': [ 'blockLogin' ],          'availability': ['server'] },
			{ 'name': 'runCommand',                      'params': [ 'command', '*desktop' ], 'availability': ['server'] },
			{ 'name': 'processProductActionRequests',    'params': [ 'logoffCurrentUser' ],   'availability': ['server'] },
			{ 'name': 'logoffCurrentUser',               'params': [ ],                       'availability': ['server'] },
			{ 'name': 'lockWorkstation',                 'params': [ ],                       'availability': ['server'] },
			{ 'name': 'setStatusMessage',                'params': [ 'message' ],             'availability': ['server'] },
			{ 'name': 'readLog',                         'params': [ '*type' ],               'availability': ['server'] },
			{ 'name': 'shutdown',                        'params': [ '*wait' ],               'availability': ['server'] },
			{ 'name': 'reboot',                          'params': [ '*wait' ],               'availability': ['server'] },
			{ 'name': 'uptime',                          'params': [ ],                       'availability': ['server'] },
			{ 'name': 'getCurrentActiveDesktopName',     'params': [ ],                       'availability': ['server'] },
			{ 'name': 'setCurrentActiveDesktopName',     'params': [ 'desktop' ],             'availability': ['server'] },
		]
		
		self._clientIdSubject.setMessage(self._config['global']['host_id'])
		
	def isRunning(self):
		return self._running
		
	
	def setConfigValue(self, section, option, value):
		if not section:
			section = 'global'
		
		logger.debug("setConfigValue(%s, %s, %s)" % (section, option, value))
		
		section = str(section).strip().lower()
		option = str(option).strip().lower()
		value = value.strip()
		
		if option in ('log_level', 'port'):
			value = int(value)
		
		
		if not self._config.has_key(section):
			self._config[section] = {}
		self._config[section][option] = value
		
		if   (section == 'config_service') and (option == 'url'):
			self.setConfigServiceUrl(self._config[section][option])
		elif (section == 'config_service') and option in ('wait_before_connect', 'connection_timeout'):
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
			
			# Read log values early
			if config.has_section('global'):
				if config.has_option('global', 'log_level'):
					self.setConfigValue('global', 'log_level', config.get('global', 'log_level'))
				if config.has_option('global', 'log_file'):
					logFile = config.get('global', 'log_file')
					if os.path.exists(logFile):
						try:
							if os.path.exists(logFile + '.0'):
								os.unlink(logFile + '.0')
							os.rename(logFile,logFile + '.0')
						except Exception, e:
							logger.error("Failed to rename %s to %s.0: %s" % (logFile, logFile, e) )
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
	
	def writeConfigFile(self):
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
		except CanceledByUserError, e:
			logger.error("Failed to get config from service: %s" % e)
			raise
		except Exception, e:
			logger.error("Failed to get config from service: %s" % e)
			logger.logException(e)
	
	def writeLogToService(self):
		logger.notice("Writing log to service")
		try:
			self._statusSubject.setMessage( _("Writing log to service") )
			if not self._configService:
				raise Exception("not connected")
			
			f = open(self._config['global']['log_file'])
			data = f.read()
			f.close()
			# Do not jsonrpc request
			logger.setFileLevel(LOG_WARNING)
			self._configService.writeLog('clientconnect', data, self._config['global']['host_id'])
			logger.setFileLevel(self._config['global']['log_level'])
		except Exception, e:
			logger.error("Failed to write log to service: %s" % e)
	
	def fillPlaceholders(self, string):
		for (section, values) in self._config.items():
			if not type(values) is dict:
				continue
			for (key, value) in values.items():
				string = string.replace('%' + str(section) + '.' + str(key) + '%', str(value))
		return string
	
	def run(self):
		self._running = True
		
		self.readConfigFile()
		
		try:
			logger.comment("Opsiclientd version: %s" % __version__)
			logger.comment("Commandline: %s" % ' '.join(sys.argv))
			logger.comment("Working directory: %s" % os.getcwd())
			logger.notice("Using host id '%s'" % self._config['global']['host_id'])
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
								httpsPort         = self._config['control_server']['port'],
								sslServerKeyFile  = self._config['control_server']['ssl_server_key_file'],
								sslServerCertFile = self._config['control_server']['ssl_server_cert_file'],
								staticDir         = self._config['control_server']['static_dir'])
				self._controlServer.start()
				logger.notice("Control server started")
			except Exception, e:
				logger.error("Failed to start control server: %s" % e)
				raise
			
			logger.notice("Starting notification server")
			try:
				self._notificationServer = NotificationServer(
								address  = self._config['notification_server']['interface'],
								port     = self._config['notification_server']['port'],
								subjects = [ self._statusSubject, self._serviceUrlSubject, self._clientIdSubject ] )
				logger.setLogFormat('[%l] [%D] [notification server] %M (%F|%N)', object=self._notificationServer)
				logger.setLogFormat('[%l] [%D] [notification server] %M (%F|%N)', object=self._notificationServer.getFactory())
				self._notificationServer.start()
				logger.notice("Notification server started")
			except Exception, e:
				logger.error("Failed to start notification server: %s" % e)
				raise
			
			self._daemonStartupEvent.fire()
			# TODO: passive wait?
			while self._running:
				time.sleep(1)
			self._daemonShutdownEvent.fire()
		
		except Exception, e:
			logger.logException(e)
		
		self._running = False
		
	def stop(self):
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
			raise ValueError("Bad url '%s'" % url)
		self._config['config_service']['url'] = url
		self._config['config_service']['host'] = self._config['config_service']['url'].split('/')[2]
		self._config['config_service']['port'] = '4447'
		if (self._config['config_service']['host'].find(':') != -1):
			(self._config['config_service']['host'], self._config['config_service']['port']) = self._config['config_service']['host'].split(':', 1)
		self._serviceUrlSubject.setMessage(self._config['config_service']['url'])
	
	def startStatusApplication(self):
		if self._statusApplicationProcess:
			# Already running
			return
		
		statusApplication = self._config['opsiclientd_notifier']['command']
		if not statusApplication:
			return
		
		statusApplication = self.fillPlaceholders(statusApplication)
		
		activeSessionId = System.getActiveConsoleSessionId()
		desktop = self.getCurrentActiveDesktopName()
		if not desktop or desktop.lower() not in ('winlogon', 'default'):
			desktop = 'winlogon'
		
		logger.notice("Starting status application in session '%s' on desktop '%s'" % (activeSessionId, desktop))
		self._statusApplicationProcess = System.runAsSystemInSession(command = statusApplication, sessionId = activeSessionId, desktop = desktop, waitForProcessEnding=False)[0]
		time.sleep(5)
	
	def stopStatusApplication(self):
		if not self._statusApplicationProcess:
			# Not running
			return
		time.sleep(2)
		logger.notice("Stopping status application")
		try:
			System.terminateProcess(self._statusApplicationProcess)
		except Exception, e:
			logger.error("Failed to terminate statusApplicationProcess: %s" % e)
		self._statusApplicationProcess = None
	
	def startActionProcessor(self):
		actionProcessor = self._config['action_processor']['command']
		if not actionProcessor:
			logger.error("No action processor command defined")
			return
		
		actionProcessor = self.fillPlaceholders(actionProcessor)
		
		activeSessionId = System.getActiveConsoleSessionId()
		desktop = self.getCurrentActiveDesktopName()
		if not desktop or desktop.lower() not in ('winlogon', 'default'):
			desktop = 'winlogon'
		
		logger.notice("Starting action processor in session '%s' on desktop '%s'" % (activeSessionId, desktop))
		self._statusSubject.setMessage( _("Starting action processor") )
		
		#self.stopStatusApplication()
		System.runAsSystemInSession(command = actionProcessor, sessionId = activeSessionId, desktop = desktop, waitForProcessEnding = True)
		
		logger.notice("Action processor ended")
		self._statusSubject.setMessage( _("Action processor ended") )
		#self.startStatusApplication()
	
	def waitForGUI(self):
		logger.notice("Waiting for GUI to start")
		logger.info("Waiting for winlogon to start")
		while not System.getPids("winlogon.exe"):
			logger.debug("   winlogon not running, sleeping 5 seconds...")
			time.sleep(5)
		logger.info("winlogon running")
	
	def processEvent(self, event):
		logger.notice("Processing event %s" % event)
		self._statusSubject.setMessage( _("Processing event %s") % event )
		try:
			if isinstance(event, DaemonStartupEvent):
				self._blockLogin = True
				
				self.waitForGUI()
				self.startStatusApplication()
				self.getConfigFromService()
				self.writeConfigFile()
				
				#startOpsiCredentialProvider = 0
				#try:
				#	startOpsiCredentialProvider = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Authentication\\Credential Provider Filters\\{d2028e19-82fe-44c6-ad64-51497c97a02a}", "StartOpsiCredentialProvider")
				#except Exception, e:
				#	logger.warning("Failed to get StartOpsiCredentialProvider from registry: %s" % e)
				#logger.info("startOpsiCredentialProvider: %s" % startOpsiCredentialProvider)
				
				self.processProductActionRequests()
				
				self._blockLogin = False
				
				#if (startOpsiCredentialProvider == 1):
				#	# Opsi credential provider was started
				#	# restart winlogon.exe to start opsi credential provider filter again
				#	System.logoffCurrentUser()
				
			elif isinstance(event, ProcessActionRequestEvent):
				#startOpsiCredentialProvider = 1
				#try:
				#	startOpsiCredentialProvider = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Authentication\\Credential Provider Filters\\{d2028e19-82fe-44c6-ad64-51497c97a02a}", "StartOpsiCredentialProvider")
				#except Exception, e:
				#	logger.warning("Failed to get StartOpsiCredentialProvider from registry: %s" % e)
				#logger.info("startOpsiCredentialProvider: %s" % startOpsiCredentialProvider)
				if event.logoffCurrentUser:
					self._blockLogin = True
					System.logoffCurrentUser()
					time.sleep(15)
				
				self.startStatusApplication()
				self.processProductActionRequests()
				
				#if event.logoffCurrentUser and (startOpsiCredentialProvider == 1):
				#	System.logoffCurrentUser()
			
		except Exception, e:
			logger.error("Failed to process event %s: %s" % (event, e))
			logger.logException(e)
		self._blockLogin = False
		self.writeLogToService()
		self.disconnectConfigServer()
		self.stopStatusApplication()
	
	def updateActionProcessor(self):
		logger.notice("Updating action processor")
		self._statusSubject.setMessage(_("Updating action processor"))
		
		self.connectConfigServer()
		networkConfig = self._configService.getNetworkConfig_hash(self._config['global']['host_id'])
		
		actionProcessorFilename = self._config['action_processor']['filename']
		
		actionProcessorLocalDir = self._config['action_processor']['local_dir']
		actionProcessorLocalTmpDir = self._config['action_processor']['local_dir'] + '.tmp'
		actionProcessorLocalFile = os.path.join(actionProcessorLocalDir, actionProcessorFilename)
		actionProcessorLocalTmpFile = os.path.join(actionProcessorLocalTmpDir, actionProcessorFilename)
		
		actionProcessorRemoteDir = os.path.join(networkConfig['depotDrive'], self._config['action_processor']['remote_dir'])
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
		
		return actionProcessorLocalFile
	
	def processProductActionRequests(self):
		if self._processingActionRequests:
			logger.error("Already processing action requests")
			return
		self._processingActionRequests = True
		self._statusSubject.setMessage(_("Getting action requests from config service"))
		
		depotShareMounted = False
		try:
			bootmode = ''
			try:
				bootmode = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\general", "bootmode")
			except Exception, e:
				logger.warning("Failed to get bootmode from registry: %s" % e)
			
			self.connectConfigServer()
			actionRequests = self._configService.getProductActionRequests_listOfHashes(self._config['global']['host_id'])
			logger.notice("Got product action requests from configservice")
			numRequests = 0
			for actionRequest in actionRequests:
				if (actionRequest['actionRequest'] != 'none'):
					numRequests += 1
					logger.notice("   [%2s] product %-15s %s" % (numRequests, actionRequest['productId'] + ':', actionRequest['actionRequest']))
			
			if (numRequests == 0) and (bootmode == 'BKSTD'):
				logger.notice("No product action requests set")
				self._statusSubject.setMessage( _("No product action requests set") )
				
			else:
				logger.notice("Start processing action requests")
				self._statusSubject.setMessage( _("Start processing action requests") )
				
				networkConfig = self._configService.getNetworkConfig_hash(self._config['global']['host_id'])
				depot = self._configService.getDepot_hash(networkConfig['depotId'])
				encryptedPassword = self._configService.getPcpatchPassword(self._config['global']['host_id'])
				pcpatchPassword = Tools.blowfishDecrypt(self._config['global']['opsi_host_key'], encryptedPassword)
				
				logger.notice("Mounting depot share")
				self._statusSubject.setMessage( _("Mounting depot share %s" % depot['depotRemoteUrl']) )
				
				System.mount(depot['depotRemoteUrl'], networkConfig['depotDrive'], username="pcpatch", password=pcpatchPassword)
				depotShareMounted = True
				
				try:
					actionProcessorLocalFile = self.updateActionProcessor()
				except Exception, e:
					logger.error("Failed to update action processor: %s" % e)
				self.startActionProcessor()
				
				logger.notice("Unmounting depot share")
				System.umount(networkConfig['depotDrive'])
			
				self._statusSubject.setMessage( _("Finished processing action requests") )
			
			rebootRequested = 0
			try:
				rebootRequested = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "RebootRequested")
			except Exception, e:
				logger.warning("Failed to get rebootRequested from registry: %s" % e)
			logger.info("rebootRequested: %s" % rebootRequested)
			if rebootRequested:
				System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "RebootRequested", 0)
				System.reboot(wait = 3)
			else:
				shutdownRequested = 0
				try:
					shutdownRequested = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "ShutdownRequested")
				except Exception, e:
					logger.warning("Failed to get shutdownRequested from registry: %s" % e)
				logger.info("shutdownRequested: %s" % shutdownRequested)
				if shutdownRequested:
					System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "ShutdownRequested", 0)
					System.shutdown(wait = 3)
				
		except Exception, e:
			logger.error("Failed to process product action requests: %s" % e)
			#logger.logException(e)
			self._statusSubject.setMessage( _("Failed to process product action requests: %s") % e )
			if depotShareMounted:
				logger.notice("Unmounting depot share")
				System.umount(networkConfig['depotDrive'])
		
		time.sleep(3)
		self._processingActionRequests = False
	
	def connectConfigServer(self):
		if self._configService:
			# Already connected
			return
		
		waitBeforeConnect = self._config['config_service']['wait_before_connect']
		
		logger.debug("Creating ServiceConnectionThread")
		
		serviceConnectionThread = ServiceConnectionThread(
					configServiceUrl    = self._config['config_service']['url'],
					username            = self._config['global']['host_id'],
					password            = self._config['global']['opsi_host_key'],
					notificationServer  = self._notificationServer,
					statusObject        = self._statusSubject,
					waitBeforeConnect   = waitBeforeConnect )
		
		timeout = int(self._config['config_service']['connection_timeout'])
		logger.info("Starting ServiceConnectionThread, timeout is %d seconds" % timeout)
		serviceConnectionThread.start()
		time.sleep(1)
		logger.debug("ServiceConnectionThread started")
		while serviceConnectionThread.running and (timeout > 0):
			logger.debug("Waiting for ServiceConnectionThread (timeout: %d)..." % timeout)
			time.sleep(1)
			timeout -= 1
		
		if serviceConnectionThread.canceled:
			logger.error("ServiceConnectionThread canceled by user")
			raise CanceledByUserError("Failed to connect to config service '%s': canceled by user" % \
						self._config['config_service']['url'] )
		elif serviceConnectionThread.running:
			logger.error("ServiceConnectionThread timed out after %d seconds" % self._config['config_service']['connection_timeout'])
			serviceConnectionThread.stop()
			raise Exception("Failed to connect to config service '%s': timed out after %d seconds" % \
						(self._config['config_service']['url'], self._config['config_service']['connection_timeout']) )
			
		if not serviceConnectionThread.connected:
			raise Exception("Failed to connect to config service '%s': reason unknown" % self._config['config_service']['url'])
		
		self._configService = serviceConnectionThread.configService
	
	def disconnectConfigServer(self):
		self._configService = None
		
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
				self._blockLogin = bool(params[0])
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
				System.runAsSystemInSession(command = str(params[0]), sessionId = None, desktop = desktop, waitForProcessEnding = False)
				return "command '%s' executed" % str(params[0])
			
			elif (method == 'logoffCurrentUser'):
				logger.notice("rpc logoffCurrentUser: logging of current user now")
				System.logoffCurrentUser()
				
			elif (method == 'lockWorkstation'):
				logger.notice("rpc lockWorkstation: locking workstation now")
				System.lockWorkstation()
				
			elif (method == 'processProductActionRequests'):
				if self._processingActionRequests:
					logger.notice("rpc processProductActionRequests: Already processing action requests")
					return "Already processing action requests"
				logger.notice("rpc processProductActionRequests: Start processing action requests")
				self._processActionRequestsEvent.logoffCurrentUser = bool(params[0])
				self._processActionRequestsEvent.fire()
				return "Processing action requests started"
			
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
			
			elif (method == 'reboot'):
				wait = 0
				if (len(params) > 0) and type(params[0]) is int:
					wait = int(params[0])
				logger.notice("rpc reboot: rebooting computer in %s seconds" % wait)
				System.reboot(wait = wait)
			
			elif (method == 'uptime'):
				uptime = int(time.time() - self._startupTime)
				logger.notice("rpc uptime: opsiclientd is running for %d seconds")
				return uptime
			
			elif (method == 'getCurrentActiveDesktopName'):
				desktop = self.getCurrentActiveDesktopName()
				logger.notice("rpc getCurrentActiveDesktopName: current active desktop name is '%s'" % desktop)
				return desktop
			
			elif (method == 'setCurrentActiveDesktopName'):
				self._CurrentActiveDesktopName = str(params[0])
				logger.notice("rpc setCurrentActiveDesktopName: current active desktop name set to '%s'" % params[0])
			
			else:
				raise NotImplementedError("Method '%s' not implemented" % method)
			
		except Exception, e:
			logger.logException(e)
			raise
	
	def getCurrentActiveDesktopName(self):
		cmd = '''pythonw.exe -c "from OPSI import System;from OPSI.Backend.JSONRPC import JSONRPCBackend;JSONRPCBackend(username = '%s', password = '%s', address = 'https://localhost:%s/rpc').setCurrentActiveDesktopName(System.getActiveDesktopName())"''' \
				% (self._config['global']['host_id'], self._config['global']['opsi_host_key'], self._config['control_server']['port'])
		System.runAsSystemInSession(command = cmd, waitForProcessEnding = True)
		return self._CurrentActiveDesktopName

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
		
		# Start opsiclientd
		self._opsiclientd = Opsiclientd()
		self._opsiclientd.start()
		while self._opsiclientd.isRunning():
			time.sleep(1)
		
	def signalHandler(self, signo, stackFrame):
		if (signo == SIGHUP):
			return
		if (signo == SIGTERM or signo == SIGINT):
			self._opsiclientd.stop()
		
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
			
			opsiclientd = Opsiclientd()
			opsiclientd.start()
			# Write to event log
			self.ReportServiceStatus(win32service.SERVICE_RUNNING)
			
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


