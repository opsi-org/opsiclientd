#! /usr/bin/env python
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
import threading
import time
import tempfile
import codecs
import traceback
import argparse
import platform
import psutil
from contextlib import contextmanager

from OPSI import System
import opsicommon.logging
from opsicommon.logging import logger, LOG_DEBUG, LOG_NONE, LOG_NOTICE
from OPSI.Types import forceBool, forceInt, forceUnicode
from OPSI.Util import randomString
from OPSI.Util.Message import MessageSubject, ChoiceSubject, NotificationServer
from OPSI import __version__ as python_opsi_version

from opsiclientd import __version__, config
from opsiclientd.Config import Config
from opsiclientd.ControlPipe import ControlPipeFactory, OpsiclientdRpcPipeInterface
from opsiclientd.ControlServer import ControlServer
from opsiclientd.Events.Basic import EventListener
from opsiclientd.Events.DaemonShutdown import DaemonShutdownEventGenerator
from opsiclientd.Events.DaemonStartup import DaemonStartupEventGenerator
from opsiclientd.Events.Panic import PanicEvent
from opsiclientd.Events.Utilities.Factories import EventGeneratorFactory
from opsiclientd.Events.Utilities.Generators import createEventGenerators, getEventGenerators
from opsiclientd.EventProcessing import EventProcessingThread
from opsiclientd.Localization import _
from opsiclientd.State import State
from opsiclientd.Timeline import Timeline
from opsiclientd.SystemCheck import RUNNING_ON_WINDOWS

try:
	from opsiclientd.nonfree import __fullversion__
except ImportError:
	__fullversion__ = False

if RUNNING_ON_WINDOWS:
	from opsiclientd.Events.Windows.GUIStartup import (
		GUIStartupEventConfig, GUIStartupEventGenerator)

timeline = Timeline()
state = State()

