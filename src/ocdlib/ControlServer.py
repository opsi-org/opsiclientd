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
from OPSI.Service.Resource import ResourceOpsi, ResourceOpsiJsonRpc, ResourceOpsiJsonInterface, ResourceOpsiDAV
from OPSI.Backend.BackendManager import BackendManager

from ocdlib.Exceptions import *
from ocdlib.ControlPipe import OpsiclientdRpcPipeInterface
from ocdlib.Config import Config
from ocdlib.Events import eventGenerators
from ocdlib.Timeline import Timeline

logger = Logger()
config = Config()
timeline = Timeline()

try:
	from ocdlibnonfree.CacheService import CacheService
except Exception, e:
	pass

infoPage = u'''
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"
"http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">

<html xmlns="http://www.w3.org/1999/xhtml">
<head>
	<title>opsi client daemon info</title>
	<meta http-equiv="refresh" content="60" />
	<link rel="stylesheet" type="text/css" href="/opsiclientd.css" />
	%(head)s
	<script type="text/javascript">
	function onPageLoad(){
		onLoad();
		var logDiv = document.getElementById("infopage-opsiclientd-log");
		logDiv.scrollTop = logDiv.scrollHeight;
	}
	</script>
</head>
<body onload="onPageLoad();" onresize="onResize();">
	<span id="title">
		<img src="/opsi_logo.png" />
		<span sytle="padding: 1px; top: 5px;">opsi client daemon info</span>
	</span>
	
	<div id="infopage-timeline-box">
		<p id="infopage-timeline-title">Timeline</p>
		<div class="timeline-default" id="opsiclientd-timeline" style="height: 400px; border: 1px solid #aaaaaa"></div>
		<noscript>
		This page uses Javascript to show you a Timeline. Please enable Javascript in your browser to see the full page. Thank you.
		</noscript>
	</div>
	
	<div id="infopage-opsiclientd-log-box">
		<p id="infopage-opsiclientd-log-title">Log</p>
		<div id="infopage-opsiclientd-log">
		%(opsiclient-log)s
		</div>
	</div>
</body>
</html>
'''

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
			
			if (self.session.user.lower() == config.get('global', 'host_id').lower()) and (self.session.password == config.get('global', 'opsi_host_key')):
				return result
			if (os.name == 'nt'):
				if (self.session.user.lower() == 'administrator'):
					import win32security
					# The LogonUser function will raise an Exception on logon failure
					win32security.LogonUser(self.session.user, 'None', self.session.password, win32security.LOGON32_LOGON_NETWORK, win32security.LOGON32_PROVIDER_DEFAULT)
					# No exception raised => user authenticated
					return result
			
			raise Exception(u"Invalid credentials")
		except Exception, e:
			raise OpsiAuthenticationError(u"Forbidden: %s" % forceUnicode(e))
		return result
	
class WorkerOpsiclientdJsonRpc(WorkerOpsiclientd, WorkerOpsiJsonRpc):
	def __init__(self, service, request, resource):
		WorkerOpsiclientd.__init__(self, service, request, resource)
		WorkerOpsiJsonRpc.__init__(self, service, request, resource)
	
	def _getCallInstance(self, result):
		self._callInstance = self.service._opsiclientdRpcInterface
		self._callInterface = self.service._opsiclientdRpcInterface.getInterface()
		#logger.debug2(u"Got call instance '%s' from service '%s' with interface: %s" % (self._callInstance, self.service, self._callInterface))
	
	def _processQuery(self, result):
		return WorkerOpsiJsonRpc._processQuery(self, result)
	
	def _generateResponse(self, result):
		return WorkerOpsiJsonRpc._generateResponse(self, result)
	
class WorkerOpsiclientdJsonInterface(WorkerOpsiclientdJsonRpc, WorkerOpsiJsonInterface):
	def __init__(self, service, request, resource):
		WorkerOpsiclientdJsonRpc.__init__(self, service, request, resource)
		WorkerOpsiJsonInterface.__init__(self, service, request, resource)
		self.path = u'interface'
		
	def _getCallInstance(self, result):
		return WorkerOpsiclientdJsonRpc._getCallInstance(self, result)
	
	def _generateResponse(self, result):
		return WorkerOpsiJsonInterface._generateResponse(self, result)

class WorkerCacheServiceJsonRpc(WorkerOpsiclientd, WorkerOpsiJsonRpc):
	def __init__(self, service, request, resource):
		WorkerOpsiclientd.__init__(self, service, request, resource)
		WorkerOpsiJsonRpc.__init__(self, service, request, resource)
		
	def _getBackend(self, result):
		if hasattr(self.session, 'callInstance') and hasattr(self.session, 'callInterface') and self.session.callInstance and self.session.callInterface:
			return result
		if not self.service._opsiclientd.getCacheService():
			raise Exception(u'Cache service not running')
		
		self.session.callInstance = self.service._opsiclientd.getCacheService().getConfigBackend()
		logger.notice(u'Backend created: %s' % self.session.callInstance)
		self.session.callInterface = self.session.callInstance.backend_getInterface()
		return result
	
	def _getCallInstance(self, result):
		self._getBackend(result)
		self._callInstance = self.session.callInstance
		self._callInterface = self.session.callInterface
	
	def _processQuery(self, result):
		return WorkerOpsiJsonRpc._processQuery(self, result)
		
	def _generateResponse(self, result):
		return WorkerOpsiJsonRpc._generateResponse(self, result)
	
	def _renderError(self, failure):
		return WorkerOpsiJsonRpc._renderError(self, failure)


