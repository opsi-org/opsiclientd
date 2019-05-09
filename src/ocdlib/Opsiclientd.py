# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org
# Copyright (C) 2010-2019 uib GmbH <info@uib.de>

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
The opsiclientd itself.
This is where all the parts come together.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:author: Erol Ueluekmen <e.ueluekmen@uib.de>
:author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU Affero General Public License version 3
"""

import os
import sys

from twisted.internet import reactor

from OPSI import System
from OPSI.Logger import Logger
from OPSI.Types import forceBool, forceInt, forceUnicode
from OPSI.Util import randomString
from OPSI.Util.Message import MessageSubject, ChoiceSubject, NotificationServer

from ocdlib import __version__
from ocdlib.EventProcessing import EventProcessingThread
from ocdlib.Events import *
from ocdlib.ControlPipe import ControlPipeFactory, OpsiclientdRpcPipeInterface
from ocdlib.ControlServer import ControlServer
from ocdlib.Localization import _, setLocaleDir
from ocdlib.Config import getLogFormat, Config
from ocdlib.Timeline import Timeline

if (os.name == 'nt'):
	from ocdlib.Windows import *
if (os.name == 'posix'):
	from ocdlib.Posix import *

try:
	from ocdlibnonfree import __fullversion__
except Exception:
	__fullversion__ = False

logger = Logger()
config = Config()
timeline = Timeline()


class Opsiclientd(EventListener, threading.Thread):
	def __init__(self):
		logger.setLogFormat(getLogFormat(u'opsiclientd'), object=self)
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

		self._blockLoginEventId = None

	def setBlockLogin(self, blockLogin):
		self._blockLogin = forceBool(blockLogin)
		logger.notice(u"Block login now set to '%s'" % self._blockLogin)

		if (self._blockLogin):
			if not self._blockLoginEventId:
				self._blockLoginEventId = timeline.addEvent(
					title         = u"Blocking login",
					description   = u"User login blocked",
					category      = u"block_login",
					durationEvent = True)
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
		else:
			if self._blockLoginEventId:
				timeline.setEventEnd(eventId = self._blockLoginEventId)
				self._blockLoginEventId = None
			if (self._blockLoginNotifierPid):
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
				ec = GUIStartupEventConfig("wait_for_gui")
				eventGenerator = EventGeneratorFactory(ec)
				eventGenerator.addEventConfig(ec)
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
		if not System.existsUser(username = self._actionProcessorUserName):
			return
		logger.notice(u"Deleting local user '%s'" % self._actionProcessorUserName)
		#timeline.addEvent(title = u"Deleting local user '%s'" % self._actionProcessorUserName, description = u'', category = u'system')
		System.deleteUser(username = self._actionProcessorUserName)
		self._actionProcessorUserName = u''
		self._actionProcessorUserPassword = u''

	def run(self):
		self._running = True
		self._stopped = False
		self._opsiclientdRunningEventId = None

		config.readConfigFile()
		setLocaleDir(config.get('global', 'locale_dir'))

		#Needed helper-exe for NT5 x64 to get Sessioninformation (WindowsAPIBug)
		self._winApiBugCommand = os.path.join(config.get('global', 'base_dir'), 'utilities\sessionhelper\getActiveSessionIds.exe')

		try:
			eventTitle = u''
			if __fullversion__:
				eventTitle = u"Opsiclientd version: %s (full) running" % __version__
				logger.essential(u"Opsiclientd version: %s (full)" % __version__)
			else:
				eventTitle = u"Opsiclientd version: %s started" % __version__
				logger.essential(u"Opsiclientd version: %s" % __version__)
			eventDescription = "Commandline: %s\n" % ' '.join(sys.argv)
			logger.essential(u"Commandline: %s" % ' '.join(sys.argv))
			eventDescription += u"Working directory: %s\n" % os.getcwd()
			logger.essential(u"Working directory: %s" % os.getcwd())
			eventDescription += u"Using host id '%s'" % config.get('global', 'host_id')
			logger.notice(u"Using host id '%s'" % config.get('global', 'host_id'))

			self.setBlockLogin(True)

			class ReactorThread(threading.Thread):
				def run(self):
					logger.notice(u"Starting reactor")
					reactor.run(installSignalHandlers=0)
			ReactorThread().start()
			timeout = 0
			while not reactor.running:
				if (timeout >= 10):
					raise Exception(u"Timed out after %d seconds while waiting for reactor to start" % timeout)
				logger.debug(u"Waiting for reactor")
				time.sleep(1)
				timeout += 1

			self._opsiclientdRunningEventId = timeline.addEvent(title = eventTitle, description = eventDescription, category = u'opsiclientd_running', durationEvent = True)

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

			self._cacheService = None
			try:
				from ocdlibnonfree.CacheService import CacheService
				logger.notice(u"Starting cache service")
				try:
					self._cacheService = CacheService(opsiclientd = self)
					self._cacheService.start()
					logger.notice(u"Cache service started")
				except Exception, e:
					logger.error(u"Failed to start cache service: %s" % forceUnicode(e))
					raise
			except Exception, e:
				logger.notice(u"Cache service not started: %s" % e)

			# Create event generators
			createEventGenerators()

			for eventGenerator in getEventGenerators():
				eventGenerator.addEventListener(self)
				eventGenerator.start()
				logger.notice(u"Event generator '%s' started" % eventGenerator)

			for eventGenerator in getEventGenerators(generatorClass = DaemonStartupEventGenerator):
				eventGenerator.createAndFireEvent()

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
				eventGenerator.createAndFireEvent()

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

			logger.info(u"Stopping timeline")
			timeline.stop()

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
		if self._opsiclientdRunningEventId:
			timeline.setEventEnd(self._opsiclientdRunningEventId)

	def stop(self):
		self._stopped = True

	def getCacheService(self):
		if not self._cacheService:
			raise Exception(u"Cache service not started")
		return self._cacheService

	def processEvent(self, event):
		logger.notice(u"Processing event %s" % event)
		eventProcessingThread = None
		self._eventProcessingThreadsLock.acquire()
		description = u"Event %s occurred\n" % event.eventConfig.getId()
		description += u"Config:\n"
		config = event.eventConfig.getConfig()
		configKeys = config.keys()
		configKeys.sort()
		for configKey in configKeys:
			description += u"%s: %s\n" % (configKey, config[configKey])
		timeline.addEvent(title = u"Event %s" % event.eventConfig.getName(), description = description, category = u"event_occurrence")
		try:
			eventProcessingThread = EventProcessingThread(self, event)

			# Always process panic events
			if not isinstance(event, PanicEvent):
				for ept in self._eventProcessingThreads:
					if (event.eventConfig.actionType != 'login') and (ept.event.eventConfig.actionType != 'login'):
						logger.notice(u"Already processing an other (non login) event: %s" % ept.event.eventConfig.getId())
						return
					if (event.eventConfig.actionType == 'login') and (ept.event.eventConfig.actionType == 'login'):
						if (ept.getSessionId() == eventProcessingThread.getSessionId()):
							logger.notice(u"Already processing login event '%s' in session %s" \
									% (ept.event.eventConfig.getName(), eventProcessingThread.getSessionId()))
							self._eventProcessingThreadsLock.release()
							return
			self.createActionProcessorUser(recreate = False)

			self._eventProcessingThreads.append(eventProcessingThread)
		finally:
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
		logger.notice(u"DEBUG: %s " % self._eventProcessingThreads)
		for ept in self._eventProcessingThreads:
			logger.notice("DEBUG: %s " % ept.getSessionId())
			if (int(ept.getSessionId()) == int(sessionId)):
				return ept
		raise Exception(u"Event processing thread for session %s not found" % sessionId)

	def processProductActionRequests(self, event):
		logger.error(u"processProductActionRequests not implemented")

	def getCurrentActiveDesktopName(self, sessionId=None):
		if not ('opsiclientd_rpc' in config.getDict() and 'command' in config.getDict()['opsiclientd_rpc']):
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

	def switchDesktop(self, desktop, sessionId=None):
		if not ('opsiclientd_rpc' in config.getDict() and 'command' in config.getDict()['opsiclientd_rpc']):
			raise Exception(u"opsiclientd_rpc command not defined")

		desktop = forceUnicode(desktop)
		if sessionId is None:
			sessionId = System.getActiveConsoleSessionId()
		sessionId = forceInt(sessionId)

		rpc = "noop(System.switchDesktop('%s'))" % desktop
		cmd = '%s "%s"' % (config.get('opsiclientd_rpc', 'command'), rpc)

		try:
			System.runCommandInSession(command = cmd, sessionId = sessionId, desktop = desktop, waitForProcessEnding = True, timeoutSeconds = 60)
		except Exception, e:
			logger.error(e)

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

	def isInstallationPending(self):
		return state.get('installation_pending', False)

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

			sessionIds = System.getActiveSessionIds(winApiBugCommand = self._winApiBugCommand)
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
