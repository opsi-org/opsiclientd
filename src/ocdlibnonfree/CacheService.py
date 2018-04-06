# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org

# Copyright (C) 2014-2018 uib GmbH
# http://www.uib.de/
# All rights reserved.

"""
ocdlibnonfree.CacheService

@copyright: uib GmbH <info@uib.de>
@author: Jan Schneider <j.schneider@uib.de>
@author: Erol Ueluekmen <e.ueluekmen@uib.de>
"""

import base64
import codecs
import os
import threading
import time
from hashlib import md5
from twisted.conch.ssh import keys

from OPSI.Logger import *
from OPSI.Types import *
from OPSI.Object import *
from OPSI.Util.Repository import *
from OPSI import System
from OPSI.Util.HTTP import urlsplit
from OPSI.Backend.Backend import ExtendedConfigDataBackend
from OPSI.Backend.BackendManager import BackendExtender
from OPSI.Backend.Cache import ClientCacheBackend
from OPSI.Backend.SQLite import SQLiteBackend, SQLiteObjectBackendModificationTracker

from ocdlib.Config import Config
from ocdlib.State import State
from ocdlib.Events import SyncCompletedEventGenerator, getEventGenerators
from ocdlib.OpsiService import ServiceConnection
from ocdlib.Timeline import Timeline

logger = Logger()
config = Config()
state = State()
timeline = Timeline()


class CacheService(threading.Thread):
	def __init__(self, opsiclientd):
		threading.Thread.__init__(self)
		self._productCacheService = None
		self._configCacheService = None

	def stop(self):
		if self._productCacheService:
			self._productCacheService.stop()
		if self._configCacheService:
			self._configCacheService.stop()

	def initializeProductCacheService(self):
		if not self._productCacheService:
			self._productCacheService = ProductCacheService()
			self._productCacheService.start()

	def initializeConfigCacheService(self):
		if not self._configCacheService:
			self._configCacheService = ConfigCacheService()
			self._configCacheService.start()

	def setConfigCacheObsolete(self):
		self.initializeConfigCacheService()
		self._configCacheService.setObsolete()

	def syncConfig(self, waitForEnding=False):
		self.initializeConfigCacheService()
		if self._configCacheService.isWorking():
			logger.info(u"Already syncing config")
		else:
			logger.info(u"Trigger config sync")
			self._configCacheService.syncConfig()
		if waitForEnding:
			time.sleep(3)
			while self._configCacheService.isRunning() and self._configCacheService.isWorking():
				time.sleep(1)

	def syncConfigToServer(self, waitForEnding=False):
		self.initializeConfigCacheService()
		if self._configCacheService.isWorking():
			logger.info(u"Already syncing config")
		else:
			logger.info(u"Trigger config sync to server")
			self._configCacheService.syncConfigToServer()
		if waitForEnding:
			time.sleep(3)
			while self._configCacheService.isRunning() and self._configCacheService.isWorking():
				time.sleep(1)

	def syncConfigFromServer(self, waitForEnding=False):
		self.initializeConfigCacheService()
		if self._configCacheService.isWorking():
			logger.info(u"Already syncing config")
		else:
			logger.info(u"Trigger config sync from server")
			self._configCacheService.syncConfigFromServer()
		if waitForEnding:
			time.sleep(3)
			while self._configCacheService.isRunning() and self._configCacheService.isWorking():
				time.sleep(1)

	def configCacheCompleted(self):
		try:
			self.initializeConfigCacheService()
		except Exception as e:
			logger.logException(e, LOG_INFO)
			logger.error(e)
			return False
		if not self._configCacheService.isWorking() and self._configCacheService.getState().get('config_cached', False):
			return True
		return False

	def getConfigBackend(self):
		self.initializeConfigCacheService()
		return self._configCacheService.getConfigBackend()

	def getConfigModifications(self):
		self.initializeConfigCacheService()
		return self._configCacheService._backendTracker.getModifications()

	def cacheProducts(self, waitForEnding=False, productProgressObserver=None, overallProgressObserver=None, dynamicBandwidth=True, maxBandwidth=0):
		self.initializeProductCacheService()
		if self._productCacheService.isWorking():
			logger.info(u"Already caching products")
		else:
			logger.info(u"Trigger product caching")
			self._productCacheService.setDynamicBandwidth(dynamicBandwidth)
			self._productCacheService.setMaxBandwidth(maxBandwidth)
			self._productCacheService.cacheProducts(productProgressObserver=productProgressObserver, overallProgressObserver=overallProgressObserver)
		if waitForEnding:
			time.sleep(3)
			while self._productCacheService.isRunning() and self._productCacheService.isWorking():
				time.sleep(1)

	def productCacheCompleted(self, configService, productIds):
		if not productIds:
			return True
		self.initializeProductCacheService()

		clientToDepotservers = configService.configState_getClientToDepotserver(
				clientIds=[config.get('global', 'host_id')],
				masterOnly=True,
				productIds=productIds)
		if not clientToDepotservers:
			raise Exception(u"Failed to get depot config from service")
		depotId = [clientToDepotservers[0]['depotId']]
		productOnDepots = {}
		for productOnDepot in configService.productOnDepot_getObjects(depotId=depotId, productId=productIds):
			productOnDepots[productOnDepot.productId] = productOnDepot

		for productId in productIds:
			productOnDepot = productOnDepots.get(productId)
			if not productOnDepot:
				raise Exception(u"Product '%s' not available on depot '%s'" % (productId, depotId))
			productState = self._productCacheService.getState().get('products', {}).get(productId)
			if not productState:
				logger.info(u"No products cached")
				return False
			if not productState.get('completed') or (productState.get('productVersion') != productOnDepot.productVersion) or (productState.get('packageVersion') != productOnDepot.packageVersion):
				logger.info(u"Product '%s_%s-%s' not yet cached (got state: %s)" % (productId, productOnDepot.productVersion, productOnDepot.packageVersion, productState))
				return False
		return True

	def getProductCacheState(self):
		self.initializeProductCacheService()
		return self._productCacheService.getState()

	def getConfigCacheState(self):
		self.initializeConfigCacheService()
		return self._configCacheService.getState()

	def getProductCacheDir(self):
		self.initializeProductCacheService()
		return self._productCacheService.getProductCacheDir()


