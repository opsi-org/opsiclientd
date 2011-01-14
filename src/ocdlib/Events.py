# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = = = =
   =   ocdlib.Events                       =
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
import os, re
import copy as pycopy

# OPSI imports
from OPSI.Logger import *
from OPSI import System
from OPSI.Types import *

from ocdlib.Config import *
from ocdlib.Localization import _, setLocaleDir, getLanguage

logger = Logger()
config = Config()

# Possible event types
EVENT_CONFIG_TYPE_PRODUCT_SYNC_COMPLETED = u'product sync completed'
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
def EventConfigFactory(type, name, **kwargs):
	if   (type == EVENT_CONFIG_TYPE_PANIC):
		return PanicEventConfig(name, **kwargs)
	elif (type == EVENT_CONFIG_TYPE_DAEMON_STARTUP):
		return DaemonStartupEventConfig(name, **kwargs)
	elif (type == EVENT_CONFIG_TYPE_DAEMON_SHUTDOWN):
		return DaemonShutdownEventConfig(name, **kwargs)
	elif (type == EVENT_CONFIG_TYPE_GUI_STARTUP):
		return GUIStartupEventConfig(name, **kwargs)
	elif (type == EVENT_CONFIG_TYPE_TIMER):
		return TimerEventConfig(name, **kwargs)
	elif (type == EVENT_CONFIG_TYPE_PRODUCT_SYNC_COMPLETED):
		return ProductSyncCompletedEventConfig(name, **kwargs)
	elif (type == EVENT_CONFIG_TYPE_PROCESS_ACTION_REQUESTS):
		return ProcessActionRequestsEventConfig(name, **kwargs)
	elif (type == EVENT_CONFIG_TYPE_USER_LOGIN):
		return UserLoginEventConfig(name, **kwargs)
	elif (type == EVENT_CONFIG_TYPE_SYSTEM_SHUTDOWN):
		return SystemShutdownEventConfig(name, **kwargs)
	elif (type == EVENT_CONFIG_TYPE_CUSTOM):
		return CustomEventConfig(name, **kwargs)
	else:
		raise TypeError("Unknown event config type '%s'" % type)
	
