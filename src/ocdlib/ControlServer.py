# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = = = =
   =   ocdlib.ControlServer                =
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

# Imports
from OpenSSL import SSL
import base64, urllib, codecs

# Twisted imports
from twisted.internet import defer, threads, reactor
from OPSI.web2 import resource, stream, server, http, responsecode, static, http_headers
from OPSI.web2.channel.http import HTTPFactory

# OPSI imports
from OPSI.Logger import *
from OPSI.Types import *
from OPSI.Util import *
from OPSI import System
from OPSI.Service import SSLContext, OpsiService
from OPSI.Service.Worker import WorkerOpsi, WorkerOpsiJsonRpc, WorkerOpsiJsonInterface, WorkerOpsiDAV, interfacePage
from OPSI.Service.Resource import ResourceOpsi, ResourceOpsiJsonRpc, ResourceOpsiJsonInterface

from ocdlib.Exceptions import *
from ocdlib.ControlPipe import OpsiclientdRpcPipeInterface
from ocdlib.Config import Config
from ocdlib.Events import eventGenerators
try:
	from ocdlibnonfree.CacheService import CacheService
except:
	from ocdlib.CacheService import CacheService

logger = Logger()
config = Config()

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

class WorkerOpsiclientd(WorkerOpsi):
	def __init__(self, service, request, resource):
		moduleName = u' %-30s' % (u'control server')
		logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)
		WorkerOpsi.__init__(self, service, request, resource)
	
	def _getCredentials(self):
		(user, password) = self._getAuthorization()
		if not user:
			user = config.get('global', 'host_id')
		return (user, password)
		
	def _authenticate(self, result):
		if self.session.authenticated:
			return result
		
		try:
			(self.session.user, self.session.password) = self._getCredentials()
			
			logger.notice(u"Authorization request from %s@%s (application: %s)" % (self.session.user, self.session.ip, self.session.userAgent))
			
			if not self.session.password:
				raise Exception(u"No password from %s (application: %s)" % (self.session.ip, self.session.userAgent))
			
			self.service._authenticate(self.session.user, self.session.password)
			
		except Exception, e:
			raise OpsiAuthenticationError(u"Forbidden: %s" % forceUnicode(e))
		return result
	
class WorkerOpsiclientdJsonRpc(WorkerOpsiclientd, WorkerOpsiJsonRpc):
	def __init__(self, service, request, resource):
		WorkerOpsiclientd.__init__(self, service, request, resource)
		WorkerOpsiJsonRpc.__init__(self, service, request, resource)
	
	def _getCallInstance(self, result):
		self._callInstance = self.service
		self._callInterface = self.service.getInterface()
		logger.debug(u"Got call instance '%s' from service '%s' with interface: %s" % (self._callInstance, self.service, self._callInterface))
		
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                       JSON INTERFACE WORKER                                       -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class WorkerOpsiclientdJsonInterface(WorkerOpsiclientdJsonRpc, WorkerOpsiJsonInterface):
	def __init__(self, service, request, resource):
		WorkerOpsiclientdJsonRpc.__init__(self, service, request, resource)
		WorkerOpsiJsonInterface.__init__(self, service, request, resource)
	
	def _generateResponse(self, result):
		return WorkerOpsiJsonInterface._generateResponse(self, result)
	
	def _getCallInstance(self, result):
		return WorkerOpsiclientdJsonRpc._getCallInstance(self, result)
		
	#def _setResponse(self, result):
	#	logger.info(u"Creating opsiclientd interface page")
	#	
	#	javascript  = u"var currentParams = new Array();\n"
	#	javascript += u"var currentMethod = null;\n"
	#	currentMethod = u''
	#	if self._rpcs:
	#		currentMethod = self._rpcs[0].getMethodName()
	#		javascript += u"currentMethod = '%s';\n" % currentMethod
	#		for i in range(len(self._rpcs[0].params)):
	#			param = self._rpcs[0].params[i]
	#			javascript += u"currentParams[%d] = '%s';\n" % (i, toJson(param))
	#	
	#	selectMethod = u''
	#	for method in self.opsiclientdRpcInterface.getInterface():
	#		javascript += u"parameters['%s'] = new Array();\n" % (method['name'])
	#		for param in range(len(method['params'])):
	#			javascript += u"parameters['%s'][%s]='%s';\n" % (method['name'], param, method['params'][param])
	#		selected = u''
	#		if (method['name'] == currentMethod):
	#			selected = u' selected'
	#		selectMethod += '<option%s>%s</option>' % (selected, method['name'])
	#	
	#	resultDiv = u'<div id="result">'
	#	for rpc in self._rpcs:
	#		resultDiv += '<div class="json">'
	#		resultDiv += objectToHtml(rpc.getResponse())
	#		resultDiv += u'</div>'
	#	resultDiv += u'</div>'
	#	
	#	html = interfacePage
	#	html = html.replace('%javascript%', javascript)
	#	html = html.replace('%select_method%', selectMethod)
	#	html = html.replace('%result%', resultDiv)
	#	
	#	if not isinstance(result, http.Response):
	#		result = http.Response()
	#	result.code = responsecode.OK
	#	result.stream = stream.IByteStream(html.encode('utf-8'))
	#	return result

