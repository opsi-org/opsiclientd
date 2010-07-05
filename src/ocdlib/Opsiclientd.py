# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = = = =
   =   opsiclientd.Opsiclientd             =
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


# Imports
import copy as pycopy

# OPSI imports
from OPSI.Logger import *
from OPSI.Util import KillableThread
from OPSI.Util.File import IniFile
from OPSI import System

from ocdlib.Events import *
from ocdlib.ControlPipe import ControlPipeFactory, OpsiclientdRpcPipeInterface
from ocdlib.ControlServer import ControlServer
from ocdlib.CacheService import CacheService

# Get logger instance
logger = Logger()



# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                     SERVICE CONNECTION THREAD                                     -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ServiceConnectionThread(KillableThread):
	def __init__(self, configServiceUrl, username, password, statusObject):
		logger.setLogFormat(u'[%l] [%D] [service connection]   %M     (%F|%N)', object=self)
		KillableThread.__init__(self)
		self._configServiceUrl = configServiceUrl
		self._username = username
		self._password = password
		self._statusSubject = statusObject
		self.configService = None
		self.running = False
		self.connected = False
		self.cancelled = False
		if not self._configServiceUrl:
			raise Exception(u"No config service url given")
	
	def setStatusMessage(self, message):
		self._statusSubject.setMessage(message)
	
	def getUsername(self):
		return self._username
	
	def run(self):
		try:
			logger.debug(u"ServiceConnectionThread started...")
			self.running = True
			self.connected = False
			self.cancelled = False
			
			tryNum = 0
			while not self.cancelled and not self.connected:
				try:
					tryNum += 1
					logger.notice(u"Connecting to config server '%s' #%d" % (self._configServiceUrl, tryNum))
					self.setStatusMessage( _(u"Connecting to config server '%s' #%d") % (self._configServiceUrl, tryNum))
					if (len(self._username.split('.')) < 3):
						logger.notice(u"Domain missing in username %s, fetching domain from service" % self._username)
						configService = JSONRPCBackend(address = self._configServiceUrl, username = u'', password = u'')
						domain = configService.getDomain()
						self._username += '.' + domain
						logger.notice(u"Got domain '%s' from service, username expanded to '%s'" % (domain, self._username))
					self.configService = JSONRPCBackend(address = self._configServiceUrl, username = self._username, password = self._password)
					self.configService.authenticated()
					self.connected = True
					self.setStatusMessage(u"Connected to config server '%s'" % self._configServiceUrl)
					logger.notice(u"Connected to config server '%s'" % self._configServiceUrl)
				except Exception, e:
					self.setStatusMessage("Failed to connect to config server '%s': %s" % (self._configServiceUrl, forceUnicode(e)))
					logger.error(u"Failed to connect to config server '%s': %s" % (self._configServiceUrl, forceUnicode(e)))
					fqdn = System.getFQDN().lower()
					if (self._username != fqdn) and (fqdn.count('.') >= 2):
						logger.notice(u"Connect failed with username '%s', got fqdn '%s' from os, trying fqdn" \
								% (self._username, fqdn))
						self._username = fqdn
					time.sleep(1)
					time.sleep(1)
					time.sleep(1)
			
		except Exception, e:
			logger.logException(e)
		self.running = False
	
	def stopConnectionCallback(self, choiceSubject):
		logger.notice(u"Connection cancelled by user")
		self.stop()
	
	def stop(self):
		logger.debug(u"Stopping thread")
		self.cancelled = True
		self.running = False
		for i in range(10):
			if not self.isAlive():
				break
			self.terminate()
			time.sleep(0.5)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                            OPSICLIENTD                                            -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class Opsiclientd(EventListener, threading.Thread):
	def __init__(self):
		logger.setLogFormat(u'[%l] [%D] [opsiclientd]   %M     (%F|%N)', object=self)
		logger.debug(u"Opsiclient initiating")
		
		EventListener.__init__(self)
		threading.Thread.__init__(self) 
		
		self._startupTime = time.time()
		self._running = False
		self._eventProcessingThreads = []
		self._eventProcessingThreadsLock = threading.Lock()
		self._blockLogin = True
		self._currentActiveDesktopName = {}
		self._eventGenerators = {}
		
		self._actionProcessorUserName = u''
		self._actionProcessorUserPassword = u''
		
		self._statusApplicationProcess = None
		self._blockLoginNotifierPid = None
		
		self._rebootRequested = False
		self._shutdownRequested = False
		
		self._popupNotificationServer = None
		self._popupNotificationLock = threading.Lock()
		
		self._config = {
			'system': {
				'program_files_dir': u'',
			},
			'global': {
				'config_file':                    u'opsiclientd.conf',
				'log_file':                       u'opsiclientd.log',
				'log_level':                      LOG_NOTICE,
				'host_id':                        System.getFQDN().lower(),
				'opsi_host_key':                  u'',
				'wait_for_gui_timeout':           120,
				'wait_for_gui_application':       u'',
				'block_login_notifier':           u'',
			},
			'config_service': {
				'server_id':              u'',
				'url':                    u'',
				'connection_timeout':     10,
				'user_cancellable_after': 0,
			},
			'depot_server': {
				'depot_id': u'',
				'url':      u'',
				'drive':    u'',
				'username': u'pcpatch',
			},
			'cache_service': {
				'storage_dir':            u'c:\\tmp\\cache_service',
				'product_cache_max_size': 6000000000,
				'backend_manager_config': u'',
			},
			'control_server': {
				'interface':            '0.0.0.0', # TODO
				'port':                 4441,
				'ssl_server_key_file':  u'opsiclientd.pem',
				'ssl_server_cert_file': u'opsiclientd.pem',
				'static_dir':           u'static_html',
			},
			'notification_server': {
				'interface':  u'127.0.0.1',
				'start_port': 44000,
				'popup_port': 45000,
			},
			'opsiclientd_notifier': {
				'command': u'',
			},
			'action_processor': {
				'local_dir':   u'',
				'remote_dir':  u'',
				'filename':    u'',
				'command':     u'',
				'run_as_user': u'SYSTEM',
				'create_user': True,
				'delete_user': True,
			}
		}
		
	
	def setBlockLogin(self, blockLogin):
		self._blockLogin = bool(blockLogin)
		logger.notice(u"Block login now set to '%s'" % self._blockLogin)
		
		if (self._blockLogin):
			if not self._blockLoginNotifierPid and self.getConfigValue('global', 'block_login_notifier'):
				logger.info(u"Starting block login notifier app")
				sessionId = System.getActiveConsoleSessionId()
				while True:
					try:
						self._blockLoginNotifierPid = System.runCommandInSession(
								command = self.getConfigValue('global', 'block_login_notifier'),
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
		elif (self._blockLoginNotifierPid):
			try:
				logger.info(u"Terminating block login notifier app (pid %s)" % self._blockLoginNotifierPid)
				System.terminateProcess(processId = self._blockLoginNotifierPid)
			except Exception, e:
				logger.warning(u"Failed to terminate block login notifier app: %s" % forceUnicode(e))
			self._blockLoginNotifierPid = None
		
	def isRunning(self):
		return self._running
	
	def getConfig(self):
		return self._config
	
	def getConfigValue(self, section, option, raw = False):
		if not section:
			section = 'global'
		section = unicode(section).strip().lower()
		option = unicode(option).strip().lower()
		if not self._config.has_key(section):
			raise ValueError(u"No such config section: %s" % section)
		if not self._config[section].has_key(option):
			raise ValueError(u"No such config option in section '%s': %s" % (section, option))
		
		value = self._config[section][option]
		if not raw and type(value) in (unicode, str) and (value.count('%') >= 2):
			value = self.fillPlaceholders(value)
		if type(value) is str:
			value = unicode(value)
		return value
		
	def setConfigValue(self, section, option, value):
		if not section:
			section = 'global'
		
		section = unicode(section).strip().lower()
		option = unicode(option).strip().lower()
		value = unicode(value.strip())
		
		logger.info(u"Setting config value %s.%s" % (section, option))
		logger.debug(u"setConfigValue(%s, %s, %s)" % (section, option, value))
		
		if option not in ('action_processor_command') and (value == ''):
			logger.warning(u"Refusing to set empty value for config value '%s' of section '%s'" % (option, section))
			return
		
		if (option == 'opsi_host_key'):
			if (len(value) != 32):
				raise ValueError("Bad opsi host key, length != 32")
			logger.addConfidentialString(value)
		
		if option in ('server_id', 'depot_id', 'host_id'):
			value = value.lower()
		
		if section in ('system'):
			return
		
		if option in ('log_level', 'wait_for_gui_timeout', 'popup_port', 'port', 'start_port'):
			value = forceInt(value)
		
		if option in ('create_user', 'delete_user'):
			value = forceBool(value)
		
		if not self._config.has_key(section):
			self._config[section] = {}
		self._config[section][option] = value
		
		if   (section == 'config_service') and (option == 'url'):
			self.setConfigServiceUrl(self._config[section][option])
		elif (section == 'config_service') and option in ('connection_timeout', 'user_cancellable_after'):
			self._config[section][option] = int(self._config[section][option])
			if (self._config[section][option] < 0):
				self._config[section][option] = 0
		elif (section == 'global') and (option == 'log_level'):
			logger.setFileLevel(self._config[section][option])
		elif (section == 'global') and (option == 'log_file'):
			logger.setLogFile(self._config[section][option])
	
	def setConfigServiceUrl(self, url):
		if not re.search('https?://[^/]+', url):
			raise ValueError("Bad config service url '%s'" % url)
		self._config['config_service']['url'] = url
		self._config['config_service']['host'] = self._config['config_service']['url'].split('/')[2]
		self._config['config_service']['port'] = '4447'
		if (self._config['config_service']['host'].find(':') != -1):
			(self._config['config_service']['host'], self._config['config_service']['port']) = self._config['config_service']['host'].split(':', 1)
		
	def readConfigFile(self):
		''' Get settings from config file '''
		logger.notice(u"Trying to read config from file: '%s'" % self.getConfigValue('global', 'config_file'))
		
		try:
			# Read Config-File
			config = IniFile(filename = self.getConfigValue('global', 'config_file'), raw = True).parse()
			
			# Read log settings early
			if config.has_section('global'):
				debug = False
				try:
					debug = bool(System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SYSTEM\\CurrentControlSet\\Services\\opsiclientd", "Debug"))
				except:
					pass
				if not debug:
					if config.has_option('global', 'log_level'):
						self.setConfigValue('global', 'log_level', config.get('global', 'log_level'))
					if config.has_option('global', 'log_file'):
						logFile = config.get('global', 'log_file')
						for i in (2, 1, 0):
							slf = None
							dlf = None
							try:
								slf = logFile + '.' + unicode(i-1)
								if (i <= 0):
									slf = logFile
								dlf = logFile + '.' + unicode(i)
								if os.path.exists(slf):
									if os.path.exists(dlf):
										os.unlink(dlf)
									os.rename(slf, dlf)
							except Exception, e:
								logger.error(u"Failed to rename %s to %s: %s" % (slf, dlf, forceUnicode(e)) )
						self.setConfigValue('global', 'log_file', logFile)
			
			# Process all sections
			for section in config.sections():
				logger.debug(u"Processing section '%s' in config file: '%s'" % (section, self.getConfigValue('global', 'config_file')))
				
				for (option, value) in config.items(section):
					option = option.lower()
					self.setConfigValue(section.lower(), option, value)
				
		except Exception, e:
			# An error occured while trying to read the config file
			logger.error(u"Failed to read config file '%s': %s" % (self.getConfigValue('global', 'config_file'), forceUnicode(e)))
			logger.logException(e)
			return
		logger.notice(u"Config read")
		logger.debug(u"Config is now:\n %s" % objectToBeautifiedText(self._config))
	
	def updateConfigFile(self):
		''' Get settings from config file '''
		logger.notice(u"Updating config file: '%s'" % self.getConfigValue('global', 'config_file'))
		
		try:
			# Read config file
			configFile = IniFile(filename = self.getConfigValue('global', 'config_file'), raw = True)
			config = configFile.parse()
			changed = False
			for (section, value) in self._config.items():
				if not type(value) is dict:
					continue
				if section in ('system'):
					continue
				if not config.has_section(section):
					config.add_section(section)
					changed = True
				for (option, value) in value.items():
					if (section == 'config_service') and option in ('host', 'port'):
						continue
					if (section == 'global') and option in ('config_file'):
						# Do not store these options
						continue
					value = unicode(value)
					if not config.has_option(section, option) or (config.get(section, option) != value):
						changed = True
						config.set(section, option, value)
			if changed:
				# Write back config file if changed
				configFile.generate(config)
				logger.notice(u"Config file '%s' written" % self.getConfigValue('global', 'config_file'))
			else:
				logger.notice(u"No need to write config file '%s', config file is up to date" % self.getConfigValue('global', 'config_file'))
			
		except Exception, e:
			# An error occured while trying to write the config file
			logger.error(u"Failed to write config file '%s': %s" % (self.getConfigValue('global', 'config_file'), forceUnicode(e)))
			logger.logException(e)
	
	def fillPlaceholders(self, string, escaped=False):
		for (section, values) in self._config.items():
			if not type(values) is dict:
				continue
			for (key, value) in values.items():
				value = unicode(value)
				if (string.find(u'"%' + unicode(section) + u'.' + unicode(key) + u'%"') != -1) and escaped:
					if (os.name == 'posix'):
						value = value.replace('"', '\\"')
					if (os.name == 'nt'):
						value = value.replace('"', '^"')
				newString = string.replace(u'%' + unicode(section) + u'.' + unicode(key) + u'%', value)
				
				if (newString != string):
					string = self.fillPlaceholders(newString, escaped)
		return unicode(string)
	
	def createEventGenerators(self):
		self._eventGenerators['panic'] = EventGeneratorFactory(
			PanicEventConfig('panic', actionProcessorCommand = self.getConfigValue('action_processor', 'command', raw=True))
		)
		
		eventConfigs = {}
		for (section, options) in self._config.items():
			section = section.lower()
			if section.startswith('event_'):
				eventConfigName = section.split('_', 1)[1]
				if not eventConfigName:
					logger.error(u"No event config name defined in section '%s'" % section)
					continue
				if eventConfigName in self._eventGenerators.keys():
					logger.error(u"Event config '%s' already defined" % eventConfigName)
					continue
				eventConfigs[eventConfigName] = {
					'active': True,
					'args':   {},
					'super':  None }
				try:
					for key in options.keys():
						if   (key.lower() == 'active'):
							eventConfigs[eventConfigName]['active'] = not options[key].lower() in ('0', 'false', 'off', 'no')
						elif (key.lower() == 'super'):
							eventConfigs[eventConfigName]['super'] = options[key]
						else:
							eventConfigs[eventConfigName]['args'][key.lower()] = options[key]
				except Exception, e:
					logger.error(u"Failed to parse event config '%s': %s" % (eventConfigName, forceUnicode(e)))
		
		def __inheritArgsFromSuperEvents(eventConfigsCopy, args, superEventConfigName):
			if not superEventConfigName in eventConfigsCopy.keys():
				logger.error(u"Super event '%s' not found" % superEventConfigName)
				return args
			superArgs = pycopy.deepcopy(eventConfigsCopy[superEventConfigName]['args'])
			if eventConfigsCopy[superEventConfigName]['super']:
				__inheritArgsFromSuperEvents(eventConfigsCopy, superArgs, eventConfigsCopy[superEventConfigName]['super'])
			superArgs.update(args)
			return superArgs
		
		eventConfigsCopy = pycopy.deepcopy(eventConfigs)
		for eventConfigName in eventConfigs.keys():
			if eventConfigs[eventConfigName]['super']:
				eventConfigs[eventConfigName]['args'] = __inheritArgsFromSuperEvents(
										eventConfigsCopy,
										eventConfigs[eventConfigName]['args'],
										eventConfigs[eventConfigName]['super'])
		
		for (eventConfigName, eventConfig) in eventConfigs.items():
			try:
				if not eventConfig['active']:
					logger.notice(u"Event config '%s' is deactivated" % eventConfigName)
					continue
				
				if not eventConfig['args'].get('type'):
					logger.error(u"Event config '%s': event type not set" % eventConfigName)
					continue
				
				#if not eventConfig['args'].get('action_processor_command'):
				#	eventConfig['args']['action_processor_command'] = self.getConfigValue('action_processor', 'command')
				
				args = {}
				for (key, value) in eventConfig['args'].items():
					if   (key == 'type'):
						continue
					elif (key == 'message'):
						args['message'] = value
					elif (key == 'max_repetitions'):
						args['maxRepetitions'] = int(value)
					elif (key == 'activation_delay'):
						args['activationDelay'] = int(value)
					elif (key == 'notification_delay'):
						args['notificationDelay'] = int(value)
					elif (key == 'warning_time'):
						args['warningTime'] = int(value)
					elif (key == 'wql'):
						args['wql'] = value
					elif (key == 'user_cancelable'):
						args['userCancelable'] = not value.lower() in ('0', 'false', 'off', 'no')
					elif (key == 'block_login'):
						args['blockLogin'] = not value.lower() in ('0', 'false', 'off', 'no')
					elif (key == 'lock_workstation'):
						args['lockWorkstation'] = value.lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'logoff_current_user'):
						args['logoffCurrentUser'] = value.lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'process_shutdown_requests'):
						args['processShutdownRequests'] = not value.lower() in ('0', 'false', 'off', 'no')
					elif (key == 'get_config_from_service'):
						args['getConfigFromService'] = not value.lower() in ('0', 'false', 'off', 'no')
					elif (key == 'update_config_file'):
						args['updateConfigFile'] = not value.lower() in ('0', 'false', 'off', 'no')
					elif (key == 'write_log_to_service'):
						args['writeLogToService'] = not value.lower() in ('0', 'false', 'off', 'no')
					elif (key == 'cache_products'):
						args['cacheProducts'] = value.lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'cache_max_bandwidth'):
						args['cacheMaxBandwidth'] = int(value)
					elif (key == 'requires_cached_products'):
						args['requiresCachedProducts'] = value.lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'sync_config'):
						args['syncConfig'] = value.lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'use_cached_config'):
						args['useCachedConfig'] = value.lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'update_action_processor'):
						args['updateActionProcessor'] = not value.lower() in ('0', 'false', 'off', 'no')
					elif (key == 'action_type'):
						args['actionType'] = value.lower()
					elif (key == 'event_notifier_command'):
						args['eventNotifierCommand'] = self.fillPlaceholders(value.lower(), escaped=True)
					elif (key == 'event_notifier_desktop'):
						args['eventNotifierDesktop'] = value.lower()
					elif (key == 'action_notifier_command'):
						args['actionNotifierCommand'] = self.fillPlaceholders(value.lower(), escaped=True)
					elif (key == 'action_notifier_desktop'):
						args['actionNotifierDesktop'] = value.lower()
					elif (key == 'action_processor_command'):
						args['actionProcessorCommand'] = value.lower()
					elif (key == 'action_processor_desktop'):
						args['actionProcessorDesktop'] = value.lower()
					elif (key == 'action_processor_timeout'):
						args['actionProcessorTimeout'] = int(value)
					elif (key == 'service_options'):
						args['serviceOptions'] = eval(value)
					elif (key == 'pre_action_processor_command'):
						args['preActionProcessorCommand'] = self.fillPlaceholders(value.lower(), escaped=True)
					elif (key == 'post_action_processor_command'):
						args['postActionProcessorCommand'] = self.fillPlaceholders(value.lower(), escaped=True)
					else:
						logger.error(u"Skipping unknown option '%s' in definition of event '%s'" % (key, eventConfigName))
				
				logger.info(u"\nEvent config '" + eventConfigName + u"' args:\n" + objectToBeautifiedText(args) + u"\n")
				
				self._eventGenerators[eventConfigName] = EventGeneratorFactory(
					EventConfigFactory(eventConfig['args']['type'], eventConfigName, **args)
				)
				logger.notice(u"%s event generator '%s' created" % (eventConfig['args']['type'], eventConfigName))
				
			except Exception, e:
				logger.error(u"Failed to create event generator '%s': %s" % (eventConfigName, forceUnicode(e)))
		
		for eventGenerator in self._eventGenerators.values():
			eventGenerator.addEventListener(self)
			eventGenerator.start()
			logger.notice(u"Event generator '%s' started" % eventGenerator)
		
	def getEventGenerators(self, generatorClass=None):
		eventGenerators = []
		for eventGenerator in self._eventGenerators.values():
			if not generatorClass or isinstance(eventGenerator, generatorClass):
				eventGenerators.append(eventGenerator)
		return eventGenerators
		
	def waitForGUI(self, timeout=None):
		if not timeout:
			timeout = None
		class WaitForGUI(EventListener):
			def __init__(self, waitApp = None):
				self._waitApp = waitApp
				self._waitAppPid = None
				if self._waitApp:
					logger.info(u"Starting wait for GUI app")
					sessionId = System.getActiveConsoleSessionId()
					while True:
						try:
							self._waitAppPid = System.runCommandInSession(
									command = self._waitApp,
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
								logger.error(u"Failed to start wait for GUI app: %s" % forceUnicode(e))
				self._guiStarted = threading.Event()
				eventGenerator = EventGeneratorFactory(GUIStartupEventConfig("wait_for_gui"))
				eventGenerator.addEventListener(self)
				eventGenerator.start()
			
			def processEvent(self, event):
				logger.info(u"GUI started")
				if self._waitAppPid:
					try:
						logger.info(u"Terminating wait for GUI app (pid %s)" % self._waitAppPid)
						System.terminateProcess(processId = self._waitAppPid)
					except Exception, e:
						logger.warning(u"Failed to terminate wait for GUI app: %s" % forceUnicode(e))
				self._guiStarted.set()
				
			def wait(self, timeout=None):
				self._guiStarted.wait(timeout)
				if not self._guiStarted.isSet():
					logger.warning(u"Timed out after %d seconds while waiting for GUI" % timeout)
				
		WaitForGUI(self.getConfigValue('global', 'wait_for_gui_application')).wait(timeout)
	
	def createActionProcessorUser(self, recreate = True):
		if not self.getConfigValue('action_processor', 'create_user'):
			return
		
		runAsUser = self.getConfigValue('action_processor', 'run_as_user')
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
		
		self._actionProcessorUserPassword = u'$!?' + unicode(randomString(16)) + u'§/%'
		logger.addConfidentialString(self._actionProcessorUserPassword)
		
		if System.existsUser(username = runAsUser):
			System.deleteUser(username = runAsUser)
		System.createUser(username = runAsUser, password = self._actionProcessorUserPassword, groups = [ System.getAdminGroupName() ])
	
	def deleteActionProcessorUser(self):
		if not self.getConfigValue('action_processor', 'delete_user'):
			return
		if not self._actionProcessorUserName:
			return
		if not System.existsUser(username = self._actionProcessorUserName):
			return
		System.deleteUser(username = self._actionProcessorUserName)
		self._actionProcessorUserName = u''
		self._actionProcessorUserPassword = u''
	
	def run(self):
		self._running = True
		self._stopped = False
		
		self.readConfigFile()
		
		try:
			logger.comment(u"Opsiclientd version: %s" % __version__)
			logger.comment(u"Commandline: %s" % ' '.join(sys.argv))
			logger.comment(u"Working directory: %s" % os.getcwd())
			logger.notice(u"Using host id '%s'" % self.getConfigValue('global', 'host_id'))
			
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
								httpsPort          = self.getConfigValue('control_server', 'port'),
								sslServerKeyFile   = self.getConfigValue('control_server', 'ssl_server_key_file'),
								sslServerCertFile  = self.getConfigValue('control_server', 'ssl_server_cert_file'),
								staticDir          = self.getConfigValue('control_server', 'static_dir') )
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
			self.createEventGenerators()
			for eventGenerator in self.getEventGenerators(generatorClass = DaemonStartupEventGenerator):
				eventGenerator.fireEvent()
			
			if self.getEventGenerators(generatorClass = GUIStartupEventGenerator):
				# Wait until gui starts up
				logger.notice(u"Waiting for gui startup (timeout: %d seconds)" % self.getConfigValue('global', 'wait_for_gui_timeout'))
				self.waitForGUI(timeout = self.getConfigValue('global', 'wait_for_gui_timeout'))
				logger.notice(u"Done waiting for GUI")
				
				# Wait some more seconds for events to fire
				time.sleep(5)
			
			if not self._eventProcessingThreads:
				logger.notice(u"No events processing, unblocking login")
				self.setBlockLogin(False)
			
			while not self._stopped:
				time.sleep(1)
			
			for eventGenerator in self.getEventGenerators(generatorClass = DaemonShutdownEventGenerator):
				eventGenerator.fireEvent()
			
			logger.notice(u"opsiclientd is going down")
			
			for eventGenerator in self.getEventGenerators():
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
		if not (self._config.has_key('opsiclientd_rpc') and self._config['opsiclientd_rpc'].has_key('command')):
			raise Exception(u"opsiclientd_rpc command not defined")
		
		if sessionId is None:
			sessionId = System.getActiveConsoleSessionId()
		rpc = 'setCurrentActiveDesktopName("%s", System.getActiveDesktopName())' % sessionId
		cmd = '%s "%s"' % (self.getConfigValue('opsiclientd_rpc', 'command'), rpc)
		
		try:
			System.runCommandInSession(command = cmd, sessionId = sessionId, waitForProcessEnding = True, timeoutSeconds = 60)
		except Exception, e:
			logger.error(e)
		
		desktop = self._currentActiveDesktopName.get(sessionId)
		if not desktop:
			logger.warning(u"Failed to get current active desktop name for session %d, using 'default'" % sessionId)
			desktop = 'default'
			self._currentActiveDesktopName[sessionId] = desktop
		logger.debug(u"Returning current active dektop name '%s' for session %s" % (desktop, sessionId))
		return desktop
	
	
	def processShutdownRequests(self):
		pass
	
	def showPopup(self, message):
		port = self.getConfigValue('notification_server', 'popup_port')
		if not port:
			raise Exception(u'notification_server.popup_port not defined')
		
		notifierCommand = self.getConfigValue('opsiclientd_notifier', 'command').replace('%port%', forceUnicode(port))
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
			
			choiceSubject.setChoices([ 'Close' ])
			choiceSubject.setCallbacks( [ self.popupCloseCallback ] )
			
			for sessionId in System.getActiveSessionIds():
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
	
	

