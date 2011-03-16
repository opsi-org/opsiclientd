# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = = = =
   =   ocdlib.EventProcessing              =
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
import sys, os, shutil, filecmp, base64
from hashlib import md5

# Twisted imports
from twisted.conch.ssh import keys

# OPSI imports
from OPSI.Logger import *
from OPSI.Util import *
from OPSI.Util.Message import *
from OPSI.Types import *
from OPSI import System
from OPSI.Object import *

from ocdlib.Exceptions import *
from ocdlib.Events import *
from ocdlib.OpsiService import ServiceConnection
if (os.name == 'nt'):
	from ocdlib.Windows import *
if (os.name == 'posix'):
	from ocdlib.Posix import *
from ocdlib.Localization import _, setLocaleDir, getLanguage
from ocdlib.Config import Config
from ocdlib.Timeline import Timeline

logger = Logger()
config = Config()
timeline = Timeline()

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                      EVENT PROCESSING THREAD                                      -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class EventProcessingThread(KillableThread, ServiceConnection):
	def __init__(self, opsiclientd, event):
		from ocdlib.Opsiclientd import __version__
		
		moduleName = u' %-30s' % (u'event processing ' + event.eventConfig.getId())
		logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)
		KillableThread.__init__(self)
		ServiceConnection.__init__(self)
		
		self.opsiclientd = opsiclientd
		self.event = event
		
		self.running = False
		self.eventCancelled = False
		self.waitCancelled = False
		
		self.shutdownCancelled = False
		self.shutdownWaitCancelled = False
		
		self._sessionId = None
		
		self._serviceConnection = None
		
		self._notificationServer = None
		
		self._depotShareMounted = False
		
		self._statusSubject = MessageSubject('status')
		self._messageSubject = MessageSubject('message')
		self._serviceUrlSubject = MessageSubject('configServiceUrl')
		self._clientIdSubject = MessageSubject('clientId')
		self._actionProcessorInfoSubject = MessageSubject('actionProcessorInfo')
		self._opsiclientdInfoSubject = MessageSubject('opsiclientdInfo')
		self._detailSubjectProxy = MessageSubjectProxy('detail')
		self._currentProgressSubjectProxy = ProgressSubjectProxy('currentProgress', fireAlways = False)
		self._overallProgressSubjectProxy = ProgressSubjectProxy('overallProgress', fireAlways = False)
		self._choiceSubject = None
		
		self._statusSubject.setMessage( _("Processing event %s") % self.event.eventConfig.getName() )
		#self._serviceUrlSubject.setMessage(config.get('config_service', 'url'))
		self._clientIdSubject.setMessage(config.get('global', 'host_id'))
		self._opsiclientdInfoSubject.setMessage("opsiclientd %s" % __version__)
		self._actionProcessorInfoSubject.setMessage("")
		
		#self.isLoginEvent = isinstance(self.event, UserLoginEvent)
		self.isLoginEvent = bool(self.event.eventConfig.actionType == 'login')
		if self.isLoginEvent:
			logger.info(u"Event is user login event")
		
		self.getSessionId()
		
		self._notificationServerPort = int(config.get('notification_server', 'start_port')) + (3 * int(self.getSessionId()))
	
	''' ServiceConnection '''
	def connectionThreadOptions(self):
		return {'statusSubject': self._statusSubject}
	
	def connectionStart(self, configServiceUrl):
		self._serviceUrlSubject.setMessage(configServiceUrl)
		cancellableAfter = forceInt(config.get('config_service', 'user_cancelable_after'))
		if self._notificationServer and (cancellableAfter < 1):
			logger.info(u"User is allowed to cancel connection after %d seconds" % cancellableAfter)
			self._choiceSubject = ChoiceSubject(id = 'choice')
			self._notificationServer.addSubject(self._choiceSubject)
	
	def connectionCancelable(self, stopConnectionCallback):
		if self._notificationServer and self._choiceSubject:
			self._choiceSubject.setChoices([ 'Stop connection' ])
			self._choiceSubject.setCallbacks( [ stopConnectionCallback ] )
			self._notificationServer.addSubject(self._choiceSubject)
	
	def connectionTimeoutChanged(self, timeout):
		if self._detailSubjectProxy:
			self._detailSubjectProxy.setMessage( _(u'Timeout: %ds') % timeout )
	
	def connectionCanceled(self):
		if self._notificationServer and self._choiceSubject:
			self._notificationServer.removeSubject(self._choiceSubject)
		self._detailSubjectProxy.setMessage(u'')
		ServiceConnection.connectionCanceled(self)
	
	def connectionTimedOut(self):
		if self._notificationServer and self._choiceSubject:
			self._notificationServer.removeSubject(self._choiceSubject)
		self._detailSubjectProxy.setMessage(u'')
		ServiceConnection.connectionTimedOut(self)
	
	def connectionEstablished(self):
		if self._notificationServer and self._choiceSubject:
			self._notificationServer.removeSubject(self._choiceSubject)
		self._detailSubjectProxy.setMessage(u'')
		
	def connectionFailed(self, error):
		if self._notificationServer and self._choiceSubject:
			self._notificationServer.removeSubject(self._choiceSubject)
		self._detailSubjectProxy.setMessage(u'')
		ServiceConnection.connectionFailed(self, error)
		
	''' / ServiceConnection '''
	
	def setSessionId(self, sessionId):
		self._sessionId = int(sessionId)
		logger.info(u"Session id set to %s" % self._sessionId)
		
	def getSessionId(self):
		logger.debug(u"getSessionId()")
		if self._sessionId is None:
			sessionId = None
			if self.isLoginEvent:
				logger.info(u"Using session id of user '%s'" % self.event.eventInfo["User"])
				userSessionsIds = System.getUserSessionIds(self.event.eventInfo["User"])
				if userSessionsIds:
					sessionId = userSessionsIds[0]
			if not sessionId:
				sessionId = System.getActiveSessionId()
				
			self.setSessionId(sessionId)
		return self._sessionId
		
	def setStatusMessage(self, message):
		self._statusSubject.setMessage(message)
		
	def startNotificationServer(self):
		logger.notice(u"Starting notification server on port %s" % self._notificationServerPort)
		error = None
		for i in range(3):
			try:
				self._notificationServer = NotificationServer(
								address  = config.get('notification_server', 'interface'),
								port     = self._notificationServerPort,
								subjects = [
									self._statusSubject,
									self._messageSubject,
									self._serviceUrlSubject,
									self._clientIdSubject,
									self._actionProcessorInfoSubject,
									self._opsiclientdInfoSubject,
									self._detailSubjectProxy,
									self._currentProgressSubjectProxy,
									self._overallProgressSubjectProxy ] )
				self._notificationServer.start()
				while not self._notificationServer.isListening() and not self._notificationServer.errorOccurred():
					time.sleep(1)
				if self._notificationServer.errorOccurred():
					raise Exception(self._notificationServer.errorOccurred())
				logger.notice(u"Notification server started")
				break
			except Exception, e:
				error = forceUnicode(e)
				logger.error(u"Failed to start notification server: %s" % error)
				self._notificationServerPort += 1
		if error:
			raise Exception(u"Failed to start notification server: %s" % error)
		
	def stopNotificationServer(self):
		if not self._notificationServer:
			return
		try:
			logger.info(u"Stopping notification server")
			self._notificationServer.stop(stopReactor = False)
		except Exception, e:
			logger.logException(e)

	def getConfigFromService(self):
		''' Get settings from service '''
		logger.notice(u"Getting config from service")
		try:
			if not self.isConfigServiceConnected():
				logger.warning(u"Cannot get config from service: not connected")
				return
			self.setStatusMessage(_(u"Getting config from service"))
			config.getFromService(self._configService)
			self.setStatusMessage(_(u"Got config from service"))
			logger.notice(u"Reconfiguring event generators")
			reconfigureEventGenerators()
		except Exception, e:
			logger.error(u"Failed to get config from service: %s" % forceUnicode(e))
			raise
	
	def writeLogToService(self):
		logger.notice(u"Writing log to service")
		try:
			if not self.isConfigServiceConnected():
				logger.warning(u"Cannot write log to service: not connected")
				return
			self.setStatusMessage( _(u"Writing log to service") )
			f = codecs.open(config.get('global', 'log_file'), 'r', 'utf-8', 'replace')
			data = f.read()
			data += u"-------------------- submitted part of log file ends here, see the rest of log file on client --------------------\n"
			f.close()
			# Do not log jsonrpc request
			logger.setFileLevel(LOG_WARNING)
			if self._configService.isLegacyOpsi():
				self._configService.writeLog('clientconnect', data.replace(u'\ufffd', u'?'), config.get('global', 'host_id'))
				#self._configService.writeLog('clientconnect', data.replace(u'\ufffd', u'?').encode('utf-8'), config.get('global', 'host_id'))
			else:
				self._configService.log_write('clientconnect', data.replace(u'\ufffd', u'?'), config.get('global', 'host_id'))
			logger.setFileLevel(config.get('global', 'log_level'))
		except Exception, e:
			logger.setFileLevel(config.get('global', 'log_level'))
			logger.error(u"Failed to write log to service: %s" % forceUnicode(e))
			raise
		
	def runCommandInSession(self, command, desktop=None, waitForProcessEnding=False, timeoutSeconds=0):
		
		sessionId = self.getSessionId()
		
		if not desktop or desktop.lower() not in (u'winlogon', u'default'):
			if self.isLoginEvent:
				desktop = u'default'
			else:
				logger.debug(u"Getting current active desktop name")
				desktop = self.opsiclientd.getCurrentActiveDesktopName(sessionId)
				logger.debug(u"Got current active desktop name: %s" % desktop)
				
		if not desktop or desktop.lower() not in (u'winlogon', u'default'):
			desktop = u'winlogon'
		
		processId = None
		while True:
			try:
				logger.info("Running command %s in session '%s' on desktop '%s'" % (command, sessionId, desktop))
				processId = System.runCommandInSession(
						command              = command,
						sessionId            = sessionId,
						desktop              = desktop,
						waitForProcessEnding = waitForProcessEnding,
						timeoutSeconds       = timeoutSeconds)[2]
				break
			except Exception, e:
				logger.error(e)
				if (e[0] == 233) and (sys.getwindowsversion()[0] == 5) and (sessionId != 0):
					# No process is on the other end
					# Problem with pipe \\\\.\\Pipe\\TerminalServer\\SystemExecSrvr\\<sessionid>
					# After logging off from a session other than 0 csrss.exe does not create this pipe or CreateRemoteProcessW is not able to read the pipe.
					logger.info(u"Retrying to run command on winlogon desktop of session 0")
					sessionId = 0
					desktop = 'winlogon'
				else:
					raise
		
		self.setSessionId(sessionId)
		return processId
	
	def startNotifierApplication(self, command, desktop=None, notifierId=None):
		logger.notice(u"Starting notifier application in session '%s'" % self.getSessionId())
		try:
			self.runCommandInSession(
				command = command.replace('%port%', forceUnicode(self._notificationServerPort)).replace('%id%', forceUnicode(notifierId)),
				desktop = desktop, waitForProcessEnding = False)
			time.sleep(3)
		except Exception, e:
			logger.error(u"Failed to start notifier application '%s': %s" % (command, e))
	
	def closeProcessWindows(self, processId):
		command = None
		try:
			command = '%s "exit(); System.closeProcessWindows(processId = %s)"' \
					% (config.get('opsiclientd_rpc', 'command'), processId)
		except Exception, e:
			raise Exception(u"opsiclientd_rpc command not defined: %s" % forceUnicode(e))
		
		self.runCommandInSession(command = cmd, waitForProcessEnding = False)
		
	def setActionProcessorInfo(self):
		try:
			actionProcessorFilename = config.get('action_processor', 'filename')
			actionProcessorLocalDir = config.get('action_processor', 'local_dir')
			actionProcessorLocalFile = os.path.join(actionProcessorLocalDir, actionProcessorFilename)
			actionProcessorLocalFile = actionProcessorLocalFile
			info = System.getFileVersionInfo(actionProcessorLocalFile)
			version = info.get('FileVersion', u'')
			name = info.get('ProductName', u'')
			logger.info(u"Action processor name '%s', version '%s'" % (name, version))
			self._actionProcessorInfoSubject.setMessage("%s %s" % (name.encode('utf-8'), version.encode('utf-8')))
		except Exception, e:
			logger.error(u"Failed to set action processor info: %s" % forceUnicode(e))
	
	def mountDepotShare(self, impersonation):
		if self._depotShareMounted:
			logger.debug(u"Depot share already mounted")
			return
		if not config.get('depot_server', 'url'):
			raise Exception(u"Cannot mount depot share, depot_server.url undefined")
		if config.get('depot_server', 'url').split('/')[2] in ('127.0.0.1', 'localhost'):
			logger.notice(u"No need to mount depot share %s, working on local depot cache" %  config.get('depot_server', 'url'))
			return
		
		logger.notice(u"Mounting depot share %s" %  config.get('depot_server', 'url'))
		self.setStatusMessage(_(u"Mounting depot share %s") % config.get('depot_server', 'url'))
		
		try:
			depotHost = config.get('depot_server', 'url').split('/')[2]
			System.setRegistryValue(
				System.HKEY_LOCAL_MACHINE,
				u"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Internet Settings\\ZoneMap\\Domains\\%s" % depotHost,
				u"file", 1)
			logger.info(u"Added depot '%s' to trusted domains" % depotHost)
		except Exception, e:
			logger.error(u"Failed to add depot to trusted domains: %s" % e)
		
		if impersonation:
			System.mount(config.get('depot_server', 'url'), config.getDepotDrive())
		else:
			(depotServerUsername, depotServerPassword) = config.getDepotserverCredentials(configService = self._configService)
			System.mount(config.get('depot_server', 'url'), config.getDepotDrive(), username = depotServerUsername, password = depotServerPassword)
		self._depotShareMounted = True
		
	def umountDepotShare(self):
		if not self._depotShareMounted:
			logger.debug(u"Depot share not mounted")
			return
		try:
			logger.notice(u"Unmounting depot share")
			System.umount(config.getDepotDrive())
			self._depotShareMounted = False
		except Exception, e:
			logger.warning(e)
		
	def updateActionProcessor(self):
		logger.notice(u"Updating action processor")
		self.setStatusMessage(_(u"Updating action processor"))
		
		impersonation = None
		try:
			mounted = False
			if not config.get('depot_server', 'url').split('/')[2].lower() in ('127.0.0.1', 'localhost'):
				# This logon type allows the caller to clone its current token and specify new credentials for outbound connections.
				# The new logon session has the same local identifier but uses different credentials for other network connections.
				(depotServerUsername, depotServerPassword) = config.getDepotserverCredentials(configService = self._configService)
				impersonation = System.Impersonate(username = depotServerUsername, password = depotServerPassword)
				impersonation.start(logonType = 'NEW_CREDENTIALS')
				self.mountDepotShare(impersonation)
				mounted = True
			
			actionProcessorFilename = config.get('action_processor', 'filename')
			actionProcessorLocalDir = config.get('action_processor', 'local_dir')
			actionProcessorLocalTmpDir = actionProcessorLocalDir + '.tmp'
			actionProcessorLocalFile = os.path.join(actionProcessorLocalDir, actionProcessorFilename)
			actionProcessorLocalTmpFile = os.path.join(actionProcessorLocalTmpDir, actionProcessorFilename)
			
			actionProcessorRemoteDir = None
			if config.get('depot_server', 'url').split('/')[2].lower() in ('127.0.0.1', 'localhost'):
				dirname = config.get('action_processor', 'remote_dir')
				while dirname.startswith('\\'):
					dirname = dirname.replace(u'\\', u'', 1)
				if dirname.startswith(u'install\\'):
					dirname = dirname.replace(u'install\\', u'', 1)
				while dirname.startswith('\\'):
					dirname = dirname.replace(u'\\', u'', 1)
				actionProcessorRemoteDir = os.path.join(
					self.opsiclientd.getCacheService().getProductCacheDir(),
					dirname
				)
				logger.notice(u"Updating action processor from local cache '%s'" % actionProcessorRemoteDir)
			else:
				actionProcessorRemoteDir = os.path.join(
					config.getDepotDrive(),
					config.get('action_processor', 'remote_dir'))
				logger.notice(u"Updating action processor from local cache '%s'" % actionProcessorRemoteDir)
			
			actionProcessorRemoteFile = os.path.join(actionProcessorRemoteDir, actionProcessorFilename)
			
			if not os.path.exists(actionProcessorLocalFile):
				logger.notice(u"Action processor needs update because file '%s' not found" % actionProcessorLocalFile)
			elif ( abs(os.stat(actionProcessorLocalFile).st_mtime - os.stat(actionProcessorRemoteFile).st_mtime) > 10 ):
				logger.notice(u"Action processor needs update because modification time difference is more than 10 seconds")
			elif not filecmp.cmp(actionProcessorLocalFile, actionProcessorRemoteFile):
				logger.notice(u"Action processor needs update because file changed")
			else:
				logger.notice(u"Local action processor exists and seems to be up to date")
				return actionProcessorLocalFile
			
			# Update files
			logger.notice(u"Start copying the action processor files")
			if os.path.exists(actionProcessorLocalTmpDir):
				logger.info(u"Deleting dir '%s'" % actionProcessorLocalTmpDir)
				shutil.rmtree(actionProcessorLocalTmpDir)
			logger.info(u"Copying from '%s' to '%s'" % (actionProcessorRemoteDir, actionProcessorLocalTmpDir))
			shutil.copytree(actionProcessorRemoteDir, actionProcessorLocalTmpDir)
			
			if not os.path.exists(actionProcessorLocalTmpFile):
				raise Exception(u"File '%s' does not exist after copy" % actionProcessorLocalTmpFile)
			
			if os.path.exists(actionProcessorLocalDir):
				logger.info(u"Deleting dir '%s'" % actionProcessorLocalDir)
				shutil.rmtree(actionProcessorLocalDir)
			
			logger.info(u"Moving dir '%s' to '%s'" % (actionProcessorLocalTmpDir, actionProcessorLocalDir))
			shutil.move(actionProcessorLocalTmpDir, actionProcessorLocalDir)
			
			logger.notice(u'Local action processor successfully updated')
			
			if self._configService.isLegacyOpsi():
				self._configService.setProductInstallationStatus(
							'opsi-winst',
							config.get('global', 'host_id'),
							'installed')
			else:
				productVersion = None
				packageVersion = None
				for productOnDepot in self._configService.productOnDepot_getIdents(
							productType = 'LocalbootProduct',
							productId   = 'opsi-winst',
							depotId     = config.get('depot_server', 'depot_id'),
							returnType  = 'dict'):
					productVersion = productOnDepot['productVersion']
					packageVersion = productOnDepot['packageVersion']
				self._configService.productOnClient_updateObjects([
					ProductOnClient(
						productId          = u'opsi-winst',
						productType        = u'LocalbootProduct',
						productVersion     = productVersion,
						packageVersion     = packageVersion,
						clientId           = config.get('global', 'host_id'),
						installationStatus = u'installed',
						actionProgress     = u'',
						actionResult       = u'successful'
					)
				])
			self.setActionProcessorInfo()
			
			if mounted:
				self.umountDepotShare()
			
		except Exception, e:
			logger.error(u"Failed to update action processor: %s" % forceUnicode(e))
		
		if impersonation:
			try:
				impersonation.end()
			except Exception, e:
				logger.warning(e)
	
	def processUserLoginActions(self):
		self.setStatusMessage(_(u"Processing login actions"))
		try:
			if not self._configService:
				raise Exception(u"Not connected to config service")
			
			if self._configService.isLegacyOpsi():
				raise Exception(u"Opsi >= 4.0 needed")
			
			productsByIdAndVersion = {}
			for product in self._configService.product_getObjects(type = 'LocalbootProduct', userLoginScript = "*.ins"):
				if not productsByIdAndVersion.has_key(product.id):
					productsByIdAndVersion[product.id] = {}
				if not productsByIdAndVersion[product.id].has_key(product.productVersion):
					productsByIdAndVersion[product.id][product.productVersion] = {}
				productsByIdAndVersion[product.id][product.productVersion][product.packageVersion] = product
			
			if not productsByIdAndVersion:
				logger.notice(u"No user login script found, nothing to do")
				return
			
			clientToDepotservers = self._configService.configState_getClientToDepotserver(clientIds = config.get('global', 'host_id'))
			if not clientToDepotservers:
				raise Exception(u"Failed to get depotserver for client '%s'" % config.get('global', 'host_id'))
			depotId = clientToDepotservers[0]['depotId']
			
			productDir = os.path.join(config.getDepotDrive(), 'install')
			
			userLoginScripts = []
			for productOnDepot in self._configService.productOnDepot_getIdents(
							productType = 'LocalbootProduct',
							depotId     = depotId,
							returnType  = 'dict'):
				product = productsByIdAndVersion.get(productOnDepot['productId'], {}).get(productOnDepot['productVersion'], {}).get(productOnDepot['packageVersion'])
				if not product:
					continue
				logger.info(u"User login script '%s' found for product %s_%s-%s" \
					% (product.userLoginScript, product.id, product.productVersion, product.packageVersion))
				userLoginScripts.append(os.path.join(productDir, product.userLoginScript))
			
			if not userLoginScripts:
				logger.notice(u"No user login script found, nothing to do")
				return
			
			logger.notice(u"User login scripts found, executing")
			additionalParams = ''
			for userLoginScript in userLoginScripts:
				additionalParams += ' "%s"' % userLoginScript
			self.runActions(additionalParams)
			
		except Exception, e:
			logger.logException(e)
			logger.error(u"Failed to process login actions: %s" % forceUnicode(e))
			self.setStatusMessage( _(u"Failed to process login actions: %s") % forceUnicode(e) )
		
	def processProductActionRequests(self):
		self.setStatusMessage(_(u"Getting action requests from config service"))
		
		try:
			bootmode = ''
			try:
				bootmode = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\general", "bootmode")
			except Exception, e:
				logger.warning(u"Failed to get bootmode from registry: %s" % forceUnicode(e))
			
			if not self._configService:
				raise Exception(u"Not connected to config service")
			
			productIds = []
			if self._configService.isLegacyOpsi():
				productStates = self._configService.getLocalBootProductStates_hash(config.get('global', 'host_id'))
				productStates = productStates.get(config.get('global', 'host_id'), [])
				
				logger.notice(u"Got product action requests from configservice")
				
				for productState in productStates:
					if (productState['actionRequest'] not in ('none', 'undefined')):
						productIds.append(productState['productId'])
						logger.notice("   [%2s] product %-20s %s" % (len(productIds), productState['productId'] + ':', productState['actionRequest']))
			else:
				for productOnClient in self._configService.productOnClient_getObjects(
							productType   = 'LocalbootProduct',
							clientId      = config.get('global', 'host_id'),
							actionRequest = ['setup', 'uninstall', 'update', 'always', 'once', 'custom'],
							attributes    = ['actionRequest']):
					if not productOnClient.productId in productIds:
						productIds.append(productOnClient.productId)
						logger.notice("   [%2s] product %-20s %s" % (len(productIds), productOnClient.productId + u':', productOnClient.actionRequest))
					
			if (len(productIds) == 0) and (bootmode == 'BKSTD'):
				logger.notice(u"No product action requests set")
				self.setStatusMessage( _(u"No product action requests set") )
				try:
					if self.event.eventConfig.useCachedConfig:
						self.opsiclientd.getCacheService().setConfigCacheObsolete()
				except Exception, e:
					logger.error(e)
			else:
				logger.notice(u"Start processing action requests")
				if productIds:
					if self.event.eventConfig.useCachedProducts:
						if self.opsiclientd.getCacheService().productCacheCompleted(self._configService, productIds):
							logger.notice(u"Event '%s' uses cached products and product caching is done" % self.event.eventConfig.getId())
						else:
							raise Exception(u"Event '%s' uses cached products but product caching is not done" % self.event.eventConfig.getId())
					
				config.selectDepotserver(configService = self._configService, event = self.event, productIds = productIds)
				self.processActionWarningTime(productIds)
				self.runActions()
				try:
					if self.event.eventConfig.useCachedConfig and not self._configService.productOnClient_getIdents(
								productType   = 'LocalbootProduct',
								clientId      = config.get('global', 'host_id'),
								actionRequest = ['setup', 'uninstall', 'update', 'always', 'once', 'custom']):
						self.opsiclientd.getCacheService().setConfigCacheObsolete()
				except Exception, e:
					logger.error(e)
				
		except Exception, e:
			logger.logException(e)
			logger.error(u"Failed to process product action requests: %s" % forceUnicode(e))
			self.setStatusMessage( _(u"Failed to process product action requests: %s") % forceUnicode(e) )
			timeline.addEvent(
				title       = u"Failed to process product action requests",
				description = u"Failed to process product action requests: %s" % forceUnicode(e),
				category    = u"error",
				isError     = True)
		time.sleep(3)
	
	def runActions(self, additionalParams=''):
		runActionsEventId = timeline.addEvent(
			title         = u"Running actions",
			description   = u"Running actions",
			category      = u"run_actions",
			durationEvent = True)
		try:
			if not additionalParams:
				additionalParams = ''
			if not self.event.getActionProcessorCommand():
				raise Exception(u"No action processor command defined")
			
			if not self.isLoginEvent:
				# check for Trusted Installer before Running Action Processor
				if (os.name == 'nt') and (sys.getwindowsversion()[0] == 6):
					logger.notice(u"Getting TrustedInstaller service configuration")
					try:
						# Trusted Installer "Start" Key in Registry: 2 = automatic Start: Registry: 3 = manuell Start; Default: 3
						automaticStartup = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SYSTEM\\CurrentControlSet\\services\\TrustedInstaller", "Start", reflection = False)
						if (automaticStartup == 2):
							logger.notice(u"Automatic startup for service Trusted Installer is set, waiting until upgrade process is finished")
							self.setStatusMessage( _(u"Waiting for TrustedInstaller") )
							waitEventId = timeline.addEvent(
									title         = u"Waiting for TrustedInstaller",
									description   = u"Automatic startup for service Trusted Installer is set, waiting until upgrade process is finished",
									category      = u"wait",
									durationEvent = True)
							while True:
								time.sleep(3)
								logger.debug(u"Checking if automatic startup for service Trusted Installer is set")
								automaticStartup = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SYSTEM\\CurrentControlSet\\services\\TrustedInstaller", "Start", reflection = False)
								if not (automaticStartup == 2):
									break
							timeline.setEventEnd(eventId = waitEventId)
					except Exception, e:
						logger.error(u"Failed to read TrustedInstaller service-configuration: %s" % e)
				
			self.setStatusMessage( _(u"Starting actions") )
			
			# Setting some registry values before starting action
			# Mainly for action processor winst
			System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "depoturl",   config.get('depot_server', 'url'))
			System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "depotdrive", config.getDepotDrive())
			System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "configurl",   "<deprecated>")
			System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "configdrive", "<deprecated>")
			System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "utilsurl",    "<deprecated>")
			System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "utilsdrive",  "<deprecated>")
			
			# action processor desktop can be one of current / winlogon / default
			desktop = self.event.eventConfig.actionProcessorDesktop
			
			# Choose desktop for action processor
			if not desktop or desktop.lower() not in ('winlogon', 'default'):
				if self.isLoginEvent:
					desktop = 'default'
				else:
					desktop = self.opsiclientd.getCurrentActiveDesktopName(self.getSessionId())
			
			if not desktop or desktop.lower() not in ('winlogon', 'default'):
				# Default desktop is winlogon
				desktop = 'winlogon'
			
			
			(depotServerUsername, depotServerPassword) = config.getDepotserverCredentials(configService = self._configService)
			
			# Update action processor
			if self.event.eventConfig.updateActionProcessor:
				self.updateActionProcessor()
			
			# Run action processor
			actionProcessorCommand = config.replace(self.event.getActionProcessorCommand())
			actionProcessorCommand = actionProcessorCommand.replace('%service_url%', self._configServiceUrl)
			actionProcessorCommand += additionalParams
			actionProcessorCommand = actionProcessorCommand.replace('"', '\\"')
			command = u'%global.base_dir%\\action_processor_starter.exe ' \
				+ u'"%global.host_id%" "%global.opsi_host_key%" "%control_server.port%" ' \
				+ u'"%global.log_file%" "%global.log_level%" ' \
				+ u'"%depot_server.url%" "' + config.getDepotDrive() + '" ' \
				+ u'"' + depotServerUsername + u'" "' + depotServerPassword + '" ' \
				+ u'"' + unicode(self.getSessionId()) + u'" "' + desktop + '" ' \
				+ u'"' + actionProcessorCommand + u'" ' + unicode(self.event.eventConfig.actionProcessorTimeout) + ' ' \
				+ u'"' + self.opsiclientd._actionProcessorUserName + u'" "' + self.opsiclientd._actionProcessorUserPassword + u'"'
			command = config.replace(command)
			
			if self.event.eventConfig.preActionProcessorCommand:
				impersonation = None
				try:
					if self.opsiclientd._actionProcessorUserName:
						impersonation = System.Impersonate(username = self.opsiclientd._actionProcessorUserName, password = self.opsiclientd._actionProcessorUserPassword)
						impersonation.start(logonType = 'INTERACTIVE', newDesktop = True)
						
					logger.notice(u"Starting pre action processor command '%s' in session '%s' on desktop '%s'" \
						% (self.event.eventConfig.preActionProcessorCommand, self.getSessionId(), desktop))
					if impersonation:
						impersonation.runCommand(command = self.event.eventConfig.preActionProcessorCommand, desktop = desktop, waitForProcessEnding = False)
					else:
						self.runCommandInSession(command = self.event.eventConfig.preActionProcessorCommand, desktop = desktop, waitForProcessEnding = False)
					time.sleep(10)
				finally:
					if impersonation:
						impersonation.end()
					
			logger.notice(u"Starting action processor in session '%s' on desktop '%s'" % (self.getSessionId(), desktop))
			self.runCommandInSession(command = command, desktop = desktop, waitForProcessEnding = True)
			
			if self.event.eventConfig.postActionProcessorCommand:
				impersonation = None
				try:
					if self.opsiclientd._actionProcessorUserName:
						impersonation = System.Impersonate(username = self.opsiclientd._actionProcessorUserName, password = self.opsiclientd._actionProcessorUserPassword)
						impersonation.start(logonType = 'INTERACTIVE', newDesktop = True)
						
					logger.notice(u"Starting post action processor command '%s' in session '%s' on desktop '%s'" \
						% (self.event.eventConfig.postActionProcessorCommand, self.getSessionId(), desktop))
					if impersonation:
						impersonation.runCommand(command = self.event.eventConfig.postActionProcessorCommand, desktop = desktop, waitForProcessEnding = False)
					else:
						self.runCommandInSession(command = self.event.eventConfig.postActionProcessorCommand, desktop = desktop, waitForProcessEnding = False)
					time.sleep(10)
				finally:
					if impersonation:
						impersonation.end()
			self.setStatusMessage( _(u"Actions completed") )
		finally:
			timeline.setEventEnd(eventId = runActionsEventId)
		
	def setEnvironment(self):
		try:
			logger.debug(u"Current environment:")
			for (k, v) in os.environ.items():
				logger.debug(u"   %s=%s" % (k,v))
			logger.debug(u"Updating environment")
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
			logger.debug(u"Updated environment:")
			for (k, v) in os.environ.items():
				logger.debug(u"   %s=%s" % (k,v))
		except Exception, e:
			logger.error(u"Failed to set environment: %s" % forceUnicode(e))
	
	def abortEventCallback(self, choiceSubject):
		logger.notice(u"Event aborted by user")
		self.eventCancelled = True
	
	def startEventCallback(self, choiceSubject):
		logger.notice(u"Event wait cancelled by user")
		self.waitCancelled = True
	
	def processActionWarningTime(self, productIds=[]):
		if not self.event.eventConfig.actionWarningTime:
			return
		cancelCounter = state.get('action_processing_cancel_counter', 0)
		waitEventId = timeline.addEvent(
				title         = u"Action warning",
				description   = u'Notifying user of actions to process %s (%s)\n' % (self.event.eventConfig.getId(), u', '.join(productIds)) \
						+ u"actionWarningTime: %s, actionUserCancelable: %s, cancelCounter: %s" % (self.event.eventConfig.actionWarningTime, self.event.eventConfig.actionUserCancelable, cancelCounter),
				category      = u"wait",
				durationEvent = True)
		self._messageSubject.setMessage(u"%s\n%s: %s" % (self.event.eventConfig.getActionMessage(), _(u'Products'), u', '.join(productIds)) )
		choiceSubject = ChoiceSubject(id = 'choice')
		if (cancelCounter < self.event.eventConfig.actionUserCancelable):
			choiceSubject.setChoices([ _('Abort'), _('Start now') ])
			choiceSubject.setCallbacks( [ self.abortEventCallback, self.startEventCallback ] )
		else:
			choiceSubject.setChoices([ _('Start now') ])
			choiceSubject.setCallbacks( [ self.startEventCallback ] )
		self._notificationServer.addSubject(choiceSubject)
		try:
			if self.event.eventConfig.actionNotifierCommand:
				self.startNotifierApplication(
						command    = self.event.eventConfig.actionNotifierCommand,
						desktop    = self.event.eventConfig.actionNotifierDesktop,
						notifierId = 'action')
				
			timeout = int(self.event.eventConfig.actionWarningTime)
			endTime = time.time() + timeout
			while (timeout > 0) and not self.eventCancelled and not self.waitCancelled:
				now = time.time()
				logger.info(u"Notifying user of actions to process %s (%s)" % (self.event, productIds))
				minutes = 0
				seconds = (endTime - now)
				if (seconds >= 60):
					minutes = int(seconds/60)
					seconds -= minutes*60
				seconds = int(seconds)
				if (minutes < 10):
					minutes = '0%d' % minutes
				if (seconds < 10):
					seconds = '0%d' % seconds
				self.setStatusMessage(_(u"Event %s: action processing will start in %s:%s") % (self.event.eventConfig.getName(), minutes, seconds))
				if ((endTime - now) <= 0):
					break
				time.sleep(1)
			
			if self.waitCancelled:
				timeline.addEvent(
					title       = u"Action processing started by user",
					description = u"Action processing wait time cancelled by user",
					category    = u"user_interaction")
			
			if self.eventCancelled:
				cancelCounter += 1
				state.set('action_processing_cancel_counter', cancelCounter)
				logger.notice(u"Action processing cancelled by user for the %d. time (max: %d)" \
					% (cancelCounter, self.event.eventConfig.actionUserCancelable))
				timeline.addEvent(
					title       = u"Action processing cancelled by user",
					description = u"Action processing cancelled by user for the %d. time (max: %d)" \
							% (cancelCounter, self.event.eventConfig.actionUserCancelable),
					category    = u"user_interaction")
				raise CanceledByUserError(u"Action processing cancelled by user")
			else:
				state.set('action_processing_cancel_counter', 0)
		finally:
			timeline.setEventEnd(waitEventId)
			try:
				if self._notificationServer:
					self._notificationServer.requestEndConnections(['action'])
					self._notificationServer.removeSubject(choiceSubject)
			except Exception, e:
				logger.logException(e)
	
	def abortShutdownCallback(self, choiceSubject):
		logger.notice(u"Shutdown aborted by user")
		self.shutdownCancelled = True
	
	def startShutdownCallback(self, choiceSubject):
		logger.notice(u"Shutdown wait cancelled by user")
		self.shutdownWaitCancelled = True
	
	def isRebootRequested(self):
		if self.event.eventConfig.reboot:
			return True
		if self.event.eventConfig.processShutdownRequests and self.opsiclientd.isRebootRequested():
			return True
		return False
		
	def isShutdownRequested(self):
		if self.event.eventConfig.shutdown:
			return True
		if self.event.eventConfig.processShutdownRequests and self.opsiclientd.isShutdownRequested():
			return True
		return False
		
	def processShutdownRequests(self):
		try:
			
			shutdown = self.isShutdownRequested()
			reboot   = self.isRebootRequested()
			if reboot or shutdown:
				if reboot:
					timeline.addEvent(title = u"Reboot requested", category = u"system")
					self.setStatusMessage(_(u"Reboot requested"))
				else:
					timeline.addEvent(title = u"Shutdown requested", category = u"system")
					self.setStatusMessage(_(u"Shutdown requested"))
				
				if self.event.eventConfig.shutdownWarningTime:
					if self._notificationServer:
						self._notificationServer.requestEndConnections()
					while True:
						shutdownCancelCounter = state.get('shutdown_cancel_counter', 0)
						waitEventId = None
						if reboot:
							logger.info(u"Notifying user of reboot")
							waitEventId = timeline.addEvent(
								title         = u"Reboot warning",
								description   = u'Notifying user of reboot\n' \
										+ u"shutdownWarningTime: %s, shutdownUserCancelable: %s, shutdownCancelCounter: %s" \
										% (self.event.eventConfig.shutdownWarningTime, self.event.eventConfig.shutdownUserCancelable, shutdownCancelCounter),
								category      = u"wait",
								durationEvent = True)
						else:
							logger.info(u"Notifying user of shutdown")
							waitEventId = timeline.addEvent(
								title         = u"Shutdown warning",
								description   = u'Notifying user of shutdown\n' \
										+ u"shutdownWarningTime: %s, shutdownUserCancelable: %s, shutdownCancelCounter: %s" \
										% (self.event.eventConfig.shutdownWarningTime, self.event.eventConfig.shutdownUserCancelable, shutdownCancelCounter),
								category      = u"wait",
								durationEvent = True)
						
						self.shutdownCancelled = False
						self.shutdownWaitCancelled = False
						
						self._messageSubject.setMessage(self.event.eventConfig.getShutdownWarningMessage())
						
						choiceSubject = ChoiceSubject(id = 'choice')
						if (shutdownCancelCounter < self.event.eventConfig.shutdownUserCancelable):
							if reboot:
								choiceSubject.setChoices([ _('Reboot now'), _('Later') ])
							else:
								choiceSubject.setChoices([ _('Shutdown now'), _('Later') ])
							choiceSubject.setCallbacks( [ self.startShutdownCallback, self.abortShutdownCallback ] )
						else:
							if reboot:
								choiceSubject.setChoices([ _('Reboot now') ])
							else:
								choiceSubject.setChoices([ _('Shutdown now') ])
							choiceSubject.setCallbacks( [ self.startShutdownCallback ] )
						self._notificationServer.addSubject(choiceSubject)
						
						if self.event.eventConfig.shutdownNotifierCommand:
							self.startNotifierApplication(
									command    = self.event.eventConfig.shutdownNotifierCommand,
									desktop    = self.event.eventConfig.shutdownNotifierDesktop,
									notifierId = 'shutdown')
								
						timeout = int(self.event.eventConfig.shutdownWarningTime)
						endTime = time.time() + timeout
						while (timeout > 0) and not self.shutdownCancelled and not self.shutdownWaitCancelled:
							now = time.time()
							minutes = 0
							seconds = (endTime - now)
							if (seconds >= 60):
								minutes = int(seconds/60)
								seconds -= minutes*60
							seconds = int(seconds)
							if (minutes < 10):
								minutes = '0%d' % minutes
							if (seconds < 10):
								seconds = '0%d' % seconds
							if reboot:
								self.setStatusMessage(_(u"Reboot in %s:%s") % (minutes, seconds))
							else:
								self.setStatusMessage(_(u"Shutdown in %s:%s") % (minutes, seconds))
							if ((endTime - now) <= 0):
								break
							time.sleep(1)
						
						try:
							if self._notificationServer:
								self._notificationServer.requestEndConnections()
								self._notificationServer.removeSubject(choiceSubject)
						except Exception, e:
							logger.logException(e)
						
						self._messageSubject.setMessage(u"")
						
						timeline.setEventEnd(waitEventId)
						
						if self.shutdownWaitCancelled:
							if reboot:
								timeline.addEvent(
									title       = u"Reboot started by user",
									description = u"Reboot wait time cancelled by user",
									category    = u"user_interaction")
							else:
								timeline.addEvent(
									title       = u"Shutdown started by user",
									description = u"Shutdown wait time cancelled by user",
									category    = u"user_interaction")
						
						if self.shutdownCancelled:
							self.opsiclientd.setBlockLogin(False)
							shutdownCancelCounter += 1
							state.set('shutdown_cancel_counter', shutdownCancelCounter)
							logger.notice(u"Shutdown cancelled by user for the %d. time (max: %d)" \
								% (shutdownCancelCounter, self.event.eventConfig.shutdownUserCancelable))
							if reboot:
								timeline.addEvent(
									title       = u"Reboot cancelled by user",
									description = u"Reboot cancelled by user for the %d. time (max: %d)" \
											% (shutdownCancelCounter, self.event.eventConfig.shutdownUserCancelable),
									category    = u"user_interaction")
							else:
								timeline.addEvent(
									title       = u"Shutdown cancelled by user",
									description = u"Shutdown cancelled by user for the %d. time (max: %d)" \
											% (shutdownCancelCounter, self.event.eventConfig.shutdownUserCancelable),
									category    = u"user_interaction")
							if (self.event.eventConfig.shutdownWarningRepetitionTime >= 0):
								logger.info(u"Shutdown warning will be repeated in %d seconds" % self.event.eventConfig.shutdownWarningRepetitionTime)
								time.sleep(self.event.eventConfig.shutdownWarningRepetitionTime)
								continue
						break
				if reboot:
					timeline.addEvent(title = u"Rebooting", category = u"system")
					self.opsiclientd.rebootMachine()
				elif shutdown:
					timeline.addEvent(title = u"Shutting down", category = u"system")
					self.opsiclientd.shutdownMachine()
		except Exception, e:
			logger.logException(e)
		
	def run(self):
		timelineEventId = None
		try:
			logger.notice(u"============= EventProcessingThread for occurrcence of event '%s' started =============" % self.event.eventConfig.getId())
			timelineEventId = timeline.addEvent(
				title         = u"Processing event %s" % self.event.eventConfig.getName(),
				description   = u"EventProcessingThread for occurrcence of event '%s' started" % self.event.eventConfig.getId(),
				category      = u"event_processing",
				durationEvent = True)
			self.running = True
			self.eventCancelled = False
			self.waitCancelled = False
			if not self.event.eventConfig.blockLogin:
				self.opsiclientd.setBlockLogin(False)
			
			try:
				config.setTemporaryDepotDrive(None)
				config.setTemporaryConfigServiceUrls([])
				
				self.startNotificationServer()
				self.setActionProcessorInfo()
				self._messageSubject.setMessage(self.event.eventConfig.getActionMessage())
				
				self.setStatusMessage(_(u"Processing event %s") % self.event.eventConfig.getName())
				
				if self.event.eventConfig.blockLogin:
					self.opsiclientd.setBlockLogin(True)
				else:
					self.opsiclientd.setBlockLogin(False)
				if self.event.eventConfig.logoffCurrentUser:
					System.logoffCurrentUser()
					time.sleep(15)
				elif self.event.eventConfig.lockWorkstation:
					System.lockWorkstation()
					time.sleep(15)
				
				if self.event.eventConfig.eventNotifierCommand:
					self.startNotifierApplication(
						command    = self.event.eventConfig.eventNotifierCommand,
						desktop    = self.event.eventConfig.eventNotifierDesktop,
						notifierId = 'event')
				
				if self.event.eventConfig.syncConfigToServer:
					self.setStatusMessage( _(u"Syncing config to server") )
					self.opsiclientd.getCacheService().syncConfigToServer(waitForEnding = True)
					self.setStatusMessage( _(u"Sync completed") )
				
				if self.event.eventConfig.syncConfigFromServer:
					self.setStatusMessage( _(u"Syncing config from server") )
					waitForEnding = self.event.eventConfig.useCachedConfig
					self.opsiclientd.getCacheService().syncConfigFromServer(waitForEnding = waitForEnding)
					if waitForEnding:
						self.setStatusMessage( _(u"Sync completed") )
				
				if self.event.eventConfig.cacheProducts:
					self.setStatusMessage( _(u"Caching products") )
					try:
						self._currentProgressSubjectProxy.attachObserver(self._detailSubjectProxy)
						waitForEnding = self.event.eventConfig.useCachedProducts
						self.opsiclientd.getCacheService().cacheProducts(
							waitForEnding           = waitForEnding,
							productProgressObserver = self._currentProgressSubjectProxy,
							overallProgressObserver = self._overallProgressSubjectProxy,
							dynamicBandwidth        = self.event.eventConfig.cacheDynamicBandwidth,
							maxBandwidth            = self.event.eventConfig.cacheMaxBandwidth
						)
						if waitForEnding:
							self.setStatusMessage( _(u"Products cached") )
					finally:
						self._detailSubjectProxy.setMessage(u"")
						try:
							self._currentProgressSubjectProxy.detachObserver(self._detailSubjectProxy)
							self._currentProgressSubjectProxy.reset()
							self._overallProgressSubjectProxy.reset()
						except Exception, e:
							logger.logException(e)
				
				if self.event.eventConfig.useCachedConfig:
					if self.opsiclientd.getCacheService().configCacheCompleted():
						logger.notice(u"Event '%s' uses cached config and config caching is done" % self.event.eventConfig.getId())
						config.setTemporaryConfigServiceUrls(['https://localhost:4441/rpc'])
					else:
						raise Exception(u"Event '%s' uses cached config but config caching is not done" % self.event.eventConfig.getId())
				
				if self.event.eventConfig.getConfigFromService or self.event.eventConfig.processActions:
					if not self.isConfigServiceConnected():
						self.connectConfigService()
					
					if self.event.eventConfig.getConfigFromService:
						self.getConfigFromService()
						if self.event.eventConfig.updateConfigFile:
							config.updateConfigFile()
					
					if self.event.eventConfig.processActions:
						if (self.event.eventConfig.actionType == 'login'):
							self.processUserLoginActions()
						else:
							self.processProductActionRequests()
					
			finally:
				self._messageSubject.setMessage(u"")
				if self.event.eventConfig.writeLogToService:
					try:
						self.writeLogToService()
					except Exception, e:
						logger.logException(e)
				
				try:
					self.disconnectConfigService()
				except Exception, e:
					logger.logException(e)
				
				config.setTemporaryConfigServiceUrls([])
				
				if self.event.eventConfig.postSyncConfigToServer:
					self.setStatusMessage( _(u"Syncing config to server") )
					self.opsiclientd.getCacheService().syncConfigToServer(waitForEnding = True)
					self.setStatusMessage( _(u"Sync completed") )
				if self.event.eventConfig.postSyncConfigFromServer:
					self.setStatusMessage( _(u"Syncing config from server") )
					self.opsiclientd.getCacheService().syncConfigFromServer(waitForEnding = self.isShutdownRequested() or self.isRebootRequested())
					self.setStatusMessage( _(u"Sync completed") )
				
				self.processShutdownRequests()
				
				if self.opsiclientd.isShutdownTriggered():
					self.setStatusMessage(_("Shutting down machine"))
				elif self.opsiclientd.isRebootTriggered():
					self.setStatusMessage(_("Rebooting machine"))
				else:
					self.setStatusMessage(_("Unblocking login"))
				
				if not self.opsiclientd.isRebootTriggered() and not self.opsiclientd.isShutdownTriggered():
					self.opsiclientd.setBlockLogin(False)
				
				self.setStatusMessage(u"")
				self.stopNotificationServer()
		except Exception, e:
			logger.error(u"Failed to process event %s: %s" % (self.event, forceUnicode(e)))
			logger.logException(e)
			timeline.addEvent(
				title       = u"Failed to process event %s" % self.event.eventConfig.getName(),
				description = u"Failed to process event %s: %s" % (self.event, forceUnicode(e)),
				category    = u"event_processing",
				isError     = True)
			self.opsiclientd.setBlockLogin(False)
		
		self.running = False
		logger.notice(u"============= EventProcessingThread for event '%s' ended =============" % self.event.eventConfig.getId())
		if timelineEventId:
			timeline.setEventEnd(eventId = timelineEventId)
	
	