'''
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                               CACHED CONFIG SERVICE JSON RPC WORKER                               -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class CacheServiceJsonRpcWorker(Worker):
	def __init__(self, request, opsiclientd, resource):
		Worker.__init__(self, request, opsiclientd, resource)
		moduleName = u' %-30s' % (u'cached cfg server')
		logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)
	
	def _realRpc(self):
		method = self.rpc.get('method')
		params = self.rpc.get('params')
		logger.info(u"RPC method: '%s' params: '%s'" % (method, params))
		
		try:
			# Execute method
			start = time.time()
			self.result['result'] = self._opsiclientd._cacheService.processRpc(method, params)
		except Exception, e:
			logger.logException(e)
			self.result['error'] = { 'class': e.__class__.__name__, 'message': unicode(e) }
			self.result['result'] = None
			return
		
		logger.debug(u'Got result...')
		duration = round(time.time() - start, 3)
		logger.debug(u'Took %0.3fs to process %s(%s)' % (duration, method, unicode(params)[1:-1]))
'''


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                    CONTROL SERVER RESOURCE ROOT                                   -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ResourceRoot(resource.Resource):
	addSlash = True
	def render(self, request):
		''' Process request. '''
		return http.Response(stream="<html><head><title>opsiclientd</title></head><body></body></html>")


class ResourceOpsiclientd(ResourceOpsi):
	WorkerClass = WorkerOpsiclientd
	
class ResourceOpsiclientdJsonRpc(ResourceOpsiJsonRpc):
	WorkerClass = WorkerOpsiclientdJsonRpc

class ResourceOpsiclientdJsonInterface(ResourceOpsiJsonInterface):
	WorkerClass = WorkerOpsiclientdJsonInterface

#class ResourceControlServerJsonRpc(ResourceOpsiJsonRpc):
#	WorkerClass = WorkerOpsiconfdJsonRpc