class ConfigCacheServiceBackendExtension(object):
	def accessControl_authenticated(self):
		return True


class ConfigCacheService(ServiceConnection, threading.Thread):
	def __init__(self):
		try:
			threading.Thread.__init__(self)
			ServiceConnection.__init__(self)
			moduleName = u' %-30s' % (u'config cache service')
			logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)

			self._configCacheDir = os.path.join(config.get('cache_service', 'storage_dir'), 'config')
			self._opsiModulesFile = os.path.join(self._configCacheDir, 'cached_modules')
			self._opsiVersionFile = os.path.join(self._configCacheDir, 'cached_version')
			self._opsiPasswdFile = os.path.join(self._configCacheDir, 'cached_passwd')
			self._auditHardwareConfigFile = os.path.join(self._configCacheDir, 'cached_opsihwaudit.json')

			self._stopped = False
			self._running = False
			self._working = False
			self._state = {}

			self._syncConfigFromServerRequested = False
			self._syncConfigToServerRequested = False

			if not os.path.exists(self._configCacheDir):
				logger.notice(u"Creating config cache dir '%s'" % self._configCacheDir)
				os.makedirs(self._configCacheDir)

			self.initBackends()

			ccss = state.get('config_cache_service')
			if ccss:
				self._state = ccss
		except Exception as e:
			logger.logException(e)
			try:
				self.setObsolete()
			except Exception:
				pass
			raise e

	def initBackends(self):
		depotId = config.get('depot_server', 'depot_id')
		if not depotId:
			connect = False
			if not self._configService:
				self.connectConfigService()
				connect = True
			config.selectDepotserver(configService=self._configService, event=None, productIds=[], masterOnly=True)
			config.updateConfigFile()
			if connect:
				self.disconnectConfigService()
			depotId = config.get('depot_server', 'depot_id')

		backendArgs = {
			'opsiModulesFile':         self._opsiModulesFile,
			'opsiVersionFile':         self._opsiVersionFile,
			'opsiPasswdFile':          self._opsiPasswdFile,
			'auditHardwareConfigFile': self._auditHardwareConfigFile,
			'depotId':                 depotId,
		}
		self._workBackend = SQLiteBackend(
			database=os.path.join(self._configCacheDir, 'work.sqlite'),
			synchronous=False,
			**backendArgs
		)
		self._workBackend.backend_createBase()

		self._snapshotBackend = SQLiteBackend(
			database=os.path.join(self._configCacheDir, 'snapshot.sqlite'),
			synchronous=False,
			**backendArgs
		)
		self._snapshotBackend.backend_createBase()

		self._cacheBackend = ClientCacheBackend(
			workBackend=self._workBackend,
			snapshotBackend=self._snapshotBackend,
			clientId=config.get('global', 'host_id'),
			**backendArgs
		)

		self._configBackend = BackendExtender(
			backend=ExtendedConfigDataBackend(
				configDataBackend=self._cacheBackend
			),
			extensionClass=ConfigCacheServiceBackendExtension,
			extensionConfigDir=config.get('cache_service', 'extension_config_dir')
		)
		self._backendTracker = SQLiteObjectBackendModificationTracker(
			database=os.path.join(self._configCacheDir, 'tracker.sqlite'),
			synchronous=False,
			lastModificationOnly=True
		)
		self._cacheBackend.addBackendChangeListener(self._backendTracker)

	def connectConfigService(self):
		ServiceConnection.connectConfigService(self, allowTemporaryConfigServiceUrls=False)
		try:
			modules = None
			helpermodules = {}
			backendinfo = self._configService.backend_info()
			hostCount = len(self._configService.host_getIdents(type="OpsiClient"))
			modules = backendinfo['modules']
			helpermodules = backendinfo['realmodules']

			if not modules.get('vpn'):
				raise Exception(u"Cannot sync products: VPN module currently disabled")

			if not modules.get('customer'):
				raise Exception(u"Cannot sync products: No customer in modules file")

			if not modules.get('valid'):
				raise Exception(u"Cannot sync products: modules file invalid")

			if (modules.get('expires', '') != 'never') and (time.mktime(time.strptime(modules.get('expires', '2000-01-01'), "%Y-%m-%d")) - time.time() <= 0):
				raise Exception(u"Cannot sync products: modules file expired")

			logger.info(u"Verifying modules file signature")
			publicKey = keys.Key.fromString(data=base64.decodestring('AAAAB3NzaC1yc2EAAAADAQABAAABAQCAD/I79Jd0eKwwfuVwh5B2z+S8aV0C5suItJa18RrYip+d4P0ogzqoCfOoVWtDojY96FDYv+2d73LsoOckHCnuh55GA0mtuVMWdXNZIE8Avt/RzbEoYGo/H0weuga7I8PuQNC/nyS8w3W8TH4pt+ZCjZZoX8S+IizWCYwfqYoYTMLgB0i+6TCAfJj3mNgCrDZkQ24+rOFS4a8RrjamEz/b81noWl9IntllK1hySkR+LbulfTGALHgHkDUlk0OSu+zBPw/hcDSOMiDQvvHfmR4quGyLPbQ2FOVm1TzE0bQPR+Bhx4V8Eo2kNYstG2eJELrz7J1TJI0rCjpB+FQjYPsP')).keyObject
			data = u''
			mks = modules.keys()
			mks.sort()
			for module in mks:
				if module in ('valid', 'signature'):
					continue
				if module in helpermodules:
					val = helpermodules[module]
					if module == 'vpn':
						if int(val) + 50 <= hostCount:
							raise Exception(u"UNDERLICENSED: You have more Clients then licensed in modules file. Disabling module vpn.")
						elif int(val) <= hostCount:
							logger.warning("WARNING UNDERLICENSED: You have more Clients then licensed in modules file.")
						modules[module] = True
					else:
						if int(val) > 0:
							modules[module] = True
				else:
					val = modules[module]
					if val == False:
						val = 'no'
					if val == True:
						val = 'yes'
				data += u'%s = %s\r\n' % (module.lower().strip(), val)
			if not bool(publicKey.verify(md5(data).digest(), [long(modules['signature'])])):
				raise Exception(u"Cannot sync products: modules file invalid")
			logger.notice(u"Modules file signature verified (customer: %s)" % modules.get('customer'))
		except Exception:
			self.disconnectConfigService()
			raise

	def getConfigBackend(self):
		return self._configBackend

	def getState(self):
		state = self._state
		state['running'] = self.isRunning()
		state['working'] = self.isWorking()
		return state

	def setObsolete(self):
		self._state['config_cached'] = False
		state.set('config_cache_service', self._state)

	def isRunning(self):
		return self._running

	def isWorking(self):
		if self._working:
			return True
		time.sleep(1)
		if self._working:
			return True
		time.sleep(1)
		if self._working:
			return True
		return False

	def stop(self):
		self._stopped = True

	def run(self):
		self._running = True
		logger.notice(u"Config cache service started")
		try:
			while not self._stopped:
				if not self._working:
					if self._syncConfigToServerRequested:
						self._syncConfigToServerRequested = False
						self._syncConfigToServer()
					elif self._syncConfigFromServerRequested:
						self._syncConfigFromServerRequested = False
						self._syncConfigFromServer()
				time.sleep(1)
		except Exception as e:
			logger.logException(e)
		logger.notice(u"Config cache service ended")
		self._running = False

	def syncConfig(self):
		self._syncConfigToServerRequested = True
		self._syncConfigFromServerRequested = True

	def syncConfigToServer(self):
		self._syncConfigToServerRequested = True

	def syncConfigFromServer(self):
		self._syncConfigFromServerRequested = True

	def _syncConfigToServer(self):
		self._working = True
		eventId = None
		try:
			modifications = self._backendTracker.getModifications()
			if not modifications:
				logger.notice(u"Cache backend was not modified, no sync to server required")
			else:
				try:
					logger.notice(u"Cache backend was modified, starting sync to server")
					eventId = timeline.addEvent(
						title=u"Config sync to server",
						description=u'Syncing config to server',
						category=u'config_sync',
						durationEvent=True
					)
					if not self._configService:
						self.connectConfigService()
					self._cacheBackend._setMasterBackend(self._configService)
					self._cacheBackend._updateMasterFromWorkBackend(modifications)
					self._backendTracker.clearModifications()
					try:
						instlog = os.path.join(config.get('global', 'log_dir'), u'opsi-script.log')
						logger.debug(u"Checking if a custom logfile is given in global action_processor section")
						try:
							commandParts = config.get('action_processor', 'command').split()
							if '/logfile' in commandParts:
								instlog = commandParts[commandParts.index('/logfile') + 1]
						except Exception as e:
							pass

						if os.path.isfile(instlog):
							logger.info(u"Syncing instlog %s" % instlog)
							f = codecs.open(instlog, 'r', 'utf-8', 'replace')
							data = f.read()
							f.close()
							self._configService.log_write(
								u'instlog',
								data=data,
								objectId=config.get('global', 'host_id'),
								append=False
							)
					except Exception as e:
						logger.error(u"Failed to sync instlog: %s" % e)

					logger.notice(u"Config synced to server")
				except Exception as e:
					logger.logException(e)
					timeline.addEvent(
						title=u"Failed to sync config to server",
						description=u"Failed to sync config to server: %s" % e,
						category=u"config_sync",
						isError=True
					)
					raise
		except Exception as e:
			logger.error(u"Errors occurred while syncing config to server: %s" % e)
			# Do not sync from server in this case!
			self._syncConfigFromServerRequested = False
		if eventId:
			timeline.setEventEnd(eventId)
		self.disconnectConfigService()
		self._working = False

	def _syncConfigFromServer(self):
		self._working = True
		try:
			self.setObsolete()
			if not self._configService:
				self.connectConfigService()

			includeProductIds = []
			excludeProductIds = []
			excludeProductGroupIds = [x for x in forceList(config.get('cache_service', 'exclude_product_group_ids')) if x != ""]
			includeProductGroupIds = [x for x in forceList(config.get('cache_service', 'include_product_group_ids')) if x != ""]

			logger.debug("Given includeProductGroupIds: '%s'" % includeProductGroupIds)
			logger.debug("Given excludeProductGroupIds: '%s'" % excludeProductGroupIds)

			if includeProductGroupIds:
				includeProductIds = [obj.objectId for obj in self._configService.objectToGroup_getObjects(groupType="ProductGroup", groupId=includeProductGroupIds)]
				logger.debug("Only products with productIds: '%s' will be cached." % includeProductIds)

			if excludeProductGroupIds:
				excludeProductIds = [obj.objectId for obj in self._configService.objectToGroup_getObjects(groupType="ProductGroup", groupId=excludeProductGroupIds)]
				logger.debug("Products with productIds: '%s' will be excluded." % excludeProductIds)

			productOnClients = [poc for poc in self._configService.productOnClient_getObjects(
					productType='LocalbootProduct',
					clientId=config.get('global', 'host_id'),
					# Exclude 'always'!
					actionRequest=['setup', 'uninstall', 'update', 'once', 'custom'],
					attributes=['actionRequest'],
					productId=includeProductGroupIds)
				if poc.productId not in excludeProductIds
			]

			logger.info(u"Product on clients: %s" % productOnClients)
			if not productOnClients:
				self._state['config_cached'] = True
				state.set('config_cache_service', self._state)
				logger.notice(u"No product action requests set on config service, no sync from server required")
			else:
				try:
					localProductOnClientsByProductId = {}
					for productOnClient in self._cacheBackend.productOnClient_getObjects(
									productType='LocalbootProduct',
									clientId=config.get('global', 'host_id'),
									actionRequest=['setup', 'uninstall', 'update', 'always', 'once', 'custom'],
									attributes=['actionRequest']):
						localProductOnClientsByProductId[productOnClient.productId] = productOnClient

					needSync = False
					for productOnClient in productOnClients:
						if not localProductOnClientsByProductId.has_key(productOnClient.productId):
							needSync = True
							break
						if (localProductOnClientsByProductId[productOnClient.productId].actionRequest != productOnClient.actionRequest):
							needSync = True
							break
						del localProductOnClientsByProductId[productOnClient.productId]
					if not needSync and localProductOnClientsByProductId:
						needSync = True

					if not needSync:
						logger.notice(u"No sync from server required configuration is unchanged")
						self._state['config_cached'] = True
						state.set('config_cache_service', self._state)
					else:
						logger.notice(u"Product on client configuration changed on config service, sync from server required")
						eventId = timeline.addEvent(title = u"Config sync from server", description = u'Syncing config from server', category = u'config_sync', durationEvent = True)
						self._cacheBackend._setMasterBackend(self._configService)
						self._backendTracker.clearModifications()
						self._cacheBackend._replicateMasterToWorkBackend()
						logger.notice(u"Config synced from server")
						self._state['config_cached'] = True
						state.set('config_cache_service', self._state)
						timeline.setEventEnd(eventId)
						for eventGenerator in getEventGenerators(generatorClass = SyncCompletedEventGenerator):
							eventGenerator.createAndFireEvent()
				except Exception as e:
					logger.logException(e)
					timeline.addEvent(
					title       = u"Failed to sync config from server",
					description = u"Failed to sync config from server: %s" % e,
					category    = u"config_sync",
					isError     = True)
					raise
		except Exception as e:
			logger.error(u"Errors occurred while syncing config from server: %s" % e)
		self.disconnectConfigService()
		self._working = False