class EventConfig(object):
	def __init__(self, name, **kwargs):
		
		if not name:
			raise TypeError("Name not given")
		self._name = unicode(name)
		
		moduleName = u' %-30s' % (u'event config ' + self._name)
		logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)
		self.setConfig(kwargs)
		
	def setConfig(self, conf):
		self.preconditions                 =     dict ( conf.get('preconditions',                 {}        ) )
		self.message                       =  unicode ( conf.get('message',                       ''        ) )
		self.maxRepetitions                =      int ( conf.get('maxRepetitions',                -1        ) )
		# wait <activationDelay> seconds before event gets active
		self.activationDelay               =      int ( conf.get('activationDelay',               0         ) )
		# wait <notificationDelay> seconds before event is fired
		self.notificationDelay             =      int ( conf.get('notificationDelay',             0         ) )
		self.warningTime                   =      int ( conf.get('warningTime',                   0         ) )
		self.userCancelable                =      int ( conf.get('userCancelable',                0         ) )
		self.cancelCounter                 =      int ( conf.get('cancelCounter',                 0         ) )
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
		self.actionProcessorCommand        =  unicode ( conf.get('actionProcessorCommand',        ''        ) )
		self.actionProcessorDesktop        =  unicode ( conf.get('actionProcessorDesktop',        'current' ) )
		self.actionProcessorTimeout        =      int ( conf.get('actionProcessorTimeout',        3*3600    ) )
		self.preActionProcessorCommand     =  unicode ( conf.get('preActionProcessorCommand',     ''        ) )
		self.postActionProcessorCommand    =  unicode ( conf.get('postActionProcessorCommand',    ''        ) )
		self.serviceOptions                =     dict ( conf.get('serviceOptions',                {}        ) )
		self.cacheProducts                 =     bool ( conf.get('cacheProducts',                 False     ) )
		self.cacheMaxBandwidth             =      int ( conf.get('cacheMaxBandwidth',             0         ) )
		self.requiresCachedProducts        =     bool ( conf.get('requiresCachedProducts',        False     ) )
		self.syncConfig                    =     bool ( conf.get('syncConfig',                    False     ) )
		self.useCachedConfig               =     bool ( conf.get('useCachedConfig',               False     ) )
		
		if not self.eventNotifierDesktop in ('winlogon', 'default', 'current'):
			logger.error(u"Bad value '%s' for eventNotifierDesktop" % self.eventNotifierDesktop)
			self.eventNotifierDesktop = 'current'
		if not self.actionNotifierDesktop in ('winlogon', 'default', 'current'):
			logger.error(u"Bad value '%s' for actionNotifierDesktop" % self.actionNotifierDesktop)
			self.actionNotifierDesktop = 'current'
		if not self.actionProcessorDesktop in ('winlogon', 'default', 'current'):
			logger.error(u"Bad value '%s' for actionProcessorDesktop" % self.actionProcessorDesktop)
			self.actionProcessorDesktop = 'current'
	
	def __unicode__(self):
		return u"<EventConfig: %s>" % self._name
	
	__repr__ = __unicode__
	
	def __str__(self):
		return str(self.__unicode__())
	
	def getName(self):
		return self._name
	
	def getMessage(self):
		message = self.message
		def toUnderscore(name):
			s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
			return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
		for (key, value) in self.__dict__.items():
			if (key.lower().find('message') != -1):
				continue
			message = message.replace('%' + key + '%', unicode(value))
			message = message.replace('%' + toUnderscore(key) + '%', unicode(value))
		return message
	
	def getShutdownWarningMessage(self):
		message = self.shutdownWarningMessage
		def toUnderscore(name):
			s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
			return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
		for (key, value) in self.__dict__.items():
			if (key.lower().find('message') != -1):
				continue
			message = message.replace('%' + key + '%', unicode(value))
			message = message.replace('%' + toUnderscore(key) + '%', unicode(value))
		return message
	
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                         PANIC EVENT CONFIG                                        -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class PanicEventConfig(EventConfig):
	def setConfig(self, conf):
		EventConfig.setConfig(self, conf)
		self.maxRepetitions          = -1
		self.message                 = 'Panic event'
		self.activationDelay         = 0
		self.notificationDelay       = 0
		self.warningTime             = 0
		self.userCancelable          = False
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
		self.serviceOptions          = {}

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
class ProductSyncCompletedEventConfig(EventConfig):
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
	elif isinstance(eventConfig, ProductSyncCompletedEventConfig):
		return ProductSyncCompletedEventGenerator(eventConfig)
	elif isinstance(eventConfig, ProcessActionRequestsEventConfig):
		return ProcessActionRequestsEventGenerator(eventConfig)
	elif isinstance(eventConfig, UserLoginEventConfig):
		return UserLoginEventGenerator(eventConfig)
	elif isinstance(eventConfig, SystemShutdownEventConfig):
		return SystemShutdownEventGenerator(eventConfig)
	elif isinstance(eventConfig, CustomEventConfig):
		return CustomEventGenerator(eventConfig)
	else:
		raise TypeError(u"Unhandled event config '%s'" % eventConfig)

class EventGenerator(threading.Thread):
	def __init__(self, eventConfig):
		threading.Thread.__init__(self)
		self._eventConfig = eventConfig
		self._preconditionEventConfigs = []
		self._eventListeners = []
		self._eventsOccured = 0
		self._threadId = None
		self._stopped = False
		self._event = None
		self._lastEventOccurence = None
		moduleName = u' %-30s' % (u'event generator ' + self._eventConfig.getName())
		logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)
	
	def __unicode__(self):
		return u'<%s %s>' % (self.__class__.__name__, self._eventConfig._name)
	
	__repr__ = __unicode__
	
	def setEventConfig(self, eventConfig):
		self._eventConfig = eventConfig
	
	def setPreconditionConfigs(self, preconditionEventConfigs):
		self._preconditionEventConfigs = forceList(preconditionEventConfigs)
	
	def addPreconditionConfig(self, preconditionEventConfig):
		self._preconditionEventConfigs.append(preconditionEventConfig)
	
	def _preconditionsFulfilled(self, preconditions):
		for (k, v) in preconditions.values():
			if (k == 'user_logged_in'):
				if (bool(v) != bool(System.getActiveSessionIds())):
					return False
		return True
		
	def addEventListener(self, eventListener):
		if not isinstance(eventListener, EventListener):
			raise TypeError(u"Failed to add event listener, got class %s, need class EventListener" % eventListener.__class__)
		
		for l in self._eventListeners:
			if (l == eventListener):
				return
		
		self._eventListeners.append(eventListener)
	
	def createEvent(self, eventInfo={}):
		eventConfig = self._eventConfig
		for pec in self._preconditionEventConfigs:
			if self._preconditionsFulfilled(pec['preconditions']):
				logger.notice(u"Preconditions for event config '%s' fulfilled" % pec.getName())
				eventConfig = pec
				break
			else:
				logger.debug(u"Preconditions for event config '%s' not fulfilled" % pec.getName())
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
			event = self.createEvent()
		
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
				moduleName = u' %-30s' % (u'event generator ' + self._event.eventConfig.getName())
				logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)
				
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
			
			if (self._eventConfig.activationDelay > 0):
				logger.debug(u"Waiting %d seconds before activation of event generator '%s'" % \
					(self._eventConfig.activationDelay, self))
				time.sleep(self.activationDelay)
			
			logger.info(u"Activating event generator '%s'" % self)
			while not self._stopped and ( (self._eventConfig.maxRepetitions < 0) or (self._eventsOccured <= self._eventConfig.maxRepetitions) ):
				logger.info(u"Getting next event...")
				event = self.getNextEvent()
				if event:
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
		return PanicEvent(eventConfig = self._eventConfig, eventInfo = eventInfo)
	
class DaemonStartupEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)
	
	def createEvent(self, eventInfo={}):
		return DaemonStartupEvent(eventConfig = self._eventConfig, eventInfo = eventInfo)
	
class DaemonShutdownEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)
	
	def createEvent(self, eventInfo={}):
		return DaemonShutdownEvent(eventConfig = self._eventConfig, eventInfo = eventInfo)
	
class WMIEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)
		self._wql = self._eventConfig.wql
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
				if type(value) is tuple:
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
		return GUIStartupEvent(eventConfig = self._eventConfig, eventInfo = eventInfo)
	
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
	
	def createEvent(self, eventInfo={}):
		return TimerEvent(eventConfig = self._eventConfig, eventInfo = eventInfo)
	
class ProductSyncCompletedEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)
	
	def createEvent(self, eventInfo={}):
		return ProductSyncCompletedEvent(eventConfig = self._eventConfig, eventInfo = eventInfo)
	
class ProcessActionRequestsEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)
	
	def createEvent(self, eventInfo={}):
		return ProcessActionRequestsEvent(eventConfig = self._eventConfig, eventInfo = eventInfo)

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
		if (eventType == 'Logon'):
		#if (eventType == 'StartShell'):
			logger.notice(u"User login detected: %s" % args[0])
			self._eventsOccured += 1
			self.fireEvent(self.createEvent(eventInfo = {'User': args[0]}))
			if (self._eventConfig.maxRepetitions > 0) and (self._eventsOccured > self._eventConfig.maxRepetitions):
				self.stop()
	
	def createEvent(self, eventInfo={}):
		return UserLoginEvent(eventConfig = self._eventConfig, eventInfo = eventInfo)

class SystemShutdownEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)

class CustomEventGenerator(WMIEventGenerator):
	def __init__(self, eventConfig):
		WMIEventGenerator.__init__(self, eventConfig)
		
	def createEvent(self, eventInfo={}):
		return CustomEvent(eventConfig = self._eventConfig, eventInfo = eventInfo)
	
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                            EVENT                                                  -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class Event(object):
	def __init__(self, eventConfig, eventInfo={}):
		self.eventConfig = eventConfig
		self.eventInfo = eventInfo
		moduleName = u' %-30s' % (u'event generator ' + self.eventConfig.getName())
		logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)
		
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

