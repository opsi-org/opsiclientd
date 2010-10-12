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

import sys

# OPSI imports
from OPSI.Logger import *
from OPSI.Types import *
from OPSI.Util import objectToBeautifiedText
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
				'storage_dir':            u'c:\\opsi\\cache',
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
			self._config['cache_service']['storage_dir'] = u'%s\\opsi\\cache' % System.getSystemDrive()
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