'''
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                 CONTROL SERVER RESOURCE JSON RPC                                  -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ControlServerResourceJsonRpc(resource.Resource):
	WorkerClass = ControlServerJsonRpcWorker
	
	def __init__(self, opsiclientdRpcInterface):
		moduleName = u' %-30s' % (u'control server')
		logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)
		resource.Resource.__init__(self)
		self._opsiclientdRpcInterface = opsiclientdRpcInterface
		
	def getChild(self, name, request):
		""" Get the child resource for the requested path. """
		if not name:
			return self
		return resource.Resource.getChild(self, name, request)
	
	def renderHTTP(self, request):
		""" Process request. """
		try:
			logger.debug2(u"%s.renderHTTP()" % self.__class__.__name__)
			if not self.WorkerClass:
				raise Exception(u"No worker class defined in resource %s" % self.__class__.__name__)
			worker = self.WorkerClass(self._opsiclientdRpcInterface, request, self)
			return worker.process()
		except Exception, e:
			logger.logException(e)
	
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                 CONTROL SERVER RESOURCE INTERFACE                                 -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ControlServerResourceInterface(ControlServerResourceJsonRpc):
	WorkerClass = ControlServerJsonInterfaceWorker
	
	def __init__(self, opsiclientdRpcInterface):
		moduleName = u' %-30s' % (u'control server')
		logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)
		ControlServerResourceJsonRpc.__init__(self, opsiclientdRpcInterface)


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                              CACHED CONFIG SERVICE RESOURCE JSON RPC                              -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class CacheServiceResourceJsonRpc(resource.Resource):
	def __init__(self, opsiclientd):
		moduleName = u' %-30s' % (u'cached cfg server')
		logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)
		resource.Resource.__init__(self)
		self._opsiclientd = opsiclientd
		
	def getChild(self, name, request):
		""" Get the child resource for the requested path. """
		if not name:
			return self
		return resource.Resource.getChild(self, name, request)
	
	def http_POST(self, request):
		""" Process POST request. """
		logger.info(u"CacheServiceResourceJsonRpc: processing POST request")
		worker = CacheServiceJsonRpcWorker(request, self._opsiclientd, method = 'POST')
		return worker.process()
		
	def http_GET(self, request):
		""" Process GET request. """
		logger.info(u"CacheServiceResourceJsonRpc: processing GET request")
		worker = CacheServiceJsonRpcWorker(request, self._opsiclientd, method = 'GET')
		return worker.process()
'''


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                           CONTROL SERVER                                          -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ControlServer(threading.Thread):
	def __init__(self, opsiclientd, httpsPort, sslServerKeyFile, sslServerCertFile, staticDir=None):
		moduleName = u' %-30s' % (u'control server')
		logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)
		threading.Thread.__init__(self)
		self._opsiclientd = opsiclientd
		self._httpsPort = httpsPort
		self._sslServerKeyFile = sslServerKeyFile
		self._sslServerCertFile = sslServerCertFile
		self._staticDir = staticDir
		self._root = None
		self._running = False
		self._server = None
		self._opsiclientdRpcInterface = OpsiclientdRpcServerInterface(self._opsiclientd)
		logger.info(u"ControlServer initiated")
		
	def run(self):
		self._running = True
		try:
			logger.info(u"creating root resource")
			self.createRoot()
			self._site = server.Site(self._root)
			self._server = reactor.listenSSL(
				self._httpsPort,
				HTTPFactory(self._site),
				SSLContext(self._sslServerKeyFile, self._sslServerCertFile) )
			logger.notice(u"Control server is accepting HTTPS requests on port %d" % self._httpsPort)
			if not reactor.running:
				reactor.run(installSignalHandlers=0)
			
		except Exception, e:
			logger.logException(e)
		logger.notice(u"Control server exiting")
		self._running = False
	
	def stop(self):
		if self._server:
			self._server.stopListening()
		self._running = False
	
	def createRoot(self):
		if self._staticDir:
			if os.path.isdir(self._staticDir):
				self._root = static.File(self._staticDir)
			else:
				logger.error(u"Cannot add static content '/': directory '%s' does not exist." % self._staticDir)
		if not self._root:
			self._root = ResourceRoot()
		self._root.putChild("opsiclientd", ResourceOpsiclientdJsonRpc(self._opsiclientdRpcInterface))
		self._root.putChild("interface",   ResourceOpsiclientdJsonInterface(self._opsiclientdRpcInterface))
		#self._root.putChild("rpc", CacheServiceResourceJsonRpc(self._opsiclientd))


