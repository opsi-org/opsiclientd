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
import sys, os, shutil

# Twisted imports
from twisted.internet import reactor

# OPSI imports
from OPSI.Logger import *
from OPSI.Util import *
from OPSI.Util.File import IniFile
from OPSI.Util.Message import *
from OPSI.Types import *
from OPSI import System
from OPSI.Backend.JSONRPC import JSONRPCBackend
from OPSI.Object import *

from ocdlib.Events import *
from ocdlib.ControlPipe import ControlPipeFactory, OpsiclientdRpcPipeInterface
from ocdlib.ControlServer import ControlServer
from ocdlib.CacheService import CacheService

# Get logger instance
logger = Logger()


# Message translation
def _(msg):
	return msg

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
		
		baseDir = u''
		try:
			baseDir = os.path.dirname(sys.argv[0])
		except Exception, e:
			logger.error(u"Failed to get base dir: %s" % e)
		
		self._config = {
			'system': {
				'program_files_dir': u'',
			},
			'global': {
				'base_dir':                       baseDir,
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
				'url':                    [],
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
		
		if option in ('depot_id', 'host_id'):
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
			urls = forceUnicodeList(self._config[section][option].split(u','))
			self._config[section][option] = []
			for url in urls:
				url = url.strip()
				if not re.search('https?://[^/]+', url):
					logger.error("Bad config service url '%s'" % url)
				self._config[section][option].append(url)
		elif (section == 'config_service') and option in ('connection_timeout', 'user_cancellable_after'):
			self._config[section][option] = int(self._config[section][option])
			if (self._config[section][option] < 0):
				self._config[section][option] = 0
		elif (section == 'global') and (option == 'log_level'):
			logger.setFileLevel(self._config[section][option])
		elif (section == 'global') and (option == 'log_file'):
			logger.setLogFile(self._config[section][option])
	
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
								slf = logFile + u'.' + unicode(i-1)
								if (i <= 0):
									slf = logFile
								dlf = logFile + u'.' + unicode(i)
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
			for (section, values) in self._config.items():
				if not type(values) is dict:
					continue
				if section in ('system'):
					continue
				if not config.has_section(section):
					config.add_section(section)
					changed = True
				for (option, value) in values.items():
					if (section == 'global') and (option == 'config_file'):
						# Do not store these option
						continue
					if type(value) is list:
						value = u', '.join(forceUnicodeList(value))
					else:
						value = forceUnicode(value)
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
			logger.logException(e)
			logger.error(u"Failed to write config file '%s': %s" % (self.getConfigValue('global', 'config_file'), forceUnicode(e)))
	
	def fillPlaceholders(self, string, escaped=False):
		for (section, values) in self._config.items():
			if not type(values) is dict:
				continue
			for (key, value) in values.items():
				value = forceUnicode(value)
				if (string.find(u'"%' + unicode(section) + u'.' + unicode(key) + u'%"') != -1) and escaped:
					if (os.name == 'posix'):
						value = value.replace('"', '\\"')
					if (os.name == 'nt'):
						value = value.replace('"', '^"')
				newString = string.replace(u'%' + unicode(section) + u'.' + unicode(key) + u'%', value)
				
				if (newString != string):
					string = self.fillPlaceholders(newString, escaped)
		return forceUnicode(string)
	
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
								break
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
						raise Exception(u"Domain missing in username '%s'" % self._username)
					self.configService = JSONRPCBackend(address = self._configServiceUrl, username = self._username, password = self._password)
					if self.configService.isLegacyOpsi():
						self.configService.authenticated()
					else:
						self.configService.accessControl_authenticated()
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
		#self._serviceUrlSubject.setMessage(self.opsiclientd.getConfigValue('config_service', 'url'))
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
			for urlIndex in range(len(self.opsiclientd.getConfigValue('config_service', 'url'))):
				url = self.opsiclientd.getConfigValue('config_service', 'url')[urlIndex]
				self._serviceUrlSubject.setMessage(url)
				
				choiceSubject = ChoiceSubject(id = 'choice')
				choiceSubject.setChoices([ 'Stop connection' ])
				
				logger.debug(u"Creating ServiceConnectionThread")
				serviceConnectionThread = ServiceConnectionThread(
							configServiceUrl    = url,
							username            = self.opsiclientd.getConfigValue('global', 'host_id'),
							password            = self.opsiclientd.getConfigValue('global', 'opsi_host_key'),
							statusObject        = self._statusSubject )
				
				choiceSubject.setCallbacks( [ serviceConnectionThread.stopConnectionCallback ] )
				
				cancelableAfter = forceInt(self.opsiclientd.getConfigValue('config_service', 'user_cancellable_after'))
				logger.info(u"User is allowed to cancel connection after %d seconds" % cancelableAfter)
				if (cancellableAfter < 1):
					self._notificationServer.addSubject(choiceSubject)
				
				timeout = forceInt(self.opsiclientd.getConfigValue('config_service', 'connection_timeout'))
				logger.info(u"Starting ServiceConnectionThread, timeout is %d seconds" % timeout)
				serviceConnectionThread.start()
				time.sleep(1)
				logger.debug(u"ServiceConnectionThread started")
				
				while serviceConnectionThread.running and (timeout > 0):
					logger.debug(u"Waiting for ServiceConnectionThread (timeout: %d, alive: %s, cancellable in: %d) " \
						% (timeout, serviceConnectionThread.isAlive(), cancelableAfter))
					self._detailSubjectProxy.setMessage( _(u'Timeout: %ds') % timeout )
					cancelableAfter -= 1
					if (cancelableAfter == 0):
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
						logger.error(u"ServiceConnectionThread timed out after %d seconds" % self.opsiclientd.getConfigValue('config_service', 'connection_timeout'))
						serviceConnectionThread.stop()
						raise Exception(u"Failed to connect to config service '%s': timed out after %d seconds" % \
									(url, self.opsiclientd.getConfigValue('config_service', 'connection_timeout')) )
					if not serviceConnectionThread.connected:
						raise Exception(u"Failed to connect to config service '%s': reason unknown" % self.opsiclientd.getConfigValue('config_service', 'url'))
				except Exception, e:
					if ( (urlIndex + 1) > len(self.opsiclientd.getConfigValue('config_service', 'url')) ):
						raise
					logger.error(e)
					continue
					
				self._configService = serviceConnectionThread.configService
				
				if (serviceConnectionThread.getUsername() != self.opsiclientd.getConfigValue('global', 'host_id')):
					self.opsiclientd.setConfigValue('global', 'host_id', serviceConnectionThread.getUsername().lower())
					logger.info(u"Updated host_id to '%s'" % self.opsiclientd.getConfigValue('global', 'host_id'))
				
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
			
			if self._configService.isLegacyOpsi():
				
				for (key, value) in self._configService.getNetworkConfig_hash(self.opsiclientd.getConfigValue('global', 'host_id')).items():
					if (key.lower() == 'depotid'):
						depotId = value
						self.opsiclientd.setConfigValue('depot_server', 'depot_id', depotId)
						self.opsiclientd.setConfigValue('depot_server', 'url', self._configService.getDepot_hash(depotId)['depotRemoteUrl'])
					elif (key.lower() == 'depotdrive'):
						self.opsiclientd.setConfigValue('depot_server', 'drive', value)
					elif (key.lower() == 'nextbootserviceurl'):
						self.opsiclientd.setConfigValue('config_service', 'url', [ value ])
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
			else:
				self._configService.backend_setOptions({"addConfigStateDefaults": True})
				for configState in self._configService.configState_getObjects(objectId = self.opsiclientd.getConfigValue('global', 'host_id')):
					logger.info(u"Got config state from service: %s" % configState)
					
					if not configState.values:
						continue
					
					if   (configState.configId == u'clientconfig.configserver.url'):
						self.opsiclientd.setConfigValue('config_service', 'url', configState.values)
					elif (configState.configId == u'clientconfig.depot.id'):
						self.opsiclientd.setConfigValue('depot_server', 'depot_id', configState.values[0])
					elif (configState.configId == u'clientconfig.depot.drive'):
						self.opsiclientd.setConfigValue('depot_server', 'drive', configState.values[0])
					elif configState.configId.startswith(u'opsiclientd.'):
						try:
							parts = configState.configId.lower().split('.')
							if (len(parts) < 3):
								continue
							
							self.opsiclientd.setConfigValue(section = parts[1], option = parts[2], value = configState.values[0])
							
						except Exception, e:
							logger.error(u"Failed to process configState '%s': %s" % (configState.configId, forceUnicode(e)))
					
			logger.notice(u"Got config from service")
			
			self.setStatusMessage(_(u"Got config from service"))
			logger.debug(u"Config is now:\n %s" % objectToBeautifiedText(self.opsiclientd.getConfig()))
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
			if self._configService.isLegacyOpsi():
				self._configService.writeLog('clientconnect', data.replace(u'\ufffd', u'?'), self.opsiclientd.getConfigValue('global', 'host_id'))
				#self._configService.writeLog('clientconnect', data.replace(u'\ufffd', u'?').encode('utf-8'), self.opsiclientd.getConfigValue('global', 'host_id'))
			else:
				self._configService.log_write('clientconnect', data.replace(u'\ufffd', u'?'), self.opsiclientd.getConfigValue('global', 'host_id'))
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
	
	def startNotifierApplication(self, command, desktop=None):
		logger.notice(u"Starting notifier application in session '%s'" % self.getSessionId())
		try:
			self.runCommandInSession(command = command.replace('%port%', unicode(self._notificationServerPort)), waitForProcessEnding = False)
			time.sleep(3)
		except Exception, e:
			logger.error(u"Failed to start notifier application '%s': %s" % (command, e))
	
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
		encryptedDepotServerPassword = u''
		if self._configService.isLegacyOpsi():
			encryptedDepotServerPassword = self._configService.getPcpatchPassword(self.opsiclientd.getConfigValue('global', 'host_id'))
		else:
			encryptedDepotServerPassword = self._configService.user_getCredentials(username = u'pcpatch', hostId = self.opsiclientd.getConfigValue('global', 'host_id'))['password']
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
			
			if self._configService.isLegacyOpsi():
				self._configService.setProductInstallationStatus(
							'opsi-winst',
							self.opsiclientd.getConfigValue('global', 'host_id'),
							'installed')
			else:
				self._configService.productOnClient_updateObjects([
					ProductOnClient(
						productId          = u'opsi-winst',
						productType        = u'LocalbootProduct',
						clientId           = self.opsiclientd.getConfigValue('global', 'host_id'),
						installationStatus = u'installed'
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
			productIds = []
			if self._configService.isLegacyOpsi():
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
				
				for productState in productStates:
					if (productState['actionRequest'] not in ('none', 'undefined')):
						productIds.append(productState['productId'])
						logger.notice("   [%2s] product %-20s %s" % (len(productIds), productState['productId'] + ':', productState['actionRequest']))
			else:
				for productOnClient in self._configService.productOnClient_getObjects(
							productType   = 'LocalbootProduct',
							clientId      = self.opsiclientd.getConfigValue('global', 'host_id'),
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
		
		
		(depotServerUsername, depotServerPassword) = self.getDepotserverCredentials()
		
		# Update action processor
		if self.opsiclientd.getConfigValue('depot_server', 'url').split('/')[2] not in ('127.0.0.1', 'localhost') and self.event.eventConfig.updateActionProcessor:
			self.updateActionProcessor()
		
		# Run action processor
		actionProcessorCommand = self.opsiclientd.fillPlaceholders(self.event.getActionProcessorCommand())
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
			configServiceUrls = self.opsiclientd.getConfigValue('config_service', 'url')
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
					logger.notice(u"Setting config service url back to %s" % configServiceUrls)
					self.opsiclientd.setConfigValue('config_service', 'url', configServiceUrls)
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