class ProductSyncCompletedEvent(Event):
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


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                          EVENT LISTENER                                           -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class EventListener(object):
	def __init__(self):
		logger.debug(u"EventListener initiated")
	
	def processEvent(event):
		logger.warning(u"%s: processEvent() not implemented" % self)
	


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                          EVENT GENERATOR                                          -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
def getEventConfigs():
	preconditions = {}
	for (section, options) in config.getDict().items():
		section = section.lower()
		if section.startswith('precondition_'):
			preconditionName = section.split('_', 1)[1]
			preconditions[preconditionName] = {}
			try:
				for key in options.keys():
					preconditions[preconditionName][key] = not options[key].lower() in ('0', 'false', 'off', 'no')
				logger.info(u"Precondition '%s' created: %s" % (preconditionName, preconditions[preconditionName]))
			except Exception, e:
				logger.error(u"Failed to parse precondition '%s': %s" % (preconditionName, forceUnicode(e)))
			
	rawEventConfigs = {}
	for (section, options) in config.getDict().items():
		section = section.lower()
		if section.startswith('event_'):
			eventConfigName = section.split('_', 1)[1]
			if not eventConfigName:
				logger.error(u"No event config name defined in section '%s'" % section)
				continue
			rawEventConfigs[eventConfigName] = {
				'active':       True,
				'args':         {},
				'super':        None,
				'precondition': None}
			try:
				for key in options.keys():
					if   (key.lower() == 'active'):
						rawEventConfigs[eventConfigName]['active'] = not options[key].lower() in ('0', 'false', 'off', 'no')
					elif (key.lower() == 'super'):
						rawEventConfigs[eventConfigName]['super'] = options[key]
					else:
						rawEventConfigs[eventConfigName]['args'][key.lower()] = options[key]
				if (eventConfigName.find('{') != -1):
					(superEventName, precondition) = eventConfigName.split('{', 1)
					rawEventConfigs[eventConfigName]['super'] = superEventName.strip()
					rawEventConfigs[eventConfigName]['precondition'] = precondition.replace('}', '').strip()
			except Exception, e:
				logger.error(u"Failed to parse event config '%s': %s" % (eventConfigName, forceUnicode(e)))
	
	def __inheritArgsFromSuperEvents(rawEventConfigsCopy, args, superEventConfigName):
		if not superEventConfigName in rawEventConfigsCopy.keys():
			logger.error(u"Super event '%s' not found" % superEventConfigName)
			return args
		superArgs = pycopy.deepcopy(rawEventConfigsCopy[superEventConfigName]['args'])
		if rawEventConfigsCopy[superEventConfigName]['super']:
			__inheritArgsFromSuperEvents(rawEventConfigsCopy, superArgs, rawEventConfigsCopy[superEventConfigName]['super'])
		superArgs.update(args)
		return superArgs
	
	rawEventConfigsCopy = pycopy.deepcopy(rawEventConfigs)
	for eventConfigName in rawEventConfigs.keys():
		if rawEventConfigs[eventConfigName]['super']:
			rawEventConfigs[eventConfigName]['args'] = __inheritArgsFromSuperEvents(
									rawEventConfigsCopy,
									rawEventConfigs[eventConfigName]['args'],
									rawEventConfigs[eventConfigName]['super'])
	
	eventConfigs = {}
	for (eventConfigName, rawEventConfig) in rawEventConfigs.items():
		try:
			if not rawEventConfig['active']:
				logger.notice(u"Event config '%s' is deactivated" % eventConfigName)
				continue
			
			if not rawEventConfig['args'].get('type'):
				logger.error(u"Event config '%s': event type not set" % eventConfigName)
				continue
			
			#if not rawEventConfig['args'].get('action_processor_command'):
			#	rawEventConfig['args']['action_processor_command'] = config.get('action_processor', 'command')
			
			eventConfigs[eventConfigName] = {}
			if rawEventConfig.get('precondition'):
				precondition = preconditions.get(rawEventConfig['precondition'])
				if not precondition:
					logger.error(u"Precondition '%s' referenced by event config '%s' not found" % (precondition, eventConfigName))
				else:
					eventConfigs[eventConfigName]['preconditions'] = precondition
			
			for (key, value) in rawEventConfig['args'].items():
				try:
					if   (key == 'type'):
						eventConfigs[eventConfigName]['type'] = value
					elif (key == 'wql'):
						eventConfigs[eventConfigName]['wql'] = value
					elif key.startswith('message'):
						mLanguage = None
						try:
							mLanguage = key.split('[')[1].split(']')[0].strip().lower()
						except:
							pass
						if mLanguage:
							if (mLanguage == getLanguage()):
								eventConfigs[eventConfigName]['message'] = value
						elif not eventConfigs[eventConfigName].get('message'):
							eventConfigs[eventConfigName]['message'] = value
					elif key.startswith('shutdown_warning_message'):
						mLanguage = None
						try:
							mLanguage = key.split('[')[1].split(']')[0].strip().lower()
						except:
							pass
						if mLanguage:
							if (mLanguage == getLanguage()):
								eventConfigs[eventConfigName]['shutdownWarningMessage'] = value
						elif not eventConfigs[eventConfigName].get('shutdownWarningMessage'):
							eventConfigs[eventConfigName]['shutdownWarningMessage'] = value
					elif (key == 'max_repetitions'):
						eventConfigs[eventConfigName]['maxRepetitions'] = int(value)
					elif (key == 'activation_delay'):
						eventConfigs[eventConfigName]['activationDelay'] = int(value)
					elif (key == 'notification_delay'):
						eventConfigs[eventConfigName]['notificationDelay'] = int(value)
					elif (key == 'warning_time'):
						eventConfigs[eventConfigName]['warningTime'] = int(value)
					elif (key == 'user_cancelable'):
						eventConfigs[eventConfigName]['userCancelable'] = int(value)
					elif (key == 'cancel_counter'):
						eventConfigs[eventConfigName]['cancelCounter'] = int(value)
					elif (key == 'shutdown_warning_time'):
						eventConfigs[eventConfigName]['shutdownWarningTime'] = int(value)
					elif (key == 'shutdown_warning_repetition_time'):
						eventConfigs[eventConfigName]['shutdownWarningRepetitionTime'] = int(value)
					elif (key == 'shutdown_user_cancelable'):
						eventConfigs[eventConfigName]['shutdownUserCancelable'] = int(value)
					elif (key == 'block_login'):
						eventConfigs[eventConfigName]['blockLogin'] = not value.lower() in ('0', 'false', 'off', 'no')
					elif (key == 'lock_workstation'):
						eventConfigs[eventConfigName]['lockWorkstation'] = value.lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'logoff_current_user'):
						eventConfigs[eventConfigName]['logoffCurrentUser'] = value.lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'process_shutdown_requests'):
						eventConfigs[eventConfigName]['processShutdownRequests'] = not value.lower() in ('0', 'false', 'off', 'no')
					elif (key == 'get_config_from_service'):
						eventConfigs[eventConfigName]['getConfigFromService'] = not value.lower() in ('0', 'false', 'off', 'no')
					elif (key == 'update_config_file'):
						eventConfigs[eventConfigName]['updateConfigFile'] = not value.lower() in ('0', 'false', 'off', 'no')
					elif (key == 'write_log_to_service'):
						eventConfigs[eventConfigName]['writeLogToService'] = not value.lower() in ('0', 'false', 'off', 'no')
					elif (key == 'cache_products'):
						eventConfigs[eventConfigName]['cacheProducts'] = value.lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'cache_max_bandwidth'):
						eventConfigs[eventConfigName]['cacheMaxBandwidth'] = int(value)
					elif (key == 'requires_cached_products'):
						eventConfigs[eventConfigName]['requiresCachedProducts'] = value.lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'sync_config'):
						eventConfigs[eventConfigName]['syncConfig'] = value.lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'use_cached_config'):
						eventConfigs[eventConfigName]['useCachedConfig'] = value.lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'update_action_processor'):
						eventConfigs[eventConfigName]['updateActionProcessor'] = not value.lower() in ('0', 'false', 'off', 'no')
					elif (key == 'action_type'):
						eventConfigs[eventConfigName]['actionType'] = value.lower()
					elif (key == 'event_notifier_command'):
						eventConfigs[eventConfigName]['eventNotifierCommand'] = config.replace(value.lower(), escaped=True)
					elif (key == 'event_notifier_desktop'):
						eventConfigs[eventConfigName]['eventNotifierDesktop'] = value.lower()
					elif (key == 'action_notifier_command'):
						eventConfigs[eventConfigName]['actionNotifierCommand'] = config.replace(value.lower(), escaped=True)
					elif (key == 'action_notifier_desktop'):
						eventConfigs[eventConfigName]['actionNotifierDesktop'] = value.lower()
					elif (key == 'action_processor_command'):
						eventConfigs[eventConfigName]['actionProcessorCommand'] = value.lower()
					elif (key == 'action_processor_desktop'):
						eventConfigs[eventConfigName]['actionProcessorDesktop'] = value.lower()
					elif (key == 'action_processor_timeout'):
						eventConfigs[eventConfigName]['actionProcessorTimeout'] = int(value)
					elif (key == 'shutdown_notifier_command'):
						eventConfigs[eventConfigName]['shutdownNotifierCommand'] = config.replace(value.lower(), escaped=True)
					elif (key == 'shutdown_notifier_desktop'):
						eventConfigs[eventConfigName]['shutdownNotifierDesktop'] = value.lower()
					elif (key == 'service_options'):
						eventConfigs[eventConfigName]['serviceOptions'] = eval(value)
					elif (key == 'pre_action_processor_command'):
						eventConfigs[eventConfigName]['preActionProcessorCommand'] = config.replace(value.lower(), escaped=True)
					elif (key == 'post_action_processor_command'):
						eventConfigs[eventConfigName]['postActionProcessorCommand'] = config.replace(value.lower(), escaped=True)
					else:
						logger.error(u"Skipping unknown option '%s' in definition of event '%s'" % (key, eventConfigName))
				except Exception, e:
					logger.logException(e, LOG_DEBUG)
					logger.error(u"Failed to set event config argument '%s' to '%s': %s" % (key, value, e))
			
			logger.info(u"\nEvent config '" + eventConfigName + u"' args:\n" + objectToBeautifiedText(eventConfigs[eventConfigName]) + u"\n")
		except Exception, e:
			logger.logException(e)
	return eventConfigs

