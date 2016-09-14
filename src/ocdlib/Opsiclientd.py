#! /usr/bin/env python
# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org

# Copyright (C) 2010-2015 uib GmbH
# http://www.uib.de/
# All rights reserved.

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
ocdlib.Opsiclientd

Basic opsiclientd implementation. This is abstract in some parts that
should be overridden in the concrete implementation for an OS.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:author: Erol Ueluekmen <e.ueluekmen@uib.de>
:author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU Affero General Public License version 3
"""

import os
import sys
from contextlib import contextmanager

from ocdlib import __version__
from ocdlib.Config import Config, getLogFormat
from ocdlib.ControlPipe import ControlPipeFactory, OpsiclientdRpcPipeInterface
from ocdlib.ControlServer import ControlServer
from ocdlib.Events import *
from ocdlib.Localization import _, setLocaleDir
from ocdlib.Timeline import Timeline
from ocdlib.SystemCheck import RUNNING_ON_WINDOWS

from OPSI import System
from OPSI.Logger import Logger
from OPSI.Types import forceUnicode, forceInt
from OPSI.Util import randomString
from OPSI.Util.Message import MessageSubject, ChoiceSubject, NotificationServer

# This is at the end to make sure that the tornado-bridge for twisted
# is installed once we reach this.
from twisted.internet import reactor
from tornado.ioloop import IOLoop

try:
	from ocdlibnonfree import __fullversion__
except ImportError:
	__fullversion__ = False

try:
	from ocdlibnonfree.EventProcessing import EventProcessingThread
except ImportError:
	from ocdlib.EventProcessing import EventProcessingThread

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

		self._stopEvent = threading.Event()
		self._stopEvent.clear()

	def setBlockLogin(self, blockLogin):
		self._blockLogin = bool(blockLogin)
		logger.notice(u"Block login now set to '%s'" % self._blockLogin)

		if self._blockLogin:
			if not self._blockLoginEventId:
				self._blockLoginEventId = timeline.addEvent(
					title=u"Blocking login",
					description=u"User login blocked",
					category=u"block_login",
					durationEvent=True)
			if not self._blockLoginNotifierPid and config.get('global', 'block_login_notifier'):
				# TODO: System.getActiveConsoleSessionId() is missing on Linux
				if RUNNING_ON_WINDOWS:
					logger.info(u"Starting block login notifier app")
					sessionId = System.getActiveConsoleSessionId()
					while True:
						try:
							self._blockLoginNotifierPid = System.runCommandInSession(
									command=config.get('global', 'block_login_notifier'),
									sessionId=sessionId,
									desktop='winlogon',
									waitForProcessEnding=False)[2]
							break
						except Exception as e:
							logger.error(e)
							if e[0] == 233 and sys.getwindowsversion()[0] == 5 and sessionId != 0:
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
				timeline.setEventEnd(eventId=self._blockLoginEventId)
				self._blockLoginEventId = None

			if self._blockLoginNotifierPid:
				try:
					logger.info(u"Terminating block login notifier app (pid %s)" % self._blockLoginNotifierPid)
					System.terminateProcess(processId=self._blockLoginNotifierPid)
				except Exception as e:
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

	def createActionProcessorUser(self, recreate=True):
		if not config.get('action_processor', 'create_user'):
			return

		runAsUser = config.get('action_processor', 'run_as_user')
		if runAsUser.lower() == 'system':
			self._actionProcessorUserName = u''
			self._actionProcessorUserPassword = u''
			return

		if '\\' in runAsUser:
			logger.warning(u"Ignoring domain part of user to run action processor '%s'" % runAsUser)
			runAsUser = runAsUser.split('\\', -1)

		if not recreate and self._actionProcessorUserName and self._actionProcessorUserPassword and System.existsUser(username=runAsUser):
			return

		self._actionProcessorUserName = runAsUser
		logger.notice(u"Creating local user '%s'" % runAsUser)

		self._actionProcessorUserPassword = u'$!?' + unicode(randomString(16)) + u'!/%'
		logger.addConfidentialString(self._actionProcessorUserPassword)

		if System.existsUser(username=runAsUser):
			System.deleteUser(username=runAsUser)
		System.createUser(username=runAsUser, password=self._actionProcessorUserPassword, groups=[System.getAdminGroupName()])

	def deleteActionProcessorUser(self):
		if not config.get('action_processor', 'delete_user'):
			return

		if not self._actionProcessorUserName:
			return

		if not System.existsUser(username=self._actionProcessorUserName):
			return

		logger.notice(u"Deleting local user '%s'" % self._actionProcessorUserName)
		System.deleteUser(username=self._actionProcessorUserName)
		self._actionProcessorUserName = u''
		self._actionProcessorUserPassword = u''

	def run(self):
		self._running = True
		self._opsiclientdRunningEventId = None

		config.readConfigFile()
		setLocaleDir(config.get('global', 'locale_dir'))

		# Needed helper-exe for NT5 x64 to get Sessioninformation (WindowsAPIBug)
		self._winApiBugCommand = os.path.join(config.get('global', 'base_dir'), 'utilities\sessionhelper\getActiveSessionIds.exe')

		@contextmanager
		def getControlPipe():
			logger.notice(u"Starting control pipe")
			try:
				controlPipe = ControlPipeFactory(OpsiclientdRpcPipeInterface(self))
				controlPipe.daemon = True
				controlPipe.start()
				logger.notice(u"Control pipe started")
				yield
			except Exception as e:
				logger.error(u"Failed to start control pipe: %s" % forceUnicode(e))
				raise
			finally:
				logger.info(u"Stopping control pipe")
				try:
					controlPipe.stop()
					controlPipe.join(2)
				except (NameError, RuntimeError) as stopError:
					logger.debug(u"Stopping controlPipe failed: {0}".format(stopError))

		@contextmanager
		def getControlServer():
			logger.notice(u"Starting control server")
			try:
				controlServer = ControlServer(
					opsiclientd=self,
					httpsPort=config.get('control_server', 'port'),
					sslServerKeyFile=config.get('control_server', 'ssl_server_key_file'),
					sslServerCertFile=config.get('control_server', 'ssl_server_cert_file'),
					staticDir=config.get('control_server', 'static_dir')
				)
				logger.debug("Current control server: {0}".format(controlServer))
				controlServer.start()
				logger.notice(u"Control server started")

				self._stopEvent.wait(1)
				if self._stopEvent.is_set():
					# Probably a failure during binding to port.
					raise RuntimeError("Received stop signal.")

				yield
			except Exception as e:
				logger.error(u"Failed to start control server: {0}".format(forceUnicode(e)))
				raise e
			finally:
				logger.info(u"Stopping control server")
				try:
					controlServer.stop()
					controlServer.join(2)
				except (NameError, RuntimeError) as stopError:
					logger.debug(u"Stopping controlServer failed: {0}".format(stopError))

		@contextmanager
		def getCacheService():
			try:
				from ocdlibnonfree.CacheService import CacheService
				logger.notice(u"Starting cache service")
				try:
					cacheService = CacheService(opsiclientd=self)
					cacheService.start()
					logger.notice(u"Cache service started")
					yield cacheService
				except Exception as e:
					logger.error(u"Failed to start cache service: %s" % forceUnicode(e))
					raise
				finally:
					logger.info(u"Stopping cache service")
					try:
						cacheService.stop()
						cacheService.join(2)
					except (NameError, RuntimeError) as stopError:
						logger.debug(u"Stopping cache service failed: {0}".format(stopError))
			except ImportError:
				yield None
			except Exception as e:
				logger.notice(u"Cache service not started: %s" % e)

		@contextmanager
		def getEventGeneratorContext():
			logger.debug("Creating event generators")
			createEventGenerators()

			for eventGenerator in getEventGenerators():
				eventGenerator.addEventListener(self)
				eventGenerator.start()
				logger.notice(u"Event generator '%s' started" % eventGenerator)

			try:
				yield
			finally:
				for eventGenerator in getEventGenerators():
					logger.info(u"Stopping event generator %s" % eventGenerator)
					eventGenerator.stop()
					eventGenerator.join(2)

		@contextmanager
		def getDaemonLoopingContext():
			with getEventGeneratorContext():
				for eventGenerator in getEventGenerators(generatorClass=DaemonStartupEventGenerator):
					eventGenerator.createAndFireEvent()

				if RUNNING_ON_WINDOWS and getEventGenerators(generatorClass=GUIStartupEventGenerator):
					# Wait until gui starts up
					logger.notice(u"Waiting for gui startup (timeout: %d seconds)" % config.get('global', 'wait_for_gui_timeout'))
					self.waitForGUI(timeout=config.get('global', 'wait_for_gui_timeout'))
					logger.notice(u"Done waiting for GUI")

					# Wait some more seconds for events to fire
					time.sleep(5)

				try:
					yield
				finally:
					for eventGenerator in getEventGenerators(generatorClass=DaemonShutdownEventGenerator):
						eventGenerator.createAndFireEvent()

		try:
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

			self._opsiclientdRunningEventId = timeline.addEvent(
				title=eventTitle,
				description=eventDescription,
				category=u'opsiclientd_running',
				durationEvent=True
			)

			with getControlPipe():
				with getControlServer():
					with getCacheService() as cacheService:
						self._cacheService = cacheService

						with getDaemonLoopingContext():
							if not self._eventProcessingThreads:
								logger.notice(u"No events processing, unblocking login")
								self.setBlockLogin(False)

							try:
								while not self._stopEvent.is_set():
									self._stopEvent.wait(1)
							finally:
								logger.notice(u"opsiclientd is going down")

								for ept in self._eventProcessingThreads:
									logger.info(u"Waiting for event processing thread %s" % ept)
									ept.join(5)

								if self._opsiclientdRunningEventId:
									timeline.setEventEnd(self._opsiclientdRunningEventId)
								logger.info(u"Stopping timeline")
								timeline.stop()
		except Exception as e:
			logger.logException(e)
			self.setBlockLogin(False)
		finally:
			self._running = False

			if reactor and reactor.running:
				logger.info(u"Stopping reactor")
				reactor.fireSystemEvent('shutdown')
				reactor.disconnectAll()
				reactor.callFromThread(reactor.stop)

				reactorStopTimeout = 60
				for _unused in range(reactorStopTimeout):
					if not reactor.running:
						break

					logger.debug(u"Waiting for reactor to stop")
					time.sleep(1)
				else:
					logger.debug("Reactor still running after {0} seconds.".format(reactorStopTimeout))
					logger.debug("Exiting anyway.")

			logger.info(u"Stopping tornado IOLoop")
			try:
				IOLoop.current().stop()
			except Exception as error:
				logger.debug(u"Stopping IOLoop failed: {0}".format(error))

			logger.info(u"Exiting opsiclientd thread")

	def stop(self):
		logger.notice(u"Stopping {0}...".format(self))
		self._stopEvent.set()

	def getCacheService(self):
		if not self._cacheService:
			raise Exception(u"Cache service not started")
		return self._cacheService

	def processEvent(self, event):
		logger.notice(u"Processing event %s" % event)
		eventProcessingThread = None
		with self._eventProcessingThreadsLock:
			description = u"Event %s occurred\n" % event.eventConfig.getId()
			description += u"Config:\n"
			config = event.eventConfig.getConfig()
			configKeys = config.keys()
			configKeys.sort()
			for configKey in configKeys:
				description += u"%s: %s\n" % (configKey, config[configKey])
			timeline.addEvent(title=u"Event %s" % event.eventConfig.getName(), description=description, category=u"event_occurrence")

			eventProcessingThread = EventProcessingThread(self, event)

			# Always process panic events
			if not isinstance(event, PanicEvent):
				for ept in self._eventProcessingThreads:
					if event.eventConfig.actionType != 'login' and ept.event.eventConfig.actionType != 'login':
						logger.notice(u"Already processing an other (non login) event: %s" % ept.event.eventConfig.getId())
						return

					if event.eventConfig.actionType == 'login' and ept.event.eventConfig.actionType == 'login':
						if ept.getSessionId() == eventProcessingThread.getSessionId():
							logger.notice(u"Already processing login event '%s' in session %s"
									% (ept.event.eventConfig.getName(), eventProcessingThread.getSessionId()))
							return
			self.createActionProcessorUser(recreate=False)

			self._eventProcessingThreads.append(eventProcessingThread)

		try:
			eventProcessingThread.start()
			eventProcessingThread.join()
			logger.notice(u"Done processing event {0!r}".format(event))
		finally:
			with self._eventProcessingThreadsLock:
				self._eventProcessingThreads.remove(eventProcessingThread)

				if not self._eventProcessingThreads:
					try:
						self.deleteActionProcessorUser()
					except Exception as error:
						logger.warning(error)

	def getEventProcessingThread(self, sessionId):
		logger.notice(u"DEBUG: %s " % self._eventProcessingThreads)
		for ept in self._eventProcessingThreads:
			logger.notice("DEBUG: %s " % ept.getSessionId())
			if int(ept.getSessionId()) == int(sessionId):
				return ept
		raise Exception(u"Event processing thread for session %s not found" % sessionId)

	def processProductActionRequests(self, event):
		logger.error(u"processProductActionRequests not implemented")

	def getCurrentActiveDesktopName(self, sessionId=None):
		if not ('opsiclientd_rpc' in config.getDict() and 'command' in config.getDict()['opsiclientd_rpc']):
			raise Exception(u"opsiclientd_rpc command not defined")

		if sessionId is None:
			sessionId = System.getActiveConsoleSessionId()

		rpc = 'setCurrentActiveDesktopName("{sessionId}", System.getActiveDesktopName())'.format(sessionId=sessionId)
		cmd = "{rpc_processor} '{command}'".format(
			rpc_processor=config.get('opsiclientd_rpc', 'command'),
			command=rpc
		)

		try:
			System.runCommandInSession(
				command=cmd,
				sessionId=sessionId,
				desktop=u"winlogon",
				waitForProcessEnding=True,
				timeoutSeconds=60
			)
		except Exception as e:
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
			System.runCommandInSession(command=cmd, sessionId=sessionId, desktop=desktop, waitForProcessEnding=True, timeoutSeconds=60)
		except Exception as e:
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
			choiceSubject = ChoiceSubject(id='choice')
			popupSubject.setMessage(message)

			logger.notice(u"Starting popup message notification server on port %d" % port)
			try:
				self._popupNotificationServer = NotificationServer(
					address="127.0.0.1",
					port=port,
					subjects=[popupSubject, choiceSubject]
				)
				self._popupNotificationServer.start()
			except Exception as e:
				logger.error(u"Failed to start notification server: %s" % forceUnicode(e))
				raise

			choiceSubject.setChoices([_('Close')])
			choiceSubject.setCallbacks([self.popupCloseCallback])

			if RUNNING_ON_WINDOWS:
				sessionIds = System.getActiveSessionIds(winApiBugCommand=self._winApiBugCommand)
				if not sessionIds:
					sessionIds = [System.getActiveConsoleSessionId()]

				for sessionId in sessionIds:
					logger.info(u"Starting popup message notifier app in session %d" % sessionId)
					try:
						System.runCommandInSession(
							command=notifierCommand,
							sessionId=sessionId,
							desktop=self.getCurrentActiveDesktopName(sessionId),
							waitForProcessEnding=False)
					except Exception as e:
						logger.error(u"Failed to start popup message notifier app in session %d: %s" % (sessionId, forceUnicode(e)))
		finally:
			self._popupNotificationLock.release()

	def hidePopup(self):
		if self._popupNotificationServer:
			try:
				logger.info(u"Stopping popup message notification server")
				self._popupNotificationServer.stop(stopReactor=False)
			except Exception as e:
				logger.error(u"Failed to stop popup notification server: %s" % e)

	def popupCloseCallback(self, choiceSubject):
		self.hidePopup()