class ProductCacheService(ServiceConnection, RepositoryObserver, threading.Thread):
	def __init__(self):
		threading.Thread.__init__(self)
		ServiceConnection.__init__(self)
		moduleName = u' %-30s' % (u'product cache service')
		logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)

		self._storageDir = config.get('cache_service', 'storage_dir')
		self._tempDir = os.path.join(self._storageDir, 'tmp')
		self._productCacheDir = os.path.join(self._storageDir, 'depot')
		self._productCacheMaxSize = forceInt(config.get('cache_service', 'product_cache_max_size'))

		self._stopped = False
		self._running = False
		self._working = False
		self._state = {}

		self._impersonation = None
		self._cacheProductsRequested = False

		self._maxBandwidth = 0
		self._dynamicBandwidth = True

		self._productProgressObserver = None
		self._overallProgressObserver = None
		self._dynamicBandwidthLimitEvent = None

		if not os.path.exists(self._storageDir):
			logger.notice(u"Creating cache service storage dir '%s'" % self._storageDir)
			os.makedirs(self._storageDir)
		if not os.path.exists(self._tempDir):
			logger.notice(u"Creating cache service temp dir '%s'" % self._tempDir)
			os.makedirs(self._tempDir)
		if not os.path.exists(self._productCacheDir):
			logger.notice(u"Creating cache service product cache dir '%s'" % self._productCacheDir)
			os.makedirs(self._productCacheDir)

		pcss = state.get('product_cache_service')
		if pcss:
			self._state = pcss

	def getProductCacheDir(self):
		return self._productCacheDir

	def dynamicBandwidthLimitChanged(self, repository, bandwidth):
		if (bandwidth <= 0):
			if self._dynamicBandwidthLimitEvent:
				timeline.setEventEnd(self._dynamicBandwidthLimitEvent)
				self._dynamicBandwidthLimitEvent = None
		else:
			if not self._dynamicBandwidthLimitEvent:
				self._dynamicBandwidthLimitEvent = timeline.addEvent(
					title=u"Dynamic bandwidth limit",
					description=u"Other traffic detected, bandwidth dynamically limited to %0.2f kByte/s" % (bandwidth/1024),
					category=u'wait',
					durationEvent=True
				)

	def getState(self):
		state = self._state
		state['running'] = self.isRunning()
		state['working'] = self.isWorking()
		state['maxBandwidth'] = self._maxBandwidth
		state['dynamicBandwidth'] = self._dynamicBandwidth
		return state

	def isRunning(self):
		return self._running

	def isWorking(self):
		return self._working

	def stop(self):
		self._stopped = True

	def setMaxBandwidth(self, maxBandwidth):
		self._maxBandwidth = forceInt(maxBandwidth)

	def setDynamicBandwidth(self, dynamicBandwidth):
		self._dynamicBandwidth = forceBool(dynamicBandwidth)

	def run(self):
		self._running = True
		logger.notice(u"Product cache service started")
		try:
			while not self._stopped:
				if self._cacheProductsRequested and not self._working:
					self._cacheProductsRequested = False
					self._cacheProducts()
				time.sleep(1)
		except Exception as e:
			logger.logException(e)
		logger.notice(u"Product cache service ended")
		self._running = False

	def cacheProducts(self, productProgressObserver=None, overallProgressObserver=None):
		self._cacheProductsRequested = True
		self._productProgressObserver = productProgressObserver
		self._overallProgressObserver = overallProgressObserver

	def connectConfigService(self):
		ServiceConnection.connectConfigService(self, allowTemporaryConfigServiceUrls=False)
		try:
			backendinfo = self._configService.backend_info()
			modules = backendinfo['modules']
			helpermodules = backendinfo['realmodules']

			if not modules.get('vpn'):
				raise Exception(u"Cannot sync products: VPN module currently disabled")

			if not modules.get('customer'):
				raise Exception(u"Cannot sync products: No customer in modules file")

			if not modules.get('valid'):
				raise Exception(u"Cannot sync products: modules file invalid")

			if (modules.get('expires', '') != 'never') and (time.mktime(time.strptime(modules.get('expires', '2000-01-01'), "%Y-%m-%d")) - time.time() <= 0):
				raise Exception(u"Cannot sync products: modules file expired")

			logger.info(u"Verifying modules file signature")
			publicKey = keys.Key.fromString(data=base64.decodestring('AAAAB3NzaC1yc2EAAAADAQABAAABAQCAD/I79Jd0eKwwfuVwh5B2z+S8aV0C5suItJa18RrYip+d4P0ogzqoCfOoVWtDojY96FDYv+2d73LsoOckHCnuh55GA0mtuVMWdXNZIE8Avt/RzbEoYGo/H0weuga7I8PuQNC/nyS8w3W8TH4pt+ZCjZZoX8S+IizWCYwfqYoYTMLgB0i+6TCAfJj3mNgCrDZkQ24+rOFS4a8RrjamEz/b81noWl9IntllK1hySkR+LbulfTGALHgHkDUlk0OSu+zBPw/hcDSOMiDQvvHfmR4quGyLPbQ2FOVm1TzE0bQPR+Bhx4V8Eo2kNYstG2eJELrz7J1TJI0rCjpB+FQjYPsP')).keyObject
			data = u''
			mks = modules.keys()
			mks.sort()
			for module in mks:
				if module in ('valid', 'signature'):
					continue
				if module in helpermodules:
					val = helpermodules[module]
					if int(val) > 0:
						modules[module] = True
				else:
					val = modules[module]
					if val == False:
						val = 'no'
					if val == True:
						val = 'yes'

				data += u'%s = %s\r\n' % (module.lower().strip(), val)
			if not bool(publicKey.verify(md5(data).digest(), [long(modules['signature'])])):
				raise Exception(u"Cannot sync products: modules file invalid")
			logger.notice(u"Modules file signature verified (customer: %s)" % modules.get('customer'))
		except Exception:
			self.disconnectConfigService()
			raise

	def _freeProductCacheSpace(self, neededSpace = 0, neededProducts=[]):
		try:
			# neededSpace in byte
			neededSpace = forceInt(neededSpace)
			neededProducts = forceProductIdList(neededProducts)

			maxFreeableSize = 0
			productDirSizes = {}
			for product in os.listdir(self._productCacheDir):
				if product not in neededProducts:
					productDirSizes[product] = System.getDirectorySize(os.path.join(self._productCacheDir, product))
					maxFreeableSize += productDirSizes[product]
			if (maxFreeableSize < neededSpace):
				raise Exception(u"Needed space: %0.3f MB, maximum freeable space: %0.3f MB" \
							% ( (float(neededSpace)/(1024*1024)), (float(maxFreeableSize)/(1024*1024)) ) )
			freedSpace = 0
			while (freedSpace < neededSpace):
				deleteProduct = None
				eldestTime = None
				for (product, size) in productDirSizes.items():
					packageContentFile = os.path.join(self._productCacheDir, product, u'%s.files' % product)
					if not os.path.exists(packageContentFile):
						logger.info(u"Package content file '%s' not found, deleting product cache to free disk space" % packageContentFile)
						deleteProduct = product
						break
					mtime = os.path.getmtime(packageContentFile)
					if not eldestTime:
						eldestTime = mtime
						deleteProduct = product
						continue
					if (mtime < eldestTime):
						eldestTime = mtime
						deleteProduct = product
				if not deleteProduct:
					raise Exception(u"Internal error")
				deleteDir = os.path.join(self._productCacheDir, deleteProduct)
				logger.notice(u"Deleting product cache directory '%s'" % deleteDir)
				if not os.path.exists(deleteDir):
					raise Exception(u"Directory '%s' not found" % deleteDir)
				shutil.rmtree(deleteDir)
				freedSpace += productDirSizes[deleteProduct]
				if self._state.get('products', {}).get(deleteProduct):
					del self._state['products'][deleteProduct]
					state.set('product_cache_service', self._state)
				del productDirSizes[deleteProduct]
			logger.notice(u"%0.3f MB of product cache freed" % (float(freedSpace)/(1024*1024)))
		except Exception as e:
			raise Exception(u"Failed to free enough disk space for product cache: %s" % forceUnicode(e))

	def _cacheProducts(self):
		self._working = True
		self._state['products_cached'] = False
		self._state['products'] = {}
		state.set('product_cache_service', self._state)
		eventId = None

		try:
			if not self._configService:
				self.connectConfigService()

			includeProductIds = []
			excludeProductIds = []
			excludeProductGroupIds = [x for x in forceList(config.get('cache_service', 'exclude_product_group_ids')) if x != ""]
			includeProductGroupIds = [x for x in forceList(config.get('cache_service', 'include_product_group_ids')) if x != ""]

			logger.debug("Given includeProductGroupIds: '%s'" % includeProductGroupIds)
			logger.debug("Given excludeProductGroupIds: '%s'" % excludeProductGroupIds)

			if includeProductGroupIds:
				includeProductIds = [obj.objectId for obj in self._configService.objectToGroup_getObjects(
					groupType="ProductGroup",
					groupId=includeProductGroupIds)]
				logger.debug("Only products with productIds: '%s' will be cached." % includeProductIds)

			if excludeProductGroupIds:
				excludeProductIds = [obj.objectId for obj in self._configService.objectToGroup_getObjects(
					groupType="ProductGroup",
					groupId=excludeProductGroupIds)]
				logger.debug("Products with productIds: '%s' will be excluded." % excludeProductIds)

			productIds = []
			productOnClients = [poc for poc in self._configService.productOnClient_getObjects(
					productType='LocalbootProduct',
					clientId=config.get('global', 'host_id'),
					actionRequest=['setup', 'uninstall', 'update', 'always', 'once', 'custom'],
					attributes=['actionRequest'],
					productId=includeProductGroupIds)
				if poc.productId not in excludeProductIds]

			for productOnClient in productOnClients:
				if productOnClient.productId not in productIds:
					productIds.append(productOnClient.productId)
			if not productIds:
				logger.notice(u"No product action request set => no products to cache")
			else:

				productOnDepots = self._configService.productOnDepot_getObjects(
					depotId=config.get('depot_server', 'depot_id'),
					productId=productIds)

				errorProductIds = []
				for productOnClient in productOnClients:
					found = False
					for productOnDepot in productOnDepots:
						if productOnDepot.productId == productOnClient.productId:
							found = True
							break
					if not found:
						logger.error(u"Requested product: '%s' not found on configured depot: '%s', please check your configuration, setting product to failed." % (productOnClient.productId, config.get('depot_server', 'depot_id')))
						self._setProductCacheState(productOnClient.productId, u"failure", u"Product not found on configured depot.")
						errorProductIds.append(productOnClient.productId)

				productIds.append('opsi-winst')
				if 'mshotfix' in productIds:
					# Windows 8.1 Bugfix, with a helper exe.
					helper = os.path.join(config.get('global', 'base_dir'), 'utilities', 'getmsversioninfo.exe')
					additionalProductId = System.getOpsiHotfixName(helper)
					logger.info(u"Requested to cache product mshotfix => additionaly caching system specific mshotfix product: %s" % additionalProductId)
					if additionalProductId not in productIds:
						productIds.append(additionalProductId)

				if errorProductIds:
					for index in range(len(productIds) -1):
						if productIds[index] in errorProductIds:
							logger.error(u"ProductId: '%s' will not be cached." % productIds[index])
							del productIds[index]

				if len(productIds) == 1 and productIds[0] == 'opsi-winst':
					logger.notice(u"Only opsi-winst is set to install, doing nothin, because a up- or downgrade from opsi-winst is only need if a other product is set to setup.")
				else:
					logger.notice(u"Caching products: %s" % ', '.join(productIds))
					eventId = timeline.addEvent(
						title=u"Cache products",
						description=u"Caching products: %s" % ', '.join(productIds),
						category=u'product_caching',
						durationEvent=True
					)

					try:
						errorsOccured = []
						for productId in productIds:
							try:
								self._cacheProduct(productId, productIds)
							except Exception as e:
								logger.logException(e, LOG_INFO)
								errorsOccured.append(forceUnicode(e))
								self._setProductCacheState(productId, 'failure', forceUnicode(e))
					except Exception as e:
						logger.logException(e)
						errorsOccured.append(forceUnicode(e))
					if errorsOccured:
						logger.error(u"Errors occurred while caching products %s: %s" % (', '.join(productIds), ', '.join(errorsOccured)))
						timeline.addEvent(
							title=u"Failed to cache products",
							description=u"Errors occurred while caching products %s: %s" % (', '.join(productIds), ', '.join(errorsOccured)),
							category=u"product_caching",
							isError=True
						)
					else:
						logger.notice(u"All products cached: %s" % ', '.join(productIds))
						self._state['products_cached'] = True
						state.set('product_cache_service', self._state)
						for eventGenerator in getEventGenerators(generatorClass=SyncCompletedEventGenerator):
							eventGenerator.createAndFireEvent()
		except Exception as e:
			logger.error(u"Failed to cache products: %s" % e)
			timeline.addEvent(
				title=u"Failed to cache products",
				description=u"Failed to cache products: %s" % e,
				category=u"product_caching",
				isError=True)
		if eventId:
			timeline.setEventEnd(eventId)
		self.disconnectConfigService()
		self._working = False

	def _setProductCacheState(self, productId, key, value, updateProductOnClient=True):
		if 'products' not in self._state:
			self._state['products'] = {}
		if productId not in self._state['products']:
			self._state['products'][productId] = {}

		self._state['products'][productId][key] = value
		state.set('product_cache_service', self._state)
		actionProgress = None
		installationStatus = None
		actionResult = None
		actionRequest = None

		if key == 'started':
			actionProgress = 'caching'
		elif (key == 'completed'):
			actionProgress = 'cached'
		elif (key == 'failure'):
			actionProgress = u"Cache failure: %s" % forceUnicode(value)
			installationStatus = u'unknown'
			actionResult = u'failed'
			if u"MD5sum mismatch" in forceUnicode(value):
				actionRequest = u'none'
		if actionProgress and updateProductOnClient:
			self._configService.productOnClient_updateObjects([
				ProductOnClient(
					productId=productId,
					productType=u'LocalbootProduct',
					clientId=config.get('global', 'host_id'),
					actionProgress=actionProgress,
					installationStatus=installationStatus,
					actionResult=actionResult,
					actionRequest=actionRequest
				)
			])

	def _getRepository(self, productId):
		config.selectDepotserver(configService=self._configService, event=None, productIds=[productId], cifsOnly=False)
		if not config.get('depot_server', 'url'):
			raise Exception(u"Cannot cache product files: depot_server.url undefined")
		(depotServerUsername, depotServerPassword) = (u'', u'')
		(scheme, host, port, baseurl, username, password) = urlsplit(config.get('depot_server', 'url'))
		if scheme.startswith('webdav'):
			(depotServerUsername, depotServerPassword) = (config.get('global', 'host_id'), config.get('global', 'opsi_host_key'))
			kwargs = {}
			if scheme.startswith('webdavs'):
				certDir = config.get('global', 'server_cert_dir')
				kwargs['caCertFile'] = os.path.join(certDir, 'cacert.pem')
				kwargs['verifyServerCert'] = config.get('global', 'verify_server_cert')
				kwargs['serverCertFile'] = os.path.join(certDir, host + '.pem')
				kwargs['verifyServerCertByCa'] = config.get('global', 'verify_server_cert_by_ca')
				kwargs['proxyURL'] = config.get('global', 'proxy_url')

			return getRepository(config.get('depot_server', 'url'), username=depotServerUsername, password=depotServerPassword, **kwargs)
		else:
			if self._impersonation:
				try:
					self._impersonation.end()
				except Exception as e:
					logger.warning(e)
			(depotServerUsername, depotServerPassword) = config.getDepotserverCredentials(configService=self._configService)
			self._impersonation = System.Impersonate(username=depotServerUsername, password=depotServerPassword)
			self._impersonation.start(logonType='NEW_CREDENTIALS')
			return getRepository(config.get('depot_server', 'url'), username=depotServerUsername, password=depotServerPassword, mount=False)

	def _cacheProduct(self, productId, neededProducts):
		logger.notice(u"Caching product '%s' (max bandwidth: %s, dynamic bandwidth: %s)" % (productId,  self._maxBandwidth, self._dynamicBandwidth))
		self._setProductCacheState(productId, 'started', time.time())
		self._setProductCacheState(productId, 'completed', None, updateProductOnClient=False)
		self._setProductCacheState(productId, 'failure', None, updateProductOnClient=False)

		eventId = None
		repository = None
		exception = None
		try:
			repository = self._getRepository(productId)
			if not config.get('depot_server', 'depot_id'):
				raise Exception(u"Cannot cache product files: depot_server.depot_id undefined")
			productOnDepots = self._configService.productOnDepot_getObjects(depotId=config.get('depot_server', 'depot_id'), productId=productId)
			if not productOnDepots:
				raise Exception(u"Product '%s' not found on depot '%s'" % (productId, config.get('depot_server', 'depot_id')))

			self._setProductCacheState(productId, 'productVersion', productOnDepots[0].productVersion, updateProductOnClient=False)
			self._setProductCacheState(productId, 'packageVersion', productOnDepots[0].packageVersion, updateProductOnClient=False)

			if not os.path.exists(os.path.join(self._productCacheDir, productId)):
				os.mkdir(os.path.join(self._productCacheDir, productId))
			packageContentFile = u'%s/%s.files' % (productId, productId)
			localPackageContentFile = os.path.join(self._productCacheDir, productId, u'%s.files' % productId)
			repository.download(source=packageContentFile, destination=localPackageContentFile)
			packageInfo = PackageContentFile(localPackageContentFile).parse()
			productSize = 0
			fileCount = 0
			for value in packageInfo.values():
				if 'size' in value:
					fileCount += 1
					productSize += int(value['size'])

			logger.info(u"Product '%s' contains %d files with a total size of %0.3f MB" \
				% (productId, fileCount, (float(productSize)/(1024*1024))))

			productCacheDirSize = 0
			if (self._productCacheMaxSize > 0):
				productCacheDirSize = System.getDirectorySize(self._productCacheDir)
				if (productCacheDirSize + productSize > self._productCacheMaxSize):
					logger.info(u"Product cache dir sizelimit of %0.3f MB exceeded. Current size: %0.3f MB, space needed for product '%s': %0.3f MB" \
							% ( (float(self._productCacheMaxSize)/(1024*1024)), (float(productCacheDirSize)/(1024*1024)), \
							    productId, (float(productSize)/(1024*1024)) ) )
					freeSpace = self._productCacheMaxSize - productCacheDirSize
					neededSpace = productSize - freeSpace + 1024
					self._freeProductCacheSpace(neededSpace=neededSpace, neededProducts=neededProducts)
					productCacheDirSize = System.getDirectorySize(self._productCacheDir)

			diskFreeSpace = System.getDiskSpaceUsage(self._productCacheDir)['available']
			if (diskFreeSpace < productSize + 500*1024*1024):
				raise Exception(u"Only %0.3f MB free space available on disk, refusing to cache product files" \
							% (float(diskFreeSpace)/(1024*1024)))

			eventId = timeline.addEvent(
				title=u"Cache product %s" % productId,
				description=u"Caching product '%s' of size %0.2f MB\nmax bandwidth: %s, dynamic bandwidth: %s" \
					% (productId,  (float(productSize)/(1024*1024)), self._maxBandwidth, self._dynamicBandwidth),
				category=u'product_caching',
				durationEvent=True
			)

			productSynchronizer = DepotToLocalDirectorySychronizer(
				sourceDepot=repository,
				destinationDirectory=self._productCacheDir,
				productIds=[productId],
				maxBandwidth=self._maxBandwidth,
				dynamicBandwidth=self._dynamicBandwidth
			)
			if self._dynamicBandwidth:
				repository.attachObserver(self)
			try:
				productSynchronizer.synchronize(productProgressObserver=self._productProgressObserver, overallProgressObserver=self._overallProgressObserver)
			finally:
				if self._dynamicBandwidth:
					repository.detachObserver(self)
				if self._dynamicBandwidthLimitEvent:
					timeline.setEventEnd(self._dynamicBandwidthLimitEvent)
					self._dynamicBandwidthLimitEvent = None
			logger.notice(u"Product '%s' cached" % productId)
			self._setProductCacheState(productId, 'completed', time.time())
		except Exception as e:
			exception = e
			timeline.addEvent(
				title=u"Failed to cache product %s" % productId,
				description=u"Failed to cache product '%s': %s" % (productId, e),
				category=u"product_caching",
				isError=True
			)
		if eventId:
			timeline.setEventEnd(eventId)
		if repository:
			try:
				repository.disconnect()
			except Exception as e:
				logger.warning(u"Failed to disconnect from repository: %s" % e)
		if self._impersonation:
			try:
				self._impersonation.end()
			except Exception as e:
				logger.warning(e)
		if exception:
			raise exception