eventGenerators = {}
def createEventGenerators():
	global eventGenerators
	eventGenerators['panic'] = EventGeneratorFactory(
		PanicEventConfig('panic', actionProcessorCommand = config.get('action_processor', 'command', raw=True))
	)
	for eventConfigType in ('main', 'precondition'):
		for (eventConfigName, eventConfig) in getEventConfigs().items():
			mainEventConfigName = eventConfigName.split('{')[0]
			if (eventConfigType == 'main') and eventConfig.get('preconditions'):
				continue
			if (eventConfigType == 'precondition') and not eventConfig.get('preconditions'):
				continue
			if (eventConfigType == 'main') and mainEventConfigName in eventGenerators.keys():
				logger.error(u"Event generator '%s' already defined" % mainEventConfigName)
				continue
			try:
				eventType = eventConfig['type']
				del eventConfig['type']
				ec = EventConfigFactory(eventType, eventConfigName, **eventConfig)
				if (eventConfigType == 'main'):
					eventGenerators[mainEventConfigName] = EventGeneratorFactory(ec)
					logger.notice(u"%s event generator '%s' created" % (eventType, mainEventConfigName))
				else:
					eventGenerators[mainEventConfigName].addPreconditionConfig(ec)
					logger.notice(u"Precondition config '%s' added to event generator '%s'" % (eventConfigName, mainEventConfigName))
					
			except Exception, e:
				if (eventConfigType == 'main'):
					logger.error(u"Failed to create event generator '%s': %s" % (mainEventConfigName, forceUnicode(e)))
				else:
					logger.error(u"Failed to add precondition config '%s' to event generator '%s': %s" % (eventConfigName, mainEventConfigName, forceUnicode(e)))

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
	for eventConfigType in ('main', 'precondition'):
		for (eventConfigName, eventConfig) in eventConfigs.items():
			mainEventConfigName = eventConfigName.split('{')[0]
			if (eventConfigType == 'main') and eventConfig.get('preconditions'):
				continue
			if (eventConfigType == 'precondition') and not eventConfig.get('preconditions'):
				continue
			if (eventConfigType == 'main') and mainEventConfigName not in eventGenerators.keys():
				continue
			try:
				eventGenerator = eventGenerators.get(mainEventConfigName)
				if not eventGenerator:
					raise Exception(u"Event generator '%s' not found" % mainEventConfigName)
				eventType = eventConfig['type']
				del eventConfig['type']
				ec = EventConfigFactory(eventType, eventConfigName, **eventConfig)
				if (eventConfigType == 'main'):
					eventGenerator.setEventConfig(ec)
					eventGenerator.setPreconditionConfigs([])
					logger.notice("Event generator '%s' reconfigured" % mainEventConfigName)
				else:
					eventGenerator.addPreconditionConfig(ec)
					logger.notice(u"Precondition config '%s' added to event generator '%s'" % (eventConfigName, mainEventConfigName))
			except Exception, e:
				if (eventConfigType == 'main'):
					logger.error(u"Failed to reconfigure event generator '%s': %s" % (mainEventConfigName, forceUnicode(e)))
				else:
					logger.error(u"Failed to add precondition config '%s' to event generator '%s': %s" % (eventConfigName, mainEventConfigName, forceUnicode(e)))
	
















