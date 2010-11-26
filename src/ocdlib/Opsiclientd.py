# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = = = =
   =   ocdlib.Opsiclientd                  =
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

__version__ = '4.0.22'

# Imports
import sys, os, shutil, filecmp, base64
from hashlib import md5

# Twisted imports
from twisted.internet import reactor
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
from ocdlib.ControlPipe import ControlPipeFactory, OpsiclientdRpcPipeInterface
from ocdlib.ControlServer import ControlServer
from ocdlib.CacheService import CacheService
from ocdlib.OpsiService import ServiceConnectionThread
if (os.name == 'nt'):
	from ocdlib.Windows import *
if (os.name == 'posix'):
	from ocdlib.Posix import *
from ocdlib.Localization import _, setLocaleDir, getLanguage
from ocdlib.Config import Config

logger = Logger()
config = Config()

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                            OPSICLIENTD                                            -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class Opsiclientd(EventListener, threading.Thread):
	def __init__(self):
		moduleName = u' %-30s' % (u'opsiclientd')
		logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)
		logger.debug(u"Opsiclient initiating")
		
		EventListener.__init__(self)
		threading.Thread.__init__(self)
		
		self._startupTime = time.time()
		self._running = False
		self._eventProcessingThreads = []
		self._eventProcessingThreadsLock = threading.Lock()
		self._blockLogin = True
		self._currentActiveDesktopName = {}
		
		self._isRebootTriggered = False
		self._isShutdownTriggered = False
		
		self._actionProcessorUserName = u''
		self._actionProcessorUserPassword = u''
		
		self._statusApplicationProcess = None
		self._blockLoginNotifierPid = None
		
		self._popupNotificationServer = None
		self._popupNotificationLock = threading.Lock()
		
	
	def setBlockLogin(self, blockLogin):
		self._blockLogin = bool(blockLogin)
		logger.notice(u"Block login now set to '%s'" % self._blockLogin)
		
		if (self._blockLogin):
			if not self._blockLoginNotifierPid and config.get('global', 'block_login_notifier'):
				logger.info(u"Starting block login notifier app")
				sessionId = System.getActiveConsoleSessionId()
				while True:
					try:
						self._blockLoginNotifierPid = System.runCommandInSession(
								command = config.get('global', 'block_login_notifier'),
								sessionId = sessionId,
								desktop = 'winlogon',
								waitForProcessEnding = False)[2]
						break
					except Exception, e:
						logger.error(e)
						if (e[0] == 233) and (sys.getwindowsversion()[0] == 5) and (sessionId != 0):
							# No process is on the other end
							# Problem with pipe \\\\.\\Pipe\\TerminalServer\\SystemExecSrvr\\<sessionid>
							# After logging off from a session other than 0 csrss.exe does not create this pipe or CreateRemoteProcessW is not able to read the pipe.
							logger.info(u"Retrying to run command in session 0")
							sessionId = 0
						else:
							logger.error(u"Failed to start block login notifier app: %s" % forceUnicode(e))
							break
		elif (self._blockLoginNotifierPid):
			try:
				logger.info(u"Terminating block login notifier app (pid %s)" % self._blockLoginNotifierPid)
				System.terminateProcess(processId = self._blockLoginNotifierPid)
			except Exception, e:
				logger.warning(u"Failed to terminate block login notifier app: %s" % forceUnicode(e))
			self._blockLoginNotifierPid = None
		
	def isRunning(self):
		return self._running
	
	def waitForGUI(self, timeout=None):
		if not timeout:
			timeout = None
		class WaitForGUI(EventListener):
			def __init__(self):
				self._guiStarted = threading.Event()
				eventGenerator = EventGeneratorFactory(GUIStartupEventConfig("wait_for_gui"))
				eventGenerator.addEventListener(self)
				eventGenerator.start()
			
			def processEvent(self, event):
				logger.info(u"GUI started")
				self._guiStarted.set()
				
			def wait(self, timeout=None):
				self._guiStarted.wait(timeout)
				if not self._guiStarted.isSet():
					logger.warning(u"Timed out after %d seconds while waiting for GUI" % timeout)
				
		WaitForGUI().wait(timeout)
	
	def createActionProcessorUser(self, recreate = True):
		if not config.get('action_processor', 'create_user'):
			return
		
		runAsUser = config.get('action_processor', 'run_as_user')
		if (runAsUser.lower() == 'system'):
			self._actionProcessorUserName = u''
			self._actionProcessorUserPassword = u''
			return
		
		if (runAsUser.find('\\') != -1):
			logger.warning(u"Ignoring domain part of user to run action processor '%s'" % runAsUser)
			runAsUser = runAsUser.split('\\', -1)
		
		if not recreate and self._actionProcessorUserName and self._actionProcessorUserPassword and System.existsUser(username = runAsUser):
			return
		
		self._actionProcessorUserName = runAsUser
		logger.notice(u"Creating local user '%s'" % runAsUser)
		
		self._actionProcessorUserPassword = u'$!?' + unicode(randomString(16)) + u'!/%'
		logger.addConfidentialString(self._actionProcessorUserPassword)
		
		if System.existsUser(username = runAsUser):
			System.deleteUser(username = runAsUser)
		System.createUser(username = runAsUser, password = self._actionProcessorUserPassword, groups = [ System.getAdminGroupName() ])
	
	def deleteActionProcessorUser(self):
		if not config.get('action_processor', 'delete_user'):
			return
		if not self._actionProcessorUserName:
			return
		logger.notice(u"Deleting local user '%s'" % self._actionProcessorUserName)
		if not System.existsUser(username = self._actionProcessorUserName):
			return
		System.deleteUser(username = self._actionProcessorUserName)
		self._actionProcessorUserName = u''
		self._actionProcessorUserPassword = u''
	
	def run(self):
		self._running = True
		self._stopped = False
		
		config.readConfigFile()
		setLocaleDir(config.get('global', 'locale_dir'))
		
		try:
			logger.comment(u"Opsiclientd version: %s" % __version__)
			logger.comment(u"Commandline: %s" % ' '.join(sys.argv))
			logger.comment(u"Working directory: %s" % os.getcwd())
			logger.notice(u"Using host id '%s'" % config.get('global', 'host_id'))
			
			self.setBlockLogin(True)
			
			logger.notice(u"Starting control pipe")
			try:
				self._controlPipe = ControlPipeFactory(OpsiclientdRpcPipeInterface(self))
				self._controlPipe.start()
				logger.notice(u"Control pipe started")
			except Exception, e:
				logger.error(u"Failed to start control pipe: %s" % forceUnicode(e))
				raise
			
			logger.notice(u"Starting control server")
			try:
				self._controlServer = ControlServer(
								opsiclientd        = self,
								httpsPort          = config.get('control_server', 'port'),
								sslServerKeyFile   = config.get('control_server', 'ssl_server_key_file'),
								sslServerCertFile  = config.get('control_server', 'ssl_server_cert_file'),
								staticDir          = config.get('control_server', 'static_dir') )
				self._controlServer.start()
				logger.notice(u"Control server started")
			except Exception, e:
				logger.error(u"Failed to start control server: %s" % forceUnicode(e))
				raise
			
			logger.notice(u"Starting cache service")
			try:
				self._cacheService = CacheService(opsiclientd = self)
				self._cacheService.start()
				logger.notice(u"Cache service started")
			except Exception, e:
				logger.error(u"Failed to start cache service: %s" % forceUnicode(e))
				raise
			
			# Create event generators
			createEventGenerators()
			
			for eventGenerator in getEventGenerators():
				eventGenerator.addEventListener(self)
				eventGenerator.start()
				logger.notice(u"Event generator '%s' started" % eventGenerator)
			
			for eventGenerator in getEventGenerators(generatorClass = DaemonStartupEventGenerator):
				eventGenerator.fireEvent()
			
			if getEventGenerators(generatorClass = GUIStartupEventGenerator):
				# Wait until gui starts up
				logger.notice(u"Waiting for gui startup (timeout: %d seconds)" % config.get('global', 'wait_for_gui_timeout'))
				self.waitForGUI(timeout = config.get('global', 'wait_for_gui_timeout'))
				logger.notice(u"Done waiting for GUI")
				
				# Wait some more seconds for events to fire
				time.sleep(5)
			
			if not self._eventProcessingThreads:
				logger.notice(u"No events processing, unblocking login")
				self.setBlockLogin(False)
			
			while not self._stopped:
				time.sleep(1)
			
			for eventGenerator in getEventGenerators(generatorClass = DaemonShutdownEventGenerator):
				eventGenerator.fireEvent()
			
			logger.notice(u"opsiclientd is going down")
			
			for eventGenerator in getEventGenerators():
				logger.info(u"Stopping event generator %s" % eventGenerator)
				eventGenerator.stop()
				eventGenerator.join(2)
			
			for ept in self._eventProcessingThreads:
				logger.info(u"Waiting for event processing thread %s" % ept)
				ept.join(5)
			
			logger.info(u"Stopping cache service")
			if self._cacheService:
				self._cacheService.stop()
				self._cacheService.join(2)
			
			logger.info(u"Stopping control server")
			if self._controlServer:
				self._controlServer.stop()
				self._controlServer.join(2)
			
			logger.info(u"Stopping control pipe")
			if self._controlPipe:
				self._controlPipe.stop()
				self._controlPipe.join(2)
			
			if reactor and reactor.running:
				logger.info(u"Stopping reactor")
				reactor.stop()
				while reactor.running:
					logger.debug(u"Waiting for reactor to stop")
					time.sleep(1)
			
			logger.info(u"Exiting main thread")
			
		except Exception, e:
			logger.logException(e)
			self.setBlockLogin(False)
		
		self._running = False
	
	def stop(self):
		self._stopped = True
	
	def processEvent(self, event):
		
		logger.notice(u"Processing event %s" % event)
		
		eventProcessingThread = None
		self._eventProcessingThreadsLock.acquire()
		try:
			eventProcessingThread = EventProcessingThread(self, event)
			
			# Always process panic events
			if not isinstance(event, PanicEvent):
				for ept in self._eventProcessingThreads:
					if (event.eventConfig.actionType != 'login') and (ept.event.eventConfig.actionType != 'login'):
						raise Exception(u"Already processing an other (non login) event: %s" % ept.event.eventConfig.getName())
					if (event.eventConfig.actionType == 'login') and (ept.event.eventConfig.actionType == 'login'):
						if (ept.getSessionId() == eventProcessingThread.getSessionId()):
							raise Exception(u"Already processing login event '%s' in session %s" \
										% (ept.event.eventConfig.getName(), eventProcessingThread.getSessionId()))
		
		except Exception, e:
			self._eventProcessingThreadsLock.release()
			raise
		
		self.createActionProcessorUser(recreate = False)
		
		self._eventProcessingThreads.append(eventProcessingThread)
		self._eventProcessingThreadsLock.release()
		
		try:
			eventProcessingThread.start()
			eventProcessingThread.join()
			logger.notice(u"Done processing event '%s'" % event)
		finally:
			self._eventProcessingThreadsLock.acquire()
			self._eventProcessingThreads.remove(eventProcessingThread)
			try:
				if not self._eventProcessingThreads:
					self.deleteActionProcessorUser()
			except Exception, e:
				logger.warning(e)
			self._eventProcessingThreadsLock.release()
		
	def getEventProcessingThread(self, sessionId):
		for ept in self._eventProcessingThreads:
			if (int(ept.getSessionId()) == int(sessionId)):
				return ept
		raise Exception(u"Event processing thread for session %s not found" % sessionId)
		
	def processProductActionRequests(self, event):
		logger.error(u"processProductActionRequests not implemented")
	
	def getCurrentActiveDesktopName(self, sessionId=None):
		if not (config.getDict().has_key('opsiclientd_rpc') and config.getDict()['opsiclientd_rpc'].has_key('command')):
			raise Exception(u"opsiclientd_rpc command not defined")
		
		if sessionId is None:
			sessionId = System.getActiveConsoleSessionId()
		rpc = 'setCurrentActiveDesktopName("%s", System.getActiveDesktopName())' % sessionId
		cmd = '%s "%s"' % (config.get('opsiclientd_rpc', 'command'), rpc)
		
		try:
			System.runCommandInSession(command = cmd, sessionId = sessionId, desktop = u"winlogon", waitForProcessEnding = True, timeoutSeconds = 60)
		except Exception, e:
			logger.error(e)
		
		desktop = self._currentActiveDesktopName.get(sessionId)
		if not desktop:
			logger.warning(u"Failed to get current active desktop name for session %d, using 'default'" % sessionId)
			desktop = 'default'
			self._currentActiveDesktopName[sessionId] = desktop
		logger.debug(u"Returning current active dektop name '%s' for session %s" % (desktop, sessionId))
		return desktop
	
	def systemShutdownInitiated(self):
		if not self.isRebootTriggered() and not self.isShutdownTriggered():
			# This shutdown was triggered by someone else
			# Reset shutdown/reboot requests to avoid reboot/shutdown on next boot
			logger.notice(u"Someone triggered a reboot or a shutdown => clearing reboot request")
			self.clearRebootRequest()
	
	def shutdownMachine(self):
		pass
		
	def rebootMachine(self):
		pass
	
	def isRebootTriggered(self):
		if self._isRebootTriggered:
			return True
		return False
		
	def isShutdownTriggered(self):
		if self._isShutdownTriggered:
			return True
		return False
	
	def clearRebootRequest(self):
		pass
		
	def clearShutdownRequest(self):
		pass
		
	def isRebootRequested(self):
		return False
		
	def isShutdownRequested(self):
		return False
	
	def showPopup(self, message):
		port = config.get('notification_server', 'popup_port')
		if not port:
			raise Exception(u'notification_server.popup_port not defined')
		
		notifierCommand = config.get('opsiclientd_notifier', 'command').replace('%port%', forceUnicode(port))
		if not notifierCommand:
			raise Exception(u'opsiclientd_notifier.command not defined')
		notifierCommand += u" -s notifier\\popup.ini"
		
		self._popupNotificationLock.acquire()
		try:
			self.hidePopup()
			
			popupSubject = MessageSubject('message')
			choiceSubject = ChoiceSubject(id = 'choice')
			popupSubject.setMessage(message)
			
			logger.notice(u"Starting popup message notification server on port %d" % port)
			try:
				self._popupNotificationServer = NotificationServer(
								address  = "127.0.0.1",
								port     = port,
								subjects = [ popupSubject, choiceSubject ] )
				self._popupNotificationServer.start()
			except Exception, e:
				logger.error(u"Failed to start notification server: %s" % forceUnicode(e))
				raise
			
			choiceSubject.setChoices([ _('Close') ])
			choiceSubject.setCallbacks( [ self.popupCloseCallback ] )
			
			sessionIds = System.getActiveSessionIds()
			if not sessionIds:
				sessionIds = [ System.getActiveConsoleSessionId() ]
			for sessionId in sessionIds:
				logger.info(u"Starting popup message notifier app in session %d" % sessionId)
				try:
					System.runCommandInSession(
						command = notifierCommand,
						sessionId = sessionId,
						desktop = self.getCurrentActiveDesktopName(sessionId),
						waitForProcessEnding = False)
				except Exception,e:
					logger.error(u"Failed to start popup message notifier app in session %d: %s" % (sessionId, forceUnicode(e)))
		finally:
			self._popupNotificationLock.release()
		
	def hidePopup(self):
		if self._popupNotificationServer:
			try:
				logger.info(u"Stopping popup message notification server")
				self._popupNotificationServer.stop(stopReactor = False)
			except Exception, e:
				logger.error(u"Failed to stop popup notification server: %s" % e)
		
	def popupCloseCallback(self, choiceSubject):
		self.hidePopup()


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                      EVENT PROCESSING THREAD                                      -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class EventProcessingThread(KillableThread):
	def __init__(self, opsiclientd, event):
		moduleName = u' %-30s' % (u'event processing ' + event.eventConfig.getName())
		logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)
		KillableThread.__init__(self)
		
		self.opsiclientd = opsiclientd
		self.event = event
		
		self.running = False
		self.eventCancelled = False
		self.waitCancelled = False
		
		self.shutdownCancelled = False
		self.shutdownWaitCancelled = False
		
		self._sessionId = None
		
		self._configService = None
		self._configServiceUrl = None
		
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
		
		self._notificationServerPort = int(config.get('notification_server', 'start_port')) + int(self.getSessionId())
		
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
			logger.notice(u"Notification server started")
		except Exception, e:
			logger.error(u"Failed to start notification server: %s" % forceUnicode(e))
			raise
		
	def connectConfigServer(self):
		if self._configService:
			# Already connected
			return
		
		try:
			self._configServiceUrl = None
			for urlIndex in range(len(config.get('config_service', 'url'))):
				url = config.get('config_service', 'url')[urlIndex]
				self._serviceUrlSubject.setMessage(url)
				
				choiceSubject = ChoiceSubject(id = 'choice')
				choiceSubject.setChoices([ 'Stop connection' ])
				
				logger.debug(u"Creating ServiceConnectionThread")
				serviceConnectionThread = ServiceConnectionThread(
							configServiceUrl    = url,
							username            = config.get('global', 'host_id'),
							password            = config.get('global', 'opsi_host_key'),
							statusObject        = self._statusSubject )
				
				choiceSubject.setCallbacks( [ serviceConnectionThread.stopConnectionCallback ] )
				
				cancellableAfter = forceInt(config.get('config_service', 'user_cancelable_after'))
				logger.info(u"User is allowed to cancel connection after %d seconds" % cancellableAfter)
				if (cancellableAfter < 1):
					self._notificationServer.addSubject(choiceSubject)
				
				timeout = forceInt(config.get('config_service', 'connection_timeout'))
				logger.info(u"Starting ServiceConnectionThread, timeout is %d seconds" % timeout)
				serviceConnectionThread.start()
				time.sleep(1)
				logger.debug(u"ServiceConnectionThread started")
				
				while serviceConnectionThread.running and (timeout > 0):
					logger.debug(u"Waiting for ServiceConnectionThread (timeout: %d, alive: %s, cancellable in: %d) " \
						% (timeout, serviceConnectionThread.isAlive(), cancellableAfter))
					self._detailSubjectProxy.setMessage( _(u'Timeout: %ds') % timeout )
					cancellableAfter -= 1
					if (cancellableAfter == 0):
						self._notificationServer.addSubject(choiceSubject)
					time.sleep(1)
					timeout -= 1
				
				self._detailSubjectProxy.setMessage(u'')
				self._notificationServer.removeSubject(choiceSubject)
				
				if serviceConnectionThread.cancelled:
					logger.error(u"ServiceConnectionThread canceled by user")
					raise CanceledByUserError(u"Failed to connect to config service '%s': cancelled by user" % url)
				
				try:
					if serviceConnectionThread.running:
						logger.error(u"ServiceConnectionThread timed out after %d seconds" % config.get('config_service', 'connection_timeout'))
						serviceConnectionThread.stop()
						raise Exception(u"Failed to connect to config service '%s': timed out after %d seconds" % \
									(url, config.get('config_service', 'connection_timeout')) )
					if not serviceConnectionThread.connected:
						raise Exception(u"Failed to connect to config service '%s': reason unknown" % config.get('config_service', 'url'))
				except Exception, e:
					if ( (urlIndex + 1) > len(config.get('config_service', 'url')) ):
						raise
					logger.error(e)
					continue
				
				if (urlIndex > 0):
					modules = None
					if serviceConnectionThread.configService.isLegacyOpsi():
						modules = serviceConnectionThread.configService.getOpsiInformation_hash()['modules']
					else:
						modules = serviceConnectionThread.configService.backend_info()['modules']
					
					if not modules.get('high_availability'):
						raise Exception(u"Failed to connect to config service '%s': High availability module currently disabled" % url)
					
					if not modules.get('customer'):
						raise Exception(u"Failed to connect to config service '%s': No customer in modules file" % url)
						
					if not modules.get('valid'):
						raise Exception(u"Failed to connect to config service '%s': modules file invalid" % url)
					
					if (modules.get('expires', '') != 'never') and (time.mktime(time.strptime(modules.get('expires', '2000-01-01'), "%Y-%m-%d")) - time.time() <= 0):
						raise Exception(u"Failed to connect to config service '%s': modules file expired" % url)
					
					logger.info(u"Verifying modules file signature")
					publicKey = keys.Key.fromString(data = base64.decodestring('AAAAB3NzaC1yc2EAAAADAQABAAABAQCAD/I79Jd0eKwwfuVwh5B2z+S8aV0C5suItJa18RrYip+d4P0ogzqoCfOoVWtDojY96FDYv+2d73LsoOckHCnuh55GA0mtuVMWdXNZIE8Avt/RzbEoYGo/H0weuga7I8PuQNC/nyS8w3W8TH4pt+ZCjZZoX8S+IizWCYwfqYoYTMLgB0i+6TCAfJj3mNgCrDZkQ24+rOFS4a8RrjamEz/b81noWl9IntllK1hySkR+LbulfTGALHgHkDUlk0OSu+zBPw/hcDSOMiDQvvHfmR4quGyLPbQ2FOVm1TzE0bQPR+Bhx4V8Eo2kNYstG2eJELrz7J1TJI0rCjpB+FQjYPsP')).keyObject
					data = u''
					mks = modules.keys()
					mks.sort()
					for module in mks:
						if module in ('valid', 'signature'):
							continue
						val = modules[module]
						if (val == False): val = 'no'
						if (val == True):  val = 'yes'
						data += u'%s = %s\r\n' % (module.lower().strip(), val)
					if not bool(publicKey.verify(md5(data).digest(), [ long(modules['signature']) ])):
						raise Exception(u"Failed to connect to config service '%s': modules file invalid" % url)
					logger.notice(u"Modules file signature verified (customer: %s)" % modules.get('customer'))
					
				self._configService = serviceConnectionThread.configService
				self._configServiceUrl = url
				
				if (serviceConnectionThread.getUsername() != config.get('global', 'host_id')):
					config.set('global', 'host_id', serviceConnectionThread.getUsername().lower())
					logger.info(u"Updated host_id to '%s'" % config.get('global', 'host_id'))
				
				if self.event.eventConfig.updateConfigFile:
					self.setStatusMessage( _(u"Updating config file") )
					config.updateConfigFile()
			
		except Exception, e:
			self.disconnectConfigServer()
			raise
		
	def disconnectConfigServer(self):
		if self._configService:
			try:
				if self._configService.isLegacyOpsi():
					self._configService.exit()
				else:
					self._configService.backend_exit()
			except Exception, e:
				logger.error(u"Failed to disconnect config service: %s" % forceUnicode(e))
		self._configService = None
		self._configServiceUrl = None
		
	def getConfigFromService(self):
		''' Get settings from service '''
		logger.notice(u"Getting config from service")
		try:
			if not self._configService:
				raise Exception(u"Not connected to config service")
			
			self.setStatusMessage(_(u"Getting config from service"))
			
			if self._configService.isLegacyOpsi():
				
				for (key, value) in self._configService.getNetworkConfig_hash(config.get('global', 'host_id')).items():
					if (key.lower() == 'depotid'):
						depotId = value
						config.set('depot_server', 'depot_id', depotId)
						config.set('depot_server', 'url', self._configService.getDepot_hash(depotId)['depotRemoteUrl'])
					elif (key.lower() == 'depotdrive'):
						config.set('depot_server', 'drive', value)
					elif (key.lower() == 'nextbootserviceurl'):
						if (value.find('/rpc') == -1):
							value = value + '/rpc'
						config.set('config_service', 'url', [ value ])
					else:
						logger.info(u"Unhandled network config key '%s'" % key)
					
				logger.notice(u"Got network config from service")
				
				for (key, value) in self._configService.getGeneralConfig_hash(config.get('global', 'host_id')).items():
					try:
						parts = key.lower().split('.')
						if (len(parts) < 3) or (parts[0] != 'opsiclientd'):
							continue
						
						config.set(section = parts[1], option = parts[2], value = value)
						
					except Exception, e:
						logger.error(u"Failed to process general config key '%s:%s': %s" % (key, value, forceUnicode(e)))
			else:
				self._configService.backend_setOptions({"addConfigStateDefaults": True})
				for configState in self._configService.configState_getObjects(objectId = config.get('global', 'host_id')):
					logger.info(u"Got config state from service: configId %s, values %s" % (configState.configId, configState.values))
					
					if not configState.values:
						continue
					
					if   (configState.configId == u'clientconfig.configserver.url'):
						config.set('config_service', 'url', configState.values)
					elif (configState.configId == u'clientconfig.depot.drive'):
						config.set('depot_server', 'drive', configState.values[0])
					elif configState.configId.startswith(u'opsiclientd.'):
						try:
							parts = configState.configId.lower().split('.')
							if (len(parts) < 3):
								continue
							
							config.set(section = parts[1], option = parts[2], value = configState.values[0])
							
						except Exception, e:
							logger.error(u"Failed to process configState '%s': %s" % (configState.configId, forceUnicode(e)))
			logger.notice(u"Got config from service")
			
			self.setStatusMessage(_(u"Got config from service"))
			logger.debug(u"Config is now:\n %s" % objectToBeautifiedText(config.getDict()))
		except Exception, e:
			logger.error(u"Failed to get config from service: %s" % forceUnicode(e))
			raise
	
	def writeLogToService(self):
		logger.notice(u"Writing log to service")
		try:
			if not self._configService:
				raise Exception(u"Not connected to config service")
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
		finally:
			logger.setFileLevel(config.get('global', 'log_level'))
		
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
	
	def startNotifierApplication(self, command, desktop=None):
		logger.notice(u"Starting notifier application in session '%s'" % self.getSessionId())
		try:
			self.runCommandInSession(command = command.replace('%port%', unicode(self._notificationServerPort)), desktop = desktop, waitForProcessEnding = False)
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
		
		logger.notice(u"Mounting depot share %s" %  config.get('depot_server', 'url'))
		self.setStatusMessage(_(u"Mounting depot share %s") % config.get('depot_server', 'url'))
		
		if impersonation:
			System.mount(config.get('depot_server', 'url'), config.get('depot_server', 'drive'))
		else:
			(depotServerUsername, depotServerPassword) = config.getDepotserverCredentials(configService = self._configService)
			System.mount(config.get('depot_server', 'url'), config.get('depot_server', 'drive'), username = depotServerUsername, password = depotServerPassword)
		self._depotShareMounted = True
		
	def umountDepotShare(self):
		if not self._depotShareMounted:
			logger.debug(u"Depot share not mounted")
			return
		try:
			logger.notice(u"Unmounting depot share")
			System.umount(config.get('depot_server', 'drive'))
			self._depotShareMounted = False
		except Exception, e:
			logger.warning(e)
		
	def updateActionProcessor(self):
		logger.notice(u"Updating action processor")
		self.setStatusMessage(_(u"Updating action processor"))
		
		impersonation = None
		try:
			# This logon type allows the caller to clone its current token and specify new credentials for outbound connections.
			# The new logon session has the same local identifier but uses different credentials for other network connections.
			(depotServerUsername, depotServerPassword) = config.getDepotserverCredentials(configService = self._configService)
			impersonation = System.Impersonate(username = depotServerUsername, password = depotServerPassword)
			impersonation.start(logonType = 'NEW_CREDENTIALS')
			
			self.mountDepotShare(impersonation)
			
			actionProcessorFilename = config.get('action_processor', 'filename')
			actionProcessorLocalDir = config.get('action_processor', 'local_dir')
			actionProcessorLocalTmpDir = actionProcessorLocalDir + '.tmp'
			actionProcessorLocalFile = os.path.join(actionProcessorLocalDir, actionProcessorFilename)
			actionProcessorLocalTmpFile = os.path.join(actionProcessorLocalTmpDir, actionProcessorFilename)
			
			actionProcessorRemoteDir = os.path.join(
							config.get('depot_server', 'drive'),
							config.get('action_processor', 'remote_dir'))
			actionProcessorRemoteFile = os.path.join(actionProcessorRemoteDir, actionProcessorFilename)
			
			if not os.path.exists(actionProcessorLocalFile):
				logger.notice(u"Action processor needs update because file '%s' not found" % actionProcessorLocalFile)
			elif ( abs(os.stat(actionProcessorLocalFile).st_mtime - os.stat(actionProcessorRemoteFile).st_mtime) > 10 ):
				logger.notice(u"Action processor needs update because modification time difference is more than 10 seconds")
			elif not filecmp.cmp(actionProcessorLocalFile, actionProcessorRemoteFile):
				logger.notice(u"Action processor needs update because file changed")
			else:
				logger.notice("Local action processor exists and seems to be up to date")
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
				self._configService.productOnClient_updateObjects([
					ProductOnClient(
						productId          = u'opsi-winst',
						productType        = u'LocalbootProduct',
						clientId           = config.get('global', 'host_id'),
						installationStatus = u'installed',
						actionResult       = u'successful'
					)
				])
			self.setActionProcessorInfo()
			
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
			
			productDir = os.path.join(config.get('depot_server', 'drive'), 'install')
			
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
				productStates = []
				if (self._configService.getLocalBootProductStates_hash.func_code.co_argcount == 2):
					if self.event.eventConfig.serviceOptions:
						logger.warning(u"Service cannot handle service options in method getLocalBootProductStates_hash")
					productStates = self._configService.getLocalBootProductStates_hash(config.get('global', 'host_id'))
					productStates = productStates.get(config.get('global', 'host_id'), [])
				else:
					productStates = self._configService.getLocalBootProductStates_hash(
								config.get('global', 'host_id'),
								self.event.eventConfig.serviceOptions )
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
			
			else:
				logger.notice(u"Start processing action requests")
				
				#if not self.event.eventConfig.useCachedConfig and self.event.eventConfig.syncConfig:
				#	logger.notice(u"Syncing config (products: %s)" % productIds)
				#	self._cacheService.init()
				#	self.setStatusMessage( _(u"Syncing config") )
				#	self._cacheService.setCurrentConfigProgressObserver(self._currentProgressSubjectProxy)
				#	self._cacheService.setOverallConfigProgressObserver(self._overallProgressSubjectProxy)
				#	self._cacheService.syncConfig(productIds = productIds, waitForEnding = True)
				#	self.setStatusMessage( _(u"Config synced") )
				#	self._currentProgressSubjectProxy.setState(0)
				#	self._overallProgressSubjectProxy.setState(0)
				
				if self.event.eventConfig.cacheProducts:
					logger.notice(u"Caching products: %s" % productIds)
					self.setStatusMessage( _(u"Caching products") )
					self.opsiclientd._cacheService.setCurrentProductSyncProgressObserver(self._currentProgressSubjectProxy)
					self.opsiclientd._cacheService.setOverallProductSyncProgressObserver(self._overallProgressSubjectProxy)
					self._currentProgressSubjectProxy.attachObserver(self._detailSubjectProxy)
					try:
						self.opsiclientd._cacheService.cacheProducts(
							self._configService,
							productIds,
							waitForEnding = self.event.eventConfig.requiresCachedProducts)
						self.setStatusMessage( _(u"Products cached") )
					finally:
						self._detailSubjectProxy.setMessage(u"")
						self._currentProgressSubjectProxy.detachObserver(self._detailSubjectProxy)
						self._currentProgressSubjectProxy.reset()
						self._overallProgressSubjectProxy.reset()
				else:
					config.selectDepotserver(configService = self._configService, productIds = productIds)
				
				savedDepotUrl = None
				savedDepotDrive = None
				if self.event.eventConfig.requiresCachedProducts:
					# Event needs cached products => initialize cache service
					if self.opsiclientd._cacheService.getProductSyncCompleted():
						logger.notice(u"Event '%s' requires cached products and product sync is done" % self.event.eventConfig.getName())
						savedDepotUrl = config.get('depot_server', 'url')
						savedDepotDrive = config.get('depot_server', 'drive')
						cacheDepotDir = self.opsiclientd._cacheService.getProductCacheDir().replace('\\', '/').replace('//', '/')
						cacheDepotDrive = cacheDepotDir.split('/')[0]
						cacheDepotUrl = 'smb://localhost/noshare/' + ('/'.join(cacheDepotDir.split('/')[1:]))
						config.set('depot_server', 'url', cacheDepotUrl)
						config.set('depot_server', 'drive', cacheDepotDrive)
					else:
						raise Exception(u"Event '%s' requires cached products but product sync is not done, exiting" % self.event.eventConfig.getName())
				
				try:
					self.runActions()
				finally:
					if savedDepotUrl:
						config.set('depot_server', 'url', savedDepotUrl)
					if savedDepotDrive:
						config.set('depot_server', 'drive', savedDepotDrive)
				
		except Exception, e:
			logger.logException(e)
			logger.error(u"Failed to process product action requests: %s" % forceUnicode(e))
			self.setStatusMessage( _(u"Failed to process product action requests: %s") % forceUnicode(e) )
		
		time.sleep(3)
	
	def runActions(self, additionalParams=''):
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
						while True:
							time.sleep(3)
							logger.debug(u"Checking if automatic startup for service Trusted Installer is set")
							automaticStartup = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SYSTEM\\CurrentControlSet\\services\\TrustedInstaller", "Start", reflection = False)
							if not (automaticStartup == 2):
								break
				except Exception, e:
					logger.error(u"Failed to read TrustedInstaller service-configuration: %s" % e)
			
		self.setStatusMessage( _(u"Starting actions") )
		
		# Setting some registry values before starting action
		# Mainly for action processor winst
		System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "depoturl",   config.get('depot_server', 'url'))
		System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "depotdrive", config.get('depot_server', 'drive'))
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
		if config.get('depot_server', 'url').split('/')[2] not in ('127.0.0.1', 'localhost') and self.event.eventConfig.updateActionProcessor:
			self.updateActionProcessor()
		
		# Run action processor
		actionProcessorCommand = config.replace(self.event.getActionProcessorCommand())
		actionProcessorCommand = actionProcessorCommand.replace('%service_url%', self._configServiceUrl)
		actionProcessorCommand += additionalParams
		actionProcessorCommand = actionProcessorCommand.replace('"', '\\"')
		command = u'%global.base_dir%\\action_processor_starter.exe ' \
			+ u'"%global.host_id%" "%global.opsi_host_key%" "%control_server.port%" ' \
			+ u'"%global.log_file%" "%global.log_level%" ' \
			+ u'"%depot_server.url%" "%depot_server.drive%" ' \
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
	
	def run(self):
		try:
			logger.notice(u"============= EventProcessingThread for occurcence of event '%s' started =============" % self.event)
			self.running = True
			self.eventCancelled = False
			self.waitCancelled = False
			if not self.event.eventConfig.blockLogin:
				self.opsiclientd.setBlockLogin(False)
			
			# Store current config service url and depot url
			configServiceUrls = config.get('config_service', 'url')
			depotServerUrl = config.get('depot_server', 'url')
			depotDrive = config.get('depot_server', 'drive')
			try:
				self.startNotificationServer()
				self.setActionProcessorInfo()
				
				if self.event.eventConfig.useCachedConfig:
					# Event needs cached config => initialize cache service
					if self.opsiclientd._cacheService.getConfigSyncCompleted():
						logger.notice(u"Event '%s' requires cached config and config sync is done" % self.event)
						self.opsiclientd._cacheService.workWithLocalConfig()
						cacheConfigServiceUrl = 'https://127.0.0.1:%s/rpc' % config.get('control_server', 'port')
						logger.notice(u"Setting config service url to cache service url '%s'" % cacheConfigServiceUrl)
						config.set('config_service', 'url', cacheConfigServiceUrl)
					else:
						logger.notice(u"Event '%s' requires cached config but config sync is not done, exiting" % self.event)
						self.running = False
						return
				
				self._messageSubject.setMessage(self.event.eventConfig.getMessage())
				if self.event.eventConfig.warningTime:
					choiceSubject = ChoiceSubject(id = 'choice')
					if (self.event.eventConfig.cancelCounter < self.event.eventConfig.userCancelable):
						choiceSubject.setChoices([ _('Abort'), _('Start now') ])
						choiceSubject.setCallbacks( [ self.abortEventCallback, self.startEventCallback ] )
					else:
						choiceSubject.setChoices([ _('Start now') ])
						choiceSubject.setCallbacks( [ self.startEventCallback ] )
					self._notificationServer.addSubject(choiceSubject)
					try:
						if self.event.eventConfig.eventNotifierCommand:
							self.startNotifierApplication(
									command      = self.event.eventConfig.eventNotifierCommand,
									desktop      = self.event.eventConfig.eventNotifierDesktop )
							
						timeout = int(self.event.eventConfig.warningTime)
						endTime = time.time() + timeout
						while (timeout > 0) and not self.eventCancelled and not self.waitCancelled:
							now = time.time()
							logger.info(u"Notifying user of event %s" % self.event)
							self.setStatusMessage(_(u"Event %s: processing will start in %0.0f seconds") % (self.event.eventConfig.getName(), (endTime - now)))
							if ((endTime - now) <= 0):
								break
							time.sleep(1)
						
						if self.eventCancelled:
							self.event.eventConfig.cancelCounter += 1
							config.set('event_%s' % self.event.eventConfig.getName(), 'cancel_counter', self.event.eventConfig.cancelCounter)
							config.updateConfigFile()
							logger.notice(u"Event cancelled by user for the %d. time (max: %d)" \
								% (self.event.eventConfig.cancelCounter, self.event.eventConfig.userCancelable))
							raise CanceledByUserError(u"Event cancelled by user")
						else:
							self.event.eventConfig.cancelCounter = 0
							config.set('event_%s' % self.event.eventConfig.getName(), 'cancel_counter', self.event.eventConfig.cancelCounter)
							config.updateConfigFile()
					finally:
						try:
							if self._notificationServer:
								self._notificationServer.requestEndConnections()
								self._notificationServer.removeSubject(choiceSubject)
						except Exception, e:
							logger.logException(e)
				
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
				
				if self.event.eventConfig.actionNotifierCommand:
					self.startNotifierApplication(
						command      = self.event.eventConfig.actionNotifierCommand,
						desktop      = self.event.eventConfig.actionNotifierDesktop )
				
				self.connectConfigServer()
				
				if not self.event.eventConfig.useCachedConfig:
					if self.event.eventConfig.getConfigFromService:
						self.getConfigFromService()
					if self.event.eventConfig.updateConfigFile:
						config.updateConfigFile()
				
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
					# Disconnect has to be called, even if connect failed!
					self.disconnectConfigServer()
				except Exception, e:
					logger.logException(e)
				
				if self.event.eventConfig.processShutdownRequests:
					try:
						reboot   = self.opsiclientd.isRebootRequested()
						shutdown = self.opsiclientd.isShutdownRequested()
						if reboot or shutdown:
							if reboot:
								self.setStatusMessage(_(u"Reboot requested"))
							else:
								self.setStatusMessage(_(u"Shutdown requested"))
							
							if self.event.eventConfig.shutdownWarningTime:
								while True:
									if reboot:
										logger.info(u"Notifying user of reboot")
									else:
										logger.info(u"Notifying user of shutdown")
									
									self.shutdownCancelled = False
									self.shutdownWaitCancelled = False
									
									self._messageSubject.setMessage(self.event.eventConfig.getShutdownWarningMessage())
									
									choiceSubject = ChoiceSubject(id = 'choice')
									if (self.event.eventConfig.shutdownCancelCounter < self.event.eventConfig.shutdownUserCancelable):
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
												command      = self.event.eventConfig.shutdownNotifierCommand,
												desktop      = self.event.eventConfig.shutdownNotifierDesktop )
											
									timeout = int(self.event.eventConfig.shutdownWarningTime)
									endTime = time.time() + timeout
									while (timeout > 0) and not self.shutdownCancelled and not self.shutdownWaitCancelled:
										now = time.time()
										if reboot:
											self.setStatusMessage(_(u"Reboot in %0.0f seconds") % (endTime - now))
										else:
											self.setStatusMessage(_(u"Shutdown in %0.0f seconds") % (endTime - now))
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
									if self.shutdownCancelled:
										self.event.eventConfig.shutdownCancelCounter += 1
										logger.notice(u"Shutdown cancelled by user for the %d. time (max: %d)" \
											% (self.event.eventConfig.shutdownCancelCounter, self.event.eventConfig.shutdownUserCancelable))
										
										if (self.event.eventConfig.shutdownWarningRepetitionTime >= 0):
											logger.info(u"Shutdown warning will be repeated in %d seconds" % self.event.eventConfig.shutdownWarningRepetitionTime)
											time.sleep(self.event.eventConfig.shutdownWarningRepetitionTime)
											continue
									break
							if reboot:
								self.opsiclientd.rebootMachine()
							elif shutdown:
								self.opsiclientd.shutdownMachine()
					except Exception, e:
						logger.logException(e)
				
				if self.opsiclientd.isShutdownTriggered():
					self.setStatusMessage(_("Shutting down machine"))
				elif self.opsiclientd.isRebootTriggered():
					self.setStatusMessage(_("Rebooting machine"))
				else:
					self.setStatusMessage(_("Unblocking login"))
				
				if not self.opsiclientd.isRebootTriggered() and not self.opsiclientd.isShutdownTriggered():
					self.opsiclientd.setBlockLogin(False)
				
				self.setStatusMessage(u"")
				
				if self.event.eventConfig.useCachedConfig:
					# Set config service url back to previous url
					logger.notice(u"Setting config service url back to %s" % configServiceUrls)
					config.set('config_service', 'url', configServiceUrls)
					logger.notice("Setting depot server url back to '%s'" % depotServerUrl)
					config.set('depot_server', 'url', depotServerUrl)
					logger.notice(u"Setting depot drive back to '%s'" % depotDrive)
					config.set('depot_server', 'drive', depotDrive)
				
				# Stop notification server thread
				if self._notificationServer:
					try:
						logger.info(u"Stopping notification server")
						self._notificationServer.stop(stopReactor = False)
					except Exception, e:
						logger.logException(e)
		except Exception, e:
			logger.error(u"Failed to process event %s: %s" % (self.event, forceUnicode(e)))
			logger.logException(e)
			self.opsiclientd.setBlockLogin(False)
		
		self.running = False
		logger.notice(u"============= EventProcessingThread for event '%s' ended =============" % self.event)
		
	def abortEventCallback(self, choiceSubject):
		logger.notice(u"Event aborted by user")
		self.eventCancelled = True
	
	def startEventCallback(self, choiceSubject):
		logger.notice(u"Event wait cancelled by user")
		self.waitCancelled = True
	
	def abortShutdownCallback(self, choiceSubject):
		logger.notice(u"Shutdown aborted by user")
		self.shutdownCancelled = True
	
	def startShutdownCallback(self, choiceSubject):
		logger.notice(u"Shutdown wait cancelled by user")
		self.shutdownWaitCancelled = True
	