class Opsiclientd(EventListener, threading.Thread):
	def __init__(self):
		System.ensure_not_already_running("opsiclientd")
		state.start()
		timeline.start()

		logger.debug("Opsiclient initiating")

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

		self._cacheService = None

	def restart(self, waitSeconds=0, env_vars={}):
		def _restart(waitSeconds=0, env_vars={}):
			time.sleep(waitSeconds)
			if env_vars:
				logger.notice("Setting environment variables: %s", env_vars)
				os.environ.update(env_vars)
			logger.notice("Executing: %s", sys.argv)
			os.execvp(sys.argv[0], sys.argv)
		logger.notice("Will restart in %d seconds", waitSeconds)
		threading.Thread(target=_restart, args=(waitSeconds, env_vars)).start()
	
	def setBlockLogin(self, blockLogin):
		self._blockLogin = forceBool(blockLogin)
		logger.notice(u"Block login now set to '%s'" % self._blockLogin)

		if self._blockLogin:
			if not self._blockLoginEventId:
				self._blockLoginEventId = timeline.addEvent(
					title=u"Blocking login",
					description=u"User login blocked",
					category=u"block_login",
					durationEvent=True
				)

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
							# The following code does not work currently ('RuntimeError' object is not subscriptable). Remove?
							#logger.error(e)
							#if e[0] == 233 and sys.getwindowsversion()[0] == 5 and sessionId != 0:
							#	# No process is on the other end
							#	# Problem with pipe \\\\.\\Pipe\\TerminalServer\\SystemExecSrvr\\<sessionid>
							#	# After logging off from a session other than 0 csrss.exe does not create this pipe or CreateRemoteProcessW is not able to read the pipe.
							#	logger.info(u"Retrying to run command in session 0")
							#	sessionId = 0
							#else:
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
		waiter = WaitForGUI()
		waiter.wait(timeout or None)

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

		self._actionProcessorUserPassword = u'$!?' + str(randomString(16)) + u'!/%'
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
		with opsicommon.logging.log_context({'instance' : 'opsiclientd'}):
			try:
				self._run()
			except Exception as exc:
				logger.error(exc, exc_info=True)
	
	def _run(self):
		self._running = True
		self._opsiclientdRunningEventId = None

		config.readConfigFile()
		
		@contextmanager
		def getControlPipe():
			logger.notice("Starting control pipe")
			try:
				controlPipe = ControlPipeFactory(OpsiclientdRpcPipeInterface(self))
				controlPipe.daemon = True
				controlPipe.start()
				logger.notice("Control pipe started")
				yield
			except Exception as e:
				logger.error("Failed to start control pipe: %s", e, exc_info=True)
				raise
			finally:
				logger.info("Stopping control pipe")
				try:
					controlPipe.stop()
					controlPipe.join(2)
					logger.info("Control pipe stopped")
				except (NameError, RuntimeError) as stopError:
					logger.debug("Stopping controlPipe failed: %s", stopError)

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
				logger.debug("Current control server: %s", controlServer)
				controlServer.start()
				logger.notice("Control server started")

				self._stopEvent.wait(1)
				if self._stopEvent.is_set():
					# Probably a failure during binding to port.
					raise RuntimeError("Received stop signal.")

				yield
			except Exception as e:
				logger.error("Failed to start control server: %s", e, exc_info=True)
				raise e
			finally:
				logger.info("Stopping control server")
				try:
					controlServer.stop()
					controlServer.join(2)
					logger.info("Control server stopped")
				except (NameError, RuntimeError) as stopError:
					logger.debug("Stopping controlServer failed: %s", stopError)

		@contextmanager
		def getCacheService():
			cacheService = None
			try:
				logger.notice("Starting cache service")
				from opsiclientd.nonfree.CacheService import CacheService
				cacheService = CacheService(opsiclientd=self)
				cacheService.start()
				logger.notice("Cache service started")
				yield cacheService
			except Exception as e:
				logger.error("Failed to start cache service: %s", e, exc_info=True)
				yield None
			finally:
				if cacheService:
					logger.info("Stopping cache service")
					try:
						cacheService.stop()
						cacheService.join(2)
						logger.info("Cache service stopped")
					except (NameError, RuntimeError) as stopError:
						logger.debug("Failed to stop cache service: %s", stopError)
		
		@contextmanager
		def getEventGeneratorContext():
			logger.debug("Creating event generators")
			createEventGenerators()

			for eventGenerator in getEventGenerators():
				eventGenerator.addEventListener(self)
				eventGenerator.start()
				logger.notice("Event generator '%s' started", eventGenerator)

			try:
				yield
			finally:
				for eventGenerator in getEventGenerators():
					logger.info("Stopping event generator %s", eventGenerator)
					eventGenerator.stop()
					eventGenerator.join(2)
					logger.info("Event generator %s stopped", eventGenerator)

		@contextmanager
		def getDaemonLoopingContext():
			with getEventGeneratorContext():
				for eventGenerator in getEventGenerators(generatorClass=DaemonStartupEventGenerator):
					eventGenerator.createAndFireEvent()

				if RUNNING_ON_WINDOWS and getEventGenerators(generatorClass=GUIStartupEventGenerator):
					# Wait until gui starts up
					logger.notice("Waiting for gui startup (timeout: %d seconds)", config.get('global', 'wait_for_gui_timeout'))
					self.waitForGUI(timeout=config.get('global', 'wait_for_gui_timeout'))
					logger.notice("Done waiting for GUI")

					# Wait some more seconds for events to fire
					time.sleep(5)

				try:
					yield
				finally:
					for eventGenerator in getEventGenerators(generatorClass=DaemonShutdownEventGenerator):
						logger.info("Create and fire shutdown event generator %s", eventGenerator)
						eventGenerator.createAndFireEvent()

		try:
			parent = psutil.Process(os.getpid()).parent()
			parent_name = parent.name() if parent else None
			eventTitle = f"Opsiclientd {__version__} [python-opsi={python_opsi_version}]" \
				f" ({'full' if __fullversion__ else 'open'})" \
				f" running on {platform.system()}"
			logger.essential(eventTitle)
			eventDescription = f"Parent process: {parent_name}\n"
			logger.essential(f"Parent process: {parent_name}")
			eventDescription += f"Commandline: {' '.join(sys.argv)}\n"
			logger.essential(f"Commandline: {' '.join(sys.argv)}")
			eventDescription += f"Working directory: {os.getcwd()}\n"
			logger.essential(f"Working directory: {os.getcwd()}")
			eventDescription += f"Using host id '{config.get('global', 'host_id')}'"
			logger.notice(f"Using host id '{config.get('global', 'host_id')}'")

			self.setBlockLogin(True)

			self._opsiclientdRunningEventId = timeline.addEvent(
				title=eventTitle,
				description=eventDescription,
				category="opsiclientd_running",
				durationEvent=True
			)

			with getControlPipe():
				with getControlServer():
					with getCacheService() as cacheService:
						self._cacheService = cacheService

						with getDaemonLoopingContext():
							if not self._eventProcessingThreads:
								logger.notice("No events processing, unblocking login")
								self.setBlockLogin(False)

							try:
								while not self._stopEvent.is_set():
									self._stopEvent.wait(1)
							finally:
								logger.notice("opsiclientd is going down")

								for ept in self._eventProcessingThreads:
									logger.info("Waiting for event processing thread %s", ept)
									ept.join(5)

								if self._opsiclientdRunningEventId:
									timeline.setEventEnd(self._opsiclientdRunningEventId)
								logger.info("Stopping timeline")
								timeline.stop()
		except Exception as e:
			if not self._stopEvent.is_set():
				logger.error(e, exc_info=True)
			self.setBlockLogin(False)
		finally:
			self._running = False

			"""
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
			"""

			for thread in threading.enumerate():
				logger.info("Runnning thread on main thread exit: %s", thread)

			logger.info("Exiting opsiclientd thread")

	def stop(self):
		logger.notice("Stopping %s...", self)
		self._stopEvent.set()

	def getCacheService(self):
		if not self._cacheService:
			raise Exception("Cache service not started")
		return self._cacheService

	def processEvent(self, event):
		logger.notice("Processing event %s", event)
		eventProcessingThread = None
		with self._eventProcessingThreadsLock:
			description = f"Event {event.eventConfig.getId()} occurred\n"
			description += "Config:\n"
			config = event.eventConfig.getConfig()
			configKeys = list(config.keys())
			configKeys.sort()
			for configKey in configKeys:
				description += f"{configKey}: {config[configKey]}\n"
			timeline.addEvent(
				title=f"Event {event.eventConfig.getName()}",
				description=description,
				category="event_occurrence"
			)

			eventProcessingThread = EventProcessingThread(self, event)

			# Always process panic events
			if not isinstance(event, PanicEvent):
				for ept in self._eventProcessingThreads:
					if event.eventConfig.actionType != 'login' and ept.event.eventConfig.actionType != 'login':
						logger.notice("Already processing an other (non login) event: %s", ept.event.eventConfig.getId())
						return

					if event.eventConfig.actionType == 'login' and ept.event.eventConfig.actionType == 'login':
						if ept.getSessionId() == eventProcessingThread.getSessionId():
							logger.notice("Already processing login event '%s' in session %s",
								ept.event.eventConfig.getName(), eventProcessingThread.getSessionId()
							)
							return
			self.createActionProcessorUser(recreate=False)
			self._eventProcessingThreads.append(eventProcessingThread)

		try:
			eventProcessingThread.start()
			eventProcessingThread.join()
			logger.notice("Done processing event %s", event)
		finally:
			with self._eventProcessingThreadsLock:
				self._eventProcessingThreads.remove(eventProcessingThread)

				if not self._eventProcessingThreads:
					try:
						self.deleteActionProcessorUser()
					except Exception as error:
						logger.warning(error)

	def getEventProcessingThread(self, sessionId):
		for ept in self._eventProcessingThreads:
			if int(ept.getSessionId()) == int(sessionId):
				return ept
		raise Exception(f"Event processing thread for session {sessionId} not found")

	def processProductActionRequests(self, event):
		logger.error("processProductActionRequests not implemented")

	def getCurrentActiveDesktopName(self, sessionId=None):
		if not RUNNING_ON_WINDOWS:
			return
		if not ('opsiclientd_rpc' in config.getDict() and 'command' in config.getDict()['opsiclientd_rpc']):
			raise Exception(u"opsiclientd_rpc command not defined")

		if sessionId is None:
			sessionId = System.getActiveConsoleSessionId()

		rpc = f"setCurrentActiveDesktopName(\"{sessionId}\", System.getActiveDesktopName())"
		cmd = '%s "%s"' % (config.get('opsiclientd_rpc', 'command'), rpc.replace('"', '\\"'))
		try:
			System.runCommandInSession(
				command=cmd,
				sessionId=sessionId,
				desktop="winlogon",
				waitForProcessEnding=True,
				timeoutSeconds=60,
				noWindow=True
			)
		except Exception as e:
			logger.error(e)

		desktop = self._currentActiveDesktopName.get(sessionId)
		if not desktop:
			logger.warning("Failed to get current active desktop name for session %s, using 'default'", sessionId)
			desktop = "default"
			self._currentActiveDesktopName[sessionId] = desktop
		logger.debug("Returning current active dektop name '%s' for session %s", desktop, sessionId)
		return desktop

	def switchDesktop(self, desktop, sessionId=None):
		if not ('opsiclientd_rpc' in config.getDict() and 'command' in config.getDict()['opsiclientd_rpc']):
			raise Exception("opsiclientd_rpc command not defined")

		desktop = forceUnicode(desktop)
		if sessionId is None:
			sessionId = System.getActiveConsoleSessionId()
		sessionId = forceInt(sessionId)

		rpc = f"noop(System.switchDesktop('{desktop}'))"
		cmd = '%s "%s"' % (config.get('opsiclientd_rpc', 'command'), rpc)

		try:
			System.runCommandInSession(
				command=cmd,
				sessionId=sessionId,
				desktop=desktop,
				waitForProcessEnding=True,
				timeoutSeconds=60,
				noWindow=True
			)
		except Exception as e:
			logger.error(e)

	def systemShutdownInitiated(self):
		if not self.isRebootTriggered() and not self.isShutdownTriggered():
			# This shutdown was triggered by someone else
			# Reset shutdown/reboot requests to avoid reboot/shutdown on next boot
			logger.notice("Someone triggered a reboot or a shutdown => clearing reboot request")
			self.clearRebootRequest()

	def rebootMachine(self, waitSeconds=3):
		self._isRebootTriggered = True
		self.clearRebootRequest()
		System.reboot(wait=waitSeconds)

	def shutdownMachine(self, waitSeconds=3):
		self._isShutdownTriggered = True
		self.clearShutdownRequest()
		System.shutdown(wait=waitSeconds)
	
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
			raise Exception('notification_server.popup_port not defined')

		notifierCommand = config.get('opsiclientd_notifier', 'command')
		if not notifierCommand:
			raise Exception('opsiclientd_notifier.command not defined')
		notifierCommand += " -s %s" % os.path.join("notifier", "popup.ini")

		self._popupNotificationLock.acquire()
		try:
			self.hidePopup()

			popupSubject = MessageSubject('message')
			choiceSubject = ChoiceSubject(id='choice')
			popupSubject.setMessage(message)

			logger.notice("Starting popup message notification server on port %d", port)
			try:
				self._popupNotificationServer = NotificationServer(
					address="127.0.0.1",
					start_port=port,
					subjects=[popupSubject, choiceSubject]
				)
				self._popupNotificationServer.daemon = True
				with opsicommon.logging.log_context({'instance' : 'popup notification server'}):
					if not self._popupNotificationServer.start_and_wait(timeout=30):
						raise Exception("Timed out while waiting for notification server")
			except Exception as e:
				logger.error("Failed to start notification server: %s", e)
				raise
			
			notifierCommand = notifierCommand.replace('%port%', str(self._popupNotificationServer.port)).replace('%id%', "popup")
			
			choiceSubject.setChoices([_('Close')])
			choiceSubject.setCallbacks([self.popupCloseCallback])

			if RUNNING_ON_WINDOWS:
				sessionIds = System.getActiveSessionIds()
				if not sessionIds:
					sessionIds = [System.getActiveConsoleSessionId()]

				for sessionId in sessionIds:
					logger.info("Starting popup message notifier app in session %s", sessionId)
					try:
						System.runCommandInSession(
							command=notifierCommand,
							sessionId=sessionId,
							desktop=self.getCurrentActiveDesktopName(sessionId),
							waitForProcessEnding=False)
					except Exception as e:
						logger.error("Failed to start popup message notifier app in session %s: %s", sessionId, e)
		finally:
			self._popupNotificationLock.release()

	def hidePopup(self):
		if self._popupNotificationServer:
			try:
				logger.info("Stopping popup message notification server")
				self._popupNotificationServer.stop(stopReactor=False)
			except Exception as e:
				logger.error("Failed to stop popup notification server: %s", e)

	def popupCloseCallback(self, choiceSubject):
		self.hidePopup()


class WaitForGUI(EventListener):
	def __init__(self):
		self._guiStarted = threading.Event()
		ec = GUIStartupEventConfig("wait_for_gui")
		eventGenerator = EventGeneratorFactory(ec)
		eventGenerator.addEventConfig(ec)
		eventGenerator.addEventListener(self)
		eventGenerator.start()

	def processEvent(self, event):
		logger.info("GUI started")
		self._guiStarted.set()

	def wait(self, timeout=None):
		self._guiStarted.wait(timeout)
		if not self._guiStarted.isSet():
			logger.warning("Timed out after %d seconds while waiting for GUI", timeout)
