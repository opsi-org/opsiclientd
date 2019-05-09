# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org
# Copyright (C) 2010-2018 uib GmbH <info@uib.de>

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
:license: GNU Affero General Public License version 3
"""

import copy as pycopy
import os
import re
import sys
import thread
import threading
import time

from OPSI import System
from OPSI.Logger import Logger, LOG_DEBUG
from OPSI.Types import forceList, forceUnicode
from OPSI.Util import objectToBeautifiedText

from ocdlib.Config import getLogFormat, Config
from ocdlib.State import State
from ocdlib.Localization import getLanguage

logger = Logger()
config = Config()
state = State()

# Possible event types
EVENT_CONFIG_TYPE_PRODUCT_SYNC_COMPLETED = u'sync completed'
EVENT_CONFIG_TYPE_SW_ON_DEMAND = u'sw on demand'
EVENT_CONFIG_TYPE_DAEMON_STARTUP = u'daemon startup'
EVENT_CONFIG_TYPE_DAEMON_SHUTDOWN = u'daemon shutdown'
EVENT_CONFIG_TYPE_GUI_STARTUP = u'gui startup'
EVENT_CONFIG_TYPE_PANIC = u'panic'
EVENT_CONFIG_TYPE_PROCESS_ACTION_REQUESTS = u'process action requests'
EVENT_CONFIG_TYPE_TIMER = u'timer'
EVENT_CONFIG_TYPE_USER_LOGIN = u'user login'
EVENT_CONFIG_TYPE_SYSTEM_SHUTDOWN = u'system shutdown'
EVENT_CONFIG_TYPE_CUSTOM = u'custom'

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                         EVENT CONFIG                                              -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
def EventConfigFactory(eventType, eventId, **kwargs):
	if   (eventType == EVENT_CONFIG_TYPE_PANIC):
		return PanicEventConfig(eventId, **kwargs)
	elif (eventType == EVENT_CONFIG_TYPE_DAEMON_STARTUP):
		return DaemonStartupEventConfig(eventId, **kwargs)
	elif (eventType == EVENT_CONFIG_TYPE_DAEMON_SHUTDOWN):
		return DaemonShutdownEventConfig(eventId, **kwargs)
	elif (eventType == EVENT_CONFIG_TYPE_GUI_STARTUP):
		return GUIStartupEventConfig(eventId, **kwargs)
	elif (eventType == EVENT_CONFIG_TYPE_TIMER):
		return TimerEventConfig(eventId, **kwargs)
	elif (eventType == EVENT_CONFIG_TYPE_PRODUCT_SYNC_COMPLETED):
		return SyncCompletedEventConfig(eventId, **kwargs)
	elif (eventType == EVENT_CONFIG_TYPE_PROCESS_ACTION_REQUESTS):
		return ProcessActionRequestsEventConfig(eventId, **kwargs)
	elif (eventType == EVENT_CONFIG_TYPE_USER_LOGIN):
		return UserLoginEventConfig(eventId, **kwargs)
	elif (eventType == EVENT_CONFIG_TYPE_SYSTEM_SHUTDOWN):
		return SystemShutdownEventConfig(eventId, **kwargs)
	elif (eventType == EVENT_CONFIG_TYPE_CUSTOM):
		return CustomEventConfig(eventId, **kwargs)
	elif (eventType == EVENT_CONFIG_TYPE_SW_ON_DEMAND):
		return SwOnDemandEventConfig(eventId, **kwargs)
	else:
		raise TypeError(u"Unknown event config type '%s'" % eventType)

class EventConfig(object):
	def __init__(self, eventId, **kwargs):
		if not eventId:
			raise TypeError(u"Event id not given")
		self._id = unicode(eventId)

		logger.setLogFormat(getLogFormat(u'event config ' + self._id), object=self)
		self.setConfig(kwargs)

	def getConfig(self):
		config = {}
		for (k, v) in self.__dict__.items():
			if not k.startswith('_'):
				config[k] = v
		return config

	def setConfig(self, conf):
		self.name                          =  unicode ( conf.get('name',            self._id.split('{')[0]  ) )
		self.preconditions                 =     dict ( conf.get('preconditions',                 {}        ) )
		self.actionMessage                 =  unicode ( conf.get('actionMessage',               ''        ) )
		self.maxRepetitions                =      int ( conf.get('maxRepetitions',                -1        ) )
		# wait <activationDelay> seconds before event gets active
		self.activationDelay               =      int ( conf.get('activationDelay',               0         ) )
		# wait <notificationDelay> seconds before event is fired
		self.notificationDelay             =      int ( conf.get('notificationDelay',             0         ) )
		self.interval                      =      int ( conf.get('interval',                      -1        ) )
		self.actionWarningTime             =      int ( conf.get('actionWarningTime',             0         ) )
		self.actionUserCancelable          =      int ( conf.get('actionUserCancelable',          0         ) )
		self.shutdown                      =     bool ( conf.get('shutdown',                      False     ) )
		self.reboot                        =     bool ( conf.get('reboot',                        False     ) )
		self.shutdownWarningMessage        =  unicode ( conf.get('shutdownWarningMessage',        ''        ) )
		self.shutdownWarningTime           =      int ( conf.get('shutdownWarningTime',           0         ) )
		self.shutdownWarningRepetitionTime =      int ( conf.get('shutdownWarningRepetitionTime', 3600      ) )
		self.shutdownUserCancelable        =      int ( conf.get('shutdownUserCancelable',        0         ) )
		self.shutdownCancelCounter         =      int ( conf.get('shutdownCancelCounter',         0         ) )
		self.blockLogin                    =     bool ( conf.get('blockLogin',                    False     ) )
		self.logoffCurrentUser             =     bool ( conf.get('logoffCurrentUser',             False     ) )
		self.lockWorkstation               =     bool ( conf.get('lockWorkstation',               False     ) )
		self.processShutdownRequests       =     bool ( conf.get('processShutdownRequests',       True      ) )
		self.getConfigFromService          =     bool ( conf.get('getConfigFromService',          True      ) )
		self.updateConfigFile              =     bool ( conf.get('updateConfigFile',              True      ) )
		self.writeLogToService             =     bool ( conf.get('writeLogToService',             True      ) )
		self.updateActionProcessor         =     bool ( conf.get('updateActionProcessor',         True      ) )
		self.actionType                    =  unicode ( conf.get('actionType',                    ''        ) )
		self.eventNotifierCommand          =  unicode ( conf.get('eventNotifierCommand',          ''        ) )
		self.eventNotifierDesktop          =  unicode ( conf.get('eventNotifierDesktop',          'current' ) )
		self.actionNotifierCommand         =  unicode ( conf.get('actionNotifierCommand',         ''        ) )
		self.actionNotifierDesktop         =  unicode ( conf.get('actionNotifierDesktop',         'current' ) )
		self.shutdownNotifierCommand       =  unicode ( conf.get('shutdownNotifierCommand',       ''        ) )
		self.shutdownNotifierDesktop       =  unicode ( conf.get('shutdownNotifierDesktop',       'current' ) )
		self.processActions                =     bool ( conf.get('processActions',                True      ) )
		self.actionProcessorCommand        =  unicode ( conf.get('actionProcessorCommand',        ''        ) )
		self.actionProcessorDesktop        =  unicode ( conf.get('actionProcessorDesktop',        'current' ) )
		self.actionProcessorTimeout        =      int ( conf.get('actionProcessorTimeout',        3*3600    ) )
		self.actionProcessorProductIds     =     list ( conf.get('actionProcessorProductIds',     []        ) )
		self.excludeProductGroupIds        =     list ( conf.get('excludeProductGroupIds',     []        ) )
		self.includeProductGroupIds        =     list ( conf.get('includeProductGroupIds',     []        ) )
		self.preActionProcessorCommand     =  unicode ( conf.get('preActionProcessorCommand',     ''        ) )
		self.postActionProcessorCommand    =  unicode ( conf.get('postActionProcessorCommand',    ''        ) )
		#self.serviceOptions                =     dict ( conf.get('serviceOptions',                {}        ) )
		self.cacheProducts                 =     bool ( conf.get('cacheProducts',                 False     ) )
		self.cacheMaxBandwidth             =      int ( conf.get('cacheMaxBandwidth',             0         ) )
		self.cacheDynamicBandwidth         =     bool ( conf.get('cacheDynamicBandwidth',         True      ) )
		self.useCachedProducts             =     bool ( conf.get('useCachedProducts',             False     ) )
		self.syncConfigToServer            =     bool ( conf.get('syncConfigToServer',            False     ) )
		self.syncConfigFromServer          =     bool ( conf.get('syncConfigFromServer',          False     ) )
		self.postSyncConfigToServer        =     bool ( conf.get('postSyncConfigToServer',        False     ) )
		self.postSyncConfigFromServer      =     bool ( conf.get('postSyncConfigFromServer',      False     ) )
		self.useCachedConfig               =     bool ( conf.get('useCachedConfig',               False     ) )

		###if not self.eventNotifierDesktop in ('winlogon', 'default', 'current'):
		###	logger.error(u"Bad value '%s' for eventNotifierDesktop" % self.eventNotifierDesktop)
		###	self.eventNotifierDesktop = 'current'
		###if not self.actionNotifierDesktop in ('winlogon', 'default', 'current'):
		###	logger.error(u"Bad value '%s' for actionNotifierDesktop" % self.actionNotifierDesktop)
		###	self.actionNotifierDesktop = 'current'
		###if not self.actionProcessorDesktop in ('winlogon', 'default', 'current'):
		###	logger.error(u"Bad value '%s' for actionProcessorDesktop" % self.actionProcessorDesktop)
		###	self.actionProcessorDesktop = 'current'

	def __unicode__(self):
		return u"<EventConfig: %s>" % self._id

	__repr__ = __unicode__

	def __str__(self):
		return str(self.__unicode__())

	def getId(self):
		return self._id

	def getName(self):
		return self.name

	def getActionMessage(self):
		message = self.actionMessage
		def toUnderscore(value):
			s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', value)
			return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
		for (key, value) in self.__dict__.items():
			if (key.lower().find('message') != -1):
				continue
			message = message.replace('%' + key + '%', unicode(value))
			message = message.replace('%' + toUnderscore(key) + '%', unicode(value))
		while True:
			match = re.search('(%state.[^%]+%)', message)
			if not match:
				break
			name = match.group(1).replace('%state.', '')[:-1]
			message = message.replace(match.group(1), forceUnicode(state.get(name)))
		return message

	def getShutdownWarningMessage(self):
		message = self.shutdownWarningMessage
		def toUnderscore(value):
			s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', value)
			return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
		for (key, value) in self.__dict__.items():
			if (key.lower().find('message') != -1):
				continue
			message = message.replace('%' + key + '%', unicode(value))
			message = message.replace('%' + toUnderscore(key) + '%', unicode(value))
		while True:
			match = re.search('(%state.[^%]+%)', message)
			if not match:
				break
			name = match.group(1).replace('%state.', '')[:-1]
			message = message.replace(match.group(1), forceUnicode(state.get(name)))
		return message

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                         PANIC EVENT CONFIG                                        -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class PanicEventConfig(EventConfig):
	def setConfig(self, conf):
		EventConfig.setConfig(self, conf)
		self.maxRepetitions          = -1
		self.actionMessage           = 'Panic event'
		self.activationDelay         = 0
		self.notificationDelay       = 0
		self.actionWarningTime       = 0
		self.actionUserCancelable    = False
		self.blockLogin              = False
		self.logoffCurrentUser       = False
		self.lockWorkstation         = False
		self.getConfigFromService    = False
		self.updateConfigFile        = False
		self.writeLogToService       = False
		self.updateActionProcessor   = False
		self.eventNotifierCommand    = None
		self.actionNotifierCommand   = None
		self.shutdownNotifierCommand = None
		self.actionProcessorDesktop  = 'winlogon'
		#self.serviceOptions          = {}

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                     DAEMON STARTUP EVENT CONFIG                                   -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class DaemonStartupEventConfig(EventConfig):
	def setConfig(self, conf):
		EventConfig.setConfig(self, conf)
		self.maxRepetitions = 0

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                    DAEMON SHUTDOWN EVENT CONFIG                                   -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class DaemonShutdownEventConfig(EventConfig):
	def setConfig(self, conf):
		EventConfig.setConfig(self, conf)
		self.maxRepetitions = 0

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                          WMI EVENT CONFIG                                         -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class WMIEventConfig(EventConfig):
	def setConfig(self, conf):
		EventConfig.setConfig(self, conf)
		self.wql = unicode( conf.get('wql', '') )

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                      GUI STARTUP EVENT CONFIG                                     -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class GUIStartupEventConfig(WMIEventConfig):
	def setConfig(self, conf):
		WMIEventConfig.setConfig(self, conf)
		self.maxRepetitions = 0
		self.processName = None

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                         TIMER EVENT CONFIG                                        -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class TimerEventConfig(EventConfig):
	pass

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                PRODUCT SYNC COMPLETED EVENT CONFIG                                -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class SyncCompletedEventConfig(EventConfig):
	pass

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                               PROCESS ACTION REQUESTS EVENT CONFIG                                -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ProcessActionRequestsEventConfig(EventConfig):
	pass

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                       USER LOGIN EVENT CONFIG                                     -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class UserLoginEventConfig(WMIEventConfig):
	def setConfig(self, conf):
		WMIEventConfig.setConfig(self, conf)
		self.blockLogin        = False
		self.logoffCurrentUser = False
		self.lockWorkstation   = False

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                    SYSTEM SHUTDOWN EVENT CONFIG                                   -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class SystemShutdownEventConfig(WMIEventConfig):
	def setConfig(self, conf):
		WMIEventConfig.setConfig(self, conf)
		self.maxRepetitions = 0

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                        CUSTOM EVENT CONFIG                                        -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class CustomEventConfig(WMIEventConfig):
	pass

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                     SW ON DEMAND EVENT CONFIG                                     -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class SwOnDemandEventConfig(EventConfig):
	pass


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                          EVENT GENERATOR                                          -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
def EventGeneratorFactory(eventConfig):
	if   isinstance(eventConfig, PanicEventConfig):
		return PanicEventGenerator(eventConfig)
	elif isinstance(eventConfig, DaemonStartupEventConfig):
		return DaemonStartupEventGenerator(eventConfig)
	elif isinstance(eventConfig, DaemonShutdownEventConfig):
		return DaemonShutdownEventGenerator(eventConfig)
	elif isinstance(eventConfig, GUIStartupEventConfig):
		return GUIStartupEventGenerator(eventConfig)
	elif isinstance(eventConfig, TimerEventConfig):
		return TimerEventGenerator(eventConfig)
	elif isinstance(eventConfig, SyncCompletedEventConfig):
		return SyncCompletedEventGenerator(eventConfig)
	elif isinstance(eventConfig, ProcessActionRequestsEventConfig):
		return ProcessActionRequestsEventGenerator(eventConfig)
	elif isinstance(eventConfig, UserLoginEventConfig):
		return UserLoginEventGenerator(eventConfig)
	elif isinstance(eventConfig, SystemShutdownEventConfig):
		return SystemShutdownEventGenerator(eventConfig)
	elif isinstance(eventConfig, CustomEventConfig):
		return CustomEventGenerator(eventConfig)
	elif isinstance(eventConfig, SwOnDemandEventConfig):
		return SwOnDemandEventGenerator(eventConfig)
	else:
		raise TypeError(u"Unhandled event config '%s'" % eventConfig)

class EventGenerator(threading.Thread):
	def __init__(self, generatorConfig):
		threading.Thread.__init__(self)
		self._eventConfigs = []
		self._generatorConfig = generatorConfig
		self._eventListeners = []
		self._eventsOccured = 0
		self._threadId = None
		self._stopped = False
		self._event = None
		self._lastEventOccurence = None
		logger.setLogFormat(getLogFormat(u'event generator ' + self._generatorConfig.getId()), object=self)

	def __unicode__(self):
		return u'<%s %s>' % (self.__class__.__name__, self._generatorConfig.getId())

	__repr__ = __unicode__

	def setEventConfigs(self, eventConfigs):
		self._eventConfigs = forceList(eventConfigs)

	def addEventConfig(self, eventConfig):
		self._eventConfigs.append(eventConfig)

	def _preconditionsFulfilled(self, preconditions):
		for (k, v) in preconditions.items():
			if (bool(v) != state.get(k)):
				return False
		return True

	def addEventListener(self, eventListener):
		if not isinstance(eventListener, EventListener):
			raise TypeError(u"Failed to add event listener, got class %s, need class EventListener" % eventListener.__class__)

		for l in self._eventListeners:
			if (l == eventListener):
				return

		self._eventListeners.append(eventListener)

	def getEventConfig(self):
		logger.info(u"Testing preconditions of configs: %s" % self._eventConfigs)
		actualConfig = { 'preconditions': {}, 'config': None }
		for pec in self._eventConfigs:
			if self._preconditionsFulfilled(pec.preconditions):
				logger.info(u"Preconditions %s for event config '%s' fulfilled" % (pec.preconditions, pec.getId()))
				if not actualConfig['config'] or (len(pec.preconditions.keys()) > len(actualConfig['preconditions'].keys())):
					actualConfig = { 'preconditions': pec.preconditions, 'config': pec }
			else:
				logger.info(u"Preconditions %s for event config '%s' not fulfilled" % (pec.preconditions, pec.getId()))
		return actualConfig['config']

	def createAndFireEvent(self, eventInfo={}):
		self.fireEvent(self.createEvent(eventInfo))

	def createEvent(self, eventInfo={}):
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None
		return Event(eventConfig = eventConfig, eventInfo = eventInfo)

	def initialize(self):
		pass

	def getNextEvent(self):
		self._event = threading.Event()
		self._event.wait()

	def cleanup(self):
		pass

	def fireEvent(self, event=None):
		if self._stopped:
			return

		if not event:
			logger.info(u"No event to fire")
			return

		self._lastEventOccurence = time.time()

		logger.info(u"Firing event '%s'" % event)
		logger.info(u"Event info:")
		for (key, value) in event.eventInfo.items():
			logger.info(u"     %s: %s" % (key, value))

		class FireEventThread(threading.Thread):
			def __init__(self, eventListener, event):
				threading.Thread.__init__(self)
				self._eventListener = eventListener
				self._event = event
				logger.setLogFormat(getLogFormat(u'event generator ' + self._event.eventConfig.getId()), object=self)

			def run(self):
				if (self._event.eventConfig.notificationDelay > 0):
					logger.debug(u"Waiting %d seconds before notifying listener '%s' of event '%s'" \
						% (self._event.eventConfig.notificationDelay, self._eventListener, self._event))
					time.sleep(self._event.eventConfig.notificationDelay)
				try:
					logger.info(u"Calling processEvent on listener %s" % self._eventListener)
					self._eventListener.processEvent(self._event)
				except Exception, e:
					logger.logException(e)

		logger.info(u"Starting FireEventThread for listeners: %s" % self._eventListeners)
		for l in self._eventListeners:
			# Create a new thread for each event listener
			FireEventThread(l, event).start()

	def run(self):
		self._threadId = thread.get_ident()
		try:
			logger.info(u"Initializing event generator '%s'" % self)
			self.initialize()

			if (self._generatorConfig.activationDelay > 0):
				logger.debug(u"Waiting %d seconds before activation of event generator '%s'" % \
					(self._generatorConfig.activationDelay, self))
				time.sleep(self._generatorConfig.activationDelay)

			logger.info(u"Activating event generator '%s'" % self)
			while not self._stopped and ( (self._generatorConfig.maxRepetitions < 0) or (self._eventsOccured <= self._generatorConfig.maxRepetitions) ):
				logger.info(u"Getting next event...")
				event = self.getNextEvent()
				self._eventsOccured += 1
				self.fireEvent(event)
			logger.info(u"Event generator '%s' now deactivated after %d event occurrences" % (self, self._eventsOccured))

		except Exception, e:
			logger.error(u"Failure in event generator '%s': %s" % (self, forceUnicode(e)))
			logger.logException(e)

		try:
			self.cleanup()
		except Exception, e:
			logger.error(u"Failed to clean up: %s" % forceUnicode(e))

		logger.info(u"Event generator '%s' exiting " % self)

	def stop(self):
		self._stopped = True
		if self._event:
			self._event.set()

class PanicEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)

	def createEvent(self, eventInfo={}):
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None
		return PanicEvent(eventConfig = eventConfig, eventInfo = eventInfo)

class DaemonStartupEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)

	def createEvent(self, eventInfo={}):
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None
		return DaemonStartupEvent(eventConfig = eventConfig, eventInfo = eventInfo)

class DaemonShutdownEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)

	def createEvent(self, eventInfo={}):
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None
		return DaemonShutdownEvent(eventConfig = eventConfig, eventInfo = eventInfo)

class WMIEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)
		self._wql = self._generatorConfig.wql
		self._watcher = None

	def initialize(self):
		if not (os.name == 'nt'):
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
		from ocdlib.Windows import importWmiAndPythoncom
		(wmi, pythoncom) = importWmiAndPythoncom()
		pythoncom.CoUninitialize()

class GUIStartupEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)
		if   (os.name == 'nt') and (sys.getwindowsversion()[0] == 5):
			self.guiProcessName = u'winlogon.exe'
		elif (os.name == 'nt') and (sys.getwindowsversion()[0] == 6):
			self.guiProcessName = u'LogonUI.exe'
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

class SensLogonEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)

	def initialize(self):
		EventGenerator.initialize(self)
		if not (os.name == 'nt'):
			return

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
		if (os.name == 'nt') and (sys.getwindowsversion()[0] == 6):
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
		#if (eventType == 'StartShell'):

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

class SystemShutdownEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)

class CustomEventGenerator(WMIEventGenerator):
	def __init__(self, eventConfig):
		WMIEventGenerator.__init__(self, eventConfig)

	def createEvent(self, eventInfo={}):
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None
		return CustomEvent(eventConfig = eventConfig, eventInfo = eventInfo)

class SwOnDemandEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)

	def createEvent(self, eventInfo={}):
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None
		return SwOnDemandEvent(eventConfig = eventConfig, eventInfo = eventInfo)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                            EVENT                                                  -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class Event(object):
	def __init__(self, eventConfig, eventInfo={}):
		self.eventConfig = eventConfig
		self.eventInfo = eventInfo
		logger.setLogFormat(getLogFormat(u'event generator ' + self.eventConfig.getId()), object=self)

	def getActionProcessorCommand(self):
		actionProcessorCommand = self.eventConfig.actionProcessorCommand
		for (key, value) in self.eventInfo.items():
			actionProcessorCommand = actionProcessorCommand.replace(u'%' + u'event.' + unicode(key.lower()) + u'%', unicode(value))
		return actionProcessorCommand

class PanicEvent(Event):
	def __init__(self, eventConfig, eventInfo={}):
		Event.__init__(self, eventConfig, eventInfo)

class DaemonStartupEvent(Event):
	def __init__(self, eventConfig, eventInfo={}):
		Event.__init__(self, eventConfig, eventInfo)

class DaemonShutdownEvent(Event):
	def __init__(self, eventConfig, eventInfo={}):
		Event.__init__(self, eventConfig, eventInfo)

class GUIStartupEvent(Event):
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

class UserLoginEvent(Event):
	def __init__(self, eventConfig, eventInfo={}):
		Event.__init__(self, eventConfig, eventInfo)

class SystemShutdownEvent(Event):
	def __init__(self, eventConfig, eventInfo={}):
		Event.__init__(self, eventConfig, eventInfo)

class CustomEvent(Event):
	def __init__(self, eventConfig, eventInfo={}):
		Event.__init__(self, eventConfig, eventInfo)

class SwOnDemandEvent(Event):
	def __init__(self, eventConfig, eventInfo={}):
		Event.__init__(self, eventConfig, eventInfo)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                          EVENT LISTENER                                           -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class EventListener(object):
	def __init__(self):
		logger.debug(u"EventListener initiated")

	def processEvent(self, event):
		logger.warning(u"%s: processEvent() not implemented" % self)



# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                          EVENT GENERATOR                                          -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
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

			#if not rawEventConfig['args'].get('action_processor_command'):
			#	rawEventConfig['args']['action_processor_command'] = config.get('action_processor', 'command')

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
					elif (key == 'shutdown_notifier_command'):
						eventConfigs[eventConfigId]['shutdownNotifierCommand'] = config.replace(unicode(value).lower(), escaped=True)
					elif (key == 'shutdown_notifier_desktop'):
						eventConfigs[eventConfigId]['shutdownNotifierDesktop'] = unicode(value).lower()
					#elif (key == 'service_options'):
					#	eventConfigs[eventConfigId]['serviceOptions'] = eval(value)
					elif (key == 'pre_action_processor_command'):
						eventConfigs[eventConfigId]['preActionProcessorCommand'] = config.replace(unicode(value).lower(), escaped=True)
					elif (key == 'post_action_processor_command'):
						eventConfigs[eventConfigId]['postActionProcessorCommand'] = config.replace(unicode(value).lower(), escaped=True)
					elif (key == 'action_processor_productids'):
						eventConfigs[eventConfigId]['actionProcessorProductIds'] = forceList(value.strip().split(","))
					elif (key == 'exclude_product_group_ids'):
						eventConfigs[eventConfigId]['excludeProductGroupIds'] = forceList(value)
					elif (key == 'include_product_group_ids'):
						eventConfigs[eventConfigId]['includeProductGroupIds'] = forceList(value)
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
		PanicEventConfig('panic', actionProcessorCommand = config.get('action_processor', 'command', raw=True))
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
		if not eventGenerators.has_key(mainEventConfigId):
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
