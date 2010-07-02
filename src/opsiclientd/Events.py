# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = = = =
   =   opsiclientd.Events                  =
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

__version__ = '4.0'


# OPSI imports
from OPSI.Logger import *

# Get logger instance
logger = Logger()


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
		
		logger.setLogFormat(u'[%l] [%D] [event config ' + self._name + ']   %M  (%F|%N)', object=self)
		
		self.message                    =  unicode ( kwargs.get('message',                    ''        ) )
		self.maxRepetitions             =      int ( kwargs.get('maxRepetitions',             -1        ) )
		# wait <activationDelay> seconds before event gets active
		self.activationDelay            =      int ( kwargs.get('activationDelay',            0         ) )
		# wait <notificationDelay> seconds before event is fired
		self.notificationDelay          =      int ( kwargs.get('notificationDelay',          0         ) )
		self.warningTime                =      int ( kwargs.get('warningTime',                0         ) )
		self.userCancelable             =     bool ( kwargs.get('userCancelable',             False     ) )
		self.blockLogin                 =     bool ( kwargs.get('blockLogin',                 False     ) )
		self.logoffCurrentUser          =     bool ( kwargs.get('logoffCurrentUser',          False     ) )
		self.lockWorkstation            =     bool ( kwargs.get('lockWorkstation',            False     ) )
		self.processShutdownRequests    =     bool ( kwargs.get('processShutdownRequests',    True      ) )
		self.getConfigFromService       =     bool ( kwargs.get('getConfigFromService',       True      ) )
		self.updateConfigFile           =     bool ( kwargs.get('updateConfigFile',           True      ) )
		self.writeLogToService          =     bool ( kwargs.get('writeLogToService',          True      ) )
		self.updateActionProcessor      =     bool ( kwargs.get('updateActionProcessor',      True      ) )
		self.actionType                 =  unicode ( kwargs.get('actionType',                 ''        ) )
		self.eventNotifierCommand       =  unicode ( kwargs.get('eventNotifierCommand',       ''        ) )
		self.eventNotifierDesktop       =  unicode ( kwargs.get('eventNotifierDesktop',       'current' ) )
		self.actionNotifierCommand      =  unicode ( kwargs.get('actionNotifierCommand',      ''        ) )
		self.actionNotifierDesktop      =  unicode ( kwargs.get('actionNotifierDesktop',      'current' ) )
		self.actionProcessorCommand     =  unicode ( kwargs.get('actionProcessorCommand',     ''        ) )
		self.actionProcessorDesktop     =  unicode ( kwargs.get('actionProcessorDesktop',     'current' ) )
		self.actionProcessorTimeout     =      int ( kwargs.get('actionProcessorTimeout',     3*3600    ) )
		self.preActionProcessorCommand  =  unicode ( kwargs.get('preActionProcessorCommand',  ''        ) )
		self.postActionProcessorCommand =  unicode ( kwargs.get('postActionProcessorCommand', ''        ) )
		self.serviceOptions             =     dict ( kwargs.get('serviceOptions',             {}        ) )
		self.cacheProducts              =     bool ( kwargs.get('cacheProducts',              False     ) )
		self.cacheMaxBandwidth          =      int ( kwargs.get('cacheMaxBandwidth',          0         ) )
		self.requiresCachedProducts     =     bool ( kwargs.get('requiresCachedProducts',     False     ) )
		self.syncConfig                 =     bool ( kwargs.get('syncConfig',                 False     ) )
		self.useCachedConfig            =     bool ( kwargs.get('useCachedConfig',            False     ) )
		
		if not self.eventNotifierDesktop in ('winlogon', 'default', 'current'):
			logger.error(u"Bad value '%s' for eventNotifierDesktop" % self.eventNotifierDesktop)
			self.eventNotifierDesktop = 'current'
		if not self.actionNotifierDesktop in ('winlogon', 'default', 'current'):
			logger.error(u"Bad value '%s' for actionNotifierDesktop" % self.actionNotifierDesktop)
			self.actionNotifierDesktop = 'current'
		if not self.actionProcessorDesktop in ('winlogon', 'default', 'current'):
			logger.error(u"Bad value '%s' for actionProcessorDesktop" % self.actionProcessorDesktop)
			self.actionProcessorDesktop = 'current'
		
	def __str__(self):
		return "<event config: %s>" % self._name
	
	def getName(self):
		return self._name
	
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                         PANIC EVENT CONFIG                                        -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class PanicEventConfig(EventConfig):
	def __init__(self, name, **kwargs):
		EventConfig.__init__(self, name, **kwargs)
		self.maxRepetitions         = -1
		self.message                = 'Panic event'
		self.activationDelay        = 0
		self.notificationDelay      = 0
		self.warningTime            = 0
		self.userCancelable         = False
		self.blockLogin             = False
		self.logoffCurrentUser      = False
		self.lockWorkstation        = False
		self.getConfigFromService   = False
		self.updateConfigFile       = False
		self.writeLogToService      = False
		self.updateActionProcessor  = False
		self.eventNotifierCommand   = None
		self.actionNotifierCommand  = None
		self.actionProcessorDesktop = 'winlogon'
		self.serviceOptions         = {}

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                     DAEMON STARTUP EVENT CONFIG                                   -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class DaemonStartupEventConfig(EventConfig):
	def __init__(self, name, **kwargs):
		EventConfig.__init__(self, name, **kwargs)
		self.maxRepetitions = 0

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                    DAEMON SHUTDOWN EVENT CONFIG                                   -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class DaemonShutdownEventConfig(EventConfig):
	def __init__(self, name, **kwargs):
		EventConfig.__init__(self, name, **kwargs)
		self.maxRepetitions = 0

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                          WMI EVENT CONFIG                                         -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class WMIEventConfig(EventConfig):
	def __init__(self, name, **kwargs):
		EventConfig.__init__(self, name, **kwargs)
		self.wql = unicode( kwargs.get('wql', '') )

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                      GUI STARTUP EVENT CONFIG                                     -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class GUIStartupEventConfig(WMIEventConfig):
	def __init__(self, name, **kwargs):
		WMIEventConfig.__init__(self, name, **kwargs)
		self.maxRepetitions = 0
		self.processName = None
	
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                         TIMER EVENT CONFIG                                        -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class TimerEventConfig(EventConfig):
	def __init__(self, name, **kwargs):
		EventConfig.__init__(self, name, **kwargs)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                PRODUCT SYNC COMPLETED EVENT CONFIG                                -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ProductSyncCompletedEventConfig(EventConfig):
	def __init__(self, name, **kwargs):
		EventConfig.__init__(self, name, **kwargs)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                               PROCESS ACTION REQUESTS EVENT CONFIG                                -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ProcessActionRequestsEventConfig(EventConfig):
	def __init__(self, name, **kwargs):
		EventConfig.__init__(self, name, **kwargs)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                       USER LOGIN EVENT CONFIG                                     -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class UserLoginEventConfig(WMIEventConfig):
	def __init__(self, name, **kwargs):
		WMIEventConfig.__init__(self, name, **kwargs)
		self.blockLogin        = False
		self.logoffCurrentUser = False
		self.lockWorkstation   = False

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                    SYSTEM SHUTDOWN EVENT CONFIG                                   -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class SystemShutdownEventConfig(WMIEventConfig):
	def __init__(self, name, **kwargs):
		WMIEventConfig.__init__(self, name, **kwargs)
		self.maxRepetitions = 0

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                        CUSTOM EVENT CONFIG                                        -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class CustomEventConfig(WMIEventConfig):
	def __init__(self, name, **kwargs):
		WMIEventConfig.__init__(self, name, **kwargs)

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
		self._eventListeners = []
		self._eventsOccured = 0
		self._threadId = None
		self._stopped = False
		self._event = None
		self._lastEventOccurence = None
		logger.setLogFormat(u'[%l] [%D] [event generator ' + self._eventConfig.getName() + ']   %M  (%F|%N)', object=self)
		
	def addEventListener(self, eventListener):
		if not isinstance(eventListener, EventListener):
			raise TypeError(u"Failed to add event listener, got class %s, need class EventListener" % eventListener.__class__)
		
		for l in self._eventListeners:
			if (l == eventListener):
				return
		
		self._eventListeners.append(eventListener)
	
	def createEvent(self, eventInfo={}):
		return Event(eventConfig = self._eventConfig, eventInfo = eventInfo)
		
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
				logger.setLogFormat(u'[%l] [%D] [event generator ' + self._event.eventConfig.getName() + ']   %M  (%F|%N)', object=self)
				
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
		
		importWmiAndPythoncom()
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
			logger.error(u"Nothing to watch for")
			self._event = threading.Event()
			self._event.wait()
			return None
		
		wqlResult = None
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
			
		importWmiAndPythoncom()
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
		
		importWmiAndPythoncom(importWmi = False, importPythoncom = True)
		pythoncom.CoInitialize()
		
		sl = SensLogon(self.callback)
		subscription_interface = pythoncom.WrapObject(sl)
		
		event_system = win32com.client.Dispatch(PROGID_EventSystem)
		
		event_subscription = win32com.client.Dispatch(PROGID_EventSubscription)
		event_subscription.EventClassID = SENSGUID_EVENTCLASS_LOGON
		event_subscription.PublisherID = SENSGUID_PUBLISHER
		event_subscription.SubscriptionName = 'opsiclientd subscription'
		event_subscription.SubscriberInterface = subscription_interface
		
		event_system.Store(PROGID_EventSubscription, event_subscription)
	
	def getNextEvent(self):
		pythoncom.PumpMessages()
		logger.info(u"Event generator '%s' now deactivated after %d event occurrences" % (self, self._eventsOccured))
		self.cleanup()
		
	def callback(self, eventType, *args):
		logger.debug(u"SensLogonEventGenerator event callback: eventType '%s', args: %s" % (eventType, args))
	
	def stop(self):
		EventGenerator.stop(self)
		# Post WM_QUIT
		win32api.PostThreadMessage(self._threadId, 18, 0, 0)
		
	def cleanup(self):
		if self._lastEventOccurence and (time.time() - self._lastEventOccurence < 10):
			# Waiting some seconds before exit to avoid Win32 releasing exceptions
			waitTime = int(10 - (time.time() - self._lastEventOccurence))
			logger.info(u"Event generator '%s' cleaning up in %d seconds" % (self, waitTime))
			time.sleep(waitTime)
		
		importWmiAndPythoncom(importWmi = False, importPythoncom = True)
		pythoncom.CoUninitialize()
		
