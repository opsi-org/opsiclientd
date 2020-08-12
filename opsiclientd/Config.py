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
Configuring opsiclientd.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:author: Erol Ueluekmen <e.ueluekmen@uib.de>
:license: GNU Affero General Public License version 3
"""

import os
import platform
import re
import sys

from opsicommon.logging import logger, LOG_NOTICE, logging_config
from opsicommon.utils import Singleton
from OPSI.Types import (
	forceBool, forceHostId, forceInt, forceFilename, forceList,
	forceProductIdList, forceUnicode, forceUnicodeLower, forceUrl,
	forceUnicodeList
)
from OPSI.Util import objectToBeautifiedText, blowfishDecrypt
from OPSI.Util.File import IniFile
from OPSI import System
from opsiclientd.SystemCheck import RUNNING_ON_WINDOWS, RUNNING_ON_LINUX, RUNNING_ON_DARWIN

OPSI_CA = '''-----BEGIN CERTIFICATE-----
MIIEYTCCA0mgAwIBAgIJAO5oKZZR8dQkMA0GCSqGSIb3DQEBBQUAMH0xCzAJBgNV
BAYTAkRFMRgwFgYDVQQIEw9SaGVpbmxhbmQtUGZhbHoxDjAMBgNVBAcTBU1haW56
MREwDwYDVQQKEwh1aWIgR21iSDEVMBMGA1UEAxMMb3BzaSBSb290IENBMRowGAYJ
KoZIhvcNAQkBFgtpbmZvQHVpYi5kZTAeFw0xMTA2MDExMDI2NTNaFw0yMTA1Mjkx
MDI2NTNaMH0xCzAJBgNVBAYTAkRFMRgwFgYDVQQIEw9SaGVpbmxhbmQtUGZhbHox
DjAMBgNVBAcTBU1haW56MREwDwYDVQQKEwh1aWIgR21iSDEVMBMGA1UEAxMMb3Bz
aSBSb290IENBMRowGAYJKoZIhvcNAQkBFgtpbmZvQHVpYi5kZTCCASIwDQYJKoZI
hvcNAQEBBQADggEPADCCAQoCggEBAJxU7TXeNrwXPlsermmdRxvPkzaNqE7q9oev
lTLrdzMFNXekpg7nTMdvMEcPezHgkxrzRnIFrbyCKebVHvYBMYDSMefL0PGdBufW
vRuQVH5VtdjCZ3SJWHjrLHeV4RCddS/5f1Mx9mxaXuO/0qtpttFQKQ7wHU5a/8eE
Y2P+ZY7K4s8E/ZA2V3Tu6HxZJIt/JG0HoGrgEShb5hhRlpTVP5gRl/14qaZp9JZq
Hn7UHMEJlWLb7EXzY7wRIiHmI//V69X9ARrkS5axbDddatlZBEGonSfgObna5YOO
6Lx5aiq/PyYMEA6YWG+le//KgxexLCf5t5i8PEiFLuBrXCrKDG0CAwEAAaOB4zCB
4DAdBgNVHQ4EFgQUYr4TyTM6odj+hYr3luci6pnFtzEwgbAGA1UdIwSBqDCBpYAU
Yr4TyTM6odj+hYr3luci6pnFtzGhgYGkfzB9MQswCQYDVQQGEwJERTEYMBYGA1UE
CBMPUmhlaW5sYW5kLVBmYWx6MQ4wDAYDVQQHEwVNYWluejERMA8GA1UEChMIdWli
IEdtYkgxFTATBgNVBAMTDG9wc2kgUm9vdCBDQTEaMBgGCSqGSIb3DQEJARYLaW5m
b0B1aWIuZGWCCQDuaCmWUfHUJDAMBgNVHRMEBTADAQH/MA0GCSqGSIb3DQEBBQUA
A4IBAQCFSalk9ngRf+03YW6StULDkuMSRF6oj1A5J3eRZzXTL1uckTseXm5CK13d
OgxjZtgzD/TiVWoOmxGPVA+YYjLKpVUpPWu6opAG8cy705MeNxfAHLj+mn+joAxn
qjjH46t2W6hdcz0x86bIVSda97/erARX8ALBreI3e3iIH9D2de8IH5uj6q0UTO/P
YJHaSeCITO1g+NXisCS/aEfL+yUjXjErQaiRjtyj0aHDxj114GVvbKUOUfHqqa6X
USZQNXthwmMy0+iIgQLAmBDu9Tz53p+yqHIhS+7eYNfzh2HeIG3EY515ncnZG2Xi
QuBW/YzuIIiknjESIHBVA6YWeLNR
-----END CERTIFICATE-----'''

class SectionNotFoundException(ValueError):
	pass


class NoConfigOptionFoundException(ValueError):
	pass


class Config(metaclass=Singleton):
	WINDOWS_DEFAULT_PATHS = {
		'global': {
			'log_dir': u'c:\\opsi.org\\log',
			'state_file': u'c:\\opsi.org\\opsiclientd\\state.json',
			'timeline_db': u'c:\\opsi.org\\opsiclientd\\timeline.sqlite',
			'server_cert_dir': u'c:\\opsi.org\\opsiclientd\\server-certs'
		},
		'cache_service': {
			'storage_dir': u'c:\\opsi.org\\cache',
		},
	}

	LINUX_DEFAULT_PATHS = {
		'global': {
			'log_dir': "/var/log/opsi",
			'locale_dir': "/usr/share/opsi-client-agent/opsiclientd/locale",
			'config_file': "/etc/opsi-client-agent/opsiclientd.conf",
			'state_file': "/var/lib/opsi-client-agent/opsiclientd/state.json",
			'timeline_db': "/var/lib/opsi-client-agent/opsiclientd/timeline.sqlite",
			'server_cert_dir': "/etc/opsi-client-agent/server-certs"
		},
		'control_server': {
			'ssl_server_key_file': "/etc/opsi-client-agent/opsiclientd.pem",
			'ssl_server_cert_file': "/etc/opsi-client-agent/opsiclientd.pem",
			'static_dir': "/usr/share/opsi-client-agent/opsiclientd/static_html"
		},
		'cache_service': {
			'storage_dir': "/var/cache/opsi-client-agent"
		},
		'depot_server': {
			'drive': "/media/opsi_depot"
		}
	}

	MACOS_DEFAULT_PATHS = {
		'global': {
			'log_dir': "/var/log/opsi",
			'locale_dir': "/usr/share/opsi-client-agent/opsiclientd/locale",
			'config_file': "/etc/opsi-client-agent/opsiclientd.conf",
			'state_file': "/var/lib/opsi-client-agent/opsiclientd/state.json",
			'timeline_db': "/var/lib/opsi-client-agent/opsiclientd/timeline.sqlite",
			'server_cert_dir': "/etc/opsi-client-agent/server-certs"
		},
		'control_server': {
			'ssl_server_key_file': "/etc/opsi-client-agent/opsiclientd.pem",
			'ssl_server_cert_file': "/etc/opsi-client-agent/opsiclientd.pem",
			'static_dir': "/usr/share/opsi-client-agent/opsiclientd/static_html"
		},
		'cache_service': {
			'storage_dir': "/var/cache/opsi-client-agent"
		},
		'depot_server': {
			'drive': "/Network/opsi_depot"
		}
	}

	def __init__(self):
		baseDir = self._getBaseDirectory()

		self._temporaryConfigServiceUrls = []
		self._temporaryDepotDrive = []

		self._config = {
			'system': {
				'program_files_dir': u'',
			},
			'global': {
				'base_dir': baseDir,
				'locale_dir': os.path.join(baseDir, "opsiclientd", "locale"),
				'config_file': os.path.join(baseDir, "opsiclientd", "opsiclientd.conf"),
				'log_file': "opsiclientd.log",
				'log_level': LOG_NOTICE,
				'host_id': System.getFQDN().lower(),
				'opsi_host_key': u'',
				'wait_for_gui_timeout': 120,
				'block_login_notifier': u'',
				'verify_server_cert': False,
				'verify_server_cert_by_ca': False,
				'proxy_mode': u'static',
				'proxy_url': u'',
			},
			'config_service': {
				'url': [],
				'connection_timeout': 10,
				'user_cancelable_after': 0,
				'sync_time_from_service': False,
			},
			'depot_server': {
				'depot_id': u'',
				'url': u'',
				'drive': u'',
				'username': u'pcpatch',
			},
			'cache_service': {
				'product_cache_max_size': 6000000000,
				'extension_config_dir': u'',
			},
			'control_server': {
				'interface': '0.0.0.0',  # TODO
				'port': 4441,
				'ssl_server_key_file': os.path.join(baseDir, "opsiclientd", "opsiclientd.pem"),
				'ssl_server_cert_file': os.path.join(baseDir, "opsiclientd", "opsiclientd.pem"),
				'static_dir': os.path.join(baseDir, "opsiclientd", "static_html"),
				'max_authentication_failures': 5,
			},
			'notification_server': {
				'interface': u'127.0.0.1',
				'start_port': 44000,
				'popup_port': 45000,
			},
			'opsiclientd_notifier': {
				'command': u'',
			},
			'action_processor': {
				'local_dir': u'',
				'remote_dir': u'',
				'filename': u'',
				'command': u'',
				'run_as_user': u'SYSTEM',
				'create_user': True,
				'delete_user': True,
				'create_environment': False,
			}
		}

		self._applySystemSpecificConfiguration()

	@staticmethod
	def _getBaseDirectory():
		if RUNNING_ON_WINDOWS:
			pfp = os.environ.get("PROGRAMFILES(X86)", os.environ.get("PROGRAMFILES"))
			baseDir = os.path.join(pfp, "opsi.org", "opsi-client-agent")
			if not os.path.exists(baseDir):
				try:
					baseDir = os.path.abspath(os.path.dirname(sys.argv[0]))
				except:
					baseDir = "."
		else:
			baseDir = os.path.join('/usr', 'lib', 'opsi-client-agent')

		return baseDir

	def _applySystemSpecificConfiguration(self):
		defaultToApply = self.WINDOWS_DEFAULT_PATHS.copy()
		if RUNNING_ON_LINUX:
			defaultToApply = self.LINUX_DEFAULT_PATHS.copy()
		elif RUNNING_ON_DARWIN:
			defaultToApply = self.MACOS_DEFAULT_PATHS.copy()
		
		baseDir = self._config["global"]["base_dir"]
		
		for key in self._config:
			if key in defaultToApply:
				self._config[key].update(defaultToApply[key])

		self._config['cache_service']['extension_config_dir'] = os.path.join(baseDir, u'opsiclientd', 'extend.d')

		if RUNNING_ON_WINDOWS:
			systemDrive = System.getSystemDrive()
			logger.debug(
				'Running on windows: adapting paths to use system drive '
				'({0}).'.format(systemDrive)
			)
			systemDrive += "\\"
			self._config['cache_service']['storage_dir'] = os.path.join(systemDrive, 'opsi.org', 'cache')
			self._config['global']['config_file'] = os.path.join(baseDir, 'opsiclientd', 'opsiclientd.conf')
			self._config['global']['log_dir'] = os.path.join(systemDrive, 'opsi.org', 'log')
			self._config['global']['state_file'] = os.path.join(systemDrive, 'opsi.org', 'opsiclientd', 'state.json')
			self._config['global']['server_cert_dir'] = os.path.join(systemDrive, 'opsi.org', 'opsiclientd', 'server-certs')
			self._config['global']['timeline_db'] = os.path.join(systemDrive,  'opsi.org', 'opsiclientd', 'timeline.sqlite')
			self._config['system']['program_files_dir'] = System.getProgramFilesDir()
			
			if sys.getwindowsversion()[0] == 5:
				self._config['action_processor']['run_as_user'] = 'pcpatch'
		else:
			if '64' in platform.architecture()[0]:
				arch = '64'
			else:
				arch = '32'

			self._config['action_processor']['remote_dir'] = self._config['action_processor']['remote_dir'].replace('%arch%', arch)

			sslCertDir = os.path.join('/etc', 'opsi-client-agent')

			for certPath in ('ssl_server_key_file', 'ssl_server_cert_file'):
				if sslCertDir not in self._config['control_server'][certPath]:
					self._config['control_server'][certPath] = os.path.join(sslCertDir, self._config['control_server'][certPath])

	def getDict(self):
		return self._config

	def get(self, section, option, raw=False):
		if not section:
			section = 'global'

		section = forceUnicodeLower(section.strip()).lower()
		option = forceUnicodeLower(option.strip()).lower()
		if section not in self._config:
			raise SectionNotFoundException(u"No such config section: %s" % section)
		if option not in self._config[section]:
			raise NoConfigOptionFoundException(u"No such config option in section '%s': %s" % (section, option))

		value = self._config[section][option]
		if not raw and isinstance(value, str) and (value.count('%') >= 2):
			value = self.replace(value)
		if isinstance(value, str):
			value = forceUnicode(value)
		return value

	def set(self, section, option, value):
		if not section:
			section = 'global'

		section = forceUnicodeLower(section).strip()
		if section == 'system':
			return

		option = forceUnicodeLower(option).strip()
		if isinstance(value, str):
			value = forceUnicode(value).strip()

		if (option == 'warning_time'):
			option = 'action_warning_time'
		elif (option == 'user_cancelable'):
			option = 'action_user_cancelable'

		logger.info(u"Setting config value %s.%s" % (section, option))
		logger.debug(u"set({0!r}, {1!r}, {2!r})".format(section, option, value))

		if 	(option.find('command') == -1) and (option.find('productids') == -1) and \
			(option.find('exclude_product_group_ids') == -1) and \
			(option.find('include_product_group_ids') == -1) and \
			(option.find('proxy_url') == -1) and \
			(option.find('working_window') == -1) and (value == ''):
			logger.warning(u"Refusing to set empty value for config value '%s' of section '%s'" % (option, section))
			return

		if (section == 'depot_server') and (option == 'drive'):
			if (RUNNING_ON_LINUX or RUNNING_ON_DARWIN) and not value.startswith("/"):
				logger.warning("Refusing to set depot_server.drive to %s on posix", value)
				return

		if option == 'opsi_host_key':
			if len(value) != 32:
				raise ValueError("Bad opsi host key, length != 32")
			logger.addConfidentialString(value)
		elif option in ('depot_id', 'host_id'):
			value = forceHostId(value.replace('_', '-'))
		elif option in ('log_level', 'wait_for_gui_timeout', 'popup_port', 'port', 'start_port', 'max_authentication_failures'):
			value = forceInt(value)
		elif option in ('create_user', 'delete_user', 'verify_server_cert', 'verify_server_cert_by_ca', 'create_environment', 'active', 'sync_time_from_service', 'trusted_installer_detection'):
			value = forceBool(value)
		elif option in ('exclude_product_group_ids', 'include_product_group_ids'):
			if not isinstance(value, list):
				value = [x.strip() for x in value.split(",")]
			else:
				value = forceList(value)

		if section not in self._config:
			self._config[section] = {}

		self._config[section][option] = value

		if (section == 'config_service') and (option == 'url'):
			urls = self._config[section][option]
			if not isinstance(urls, list):
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
			logging_config(file_level=self._config[section][option])
		#elif (section == 'global') and (option == 'log_file'):
		#	logger.setLogFile(self._config[section][option])
		elif (section == 'global') and (option == 'server_cert_dir'):
			value = forceFilename(value)
			if not os.path.exists(value):
				os.makedirs(value)

			with open(os.path.join(value, 'cacert.pem'), 'w') as f:
				f.write(OPSI_CA)

	def replace(self, string, escaped=False):
		for (section, values) in self._config.items():
			if not isinstance(values, dict):
				continue
			for (key, value) in values.items():
				value = forceUnicode(value)
				if (string.find(u'"%' + forceUnicode(section) + u'.' + forceUnicode(key) + u'%"') != -1) and escaped:
					if (os.name == 'posix'):
						value = value.replace('"', '\\"')
					elif RUNNING_ON_WINDOWS:
						value = value.replace('"', '^"')
				newString = string.replace(u'%' + forceUnicode(section) + u'.' + forceUnicode(key) + u'%', value)

				if (newString != string):
					string = self.replace(newString, escaped)
		return forceUnicode(string)

	def readConfigFile(self):
		''' Get settings from config file '''
		logger.notice(u"Trying to read config from file: '%s'" % self.get('global', 'config_file'))

		try:
			# Read Config-File
			config = IniFile(filename=self.get('global', 'config_file'), raw=True).parse()
			
			# Read log settings early
			if config.has_section('global'):
				if config.has_option('global', 'log_level'):
					self.set('global', 'log_level', config.get('global', 'log_level'))
				#if config.has_option('global', 'log_file'):
				#	logFile = config.get('global', 'log_file')
					
			for section in config.sections():
				logger.debug(u"Processing section '%s' in config file: '%s'" % (section, self.get('global', 'config_file')))

				for (option, value) in config.items(section):
					option = option.lower()
					self.set(section.lower(), option, value)
		except Exception as e:
			# An error occured while trying to read the config file
			logger.error(u"Failed to read config file '%s': %s" % (self.get('global', 'config_file'), forceUnicode(e)))
			logger.logException(e)
			return
		logger.notice(u"Config read")
		logger.debug(u"Config is now:\n %s" % objectToBeautifiedText(self._config))

	def updateConfigFile(self):
		logger.notice(u"Updating config file: '%s'" % self.get('global', 'config_file'))

		try:
			configFile = IniFile(filename=self.get('global', 'config_file'), raw=True)
			configFile.setKeepOrdering(True)
			(config, comments) = configFile.parse(returnComments=True)
			changed = False
			for (section, values) in self._config.items():
				if not isinstance(values, dict):
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
					if isinstance(value, list):
						value = u', '.join(forceUnicodeList(value))
					else:
						value = forceUnicode(value)

					if not config.has_option(section, option) or (config.get(section, option) != value):
						changed = True
						config.set(section, option, value)

			if changed:
				# Write back config file if changed
				configFile.generate(config, comments=comments)
				logger.notice(u"Config file '%s' written" % self.get('global', 'config_file'))
			else:
				logger.notice(u"No need to write config file '%s', config file is up to date" % self.get('global', 'config_file'))
		except Exception as e:
			# An error occured while trying to write the config file
			logger.logException(e)
			logger.error(u"Failed to write config file '%s': %s" % (self.get('global', 'config_file'), forceUnicode(e)))

	def setTemporaryDepotDrive(self, temporaryDepotDrive):
		self._temporaryDepotDrive = temporaryDepotDrive

	def getDepotDrive(self):
		if self._temporaryDepotDrive:
			return self._temporaryDepotDrive
		return self.get('depot_server', 'drive')
	
	def setTemporaryConfigServiceUrls(self, temporaryConfigServiceUrls):
		self._temporaryConfigServiceUrls = forceList(temporaryConfigServiceUrls)

	def getConfigServiceUrls(self, allowTemporaryConfigServiceUrls=True):
		if allowTemporaryConfigServiceUrls and self._temporaryConfigServiceUrls:
			return self._temporaryConfigServiceUrls

		return self.get('config_service', 'url')

	def selectDepotserver(self, configService, event, productIds=[], cifsOnly=True, masterOnly=False):
		productIds = forceProductIdList(productIds)

		logger.notice(u"Selecting depot for products %s" % productIds)
		logger.notice(u"MasterOnly --> '%s'" % masterOnly)

		if event and event.eventConfig.useCachedProducts:
			cacheDepotDir = os.path.join(self.get('cache_service', 'storage_dir'), 'depot').replace('\\', '/').replace('//', '/')
			logger.notice(u"Using depot cache: %s" % cacheDepotDir)
			self.setTemporaryDepotDrive(cacheDepotDir.split(':')[0] + u':')
			self.set('depot_server', 'url', 'smb://localhost/noshare/' + ('/'.join(cacheDepotDir.split('/')[1:])))
			return

		if not configService:
			raise Exception(u"Not connected to config service")

		selectedDepot = None

		configService.backend_setOptions({"addConfigStateDefaults": True})

		depotIds = []
		configStates = []
		dynamicDepot = False
		depotProtocol = 'cifs'
		configStates = configService.configState_getObjects(
			configId=['clientconfig.depot.dynamic', 'clientconfig.depot.protocol', 'opsiclientd.depot_server.depot_id', 'opsiclientd.depot_server.url'],
			objectId=self.get('global', 'host_id')
		)
		for configState in configStates:
			if not configState.values or not configState.values[0]:
				continue

			if configState.configId == 'opsiclientd.depot_server.url' and configState.values:
				try:
					depotUrl = forceUrl(configState.values[0])
					self.set('depot_server', 'depot_id', u'')
					self.set('depot_server', 'url', depotUrl)
					logger.notice(u"Depot url was set to '%s' from configState %s" % (depotUrl, configState))
					return
				except Exception as error:
					logger.error(u"Failed to set depot url from values %s in configState %s: %s" % (configState.values, configState, error))
			elif configState.configId == 'opsiclientd.depot_server.depot_id' and configState.values:
				try:
					depotId = forceHostId(configState.values[0])
					depotIds.append(depotId)
					logger.notice(u"Depot was set to '%s' from configState %s" % (depotId, configState))
				except Exception as error:
					logger.error(u"Failed to set depot id from values %s in configState %s: %s" % (configState.values, configState, error))
			elif not masterOnly and (configState.configId == 'clientconfig.depot.dynamic') and configState.values:
				dynamicDepot = forceBool(configState.values[0])
			elif (configState.configId == 'clientconfig.depot.protocol') and configState.values and configState.values[0] and (configState.values[0] == 'webdav'):
				depotProtocol = 'webdav'

		if dynamicDepot:
			if not depotIds:
				logger.info(u"Dynamic depot selection enabled")
			else:
				logger.info(u"Dynamic depot selection enabled, but depot is already selected")
		else:
			logger.info(u"Dynamic depot selection disabled")

		if not depotIds:
			clientToDepotservers = configService.configState_getClientToDepotserver(
				clientIds=[self.get('global', 'host_id')],
				masterOnly=bool(not dynamicDepot),
				productIds=productIds
			)
			if not clientToDepotservers:
				raise Exception(u"Failed to get depot config from service")

			depotIds = [clientToDepotservers[0]['depotId']]
			if dynamicDepot:
				depotIds.extend(clientToDepotservers[0].get('alternativeDepotIds', []))

		masterDepot = None
		alternativeDepots = []
		for depot in configService.host_getObjects(type='OpsiDepotserver', id=depotIds):
			if depot.id == depotIds[0]:
				masterDepot = depot
			else:
				alternativeDepots.append(depot)

		if not masterDepot:
			raise Exception(u"Failed to get info for master depot '%s'" % depotIds[0])

		logger.info(u"Master depot for products %s is %s" % (productIds, masterDepot.id))
		selectedDepot = masterDepot
		if dynamicDepot:
			if alternativeDepots:
				logger.info(u"Got alternative depots for products: %s" % productIds)
				for index, depot in enumerate(alternativeDepots, start=1):
					logger.info(u"%d. alternative depot is %s", index, depot.id)

				defaultInterface = None
				try:
					networkInterfaces = System.getNetworkInterfaces()
					if not networkInterfaces:
						raise Exception(u"No network interfaces found")

					for networkInterface in networkInterfaces:
						logger.info(u"Found network interface: %s" % networkInterface)

					defaultInterface = networkInterfaces[0]
					for networkInterface in networkInterfaces:
						if networkInterface.ipAddressList.ipAddress == '0.0.0.0':
							continue

						if networkInterface.gatewayList.ipAddress:
							defaultInterface = networkInterface
							break

					clientConfig = {
						"clientId": self.get('global', 'host_id'),
						"opsiHostKey": self.get('global', 'opsi_host_key'),
						"ipAddress": forceUnicode(defaultInterface.ipAddressList.ipAddress),
						"netmask": forceUnicode(defaultInterface.ipAddressList.ipMask),
						"defaultGateway": forceUnicode(defaultInterface.gatewayList.ipAddress)
					}

					logger.info(u"Passing client configuration to depot selection algorithm: %s" % clientConfig)

					depotSelectionAlgorithm = configService.getDepotSelectionAlgorithm()
					logger.debug2(u"depotSelectionAlgorithm:\n%s" % depotSelectionAlgorithm)
					
					currentLocals = locals()
					exec(depotSelectionAlgorithm, None, currentLocals)
					selectDepot = currentLocals['selectDepot']

					selectedDepot = selectDepot(
						clientConfig=clientConfig,
						masterDepot=masterDepot,
						alternativeDepots=alternativeDepots
					)
					if not selectedDepot:
						selectedDepot = masterDepot
				except Exception as error:
					logger.logException(error)
					logger.error(u"Failed to select depot: %s" % error)
			else:
				logger.info(u"No alternative depot for products: %s" % productIds)

		logger.notice(u"Selected depot is: %s" % selectedDepot)
		self.set('depot_server', 'depot_id', selectedDepot.id)
		if (depotProtocol == 'webdav') and not cifsOnly:
			self.set('depot_server', 'url', selectedDepot.depotWebdavUrl)
		else:
			self.set('depot_server', 'url', selectedDepot.depotRemoteUrl)

	def getDepotserverCredentials(self, configService):
		if not configService:
			raise Exception(u"Not connected to config service")

		depotServerUsername = self.get('depot_server', 'username')
		encryptedDepotServerPassword = configService.user_getCredentials(
			username=u'pcpatch',
			hostId=self.get('global', 'host_id')
		)['password']
		depotServerPassword = blowfishDecrypt(self.get('global', 'opsi_host_key'), encryptedDepotServerPassword)
		logger.addConfidentialString(depotServerPassword)
		logger.debug(u"Using username '%s' for depot connection" % depotServerUsername)
		return (depotServerUsername, depotServerPassword)

	def getFromService(self, configService):
		''' Get settings from service '''
		logger.notice(u"Getting config from service")
		if not configService:
			raise Exception(u"Config service is undefined")

		query = {
			"objectId": self.get('global', 'host_id'),
			"configId": [
				'clientconfig.configserver.url',
				'clientconfig.depot.drive',
				'clientconfig.depot.id',
				'clientconfig.depot.user',
				'opsiclientd.*'  # everything starting with opsiclientd.
			]
		}

		configService.backend_setOptions({"addConfigStateDefaults": True})
		for configState in configService.configState_getObjects(**query):
			logger.info(u"Got config state from service: %r" % configState)

			if not configState.values:
				logger.debug(u"No values - skipping {0!r}".format(configState.configId))
				continue

			if configState.configId == u'clientconfig.configserver.url':
				self.set('config_service', 'url', configState.values)
			elif configState.configId == u'clientconfig.depot.drive':
				self.set('depot_server', 'drive', configState.values[0])
			elif configState.configId == u'clientconfig.depot.id':
				self.set('depot_server', 'depot_id', configState.values[0])
			elif configState.configId == u'clientconfig.depot.user':
				self.set('depot_server', 'username', configState.values[0])
			elif configState.configId.startswith(u'opsiclientd.'):
				try:
					parts = configState.configId.lower().split('.')
					if len(parts) < 3:
						logger.debug(u"Expected at least 3 parts in {0!r} - skipping.".format(configState.configId))
						continue

					self.set(section=parts[1], option=parts[2], value=configState.values[0])
				except Exception as e:
					logger.error(u"Failed to process configState '%s': %s" % (configState.configId, forceUnicode(e)))

		logger.notice(u"Got config from service")
		logger.debug(u"Config is now:\n %s" % objectToBeautifiedText(self.getDict()))
