# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = = = =
   =   ocdlib.Config                       =
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

import sys, base64
from hashlib import md5
from twisted.conch.ssh import keys

# OPSI imports
from OPSI.Logger import *
from OPSI.Types import *
from OPSI.Util import objectToBeautifiedText, blowfishDecrypt
from OPSI.Util.File import IniFile
from OPSI import System

# Get logger instance
logger = Logger()



class ConfigImplementation(object):
	
	def __init__(self):
		
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
				'base_dir':             baseDir,
				'locale_dir':           os.path.join(baseDir, 'locale'),
				'config_file':          u'opsiclientd.conf',
				'log_file':             u'opsiclientd.log',
				'log_level':            LOG_NOTICE,
				'host_id':              System.getFQDN().lower(),
				'opsi_host_key':        u'',
				'wait_for_gui_timeout': 120,
				'block_login_notifier': u'',
			},
			'config_service': {
				'url':                   [],
				'connection_timeout':    10,
				'user_cancelable_after': 0,
			},
			'depot_server': {
				'depot_id': u'',
				'url':      u'',
				'drive':    u'',
				'username': u'pcpatch',
			},
			'cache_service': {
				'storage_dir':            u'c:\\opsi.org\\cache',
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
		
		if (os.name == 'nt'):
			self._config['system']['program_files_dir'] = System.getProgramFilesDir()
			self._config['cache_service']['storage_dir'] = u'%s\\opsi.org\\cache' % System.getSystemDrive()
			self._config['cache_service']['backend_manager_config'] = os.path.join(baseDir, u'opsiclientd', 'backendManager.d')
			self._config['global']['config_file'] = os.path.join(baseDir, u'opsiclientd', 'opsiclientd.conf')
			
		if (sys.getwindowsversion()[0] == 5):
			self._config['action_processor']['run_as_user'] = 'pcpatch'
		
	def getDict(self):
		return self._config
	
	def get(self, section, option, raw = False):
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
			value = self.replace(value)
		if type(value) is str:
			value = unicode(value)
		return value
	
	def set(self, section, option, value):
		if not section:
			section = 'global'
		
		section = forceUnicodeLower(section).strip()
		option = forceUnicodeLower(option).strip()
		if type(value) in (str, unicode):
			value = forceUnicode(value).strip()
		
		logger.info(u"Setting config value %s.%s" % (section, option))
		logger.debug(u"set(%s, %s, %s)" % (section, option, value))
		
		if option not in ('action_processor_command') and (value == ''):
			logger.warning(u"Refusing to set empty value for config value '%s' of section '%s'" % (option, section))
			return
		
		if (option == 'opsi_host_key'):
			if (len(value) != 32):
				raise ValueError("Bad opsi host key, length != 32")
			logger.addConfidentialString(value)
		
		if option in ('depot_id', 'host_id'):
			value = forceHostId(value.replace('_', '-'))
		
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
			urls = self._config[section][option]
			if not type(urls) is list:
				urls = forceUnicode(self._config[section][option]).split(u',')
			self._config[section][option] = []
			for url in forceUnicodeList(urls):
				url = url.strip()
				if not re.search('https?://[^/]+', url):
					logger.error("Bad config service url '%s'" % url)
				self._config[section][option].append(url)
		elif (section == 'config_service') and option in ('connection_timeout', 'user_cancelable_after'):
			self._config[section][option] = int(self._config[section][option])
			if (self._config[section][option] < 0):
				self._config[section][option] = 0
		elif (section == 'global') and (option == 'log_level'):
			logger.setFileLevel(self._config[section][option])
		elif (section == 'global') and (option == 'log_file'):
			logger.setLogFile(self._config[section][option])
	
	def replace(self, string, escaped=False):
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
					string = self.replace(newString, escaped)
		return forceUnicode(string)
	
	def readConfigFile(self):
		''' Get settings from config file '''
		logger.notice(u"Trying to read config from file: '%s'" % self.get('global', 'config_file'))
		
		try:
			# Read Config-File
			config = IniFile(filename = self.get('global', 'config_file'), raw = True).parse()
			
			# Read log settings early
			if config.has_section('global'):
				debug = False
				if (os.name == 'nt'):
					try:
						debug = forceBool(System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SYSTEM\\CurrentControlSet\\Services\\opsiclientd", "Debug"))
					except:
						pass
				if not debug:
					if config.has_option('global', 'log_level'):
						self.set('global', 'log_level', config.get('global', 'log_level'))
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
						self.set('global', 'log_file', logFile)
			
			# Process all sections
			for section in config.sections():
				logger.debug(u"Processing section '%s' in config file: '%s'" % (section, self.get('global', 'config_file')))
				
				for (option, value) in config.items(section):
					option = option.lower()
					self.set(section.lower(), option, value)
				
		except Exception, e:
			# An error occured while trying to read the config file
			logger.error(u"Failed to read config file '%s': %s" % (self.get('global', 'config_file'), forceUnicode(e)))
			logger.logException(e)
			return
		logger.notice(u"Config read")
		logger.debug(u"Config is now:\n %s" % objectToBeautifiedText(self._config))
	
	def updateConfigFile(self):
		''' Get settings from config file '''
		logger.notice(u"Updating config file: '%s'" % self.get('global', 'config_file'))
		
		try:
			# Read config file
			configFile = IniFile(filename = self.get('global', 'config_file'), raw = True)
			configFile.setSectionSequence(['global', 'config_service', 'depot_server', 'cache_service', 'control_server', 'notification_server', 'opsiclientd_notifier', 'opsiclientd_rpc', 'action_processor'])
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
				logger.notice(u"Config file '%s' written" % self.get('global', 'config_file'))
			else:
				logger.notice(u"No need to write config file '%s', config file is up to date" % self.get('global', 'config_file'))
			
		except Exception, e:
			# An error occured while trying to write the config file
			logger.logException(e)
			logger.error(u"Failed to write config file '%s': %s" % (self.get('global', 'config_file'), forceUnicode(e)))
	
	def selectDepot(self, configService, productIds=[]):
		logger.notice(u"Selecting depot")
		if not configService:
			raise Exception(u"Not connected to config service")
		
		if configService.isLegacyOpsi():
			return
		
		selectedDepot = None
		
		configService.backend_setOptions({"addConfigStateDefaults": True})
		
		depotIds = []
		dynamicDepot = False
		for configState in configService.configState_getObjects(
					configId = ['clientconfig.depot.dynamic', 'opsiclientd.depot_server.depot_id', 'opsiclientd.depot_server.url'],
					objectId = self.get('global', 'host_id')):
			if not configState.values or not configState.values[0]:
				continue
			if   (configState.configId == 'opsiclientd.depot_server.url'):
				try:
					depotUrl = forceUrl(configState.values[0])
					self.set('depot_server', 'depot_id', u'')
					self.set('depot_server', 'url', depotUrl)
					logger.notice(u"Depot url was set to '%s' from configState %s" % (depotUrl, configState))
					return
				except Exception, e:
					logger.error(u"Failed to set depot url from values %s in configState %s: %s" % (configState.values, configState, e))
			elif (configState.configId == 'opsiclientd.depot_server.depot_id'):
				try:
					depotId = forceHostId(configState.values[0])
					depotIds.append(depotId)
					logger.notice(u"Depot was set to '%s' from configState %s" % (depotId, configState))
				except Exception, e:
					logger.error(u"Failed to set depot id from values %s in configState %s: %s" % (configState.values, configState, e))
			elif (configState.configId == 'clientconfig.depot.dynamic'):
				dynamicDepot = forceBool(configState.values[0])
		
		if not depotIds:
			if dynamicDepot:
				logger.info(u"Dynamic depot selection enabled")
			clientToDepotservers = configService.configState_getClientToDepotserver(
					clientIds  = [ self.get('global', 'host_id') ],
					masterOnly = (not dynamicDepot),
					productIds = productIds)
			if not clientToDepotservers:
				raise Exception(u"Failed to get depot config from service")
			
			depotIds = [ clientToDepotservers[0]['depotId'] ]
			if dynamicDepot:
				depotIds.extend(clientToDepotservers[0].get('slaveDepotIds', []))
		masterDepot = None
		alternativeDepots = []
		for depot in configService.host_getObjects(type = 'OpsiDepotserver', id = depotIds):
			if (depot.id == depotIds[0]):
				masterDepot = depot
			else:
				alternativeDepots.append(depot)
		if not masterDepot:
			raise Exception(u"Failed to get info for master depot '%s'" % depotIds[0])
		
		selectedDepot = masterDepot
		if dynamicDepot and alternativeDepots:
			try:
				modules = configService.backend_info()['modules']
			
				if not modules.get('dynamic_depot'):
					raise Exception(u"Dynamic depot module currently disabled")
				
				if not modules.get('customer'):
					raise Exception(u"No customer in modules file")
					
				if not modules.get('valid'):
					raise Exception(u"Modules file invalid")
				
				if (modules.get('expires', '') != 'never') and (time.mktime(time.strptime(modules.get('expires', '2000-01-01'), "%Y-%m-%d")) - time.time() <= 0):
					raise Exception(u"Modules file expired")
				
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
					raise Exception(u"Modules file invalid")
				logger.notice(u"Modules file signature verified (customer: %s)" % modules.get('customer'))
				
				defaultInterface = None
				networkInterfaces = System.getNetworkInterfaces()
				if not networkInterfaces:
					raise Exception(u"No network interfaces found")
				defaultInterface = networkInterfaces[0]
				for networkInterface in networkInterfaces:
					if networkInterface.gatewayList.ipAddress:
						defaultInterface = networkInterface
						break
				clientConfig = {
					"clientId":       self.get('global', 'host_id'),
					"ipAddress":      forceUnicode(defaultInterface.ipAddressList.ipAddress),
					"netmask":        forceUnicode(defaultInterface.ipAddressList.ipMask),
					"defaultGateway": forceUnicode(defaultInterface.gatewayList.ipAddress)
				}
				
				depotSelectionAlgorithm = configService.getDepotSelectionAlgorithm()
				logger.debug2(u"depotSelectionAlgorithm:\n%s" % depotSelectionAlgorithm)
				exec(depotSelectionAlgorithm)
				selectedDepot = selectDepot(clientConfig = clientConfig, masterDepot = masterDepot, alternativeDepots = alternativeDepots)
				
			except Exception, e:
				logger.logException(e)
				logger.error(u"Failed to select depot: %s" % e)
			
		logger.notice(u"Selected depot is: %s" % selectedDepot)
		self.set('depot_server', 'depot_id', selectedDepot.id)
		self.set('depot_server', 'url', selectedDepot.depotRemoteUrl)
	
	def getDepotserverCredentials(self, configService):
		if not configService:
			raise Exception(u"Not connected to config service")
		
		depotServerUsername = self.get('depot_server', 'username')
		encryptedDepotServerPassword = u''
		if configService.isLegacyOpsi():
			encryptedDepotServerPassword = configService.getPcpatchPassword(self.get('global', 'host_id'))
		else:
			encryptedDepotServerPassword = configService.user_getCredentials(username = u'pcpatch', hostId = self.get('global', 'host_id'))['password']
		depotServerPassword = blowfishDecrypt(self.get('global', 'opsi_host_key'), encryptedDepotServerPassword)
		logger.addConfidentialString(depotServerPassword)
		return (depotServerUsername, depotServerPassword)
	
class Config(ConfigImplementation):
	# Storage for the instance reference
	__instance = None
	
	def __init__(self):
		""" Create singleton instance """
		
		# Check whether we already have an instance
		if Config.__instance is None:
			# Create and remember instance
			Config.__instance = ConfigImplementation()
		
		# Store instance reference as the only member in the handle
		self.__dict__['_Config__instance'] = Config.__instance
	
	
	def __getattr__(self, attr):
		""" Delegate access to implementation """
		return getattr(self.__instance, attr)

	def __setattr__(self, attr, value):
		""" Delegate access to implementation """
	 	return setattr(self.__instance, attr, value)