class OpsiclientdRpcServerInterface(OpsiclientdRpcPipeInterface, OpsiService):
	def __init__(self, opsiclientd):
		OpsiclientdRpcPipeInterface.__init__(self, opsiclientd)
		OpsiService.__init__(self)
	
	def _authenticate(self, username, password):
		if (username.lower() == config.get('global', 'host_id').lower()) and (password == config.get('global', 'opsi_host_key')):
			return True
		if (os.name == 'nt'):
			if (username.lower() == 'administrator'):
				import win32security
				# The LogonUser function will raise an Exception on logon failure
				win32security.LogonUser(username, 'None', password, win32security.LOGON32_LOGON_NETWORK, win32security.LOGON32_PROVIDER_DEFAULT)
				# No exception raised => user authenticated
				return True
		raise Exception(u"Invalid credentials")
	
	def setBlockLogin(self, blockLogin):
		self.opsiclientd.setBlockLogin(bool(blockLogin))
		logger.notice(u"rpc setBlockLogin: blockLogin set to '%s'" % self.opsiclientd._blockLogin)
		if self.opsiclientd._blockLogin:
			return u"Login blocker is on"
		else:
			return u"Login blocker is off"
	
	def readLog(self, logType='opsiclientd'):
		logType = forceUnicode(logType)
		if not logType in ('opsiclientd'):
			raise ValueError(u"Unknown log type '%s'" % logType)
		
		logger.notice(u"rpc readLog: reading log of type '%s'" % logType)
		
		if (logType == 'opsiclientd'):
			f = codecs.open(config.get('global', 'log_file'), 'r', 'utf-8', 'replace')
			data = f.read()
			f.close()
			return data
		return u""
	
	def runCommand(self, command, sessionId=None, desktop=None):
		command = forceUnicode(command)
		if not command:
			raise ValueError("No command given")
		if sessionId:
			sessionId = forceInt(sessionId)
		else:
			sessionId = System.getActiveSessionId()
		if desktop:
			desktop = forceUnicode(desktop)
		else:
			desktop = self.opsiclientd.getCurrentActiveDesktopName()
		logger.notice(u"rpc runCommand: executing command '%s' in session %d on desktop '%s'" % (command, sessionId, desktop))
		System.runCommandInSession(command = command, sessionId = sessionId, desktop = desktop, waitForProcessEnding = False)
		return u"command '%s' executed" % command
	
	def logoffCurrentUser(self):
		logger.notice(u"rpc logoffCurrentUser: logging of current user now")
		System.logoffCurrentUser()
	
	def lockWorkstation(self):
		logger.notice(u"rpc lockWorkstation: locking workstation now")
		System.lockWorkstation()
	
	def shutdown(self, waitSeconds=0):
		waitSeconds = forceInt(waitSeconds)
		logger.notice(u"rpc shutdown: shutting down computer in %s seconds" % waitSeconds)
		System.shutdown(wait = waitSeconds)
	
	def reboot(self, waitSeconds=0):
		waitSeconds = forceInt(waitSeconds)
		logger.notice(u"rpc reboot: rebooting computer in %s seconds" % waitSeconds)
		System.reboot(wait = waitSeconds)
		
	def uptime(self):
		uptime = int(time.time() - self.opsiclientd._startupTime)
		logger.notice(u"rpc uptime: opsiclientd is running for %d seconds" % uptime)
		return uptime
	
	def fireEvent(self, name):
		name = forceUnicode(name)
		if not name in eventGenerators.keys():
			raise ValueError(u"Event '%s' not in list of known events: %s" % (name, ', '.join(eventGenerators.keys())))
		logger.notice(u"Firing event '%s'" % name)
		eventGenerators[name].fireEvent()
		
	def setStatusMessage(self, sessionId, message):
		sessionId = forceInt(sessionId)
		message = forceUnicode(message)
		ept = self.opsiclientd.getEventProcessingThread(sessionId)
		logger.notice(u"rpc setStatusMessage: Setting status message to '%s'" % message)
		ept.setStatusMessage(message)
	
	def getCurrentActiveDesktopName(self, sessionId=None):
		desktop = self.opsiclientd.getCurrentActiveDesktopName(sessionId)
		logger.notice(u"rpc getCurrentActiveDesktopName: current active desktop name is '%s'" % desktop)
		return desktop
	
	def setCurrentActiveDesktopName(self, sessionId, desktop):
		sessionId = forceInt(sessionId)
		desktop = forceUnicode(desktop)
		self.opsiclientd._currentActiveDesktopName[sessionId] = desktop
		logger.notice(u"rpc setCurrentActiveDesktopName: current active desktop name for session %s set to '%s'" % (sessionId, desktop))
	
	def set(self, section, option, value):
		section = forceUnicode(section)
		option = forceUnicode(option)
		value = forceUnicode(value)
		return config.set(section, option, value)
	
	def updateConfigFile(self):
		config.updateConfigFile()
		
	def showPopup(self, message):
		message = forceUnicode(message)
		self.opsiclientd.showPopup(message)
		
	