class WorkerCacheServiceJsonInterface(WorkerCacheServiceJsonRpc, WorkerOpsiJsonInterface):
	def __init__(self, service, request, resource):
		WorkerCacheServiceJsonRpc.__init__(self, service, request, resource)
		WorkerOpsiJsonInterface.__init__(self, service, request, resource)
		self.path = u'rpcinterface'
		
	def _getCallInstance(self, result):
		return WorkerCacheServiceJsonRpc._getCallInstance(self, result)
	
	def _generateResponse(self, result):
		return WorkerOpsiJsonInterface._generateResponse(self, result)


class WorkerOpsiclientdInfo(WorkerOpsiclientd):
	def __init__(self, service, request, resource):
		WorkerOpsiclientd.__init__(self, service, request, resource)
	
	def _processQuery(self, result):
		return result
	
	def _generateResponse(self, result):
		logger.info(u"Creating opsiclientd info page")
		
		#if not self.session.isAdmin:
		#	raise OpsiAuthenticationError(u"Permission denied")
		
		
		log = u''
		regex = re.compile('^\[(\d)\].*')
		try:
			f = codecs.open(config.get('global', 'log_file'), 'r', 'utf-8')
			lastLogLevel = 0
			for line in f.readlines():
				logLevel = 0
				match = regex.search(line)
				if match:
					logLevel = int(match.group(1))
				if logLevel and (logLevel != lastLogLevel):
					if lastLogLevel:
						log += u'</span>'
					log += u'<span class="loglevel-%s">' % logLevel
					lastLogLevel = logLevel
				log += line.rstrip() \
					.replace(u'\r', u'')\
					.replace(u'\t', u'   ')\
					.replace(u'&',  u'&amp;')\
					.replace(u'"',  u'&quot;')\
					.replace(u"'",  u'&apos;')\
					.replace(u' ',  u'&#x202f;')\
					.replace(u'<',  u'&lt;')\
					.replace(u'>',  u'&gt;')
				log += u'<br />\n'
			f.close()
			if lastLogLevel:
				log += u'</span>'
		except Exception, e:
			logger.error(e)
		
		html = infoPage % {
			'head': timeline.getHtmlHead(),
			'opsiclient-log': log
		}
		if not isinstance(result, http.Response):
			result = http.Response()
		result.code = responsecode.OK
		result.stream = stream.IByteStream(html.encode('utf-8').strip())
		return result


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

class ResourceCacheServiceJsonRpc(ResourceOpsiJsonRpc):
	WorkerClass = WorkerCacheServiceJsonRpc

class ResourceCacheServiceJsonInterface(ResourceOpsiJsonInterface):
	WorkerClass = WorkerCacheServiceJsonInterface

class ResourceOpsiclientdInfo(ResourceOpsiclientd):
	WorkerClass = WorkerOpsiclientdInfo
	
	def __init__(self, service):
		ResourceOpsiclientd.__init__(self, service)

class ControlServer(OpsiService, threading.Thread):
	def __init__(self, opsiclientd, httpsPort, sslServerKeyFile, sslServerCertFile, staticDir=None):
		OpsiService.__init__(self)
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
		self._opsiclientdRpcInterface = OpsiclientdRpcInterface(self._opsiclientd)
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
		ResourceSoftwareOnDemand = None
		try:
			from ocdlibnonfree.SoftwareOnDemand import WorkerSoftwareOnDemand, ResourceSoftwareOnDemand
		except Exception, e:
			logger.notice(u"Software on demand not available: %s" % e)
		
		if self._staticDir:
			if os.path.isdir(self._staticDir):
				self._root = ResourceOpsiDAV(self, path = self._staticDir, readOnly = True, authRequired = False)
				#self._root = static.File(self._staticDir)
			else:
				logger.error(u"Cannot add static content '/': directory '%s' does not exist." % self._staticDir)
		if not self._root:
			self._root = ResourceRoot()
		self._root.putChild("opsiclientd", ResourceOpsiclientdJsonRpc(self))
		self._root.putChild("interface",   ResourceOpsiclientdJsonInterface(self))
		self._root.putChild("rpc", ResourceCacheServiceJsonRpc(self))
		self._root.putChild("rpcinterface", ResourceCacheServiceJsonInterface(self))
		self._root.putChild("info.html", ResourceOpsiclientdInfo(self))
		if ResourceSoftwareOnDemand:
			self._root.putChild("swondemand", ResourceSoftwareOnDemand(self))
		
class OpsiclientdRpcInterface(OpsiclientdRpcPipeInterface):
	def __init__(self, opsiclientd):
		OpsiclientdRpcPipeInterface.__init__(self, opsiclientd)
	
	def cacheService_syncConfig(self):
		return self.opsiclientd.getCacheService().syncConfig()
	
	def cacheService_getConfigCacheState(self):
		return self.opsiclientd.getCacheService().getConfigCacheState()
	
	def cacheService_getProductCacheState(self):
		return self.opsiclientd.getCacheService().getProductCacheState()
	
	def cacheService_getConfigModifications(self):
		return self.opsiclientd.getCacheService().getConfigModifications()
	
	def timeline_getEvents(self):
		return timeline.getEvents()
	
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
	
	def execute(self, command, waitForEnding=True, captureStderr=True, encoding=None, timeout=300):
		return System.execute(cmd = command, waitForEnding = waitForEnding, captureStderr = captureStderr, encoding = encoding, timeout = timeout)
		
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
	










