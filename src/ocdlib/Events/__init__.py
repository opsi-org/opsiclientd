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
Events and their configuration.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:author: Erol Ueluekmen <e.ueluekmen@uib.de>
:author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU Affero General Public License version 3
"""

from __future__ import absolute_import

import copy as pycopy
import sys
import threading
import time

from OPSI import System
from OPSI.Logger import Logger, LOG_DEBUG
from OPSI.Types import forceBool, forceList, forceUnicode
from OPSI.Util import objectToBeautifiedText

from ocdlib.Config import Config
from ocdlib.EventConfiguration import EventConfig
from ocdlib.State import State
from ocdlib.Localization import getLanguage
from ocdlib.SystemCheck import RUNNING_ON_WINDOWS

from .Basic import Event, EventGenerator
from .Panic import (
	EVENT_CONFIG_TYPE_PANIC, PanicEventConfig, PanicEventGenerator)
from .DaemonStartup import (
	EVENT_CONFIG_TYPE_DAEMON_STARTUP,
	DaemonStartupEventConfig, DaemonStartupEventGenerator)

logger = Logger()
config = Config()
state = State()

# Possible event types
EVENT_CONFIG_TYPE_PRODUCT_SYNC_COMPLETED = u'sync completed'
EVENT_CONFIG_TYPE_SW_ON_DEMAND = u'sw on demand'
EVENT_CONFIG_TYPE_DAEMON_SHUTDOWN = u'daemon shutdown'
EVENT_CONFIG_TYPE_GUI_STARTUP = u'gui startup'
EVENT_CONFIG_TYPE_PROCESS_ACTION_REQUESTS = u'process action requests'
EVENT_CONFIG_TYPE_TIMER = u'timer'
EVENT_CONFIG_TYPE_USER_LOGIN = u'user login'
EVENT_CONFIG_TYPE_SYSTEM_SHUTDOWN = u'system shutdown'
EVENT_CONFIG_TYPE_CUSTOM = u'custom'


def EventConfigFactory(eventType, eventId, **kwargs):
	if   (eventType == EVENT_CONFIG_TYPE_PANIC):
		return PanicEventConfig(eventId, **kwargs)
	elif (eventType == EVENT_CONFIG_TYPE_DAEMON_STARTUP):
		return DaemonStartupEventConfig(eventId, **kwargs)
	elif (eventType == EVENT_CONFIG_TYPE_DAEMON_SHUTDOWN):
		return DaemonShutdownEventConfig(eventId, **kwargs)
	elif RUNNING_ON_WINDOWS and eventType == EVENT_CONFIG_TYPE_GUI_STARTUP:
		return GUIStartupEventConfig(eventId, **kwargs)
	elif (eventType == EVENT_CONFIG_TYPE_TIMER):
		return TimerEventConfig(eventId, **kwargs)
	elif (eventType == EVENT_CONFIG_TYPE_PRODUCT_SYNC_COMPLETED):
		return SyncCompletedEventConfig(eventId, **kwargs)
	elif (eventType == EVENT_CONFIG_TYPE_PROCESS_ACTION_REQUESTS):
		return ProcessActionRequestsEventConfig(eventId, **kwargs)
	elif RUNNING_ON_WINDOWS and eventType == EVENT_CONFIG_TYPE_USER_LOGIN:
		return UserLoginEventConfig(eventId, **kwargs)
	elif RUNNING_ON_WINDOWS and eventType == EVENT_CONFIG_TYPE_SYSTEM_SHUTDOWN:
		return SystemShutdownEventConfig(eventId, **kwargs)
	elif (eventType == EVENT_CONFIG_TYPE_CUSTOM):
		return CustomEventConfig(eventId, **kwargs)
	elif (eventType == EVENT_CONFIG_TYPE_SW_ON_DEMAND):
		return SwOnDemandEventConfig(eventId, **kwargs)
	else:
		raise TypeError(u"Unknown event config type '%s'" % eventType)


class DaemonShutdownEventConfig(EventConfig):
	def setConfig(self, conf):
		EventConfig.setConfig(self, conf)
		self.maxRepetitions = 0


class TimerEventConfig(EventConfig):
	pass


class SyncCompletedEventConfig(EventConfig):
	pass


class ProcessActionRequestsEventConfig(EventConfig):
	pass


class SwOnDemandEventConfig(EventConfig):
	pass


if RUNNING_ON_WINDOWS:
	class WMIEventConfig(EventConfig):
		def setConfig(self, conf):
			EventConfig.setConfig(self, conf)
			self.wql = unicode( conf.get('wql', '') )


	class GUIStartupEventConfig(WMIEventConfig):
		def setConfig(self, conf):
			WMIEventConfig.setConfig(self, conf)
			self.maxRepetitions = 0
			self.processName = None


	class UserLoginEventConfig(WMIEventConfig):
		def setConfig(self, conf):
			WMIEventConfig.setConfig(self, conf)
			self.blockLogin = False
			self.logoffCurrentUser = False
			self.lockWorkstation = False


	class SystemShutdownEventConfig(WMIEventConfig):
		def setConfig(self, conf):
			WMIEventConfig.setConfig(self, conf)
			self.maxRepetitions = 0


	class CustomEventConfig(WMIEventConfig):
		pass
else:
	# On $NotWindows wo do not want to depend on WMI
	try:
		from ocdlibnonfree.Events import CustomEventConfig
	except ImportError as error:
		logger.critical(
			u"Unable to import from ocdlibnonfree."
			u"Is this the full version?"
		)
		raise error


def EventGeneratorFactory(eventConfig):
	if isinstance(eventConfig, PanicEventConfig):
		return PanicEventGenerator(eventConfig)
	elif isinstance(eventConfig, DaemonStartupEventConfig):
		return DaemonStartupEventGenerator(eventConfig)
	elif isinstance(eventConfig, DaemonShutdownEventConfig):
		return DaemonShutdownEventGenerator(eventConfig)
	elif RUNNING_ON_WINDOWS and isinstance(eventConfig, GUIStartupEventConfig):
		return GUIStartupEventGenerator(eventConfig)
	elif isinstance(eventConfig, TimerEventConfig):
		return TimerEventGenerator(eventConfig)
	elif isinstance(eventConfig, SyncCompletedEventConfig):
		return SyncCompletedEventGenerator(eventConfig)
	elif isinstance(eventConfig, ProcessActionRequestsEventConfig):
		return ProcessActionRequestsEventGenerator(eventConfig)
	elif RUNNING_ON_WINDOWS and isinstance(eventConfig, UserLoginEventConfig):
		return UserLoginEventGenerator(eventConfig)
	elif RUNNING_ON_WINDOWS and  isinstance(eventConfig, SystemShutdownEventConfig):
		return SystemShutdownEventGenerator(eventConfig)
	elif isinstance(eventConfig, CustomEventConfig):
		return CustomEventGenerator(eventConfig)
	elif isinstance(eventConfig, SwOnDemandEventConfig):
		return SwOnDemandEventGenerator(eventConfig)
	else:
		raise TypeError(u"Unhandled event config '%s'" % eventConfig)


class DaemonShutdownEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)

	def createEvent(self, eventInfo={}):
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None
		return DaemonShutdownEvent(eventConfig = eventConfig, eventInfo = eventInfo)


class TimerEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)

	def getNextEvent(self):
		self._event = threading.Event()
		if (self._generatorConfig.interval > 0):
			self._event.wait(self._generatorConfig.interval)
			return self.createEvent()
		else:
			self._event.wait()

	def createEvent(self, eventInfo={}):
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None
		return TimerEvent(eventConfig = eventConfig, eventInfo = eventInfo)


class SyncCompletedEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)

	def createEvent(self, eventInfo={}):
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None
		return SyncCompletedEvent(eventConfig = eventConfig, eventInfo = eventInfo)


class ProcessActionRequestsEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)

	def createEvent(self, eventInfo={}):
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None
		return ProcessActionRequestsEvent(eventConfig = eventConfig, eventInfo = eventInfo)


if RUNNING_ON_WINDOWS:
	class GUIStartupEventGenerator(EventGenerator):
		def __init__(self, eventConfig):
			EventGenerator.__init__(self, eventConfig)
			if RUNNING_ON_WINDOWS:
				if sys.getwindowsversion()[0] == 5:
					self.guiProcessName = u'winlogon.exe'
				elif sys.getwindowsversion()[0] == 6:
					self.guiProcessName = u'LogonUI.exe'
				else:
					raise Exception('Windows version unsupported')
			else:
				raise Exception(u"OS unsupported")

		def createEvent(self, eventInfo={}):
			eventConfig = self.getEventConfig()
			if not eventConfig:
				return None
			return GUIStartupEvent(eventConfig = eventConfig, eventInfo = eventInfo)

		def getNextEvent(self):
			while not self._stopped:
				logger.debug(u"Checking if process '%s' running" % self.guiProcessName)
				if System.getPid(self.guiProcessName):
					logger.debug(u"Process '%s' is running" % self.guiProcessName)
					return self.createEvent()
				time.sleep(3)

	class SensLogonEventGenerator(EventGenerator):
		def __init__(self, eventConfig):
			EventGenerator.__init__(self, eventConfig)

		def initialize(self):
			EventGenerator.initialize(self)

			logger.notice(u'Registring ISensLogon')

			from ocdlib.Windows import importWmiAndPythoncom, SensLogon

			(wmi, pythoncom) = importWmiAndPythoncom(importWmi = False, importPythoncom = True)
			pythoncom.CoInitialize()

			sl = SensLogon(self.callback)
			sl.subscribe()

		def getNextEvent(self):
			from ocdlib.Windows import importWmiAndPythoncom
			(wmi, pythoncom) = importWmiAndPythoncom(importWmi = False, importPythoncom = True)
			pythoncom.PumpMessages()
			logger.info(u"Event generator '%s' now deactivated after %d event occurrences" % (self, self._eventsOccured))
			self.cleanup()

		def callback(self, eventType, *args):
			logger.debug(u"SensLogonEventGenerator event callback: eventType '%s', args: %s" % (eventType, args))

		def stop(self):
			EventGenerator.stop(self)
			# Post WM_QUIT
			import win32api
			win32api.PostThreadMessage(self._threadId, 18, 0, 0)

		def cleanup(self):
			if self._lastEventOccurence and (time.time() - self._lastEventOccurence < 10):
				# Waiting some seconds before exit to avoid Win32 releasing exceptions
				waitTime = int(10 - (time.time() - self._lastEventOccurence))
				logger.info(u"Event generator '%s' cleaning up in %d seconds" % (self, waitTime))
				time.sleep(waitTime)

			from ocdlib.Windows import importWmiAndPythoncom
			(wmi, pythoncom) = importWmiAndPythoncom(importWmi = False, importPythoncom = True)
			pythoncom.CoUninitialize()


	class UserLoginEventGenerator(SensLogonEventGenerator):
		def __init__(self, eventConfig):
			SensLogonEventGenerator.__init__(self, eventConfig)

		def callback(self, eventType, *args):
			logger.debug(u"UserLoginEventGenerator event callback: eventType '%s', args: %s" % (eventType, args))
			if sys.getwindowsversion()[0] == 6:
				# Try to find out, if the Login is from the WindowManager (Win8 Bugfix for UserLoginScripts)
				sessionIds = None
				sessionId = None
				sessionData = None

				sessionIds = System.getUserSessionIds(args[0])
				if sessionIds:
					sessionId = sessionIds[0]
					sessionData = System.getSessionInformation(sessionId)
					if sessionData.get(u'LogonDomain', '') == u'Window Manager':
						logger.notice(u"Windows Manager Login detected, no UserLoginAction will be fired.")
						return

			if (eventType == 'Logon'):
				logger.notice(u"User login detected: %s" % args[0])
				self._eventsOccured += 1
				self.fireEvent(self.createEvent(eventInfo = {'User': args[0]}))
				if (self._generatorConfig.maxRepetitions > 0) and (self._eventsOccured > self._generatorConfig.maxRepetitions):
					self.stop()

		def createEvent(self, eventInfo={}):
			eventConfig = self.getEventConfig()
			if not eventConfig:
				return None
			return UserLoginEvent(eventConfig = eventConfig, eventInfo = eventInfo)

	# Event config depends on WMI
	class SystemShutdownEventGenerator(EventGenerator):
		def __init__(self, eventConfig):
			EventGenerator.__init__(self, eventConfig)


	class WMIEventGenerator(EventGenerator):
		def __init__(self, eventConfig):
			EventGenerator.__init__(self, eventConfig)
			self._wql = self._generatorConfig.wql
			self._watcher = None

		def initialize(self):
			if not RUNNING_ON_WINDOWS:
				return
			if not self._wql:
				return

			from ocdlib.Windows import importWmiAndPythoncom
			(wmi, pythoncom) = importWmiAndPythoncom()
			pythoncom.CoInitialize()
			if self._wql:
				while not self._watcher:
					try:
						logger.debug(u"Creating wmi object")
						c = wmi.WMI(privileges = ["Security"])
						logger.info(u"Watching for wql: %s" % self._wql)
						self._watcher = c.watch_for(raw_wql = self._wql, wmi_class = '')
					except Exception, e:
						try:
							logger.warning(u"Failed to create wmi watcher: %s" % forceUnicode(e))
						except Exception:
							logger.warning(u"Failed to create wmi watcher, failed to log exception")
						time.sleep(1)
			logger.debug(u"Initialized")

		def getNextEvent(self):
			if not self._watcher:
				logger.info(u"Nothing to watch for")
				self._event = threading.Event()
				self._event.wait()
				return None

			wqlResult = None
			from ocdlib.Windows import importWmiAndPythoncom
			(wmi, pythoncom) = importWmiAndPythoncom()
			while not self._stopped:
				try:
					wqlResult = self._watcher(timeout_ms=500)
					break
				except wmi.x_wmi_timed_out:
					continue

			if wqlResult:
				eventInfo = {}
				for p in wqlResult.properties:
					value = getattr(wqlResult, p)
					if isinstance(value, tuple):
						eventInfo[p] = []
						for v in value:
							eventInfo[p].append(v)
					else:
						eventInfo[p] = value
				return self.createEvent(eventInfo)

		def cleanup(self):
			if self._lastEventOccurence and (time.time() - self._lastEventOccurence < 10):
				# Waiting some seconds before exit to avoid Win32 releasing exceptions
				waitTime = int(10 - (time.time() - self._lastEventOccurence))
				logger.info(u"Event generator '%s' cleaning up in %d seconds" % (self, waitTime))
				time.sleep(waitTime)
			try:
				from ocdlib.Windows import importWmiAndPythoncom
				(wmi, pythoncom) = importWmiAndPythoncom()
				pythoncom.CoUninitialize()
			except ImportError:
				# Probably not running on Windows.
				pass

	class CustomEventGenerator(WMIEventGenerator):
		def __init__(self, eventConfig):
			WMIEventGenerator.__init__(self, eventConfig)

		def createEvent(self, eventInfo={}):
			eventConfig = self.getEventConfig()
			if not eventConfig:
				return None
			return CustomEvent(eventConfig=eventConfig, eventInfo=eventInfo)
else:
	class CustomEventGenerator(EventGenerator):
		def createEvent(self, eventInfo={}):
			eventConfig = self.getEventConfig()
			if not eventConfig:
				return None
			return CustomEvent(eventConfig=eventConfig, eventInfo=eventInfo)

		def getNextEvent(self):
			self._event = threading.Event()
			if self._generatorConfig.interval > 0:
				self._event.wait(self._generatorConfig.interval)
				return self.createEvent()
			else:
				self._event.wait()


class SwOnDemandEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)

	def createEvent(self, eventInfo={}):
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None
		return SwOnDemandEvent(eventConfig = eventConfig, eventInfo = eventInfo)


class DaemonShutdownEvent(Event):
	def __init__(self, eventConfig, eventInfo={}):
		Event.__init__(self, eventConfig, eventInfo)


class TimerEvent(Event):
	def __init__(self, eventConfig, eventInfo={}):
		Event.__init__(self, eventConfig, eventInfo)


class SyncCompletedEvent(Event):
	def __init__(self, eventConfig, eventInfo={}):
		Event.__init__(self, eventConfig, eventInfo)


class ProcessActionRequestsEvent(Event):
	def __init__(self, eventConfig, eventInfo={}):
		Event.__init__(self, eventConfig, eventInfo)

if RUNNING_ON_WINDOWS:
	class GUIStartupEvent(Event):
		def __init__(self, eventConfig, eventInfo={}):
			Event.__init__(self, eventConfig, eventInfo)


	class UserLoginEvent(Event):
		def __init__(self, eventConfig, eventInfo={}):
			Event.__init__(self, eventConfig, eventInfo)


	# Event config depends on WMI
	class SystemShutdownEvent(Event):
		def __init__(self, eventConfig, eventInfo={}):
			Event.__init__(self, eventConfig, eventInfo)


class CustomEvent(Event):
	def __init__(self, eventConfig, eventInfo={}):
		Event.__init__(self, eventConfig, eventInfo)


class SwOnDemandEvent(Event):
	def __init__(self, eventConfig, eventInfo={}):
		Event.__init__(self, eventConfig, eventInfo)


def getEventConfigs():
	preconditions = {}
	for (section, options) in config.getDict().items():
		section = section.lower()
		if section.startswith('precondition_'):
			preconditionId = section.split('_', 1)[1]
			preconditions[preconditionId] = {}
			try:
				for key in options.keys():
					preconditions[preconditionId][key] = options[key].lower() not in ('0', 'false', 'off', 'no')
				logger.info(u"Precondition '%s' created: %s" % (preconditionId, preconditions[preconditionId]))
			except Exception, e:
				logger.error(u"Failed to parse precondition '%s': %s" % (preconditionId, forceUnicode(e)))

	rawEventConfigs = {}
	for (section, options) in config.getDict().items():
		section = section.lower()
		if section.startswith('event_'):
			eventConfigId = section.split('_', 1)[1]
			if not eventConfigId:
				logger.error(u"No event config id defined in section '%s'" % section)
				continue
			rawEventConfigs[eventConfigId] = {
				'active':       True,
				'args':         {},
				'super':        None,
				'precondition': None}
			try:
				for key in options.keys():
					if   (key.lower() == 'active'):
						rawEventConfigs[eventConfigId]['active'] = unicode(options[key]).lower() not in ('0', 'false', 'off', 'no')
					elif (key.lower() == 'super'):
						rawEventConfigs[eventConfigId]['super'] = options[key]
						if rawEventConfigs[eventConfigId]['super'].startswith('event_'):
							rawEventConfigs[eventConfigId]['super'] = rawEventConfigs[eventConfigId]['super'].split('_', 1)[1]
					else:
						rawEventConfigs[eventConfigId]['args'][key.lower()] = options[key]
				if (eventConfigId.find('{') != -1):
					(superEventName, precondition) = eventConfigId.split('{', 1)
					if not rawEventConfigs[eventConfigId]['super']:
						rawEventConfigs[eventConfigId]['super'] = superEventName.strip()
					rawEventConfigs[eventConfigId]['precondition'] = precondition.replace('}', '').strip()
			except Exception, e:
				logger.error(u"Failed to parse event config '%s': %s" % (eventConfigId, forceUnicode(e)))

	def __inheritArgsFromSuperEvents(rawEventConfigsCopy, args, superEventConfigId):
		if not superEventConfigId in rawEventConfigsCopy.keys():
			logger.error(u"Super event '%s' not found" % superEventConfigId)
			return args
		superArgs = pycopy.deepcopy(rawEventConfigsCopy[superEventConfigId]['args'])
		if rawEventConfigsCopy[superEventConfigId]['super']:
			superArgs = __inheritArgsFromSuperEvents(rawEventConfigsCopy, superArgs, rawEventConfigsCopy[superEventConfigId]['super'])
		superArgs.update(args)
		return superArgs

	rawEventConfigsCopy = pycopy.deepcopy(rawEventConfigs)
	for eventConfigId in rawEventConfigs.keys():
		if rawEventConfigs[eventConfigId]['super']:
			rawEventConfigs[eventConfigId]['args'] = __inheritArgsFromSuperEvents(
									rawEventConfigsCopy,
									rawEventConfigs[eventConfigId]['args'],
									rawEventConfigs[eventConfigId]['super'])

	eventConfigs = {}
	for (eventConfigId, rawEventConfig) in rawEventConfigs.items():
		try:
			if (rawEventConfig['args'].get('type', 'template').lower() == 'template'):
				continue

			if not rawEventConfig['active']:
				logger.notice(u"Event config '%s' is deactivated" % eventConfigId)
				continue

			eventConfigs[eventConfigId] = {'preconditions': {}}
			if rawEventConfig.get('precondition'):
				precondition = preconditions.get(rawEventConfig['precondition'])
				if not precondition:
					logger.error(u"Precondition '%s' referenced by event config '%s' not found" % (precondition, eventConfigId))
				else:
					eventConfigs[eventConfigId]['preconditions'] = precondition

			for (key, value) in rawEventConfig['args'].items():
				try:
					if   (key == 'type'):
						eventConfigs[eventConfigId]['type'] = value
					elif (key == 'wql'):
						eventConfigs[eventConfigId]['wql'] = value
					elif key.startswith('action_message') or key.startswith('message'):
						mLanguage = None
						try:
							mLanguage = key.split('[')[1].split(']')[0].strip().lower()
						except Exception:
							pass
						if mLanguage:
							if (mLanguage == getLanguage()):
								eventConfigs[eventConfigId]['actionMessage'] = value
						elif not eventConfigs[eventConfigId].get('actionMessage'):
							eventConfigs[eventConfigId]['actionMessage'] = value
					elif key.startswith('shutdown_warning_message'):
						mLanguage = None
						try:
							mLanguage = key.split('[')[1].split(']')[0].strip().lower()
						except Exception:
							pass
						if mLanguage:
							if (mLanguage == getLanguage()):
								eventConfigs[eventConfigId]['shutdownWarningMessage'] = value
						elif not eventConfigs[eventConfigId].get('shutdownWarningMessage'):
							eventConfigs[eventConfigId]['shutdownWarningMessage'] = value
					elif key.startswith('name'):
						mLanguage = None
						try:
							mLanguage = key.split('[')[1].split(']')[0].strip().lower()
						except Exception:
							pass
						if mLanguage:
							if (mLanguage == getLanguage()):
								eventConfigs[eventConfigId]['name'] = value
						elif not eventConfigs[eventConfigId].get('name'):
							eventConfigs[eventConfigId]['name'] = value
					elif (key == 'interval'):
						eventConfigs[eventConfigId]['interval'] = int(value)
					elif (key == 'max_repetitions'):
						eventConfigs[eventConfigId]['maxRepetitions'] = int(value)
					elif (key == 'activation_delay'):
						eventConfigs[eventConfigId]['activationDelay'] = int(value)
					elif (key == 'notification_delay'):
						eventConfigs[eventConfigId]['notificationDelay'] = int(value)
					elif (key == 'action_warning_time'):
						eventConfigs[eventConfigId]['actionWarningTime'] = int(value)
					elif (key == 'action_user_cancelable'):
						eventConfigs[eventConfigId]['actionUserCancelable'] = int(value)
					elif (key == 'shutdown'):
						eventConfigs[eventConfigId]['shutdown'] = unicode(value).lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'reboot'):
						eventConfigs[eventConfigId]['reboot'] = unicode(value).lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'shutdown_warning_time'):
						eventConfigs[eventConfigId]['shutdownWarningTime'] = int(value)
					elif (key == 'shutdown_warning_repetition_time'):
						eventConfigs[eventConfigId]['shutdownWarningRepetitionTime'] = int(value)
					elif (key == 'shutdown_user_cancelable'):
						eventConfigs[eventConfigId]['shutdownUserCancelable'] = int(value)
					elif (key == 'block_login'):
						eventConfigs[eventConfigId]['blockLogin'] = unicode(value).lower() not in ('0', 'false', 'off', 'no')
					elif (key == 'lock_workstation'):
						eventConfigs[eventConfigId]['lockWorkstation'] = unicode(value).lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'logoff_current_user'):
						eventConfigs[eventConfigId]['logoffCurrentUser'] = unicode(value).lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'process_shutdown_requests'):
						eventConfigs[eventConfigId]['processShutdownRequests'] = unicode(value).lower() not in ('0', 'false', 'off', 'no')
					elif (key == 'get_config_from_service'):
						eventConfigs[eventConfigId]['getConfigFromService'] = unicode(value).lower() not in ('0', 'false', 'off', 'no')
					elif (key == 'update_config_file'):
						eventConfigs[eventConfigId]['updateConfigFile'] = unicode(value).lower() not in ('0', 'false', 'off', 'no')
					elif (key == 'write_log_to_service'):
						eventConfigs[eventConfigId]['writeLogToService'] = unicode(value).lower() not in ('0', 'false', 'off', 'no')
					elif (key == 'cache_products'):
						eventConfigs[eventConfigId]['cacheProducts'] = unicode(value).lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'cache_max_bandwidth'):
						eventConfigs[eventConfigId]['cacheMaxBandwidth'] = int(value)
					elif (key == 'cache_dynamic_bandwidth'):
						eventConfigs[eventConfigId]['cacheDynamicBandwidth'] = unicode(value).lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'use_cached_products'):
						eventConfigs[eventConfigId]['useCachedProducts'] = unicode(value).lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'sync_config_from_server'):
						eventConfigs[eventConfigId]['syncConfigFromServer'] = unicode(value).lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'sync_config_to_server'):
						eventConfigs[eventConfigId]['syncConfigToServer'] = unicode(value).lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'post_sync_config_from_server'):
						eventConfigs[eventConfigId]['postSyncConfigFromServer'] = unicode(value).lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'post_sync_config_to_server'):
						eventConfigs[eventConfigId]['postSyncConfigToServer'] = unicode(value).lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'use_cached_config'):
						eventConfigs[eventConfigId]['useCachedConfig'] = unicode(value).lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'update_action_processor'):
						eventConfigs[eventConfigId]['updateActionProcessor'] = unicode(value).lower() not in ('0', 'false', 'off', 'no')
					elif (key == 'action_type'):
						eventConfigs[eventConfigId]['actionType'] = unicode(value).lower()
					elif (key == 'event_notifier_command'):
						eventConfigs[eventConfigId]['eventNotifierCommand'] = config.replace(unicode(value).lower(), escaped=True)
					elif (key == 'event_notifier_desktop'):
						eventConfigs[eventConfigId]['eventNotifierDesktop'] = unicode(value).lower()
					elif (key == 'process_actions'):
						eventConfigs[eventConfigId]['processActions'] = unicode(value).lower() not in ('0', 'false', 'off', 'no')
					elif (key == 'action_notifier_command'):
						eventConfigs[eventConfigId]['actionNotifierCommand'] = config.replace(unicode(value).lower(), escaped=True)
					elif (key == 'action_notifier_desktop'):
						eventConfigs[eventConfigId]['actionNotifierDesktop'] = unicode(value).lower()
					elif (key == 'action_processor_command'):
						eventConfigs[eventConfigId]['actionProcessorCommand'] = unicode(value).lower()
					elif (key == 'action_processor_desktop'):
						eventConfigs[eventConfigId]['actionProcessorDesktop'] = unicode(value).lower()
					elif (key == 'action_processor_timeout'):
						eventConfigs[eventConfigId]['actionProcessorTimeout'] = int(value)
					elif (key == 'trusted_installer_detection'):
						eventConfigs[eventConfigId]['trustedInstallerDetection'] = forceBool(value)
					elif (key == 'shutdown_notifier_command'):
						eventConfigs[eventConfigId]['shutdownNotifierCommand'] = config.replace(unicode(value).lower(), escaped=True)
					elif (key == 'shutdown_notifier_desktop'):
						eventConfigs[eventConfigId]['shutdownNotifierDesktop'] = unicode(value).lower()
					elif (key == 'pre_action_processor_command'):
						eventConfigs[eventConfigId]['preActionProcessorCommand'] = config.replace(unicode(value).lower(), escaped=True)
					elif (key == 'post_action_processor_command'):
						eventConfigs[eventConfigId]['postActionProcessorCommand'] = config.replace(unicode(value).lower(), escaped=True)
					elif (key == 'trusted_installer_check'):
						eventConfigs[eventConfigId]['trustedInstallerCheck'] = unicode(value).lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'action_processor_productids'):
						eventConfigs[eventConfigId]['actionProcessorProductIds'] = forceList(value.strip().split(","))
					elif (key == 'exclude_product_group_ids'):
						eventConfigs[eventConfigId]['excludeProductGroupIds'] = forceList(value)
					elif (key == 'include_product_group_ids'):
						eventConfigs[eventConfigId]['includeProductGroupIds'] = forceList(value)
					elif (key == 'working_window'):
						eventConfigs[eventConfigId]['workingWindow'] = unicode(value)
					else:
						logger.error(u"Skipping unknown option '%s' in definition of event '%s'" % (key, eventConfigId))
				except Exception, e:
					logger.logException(e, LOG_DEBUG)
					logger.error(u"Failed to set event config argument '%s' to '%s': %s" % (key, value, e))

			logger.info(u"\nEvent config '" + eventConfigId + u"' args:\n" + objectToBeautifiedText(eventConfigs[eventConfigId]) + u"\n")
		except Exception, e:
			logger.logException(e)
	return eventConfigs


eventGenerators = {}
def createEventGenerators():
	global eventGenerators
	eventGenerators['panic'] = EventGeneratorFactory(
		PanicEventConfig('panic', actionProcessorCommand=config.get('action_processor', 'command', raw=True))
	)

	for (eventConfigId, eventConfig) in getEventConfigs().items():
		mainEventConfigId = eventConfigId.split('{')[0]
		if (mainEventConfigId == eventConfigId):
			try:
				eventType = eventConfig['type']
				del eventConfig['type']
				ec = EventConfigFactory(eventType, eventConfigId, **eventConfig)
				eventGenerators[mainEventConfigId] = EventGeneratorFactory(ec)
				logger.notice("Event generator '%s' created" % mainEventConfigId)
			except Exception, e:
				logger.error(u"Failed to create event generator '%s': %s" % (mainEventConfigId, forceUnicode(e)))

	for (eventConfigId, eventConfig) in getEventConfigs().items():
		mainEventConfigId = eventConfigId.split('{')[0]
		eventType = eventConfig['type']
		del eventConfig['type']
		ec = EventConfigFactory(eventType, eventConfigId, **eventConfig)
		if mainEventConfigId not in eventGenerators:
			try:
				eventGenerators[mainEventConfigId] = EventGeneratorFactory(ec)
				logger.notice("Event generator '%s' created" % mainEventConfigId)
			except Exception, e:
				logger.error(u"Failed to create event generator '%s': %s" % (mainEventConfigId, forceUnicode(e)))

		try:
			eventGenerators[mainEventConfigId].addEventConfig(ec)
			logger.notice("Event config '%s' added to event generator '%s'" % (eventConfigId, mainEventConfigId))
		except Exception, e:
			logger.error(u"Failed to add event config '%s' to event generator '%s': %s" % (eventConfigId, mainEventConfigId, forceUnicode(e)))


def getEventGenerators(generatorClass=None):
	global eventGenerators
	egs = []
	for eventGenerator in eventGenerators.values():
		if not generatorClass or isinstance(eventGenerator, generatorClass):
			egs.append(eventGenerator)
	return egs


def reconfigureEventGenerators():
	global eventGenerators
	eventConfigs = getEventConfigs()
	for eventGenerator in eventGenerators.values():
		eventGenerator.setEventConfigs([])
	for (eventConfigId, eventConfig) in eventConfigs.items():
		mainEventConfigId = eventConfigId.split('{')[0]
		try:
			eventGenerator = eventGenerators.get(mainEventConfigId)
			if not eventGenerator:
				logger.info(u"Cannot reconfigure event generator '%s': not found" % mainEventConfigId)
				continue
			eventType = eventConfig['type']
			del eventConfig['type']
			ec = EventConfigFactory(eventType, eventConfigId, **eventConfig)
			eventGenerator.addEventConfig(ec)
			logger.notice("Event config '%s' added to event generator '%s'" % (eventConfigId, mainEventConfigId))
		except Exception, e:
			logger.error(u"Failed to reconfigure event generator '%s': %s" % (mainEventConfigId, forceUnicode(e)))