class UserLoginEventGenerator(SensLogonEventGenerator):
	def __init__(self, eventConfig):
		SensLogonEventGenerator.__init__(self, eventConfig)
	
	def callback(self, eventType, *args):
		logger.debug(u"UserLoginEventGenerator event callback: eventType '%s', args: %s" % (eventType, args))
		#if (eventType == 'Logon'):
		if (eventType == 'StartShell'):
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

class CustomEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)
	
	def createEvent(self, eventInfo={}):
		return CustomEvent(eventConfig = self._eventConfig, eventInfo = eventInfo)
	
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                            EVENT                                                  -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class Event(object):
	def __init__(self, eventConfig, eventInfo={}):
		self.eventConfig = eventConfig
		self.eventInfo = eventInfo
		logger.setLogFormat(u'[%l] [%D] [event ' + self.eventConfig.getName() + ']   %M  (%F|%N)', object=self)
		
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
# -                                      EVENT PROCESSING THREAD                                      -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class EventProcessingThread(KillableThread):
	def __init__(self, opsiclientd, event):
		logger.setLogFormat(u'[%l] [%D] [event processing ' + event.eventConfig.getName() + ']   %M     (%F|%N)', object=self)
		KillableThread.__init__(self)
		
		self.opsiclientd = opsiclientd
		self.event = event
		
		self.running = False
		self.eventCancelled = False
		self.waiting = False
		self.waitCancelled = False
		
		self._sessionId = None
		
		self._configService = None
		self._configServiceException = None
		
		self._notificationServer = None
		
		self._depotShareMounted = False
		
		self._statusSubject = MessageSubject('status')
		self._eventSubject = MessageSubject('event')
		self._serviceUrlSubject = MessageSubject('configServiceUrl')
		self._clientIdSubject = MessageSubject('clientId')
		self._actionProcessorInfoSubject = MessageSubject('actionProcessorInfo')
		self._opsiclientdInfoSubject = MessageSubject('opsiclientdInfo')
		self._detailSubjectProxy = MessageSubjectProxy('detail')
		self._currentProgressSubjectProxy = ProgressSubjectProxy('currentProgress')
		self._overallProgressSubjectProxy = ProgressSubjectProxy('overallProgress')
		
		self._statusSubject.setMessage( _("Processing event %s") % self.event.eventConfig.getName() )
		self._serviceUrlSubject.setMessage(self.opsiclientd.getConfigValue('config_service', 'url'))
		self._clientIdSubject.setMessage(self.opsiclientd.getConfigValue('global', 'host_id'))
		self._opsiclientdInfoSubject.setMessage("opsiclientd %s" % __version__)
		self._actionProcessorInfoSubject.setMessage("")
		
		
		#self.isLoginEvent = isinstance(self.event, UserLoginEvent)
		self.isLoginEvent = bool(self.event.eventConfig.actionType == 'login')
		if self.isLoginEvent:
			logger.info(u"Event is user login event")
		
		self.getSessionId()
		
		self._notificationServerPort = int(self.opsiclientd.getConfigValue('notification_server', 'start_port')) + int(self.getSessionId())
		
	def setSessionId(self, sessionId):
		self._sessionId = int(sessionId)
		logger.info(u"Session id set to %s" % self._sessionId)
		
	def getSessionId(self):
		logger.debug(u"getSessionId()")
		if self._sessionId is None:
			sessionId = None
			if self.isLoginEvent:
				logger.info(u"Using session id of user '%s'" % self.event.eventInfo["User"])
				#timeout = 30
				#while True:
				#	if (win32serviceutil.QueryServiceStatus("TermService")[1] == 4):
				#		break
				#	logger.debug(u"TermService not running, waiting...")
				#	if (timeout <= 0):
				#		raise Exception(u"Timed out while waiting for TermService")
				#	timeout -= 1
				userSessionsIds = System.getUserSessionIds(self.event.eventInfo["User"])
				if userSessionsIds:
					sessionId = userSessionsIds[0]
			if not sessionId:
				logger.info(u"Using active console session id")
				sessionId = System.getActiveConsoleSessionId()
			self.setSessionId(sessionId)
		return self._sessionId
		
	def setStatusMessage(self, message):
		self._statusSubject.setMessage(message)
		
	def startNotificationServer(self):
		logger.notice(u"Starting notification server on port %s" % self._notificationServerPort)
		try:
			self._notificationServer = NotificationServer(
							address  = self.opsiclientd.getConfigValue('notification_server', 'interface'),
							port     = self._notificationServerPort,
							subjects = [
								self._statusSubject,
								self._eventSubject,
								self._serviceUrlSubject,
								self._clientIdSubject,
								self._actionProcessorInfoSubject,
								self._opsiclientdInfoSubject,
								self._detailSubjectProxy,
								self._currentProgressSubjectProxy,
								self._overallProgressSubjectProxy ] )
			#logger.setLogFormat('[%l] [%D] [notification server]   %M     (%F|%N)', object=self._notificationServer)
			#logger.setLogFormat('[%l] [%D] [notification server]   %M     (%F|%N)', object=self._notificationServer.getObserver())
			self._notificationServer.start()
			logger.notice(u"Notification server started")
		except Exception, e:
			logger.error(u"Failed to start notification server: %s" % forceUnicode(e))
			raise
		
	def connectConfigServer(self):
		if self._configService:
			# Already connected
			return
		
		if self._configServiceException:
			# Exception will be cleared on disconnect
			raise Exception(u"Connect failed, will not retry")
		
		try:
			choiceSubject = ChoiceSubject(id = 'choice')
			choiceSubject.setChoices([ 'Stop connection' ])
			
			logger.debug(u"Creating ServiceConnectionThread")
			serviceConnectionThread = ServiceConnectionThread(
						configServiceUrl    = self.opsiclientd.getConfigValue('config_service', 'url'),
						username            = self.opsiclientd.getConfigValue('global', 'host_id'),
						password            = self.opsiclientd.getConfigValue('global', 'opsi_host_key'),
						statusObject        = self._statusSubject )
			
			choiceSubject.setCallbacks( [ serviceConnectionThread.stopConnectionCallback ] )
			
			cancellableAfter = forceInt(self.opsiclientd.getConfigValue('config_service', 'user_cancellable_after'))
			logger.info(u"User is allowed to cancel connection after %d seconds" % cancellableAfter)
			if (cancellableAfter < 1):
				self._notificationServer.addSubject(choiceSubject)
			
			timeout = forceInt(self.opsiclientd.getConfigValue('config_service', 'connection_timeout'))
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
			
			self._detailSubjectProxy.setMessage('')
			self._notificationServer.removeSubject(choiceSubject)
			
			if serviceConnectionThread.cancelled:
				logger.error(u"ServiceConnectionThread canceled by user")
				raise CanceledByUserError(u"Failed to connect to config service '%s': cancelled by user" % \
							self.opsiclientd.getConfigValue('config_service', 'url') )
			elif serviceConnectionThread.running:
				logger.error(u"ServiceConnectionThread timed out after %d seconds" % self.opsiclientd.getConfigValue('config_service', 'connection_timeout'))
				serviceConnectionThread.stop()
				raise Exception(u"Failed to connect to config service '%s': timed out after %d seconds" % \
							(self.opsiclientd.getConfigValue('config_service', 'url'), self.opsiclientd.getConfigValue('config_service', 'connection_timeout')) )
				
			if not serviceConnectionThread.connected:
				raise Exception(u"Failed to connect to config service '%s': reason unknown" % self.opsiclientd.getConfigValue('config_service', 'url'))
			
			if (serviceConnectionThread.getUsername() != self.opsiclientd.getConfigValue('global', 'host_id')):
				self.opsiclientd.setConfigValue('global', 'host_id', serviceConnectionThread.getUsername().lower())
				logger.info(u"Updated host_id to '%s'" % self.opsiclientd.getConfigValue('global', 'host_id'))
			self._configService = serviceConnectionThread.configService
			self.opsiclientd.setConfigValue('config_service', 'server_id', self._configService.getServerId(self.opsiclientd.getConfigValue('global', 'host_id')))
			logger.info(u"Updated config_service.host_id to '%s'" % self.opsiclientd.getConfigValue('config_service', 'server_id'))
			
			if self.event.eventConfig.updateConfigFile:
				self.setStatusMessage( _(u"Updating config file") )
				self.opsiclientd.updateConfigFile()
			
		except Exception, e:
			self.disconnectConfigServer()
			self._configServiceException = e
			raise
		
	def disconnectConfigServer(self):
		if self._configService:
			try:
				self._configService.exit()
			except Exception, e:
				logger.error(u"Failed to disconnect config service: %s" % forceUnicode(e))
		self._configService = None
		self._configServiceException = None
	
	def getConfigFromService(self):
		''' Get settings from service '''
		logger.notice(u"Getting config from service")
		try:
			self.setStatusMessage(_(u"Getting config from service"))
			
			self.connectConfigServer()
			
			for (key, value) in self._configService.getNetworkConfig_hash(self.opsiclientd.getConfigValue('global', 'host_id')).items():
				if (key.lower() == 'depotid'):
					depotId = value
					self.opsiclientd.setConfigValue('depot_server', 'depot_id', depotId)
					self.opsiclientd.setConfigValue('depot_server', 'url', self._configService.getDepot_hash(depotId)['depotRemoteUrl'])
				elif (key.lower() == 'depotdrive'):
					self.opsiclientd.setConfigValue('depot_server', 'drive', value)
				else:
					logger.info(u"Unhandled network config key '%s'" % key)
				
			logger.notice(u"Got network config from service")
			
			for (key, value) in self._configService.getGeneralConfig_hash(self.opsiclientd.getConfigValue('global', 'host_id')).items():
				try:
					parts = key.lower().split('.')
					if (len(parts) < 3) or (parts[0] != 'opsiclientd'):
						continue
					
					self.opsiclientd.setConfigValue(section = parts[1], option = parts[2], value = value)
					
				except Exception, e:
					logger.error(u"Failed to process general config key '%s:%s': %s" % (key, value, forceUnicode(e)))
			
			logger.notice(u"Got config from service")
			
			self.setStatusMessage(_(u"Got config from service"))
			logger.debug(u"Config is now:\n %s" % objectToBeautifiedText(self.opsiclientd.getConfig()))
		#except CanceledByUserError, e:
		#	logger.error("Failed to get config from service: %s" % forceUnicode(e))
		#	raise
		#except Exception, e:
		#	logger.error("Failed to get config from service: %s" % forceUnicode(e))
		#	logger.logException(e)
		except Exception, e:
			logger.error(u"Failed to get config from service: %s" % forceUnicode(e))
			raise
		
	def writeLogToService(self):
		logger.notice(u"Writing log to service")
		try:
			if not self._configService:
				raise Exception(u"Not connected to config service")
			self.setStatusMessage( _(u"Writing log to service") )
			f = codecs.open(self.opsiclientd.getConfigValue('global', 'log_file'), 'r', 'utf-8', 'replace')
			data = f.read()
			data += u"-------------------- submitted part of log file ends here, see the rest of log file on client --------------------\n"
			f.close()
			# Do not log jsonrpc request
			logger.setFileLevel(LOG_WARNING)
			self._configService.writeLog('clientconnect', data.replace(u'\ufffd', u'?'), self.opsiclientd.getConfigValue('global', 'host_id'))
			#self._configService.writeLog('clientconnect', data.replace(u'\ufffd', u'?').encode('utf-8'), self.opsiclientd.getConfigValue('global', 'host_id'))
		finally:
			logger.setFileLevel(self.opsiclientd.getConfigValue('global', 'log_level'))
		
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
	
	def startNotifierApplication(self, notifierType, command, desktop=None):
		logger.notice(u"Starting notifier application type '%s' in session '%s'" % (notifierType, self.getSessionId()))
		self.runCommandInSession(command = command.replace('%port%', unicode(self._notificationServerPort)), waitForProcessEnding = False)
		time.sleep(3)
	
	def closeProcessWindows(self, processId):
		command = None
		try:
			command = '%s "exit(); System.closeProcessWindows(processId = %s)"' \
					% (self.opsiclientd.getConfigValue('opsiclientd_rpc', 'command'), processId)
		except Exception, e:
			raise Exception(u"opsiclientd_rpc command not defined: %s" % forceUnicode(e))
		
		self.runCommandInSession(command = cmd, waitForProcessEnding = False)
		
	def setActionProcessorInfo(self):
		try:
			actionProcessorFilename = self.opsiclientd.getConfigValue('action_processor', 'filename')
			actionProcessorLocalDir = self.opsiclientd.getConfigValue('action_processor', 'local_dir')
			actionProcessorLocalFile = os.path.join(actionProcessorLocalDir, actionProcessorFilename)
			actionProcessorLocalFile = actionProcessorLocalFile
			info = System.getFileVersionInfo(actionProcessorLocalFile)
			version = info.get('FileVersion', u'')
			name = info.get('ProductName', u'')
			logger.info(u"Action processor name '%s', version '%s'" % (name, version))
			self._actionProcessorInfoSubject.setMessage("%s %s" % (name.encode('utf-8'), version.encode('utf-8')))
		except Exception, e:
			logger.error(u"Failed to set action processor info: %s" % forceUnicode(e))
	
	def getDepotserverCredentials(self):
		self.connectConfigServer()
		depotServerUsername = self.opsiclientd.getConfigValue('depot_server', 'username')
		encryptedDepotServerPassword = self._configService.getPcpatchPassword(self.opsiclientd.getConfigValue('global', 'host_id'))
		depotServerPassword = blowfishDecrypt(self.opsiclientd.getConfigValue('global', 'opsi_host_key'), encryptedDepotServerPassword)
		logger.addConfidentialString(depotServerPassword)
		return (depotServerUsername, depotServerPassword)
		
	def mountDepotShare(self, impersonation):
		if self._depotShareMounted:
			logger.debug(u"Depot share already mounted")
			return
		
		logger.notice(u"Mounting depot share %s" %  self.opsiclientd.getConfigValue('depot_server', 'url'))
		self.setStatusMessage(_(u"Mounting depot share %s") % self.opsiclientd.getConfigValue('depot_server', 'url'))
		
		if impersonation:
			System.mount(self.opsiclientd.getConfigValue('depot_server', 'url'), self.opsiclientd.getConfigValue('depot_server', 'drive'))
		else:
			(depotServerUsername, depotServerPassword) = self.getDepotserverCredentials()
			System.mount(self.opsiclientd.getConfigValue('depot_server', 'url'), self.opsiclientd.getConfigValue('depot_server', 'drive'), username = depotServerUsername, password = depotServerPassword)
		self._depotShareMounted = True
		
	def umountDepotShare(self):
		if not self._depotShareMounted:
			logger.debug(u"Depot share not mounted")
			return
		try:
			logger.notice(u"Unmounting depot share")
			System.umount(self.opsiclientd.getConfigValue('depot_server', 'drive'))
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
			(depotServerUsername, depotServerPassword) = self.getDepotserverCredentials()
			impersonation = System.Impersonate(username = depotServerUsername, password = depotServerPassword)
			impersonation.start(logonType = 'NEW_CREDENTIALS')
			
			self.mountDepotShare(impersonation)
			
			actionProcessorFilename = self.opsiclientd.getConfigValue('action_processor', 'filename')
			actionProcessorLocalDir = self.opsiclientd.getConfigValue('action_processor', 'local_dir')
			actionProcessorLocalTmpDir = actionProcessorLocalDir + '.tmp'
			actionProcessorLocalFile = os.path.join(actionProcessorLocalDir, actionProcessorFilename)
			actionProcessorLocalTmpFile = os.path.join(actionProcessorLocalTmpDir, actionProcessorFilename)
			
			actionProcessorRemoteDir = os.path.join(
							self.opsiclientd.getConfigValue('depot_server', 'drive'),
							self.opsiclientd.getConfigValue('action_processor', 'remote_dir'))
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
			
			self._configService.setProductInstallationStatus(
							'opsi-winst',
							self.opsiclientd.getConfigValue('global', 'host_id'),
							'installed')
			
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
		
		impersonation = None
		try:
			# This logon type allows the caller to clone its current token and specify new credentials for outbound connections.
			# The new logon session has the same local identifier but uses different credentials for other network connections.
			(depotServerUsername, depotServerPassword) = self.getDepotserverCredentials()
			impersonation = System.Impersonate(username = depotServerUsername, password = depotServerPassword)
			impersonation.start(logonType = 'NEW_CREDENTIALS')
			
			self.mountDepotShare(impersonation)
			
			userScripts = []
			productDir = os.path.join(self.opsiclientd.getConfigValue('depot_server', 'drive'), 'install')
			for entry in os.listdir(productDir):
				if not os.path.isdir( os.path.join(productDir, entry) ):
					continue
				userScript = os.path.join(productDir, entry, 'userscript.ins')
				if not os.path.isfile(userScript):
					continue
				logger.info(u"User script found: %s" % userScript)
				userScripts.append(userScript)
			
			self.umountDepotShare()
			
			if userScripts:
				logger.notice(u"User scripts found, executing")
				additionalParams = ''
				for userScript in userScripts:
					additionalParams += ' "%s"' % userScript
				self.runActions(additionalParams)
			else:
				logger.notice(u"No user script found, nothing to do")
			
		except Exception, e:
			logger.logException(e)
			logger.error(u"Failed to process login actions: %s" % forceUnicode(e))
			self.setStatusMessage( _(u"Failed to process login actions: %s") % forceUnicode(e) )
		
		if impersonation:
			try:
				impersonation.end()
			except Exception, e:
				logger.warning(e)
		
	def processProductActionRequests(self):
		self.setStatusMessage(_(u"Getting action requests from config service"))
		
		try:
			bootmode = ''
			try:
				bootmode = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\general", "bootmode")
			except Exception, e:
				logger.warning(u"Failed to get bootmode from registry: %s" % forceUnicode(e))
			
			self.connectConfigServer()
			productStates = []
			if (self._configService.getLocalBootProductStates_hash.func_code.co_argcount == 2):
				if self.event.eventConfig.serviceOptions:
					logger.warning(u"Service cannot handle service options in method getLocalBootProductStates_hash")
				productStates = self._configService.getLocalBootProductStates_hash(self.opsiclientd.getConfigValue('global', 'host_id'))
				productStates = productStates.get(self.opsiclientd.getConfigValue('global', 'host_id'), [])
			else:
				productStates = self._configService.getLocalBootProductStates_hash(
							self.opsiclientd.getConfigValue('global', 'host_id'),
							self.event.eventConfig.serviceOptions )
				productStates = productStates.get(self.opsiclientd.getConfigValue('global', 'host_id'), [])
			
			logger.notice(u"Got product action requests from configservice")
			productIds = []
			for productState in productStates:
				if (productState['actionRequest'] not in ('none', 'undefined')):
					productIds.append(productState['productId'])
					logger.notice("   [%2s] product %-20s %s" % (len(productIds), productState['productId'] + ':', productState['actionRequest']))
			
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
				
				savedDepotUrl = None
				savedDepotDrive = None
				if self.event.eventConfig.requiresCachedProducts:
					# Event needs cached products => initialize cache service
					if self.opsiclientd._cacheService.getProductSyncCompleted():
						logger.notice(u"Event '%s' requires cached products and product sync is done" % self.event.eventConfig.getName())
						savedDepotUrl = self.opsiclientd.getConfigValue('depot_server', 'url')
						savedDepotDrive = self.opsiclientd.getConfigValue('depot_server', 'drive')
						cacheDepotDir = self.opsiclientd._cacheService.getProductCacheDir().replace('\\', '/').replace('//', '/')
						cacheDepotDrive = cacheDepotDir.split('/')[0]
						cacheDepotUrl = 'smb://localhost/noshare/' + ('/'.join(cacheDepotDir.split('/')[1:]))
						self.opsiclientd.setConfigValue('depot_server', 'url', cacheDepotUrl)
						self.opsiclientd.setConfigValue('depot_server', 'drive', cacheDepotDrive)
					else:
						raise Exception(u"Event '%s' requires cached products but product sync is not done, exiting" % self.event.eventConfig.getName())
				
				try:
					self.runActions()
				finally:
					if savedDepotUrl:
						self.opsiclientd.setConfigValue('depot_server', 'url', savedDepotUrl)
					if savedDepotDrive:
						self.opsiclientd.setConfigValue('depot_server', 'drive', savedDepotDrive)
				
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
		
		# Before Running Action Processor check for Trusted Installer
		if (os.name == 'nt') and (sys.getwindowsversion()[0] == 6):
			logger.debug(u"Try to read TrustedInstaller service-configuration")
			try:
				# Trusted Installer "Start" Key in Registry: 2 = automatic Start: Registry: 3 = manuell Start; Default: 3
				automaticStartup = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SYSTEM\\CurrentControlSet\\services\\TrustedInstaller", "Start", reflection = False)
				if (automaticStartup == 2):
					logger.notice(u"Automatic startup for service Trusted Installer is set, waiting until upgrade process is finished")
					self.setStatusMessage( _(u"Waiting for trusted installer") )
					while True:
						time.sleep(3)
						logger.debug(u"Checking if automatic startup for service Trusted Installer is set")
						automaticStartup = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SYSTEM\\CurrentControlSet\\services\\TrustedInstaller", "Start")
						if not (automaticStartup == 2):
							break
			except Exception, e:
				logger.error(u"Failed to read TrustedInstaller service-configuration: %s" % e)
		
		self.setStatusMessage( _(u"Starting actions") )
		
		# Setting some registry values before starting action
		# Mainly for action processor winst
		System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "depoturl",   self.opsiclientd.getConfigValue('depot_server', 'url'))
		System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "depotdrive", self.opsiclientd.getConfigValue('depot_server', 'drive'))
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
		
		
		depotServerUsername = self.opsiclientd.getConfigValue('depot_server', 'username')
		encryptedDepotServerPassword = self._configService.getPcpatchPassword(self.opsiclientd.getConfigValue('global', 'host_id'))
		depotServerPassword = blowfishDecrypt(self.opsiclientd.getConfigValue('global', 'opsi_host_key'), encryptedDepotServerPassword)
		logger.addConfidentialString(depotServerPassword)
		
		# Update action processor
		if self.opsiclientd.getConfigValue('depot_server', 'url').split('/')[2] not in ('127.0.0.1', 'localhost') and self.event.eventConfig.updateActionProcessor:
			self.updateActionProcessor()
		
		# Run action processor
		actionProcessorCommand = self.opsiclientd.fillPlaceholders(self.event.getActionProcessorCommand())
		actionProcessorCommand += additionalParams
		actionProcessorCommand = actionProcessorCommand.replace('"', '\\"')
		command = u'%system.program_files_dir%\\opsi.org\\preloginloader\\action_processor_starter.exe ' \
			+ u'"%global.host_id%" "%global.opsi_host_key%" "%control_server.port%" ' \
			+ u'"%global.log_file%" "%global.log_level%" ' \
			+ u'"%depot_server.url%" "%depot_server.drive%" ' \
			+ u'"' + depotServerUsername + u'" "' + depotServerPassword + '" ' \
			+ u'"' + unicode(self.getSessionId()) + u'" "' + desktop + '" ' \
			+ u'"' + actionProcessorCommand + u'" ' + unicode(self.event.eventConfig.actionProcessorTimeout) + ' ' \
			+ u'"' + self.opsiclientd._actionProcessorUserName + u'" "' + self.opsiclientd._actionProcessorUserPassword + u'"'
		command = self.opsiclientd.fillPlaceholders(command)
		
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
			self.waiting = False
			self.waitCancelled = False
			
			# Store current config service url and depot url
			configServiceUrl = self.opsiclientd.getConfigValue('config_service', 'url')
			depotServerUrl = self.opsiclientd.getConfigValue('depot_server', 'url')
			depotDrive = self.opsiclientd.getConfigValue('depot_server', 'drive')
			try:
				self.startNotificationServer()
				self.setActionProcessorInfo()
				
				if self.event.eventConfig.useCachedConfig:
					# Event needs cached config => initialize cache service
					if self.opsiclientd._cacheService.getConfigSyncCompleted():
						logger.notice(u"Event '%s' requires cached config and config sync is done" % self.event)
						self.opsiclientd._cacheService.workWithLocalConfig()
						cacheConfigServiceUrl = 'https://127.0.0.1:%s/rpc' % self.opsiclientd.getConfigValue('control_server', 'port')
						logger.notice(u"Setting config service url to cache service url '%s'" % cacheConfigServiceUrl)
						self.opsiclientd.setConfigValue('config_service', 'url', cacheConfigServiceUrl)
					else:
						logger.notice(u"Event '%s' requires cached config but config sync is not done, exiting" % self.event)
						self.running = False
						return
				
				self._eventSubject.setMessage(self.event.eventConfig.message)
				if self.event.eventConfig.warningTime:
					choiceSubject = ChoiceSubject(id = 'choice')
					if self.event.eventConfig.userCancelable:
						choiceSubject.setChoices([ 'Abort', 'Start now' ])
						choiceSubject.setCallbacks( [ self.abortEventCallback, self.startEventCallback ] )
					else:
						choiceSubject.setChoices([ 'Start now' ])
						choiceSubject.setCallbacks( [ self.startEventCallback ] )
					self._notificationServer.addSubject(choiceSubject)
					try:
						if self.event.eventConfig.eventNotifierCommand:
							self.startNotifierApplication(
									notifierType = 'event',
									command      = self.event.eventConfig.eventNotifierCommand,
									desktop      = self.event.eventConfig.eventNotifierDesktop )
							
						timeout = int(self.event.eventConfig.warningTime)
						while(timeout > 0) and not self.eventCancelled and not self.waitCancelled:
							self.waiting = True
							logger.info(u"Notifying user of event %s" % self.event)
							self.setStatusMessage(u"Event %s: processing will start in %d seconds" % (self.event.eventConfig.getName(), timeout))
							timeout -= 1
							time.sleep(1)
						
						if self.eventCancelled:
							raise CanceledByUserError(u"Cancelled by user")
					finally:
						self.waiting = False
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
						notifierType = 'action',
						command      = self.event.eventConfig.actionNotifierCommand,
						desktop      = self.event.eventConfig.actionNotifierDesktop )
				
				if not self.event.eventConfig.useCachedConfig:
					if self.event.eventConfig.getConfigFromService:
						self.getConfigFromService()
					if self.event.eventConfig.updateConfigFile:
						self.opsiclientd.updateConfigFile()
				
				if (self.event.eventConfig.actionType == 'login'):
					self.processUserLoginActions()
				else:
					self.processProductActionRequests()
			
			finally:
				self._eventSubject.setMessage(u"")
				
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
						self.opsiclientd.processShutdownRequests()
					except Exception, e:
						logger.logException(e)
				
				if self.opsiclientd._shutdownRequested:
					self.setStatusMessage(_("Shutting down machine"))
				elif self.opsiclientd._rebootRequested:
					self.setStatusMessage(_("Rebooting machine"))
				else:
					self.setStatusMessage(_("Unblocking login"))
				
				if not self.opsiclientd._rebootRequested and not self.opsiclientd._shutdownRequested:
					self.opsiclientd.setBlockLogin(False)
				
				self.setStatusMessage(u"")
				
				if self.event.eventConfig.useCachedConfig:
					# Set config service url back to previous url
					logger.notice(u"Setting config service url back to '%s'" % configServiceUrl)
					self.opsiclientd.setConfigValue('config_service', 'url', configServiceUrl)
					logger.notice("Setting depot server url back to '%s'" % depotServerUrl)
					self.opsiclientd.setConfigValue('depot_server', 'url', depotServerUrl)
					logger.notice(u"Setting depot drive back to '%s'" % depotDrive)
					self.opsiclientd.setConfigValue('depot_server', 'drive', depotDrive)
				
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
		logger.notice(u"Waiting cancelled by user")
		self.waitCancelled = True
	
	
	#def stop(self):
	#	time.sleep(5)
	#	if self.running and self.isAlive():
	#		logger.debug(u"Terminating thread")
	#		self.terminate()






