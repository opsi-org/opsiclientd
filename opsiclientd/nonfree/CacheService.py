# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org

# Copyright (C) 2014-2019 uib GmbH
# http://www.uib.de/
# All rights reserved.
"""
opsiclientd.nonfree.CacheService

@copyright:	uib GmbH <info@uib.de>
"""

# pylint: disable=too-many-lines

import codecs
import os
import shutil
import threading
import time

from OPSI.Object import ProductOnClient
from OPSI.Types import (
	forceBool, forceInt, forceList, forceProductIdList, forceUnicode
)
from OPSI.Util.File.Opsi import PackageContentFile
from OPSI.Util.Repository import getRepository
from OPSI.Util.Repository import (
	DepotToLocalDirectorySychronizer, RepositoryObserver
)
from OPSI import System
from OPSI.Util.HTTP import urlsplit
from OPSI.Backend.Backend import ExtendedConfigDataBackend
from OPSI.Backend.BackendManager import BackendExtender
from OPSI.Backend.SQLite import (
	SQLiteBackend, SQLiteObjectBackendModificationTracker
)

from opsicommon.logging import logger, log_context

from opsiclientd.Config import Config
from opsiclientd.State import State
from opsiclientd.Events.SyncCompleted import SyncCompletedEventGenerator
from opsiclientd.Events.Utilities.Generators import getEventGenerators
from opsiclientd.OpsiService import ServiceConnection
from opsiclientd.Timeline import Timeline

from opsiclientd.nonfree import verify_modules
from opsiclientd.nonfree.CacheBackend import ClientCacheBackend

__all__ = [
	'CacheService', 'ConfigCacheService', 'ConfigCacheServiceBackendExtension',
	'ProductCacheService'
]

config = Config()
state = State()
timeline = Timeline()


class CacheService(threading.Thread):
	def __init__(self, opsiclientd):
		threading.Thread.__init__(self)
		self._opsiclientd = opsiclientd
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

	def setConfigCacheFaulty(self):
		self.initializeConfigCacheService()
		self._configCacheService.setFaulty()

	def syncConfig(self, waitForEnding=False, force=False):
		self.initializeConfigCacheService()
		if self._configCacheService.isWorking():
			logger.info("Already syncing config")
		else:
			logger.info("Trigger config sync")
			self._configCacheService.syncConfig(force)

		if waitForEnding:
			time.sleep(3)
			while self._configCacheService.isRunning() and self._configCacheService.isWorking():
				time.sleep(1)

	def syncConfigToServer(self, waitForEnding=False):
		self.initializeConfigCacheService()
		if self._configCacheService.isWorking():
			logger.info("Already syncing config")
			return
		logger.info("Trigger config sync to server")
		self._configCacheService.syncConfigToServer()

		if waitForEnding:
			time.sleep(3)
			while self._configCacheService.isRunning() and self._configCacheService.isWorking():
				time.sleep(1)

	def isConfigCacheServiceWorking(self):
		self.initializeConfigCacheService()
		return self._configCacheService.isWorking()

	def syncConfigFromServer(self, waitForEnding=False):
		self.initializeConfigCacheService()
		if self._configCacheService.isWorking():
			logger.info("Already syncing config")
			return

		logger.info("Trigger config sync from server")
		self._configCacheService.syncConfigFromServer()

		if waitForEnding:
			time.sleep(3)
			while self._configCacheService.isRunning() and self._configCacheService.isWorking():
				time.sleep(1)

	def configCacheCompleted(self):
		try:
			self.initializeConfigCacheService()
		except Exception as cacheInitError: # pylint: disable=broad-except
			logger.info(cacheInitError, exc_info=True)
			logger.error(cacheInitError)
			return False

		if not self._configCacheService.isWorking() and self._configCacheService.getState().get('config_cached', False):
			return True

		return False

	def getConfigBackend(self):
		self.initializeConfigCacheService()
		return self._configCacheService.getConfigBackend()

	def getConfigModifications(self):
		self.initializeConfigCacheService()
		return self._configCacheService._backendTracker.getModifications() # pylint: disable=protected-access

	def isProductCacheServiceWorking(self):
		self.initializeProductCacheService()
		return self._productCacheService.isWorking()

	def cacheProducts( # pylint: disable=too-many-arguments
		self, waitForEnding=False, productProgressObserver=None, overallProgressObserver=None,
		dynamicBandwidth=True, maxBandwidth=0
	):
		self.initializeProductCacheService()
		if self._productCacheService.isWorking():
			logger.info("Already caching products")
			return

		logger.info("Trigger product caching")
		self._productCacheService.setDynamicBandwidth(dynamicBandwidth)
		self._productCacheService.setMaxBandwidth(maxBandwidth)
		self._productCacheService.cacheProducts(productProgressObserver=productProgressObserver, overallProgressObserver=overallProgressObserver)

		if waitForEnding:
			time.sleep(3)
			while self._productCacheService.isRunning() and self._productCacheService.isWorking():
				time.sleep(1)

	def productCacheCompleted(self, configService, productIds, checkCachedProductVersion=False):
		logger.debug("productCacheCompleted: configService=%s productIds=%s", configService, productIds)
		if not productIds:
			return True

		workingWithCachedConfig = bool(configService._host in ("localhost", "127.0.0.1")) # pylint: disable=protected-access

		self.initializeProductCacheService()

		masterDepotId = config.get('depot_server', 'master_depot_id')
		if workingWithCachedConfig:
			depotIds = []
			for depot in configService.host_getObjects(type="OpsiDepotserver"):
				depotIds.append(depot.id)
			if not masterDepotId in depotIds:
				self.setConfigCacheFaulty()
				raise Exception(
					f"Config cache problem: depot '{masterDepotId}' not available in cached depots: {depotIds}."
					" Probably the depot was switched after the last config sync from server."
				)

		productOnDepots = {
			productOnDepot.productId: productOnDepot
			for productOnDepot
			in configService.productOnDepot_getObjects(depotId=masterDepotId, productId=productIds)
		}
		logger.trace("productCacheCompleted: productOnDepots=%s", productOnDepots)

		pcsState = self._productCacheService.getState()
		logger.debug("productCacheCompleted: productCacheService state=%s", pcsState)
		productCacheState = pcsState.get('products', {})

		for productId in productIds:
			try:
				productOnDepot = productOnDepots[productId]
			except KeyError as err:
				# Problem with cached config
				if workingWithCachedConfig:
					self.setConfigCacheFaulty()
					raise Exception(f"Config cache problem: product '{productId}' not available on depot '{masterDepotId}'") from err
				raise Exception(f"Product '{productId}' not available on depot '{masterDepotId}'") from err

			productState = productCacheState.get(productId)
			if not productState:
				logger.info(
					"Caching of product '%s_%s-%s' not yet started",
					productId, productOnDepot.productVersion, productOnDepot.packageVersion
				)
				return False

			if not productState.get('completed'):
				logger.info(
					"Caching of product '%s_%s-%s' not yet completed (got state: %s)",
					productId, productOnDepot.productVersion, productOnDepot.packageVersion, productState
				)
				return False

			if (
				(productState.get('productVersion') != productOnDepot.productVersion) or
				(productState.get('packageVersion') != productOnDepot.packageVersion)
			):
				logger.warning(
					"Product '%s_%s-%s' on depot but different version cached (got state: %s)",
					productId, productOnDepot.productVersion, productOnDepot.packageVersion, productState
				)
				if checkCachedProductVersion:
					return False
				logger.warning("Ignoring version difference")

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


class ConfigCacheServiceBackendExtension: # pylint: disable=too-few-public-methods
	def accessControl_authenticated(self): # pylint: disable=no-self-use
		return True


class ConfigCacheService(ServiceConnection, threading.Thread): # pylint: disable=too-many-instance-attributes
	def __init__(self):
		try:
			threading.Thread.__init__(self)
			ServiceConnection.__init__(self)

			self._configCacheDir = os.path.join(config.get('cache_service', 'storage_dir'), 'config')
			self._opsiModulesFile = os.path.join(self._configCacheDir, 'cached_modules')
			self._opsiPasswdFile = os.path.join(self._configCacheDir, 'cached_passwd')
			self._auditHardwareConfigFile = os.path.join(self._configCacheDir, 'cached_opsihwaudit.json')

			self._stopped = False
			self._running = False
			self._working = False
			self._state = {}

			self._syncConfigFromServerRequested = False
			self._syncConfigToServerRequested = False
			self._forceSync = False

			if not os.path.exists(self._configCacheDir):
				logger.notice("Creating config cache dir '%s'", self._configCacheDir)
				os.makedirs(self._configCacheDir)

			self.initBackends()

			ccss = state.get('config_cache_service')
			if ccss:
				self._state = ccss
		except Exception as err: # pylint: disable=broad-except
			logger.error(err, exc_info=True)
			try:
				self.setObsolete()
			except Exception: # pylint: disable=broad-except
				pass
			raise err

	def initBackends(self):
		clientId = config.get('global', 'host_id')
		masterDepotId = config.get('depot_server', 'master_depot_id')

		backendArgs = {
			'opsiModulesFile': self._opsiModulesFile,
			'opsiPasswdFile': self._opsiPasswdFile,
			'auditHardwareConfigFile': self._auditHardwareConfigFile,
			'depotId': masterDepotId,
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
			clientId=clientId,
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

	def connectConfigService(self, allowTemporaryConfigServiceUrls=True): # pylint: disable=too-many-branches,too-many-statements
		ServiceConnection.connectConfigService(self, allowTemporaryConfigServiceUrls=False)

		try:
			backend_info = self._configService.backend_info()
			try:
				verify_modules(backend_info, ['vpn'])
			except RuntimeError as err:
				raise RuntimeError("Cannot sync products: {err}") from err

			try:
				if self._configService._host not in ("localhost", "127.0.0.1"): # pylint: disable=protected-access
					config.set(
						'depot_server', 'master_depot_id',
						self._configService.getDepotId(config.get('global', 'host_id')) # pylint: disable=no-member
					)
					config.updateConfigFile()
			except Exception as err: # pylint: disable=broad-except
				logger.warning(err)
		except Exception:
			self.disconnectConfigService()
			raise

	def getConfigBackend(self):
		return self._configBackend

	def getState(self):
		_state = self._state
		_state['running'] = self.isRunning()
		_state['working'] = self.isWorking()
		return _state

	def setObsolete(self):
		self._state['config_cached'] = False
		state.set('config_cache_service', self._state)

	def setFaulty(self):
		self._forceSync = True
		self.setObsolete()

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
		with log_context({'instance' : 'config cache service'}):
			self._running = True
			logger.notice("Config cache service started")
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
			except Exception as error: # pylint: disable=broad-except
				logger.error(error, exc_info=True)
			logger.notice("Config cache service ended")
			self._running = False

	def syncConfig(self, force=False):
		self._forceSync = bool(force)
		self._syncConfigToServerRequested = True
		self._syncConfigFromServerRequested = True

	def syncConfigToServer(self):
		self._syncConfigToServerRequested = True

	def syncConfigFromServer(self):
		self._syncConfigFromServerRequested = True

	def _syncConfigToServer(self):
		self._working = True
		eventId = None
		try: # pylint: disable=too-many-nested-blocks
			modifications = self._backendTracker.getModifications()
			if not modifications:
				logger.notice("Cache backend was not modified, no sync to server required")
			else:
				try:
					logger.debug("Tracked modifications: %s", modifications)
					logger.notice("Cache backend was modified, starting sync to server")
					eventId = timeline.addEvent(
						title="Config sync to server",
						description='Syncing config to server',
						category='config_sync',
						durationEvent=True
					)
					if not self._configService:
						self.connectConfigService()
					self._cacheBackend._setMasterBackend(self._configService) # pylint: disable=protected-access
					self._cacheBackend._updateMasterFromWorkBackend(modifications) # pylint: disable=protected-access
					logger.info("Clearing modifications in tracker")
					self._backendTracker.clearModifications()
					try:
						instlog = os.path.join(config.get('global', 'log_dir'), 'opsi-script.log')
						logger.debug("Checking if a custom logfile is given in global action_processor section")
						try:
							commandParts = config.get('action_processor', 'command').split()
							if '/logfile' in commandParts:
								instlog = commandParts[commandParts.index('/logfile') + 1]
						except Exception: # pylint: disable=broad-except
							pass

						if os.path.isfile(instlog):
							logger.info("Syncing instlog %s", instlog)
							with codecs.open(instlog, 'r', 'utf-8', 'replace') as file:
								data = file.read()

							self._configService.log_write( # pylint: disable=no-member
								'instlog',
								data=data,
								objectId=config.get('global', 'host_id'),
								append=False
							)
					except Exception as err: # pylint: disable=broad-except
						logger.error("Failed to sync instlog: %s", err)

					logger.notice("Config synced to server")
				except Exception as err: # pylint: disable=broad-except
					logger.error(err, exc_info=True)
					timeline.addEvent(
						title="Failed to sync config to server",
						description=f"Failed to sync config to server: {err}",
						category="config_sync",
						isError=True
					)
					raise
		except Exception as err: # pylint: disable=broad-except
			logger.error("Errors occurred while syncing config to server: %s", err)
			# Do not sync from server in this case!
			self._syncConfigFromServerRequested = False
		if eventId:
			timeline.setEventEnd(eventId)
		self.disconnectConfigService()
		self._working = False

	def _syncConfigFromServer(self): # pylint: disable=too-many-locals,too-many-branches,too-many-statements
		self._working = True
		try:
			self.setObsolete()
			if not self._configService:
				self.connectConfigService()

			masterDepotId = config.get('depot_server', 'master_depot_id')

			needSync = False
			if self._forceSync:
				logger.notice("Forced sync from server")
				needSync = True

			if not needSync:
				cachedDepotIds = []
				try:
					for depot in self._cacheBackend.host_getObjects(type="OpsiDepotserver"):
						cachedDepotIds.append(depot.id)
				except Exception as depError: # pylint: disable=broad-except
					logger.warning(depError)
				if cachedDepotIds and masterDepotId not in cachedDepotIds:
					logger.notice(
						f"Depot '{masterDepotId}' not available in cached depots: {cachedDepotIds}."
						" Probably the depot was switched after the last config sync from server. New sync required."
					)
					needSync = True

			self._cacheBackend.depotId = masterDepotId

			if not needSync:
				includeProductIds = []
				excludeProductIds = []
				excludeProductGroupIds = [x for x in forceList(config.get('cache_service', 'exclude_product_group_ids')) if x != ""]
				includeProductGroupIds = [x for x in forceList(config.get('cache_service', 'include_product_group_ids')) if x != ""]

				logger.debug("Given includeProductGroupIds: '%s'", includeProductGroupIds)
				logger.debug("Given excludeProductGroupIds: '%s'", excludeProductGroupIds)

				if includeProductGroupIds:
					includeProductIds = [
						obj.objectId for obj in
						self._configService.objectToGroup_getObjects(groupType="ProductGroup", groupId=includeProductGroupIds) # pylint: disable=no-member
					]
					logger.debug("Only products with productIds: '%s' will be cached.", includeProductIds)

				if excludeProductGroupIds:
					excludeProductIds = [
						obj.objectId for obj in
						self._configService.objectToGroup_getObjects(groupType="ProductGroup", groupId=excludeProductGroupIds) # pylint: disable=no-member
					]
					logger.debug("Products with productIds: '%s' will be excluded.", excludeProductIds)

				productOnClients = [
					poc for poc in self._configService.productOnClient_getObjects( # pylint: disable=no-member
						productType='LocalbootProduct',
						clientId=config.get('global', 'host_id'),
						# Exclude 'always'!
						actionRequest=['setup', 'uninstall', 'update', 'once', 'custom'],
						attributes=['actionRequest'],
						productId=includeProductGroupIds
					)
					if poc.productId not in excludeProductIds
				]

				logger.info("Product on clients: %s", productOnClients)
				if not productOnClients:
					logger.notice("No product action requests set on config service, no sync from server required")
				else:
					localProductOnClientsByProductId = {} # pylint: disable=invalid-name
					for productOnClient in self._cacheBackend.productOnClient_getObjects(
									productType='LocalbootProduct',
									clientId=config.get('global', 'host_id'),
									actionRequest=['setup', 'uninstall', 'update', 'always', 'once', 'custom'],
									attributes=['actionRequest']):
						localProductOnClientsByProductId[productOnClient.productId] = productOnClient

					for productOnClient in list(productOnClients):
						if productOnClient.productId not in localProductOnClientsByProductId:
							# ProductOnClient not cached
							needSync = True
							break

						if localProductOnClientsByProductId[productOnClient.productId].actionRequest != productOnClient.actionRequest:
							# ProductOnClient actionRequest changed
							needSync = True
							break

						del localProductOnClientsByProductId[productOnClient.productId]

					if not needSync and localProductOnClientsByProductId:
						# Obsolete ProductOnClients found
						needSync = True

					if needSync:
						logger.notice("Product on client configuration changed on config service, sync from server required")
					else:
						logger.notice("Product on client configuration not changed on config service, sync from server not required")

			if needSync:
				eventId = None
				try:
					self._forceSync = False
					eventId = timeline.addEvent(
						title="Config sync from server",
						description='Syncing config from server',
						category='config_sync',
						durationEvent=True
					)
					self._cacheBackend._setMasterBackend(self._configService) # pylint: disable=protected-access
					logger.info("Clearing modifications in tracker")
					self._backendTracker.clearModifications()
					self._cacheBackend._replicateMasterToWorkBackend() # pylint: disable=protected-access
					logger.notice("Config synced from server")
					self._state['config_cached'] = True
					state.set('config_cache_service', self._state)
					timeline.setEventEnd(eventId)

					for eventGenerator in getEventGenerators(generatorClass=SyncCompletedEventGenerator):
						eventGenerator.createAndFireEvent()
				except Exception as err:
					logger.error(err, exc_info=True)
					timeline.addEvent(
						title="Failed to sync config from server",
						description=f"Failed to sync config from server: {err}",
						category="config_sync",
						isError=True
					)
					if eventId:
						timeline.setEventEnd(eventId)
					self.setFaulty()
					raise
			else:
				self._state['config_cached'] = True
				state.set('config_cache_service', self._state)

		except Exception as err: # pylint: disable=broad-except
			logger.error("Errors occurred while syncing config from server: %s", err, exc_info=True)

		self.disconnectConfigService()
		self._working = False


class ProductCacheService(ServiceConnection, RepositoryObserver, threading.Thread): # pylint: disable=too-many-instance-attributes
	def __init__(self):
		threading.Thread.__init__(self)
		ServiceConnection.__init__(self)

		self._updateConfig()

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
			logger.notice("Creating cache service storage dir '%s'", self._storageDir)
			os.makedirs(self._storageDir)
		if not os.path.exists(self._tempDir):
			logger.notice("Creating cache service temp dir '%s'", self._tempDir)
			os.makedirs(self._tempDir)
		if not os.path.exists(self._productCacheDir):
			logger.notice("Creating cache service product cache dir '%s'", self._productCacheDir)
			os.makedirs(self._productCacheDir)

		pcss = state.get('product_cache_service')
		if pcss:
			self._state = pcss

	def _updateConfig(self):
		self._storageDir = config.get('cache_service', 'storage_dir')
		self._tempDir = os.path.join(self._storageDir, 'tmp')
		self._productCacheDir = os.path.join(self._storageDir, 'depot')
		self._productCacheMaxSize = forceInt(config.get('cache_service', 'product_cache_max_size'))

	def getProductCacheDir(self):
		return self._productCacheDir

	def dynamicBandwidthLimitChanged(self, repository, bandwidth):
		if bandwidth <= 0:
			if self._dynamicBandwidthLimitEvent:
				timeline.setEventEnd(self._dynamicBandwidthLimitEvent)
				self._dynamicBandwidthLimitEvent = None
		else:
			if not self._dynamicBandwidthLimitEvent:
				self._dynamicBandwidthLimitEvent = timeline.addEvent(
					title="Dynamic bandwidth limit",
					description="Other traffic detected, bandwidth dynamically limited to %0.2f kByte/s" % (bandwidth/1024),
					category='wait',
					durationEvent=True
				)

	def getState(self):
		_state = self._state
		_state['running'] = self.isRunning()
		_state['working'] = self.isWorking()
		_state['maxBandwidth'] = self._maxBandwidth
		_state['dynamicBandwidth'] = self._dynamicBandwidth
		return _state

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
		with log_context({'instance' : 'product cache service'}):
			self._running = True
			logger.notice("Product cache service started")
			try:
				while not self._stopped:
					if self._cacheProductsRequested and not self._working:
						self._cacheProductsRequested = False
						self._cacheProducts()
					time.sleep(1)
			except Exception as err: # pylint: disable=broad-except
				logger.error(err, exc_info=True)
			logger.notice("Product cache service ended")
			self._running = False

	def cacheProducts(self, productProgressObserver=None, overallProgressObserver=None):
		self._cacheProductsRequested = True
		self._productProgressObserver = productProgressObserver
		self._overallProgressObserver = overallProgressObserver

	def connectConfigService(self, allowTemporaryConfigServiceUrls=True): # pylint: disable=too-many-branches,too-many-statements
		ServiceConnection.connectConfigService(self, allowTemporaryConfigServiceUrls=False)
		try:
			backend_info = self._configService.backend_info()
			try:
				verify_modules(backend_info, ['vpn'])
			except RuntimeError as err:
				raise RuntimeError("Cannot cache config: {err}") from err

			try:
				if self._configService._host not in ("localhost", "127.0.0.1"):# pylint: disable=protected-access
					config.set(
						'depot_server', 'master_depot_id',
						self._configService.getDepotId(config.get('global', 'host_id')) # pylint: disable=no-member
					)
					config.updateConfigFile()
			except Exception as err:# pylint: disable=broad-except
				logger.warning(err)
		except Exception:
			self.disconnectConfigService()
			raise

	def _freeProductCacheSpace(self, neededSpace=0, neededProducts=[]): # pylint: disable=dangerous-default-value
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

			if maxFreeableSize < neededSpace:
				raise Exception(
					"Needed space: %0.3f MB, maximum freeable space: %0.3f MB (max product cache size: %0.0f MB)" % (
						float(neededSpace) / (1000 * 1000),
						float(maxFreeableSize) / (1000 * 1000),
						float(self._productCacheMaxSize) / (1000 * 1000)
					)
				)

			freedSpace = 0
			while freedSpace < neededSpace:
				deleteProduct = None
				eldestTime = None
				for product, _size in productDirSizes.items():
					packageContentFile = os.path.join(self._productCacheDir, product, f'{product}.files')
					if not os.path.exists(packageContentFile):
						logger.info("Package content file '%s' not found, deleting product cache to free disk space", packageContentFile)
						deleteProduct = product
						break

					mtime = os.path.getmtime(packageContentFile)
					if not eldestTime:
						eldestTime = mtime
						deleteProduct = product
						continue

					if mtime < eldestTime:
						eldestTime = mtime
						deleteProduct = product

				if not deleteProduct:
					raise Exception("Internal error")

				deleteDir = os.path.join(self._productCacheDir, deleteProduct)
				logger.notice("Deleting product cache directory '%s'", deleteDir)
				if not os.path.exists(deleteDir):
					raise Exception(f"Directory '{deleteDir}' not found")

				shutil.rmtree(deleteDir)
				freedSpace += productDirSizes[deleteProduct]
				if self._state.get('products', {}).get(deleteProduct):
					del self._state['products'][deleteProduct]
					state.set('product_cache_service', self._state)

				del productDirSizes[deleteProduct]

			logger.notice("%0.3f MB of product cache freed", float(freedSpace)/(1000*1000))
		except Exception as err:
			raise Exception(f"Failed to free enough disk space for product cache: {err}") from err

	def _cacheProducts(self): # pylint: disable=too-many-locals,too-many-branches,too-many-statements
		self._updateConfig()
		self._working = True
		self._state['products_cached'] = False
		self._state['products'] = {}
		state.set('product_cache_service', self._state)
		eventId = None

		try: # pylint: disable=too-many-nested-blocks
			if not self._configService:
				self.connectConfigService()

			includeProductIds = []
			excludeProductIds = []
			excludeProductGroupIds = [x for x in forceList(config.get('cache_service', 'exclude_product_group_ids')) if x != ""]
			includeProductGroupIds = [x for x in forceList(config.get('cache_service', 'include_product_group_ids')) if x != ""]

			logger.debug("Given includeProductGroupIds: '%s'", includeProductGroupIds)
			logger.debug("Given excludeProductGroupIds: '%s'", excludeProductGroupIds)

			if includeProductGroupIds:
				includeProductIds = [obj.objectId for obj in self._configService.objectToGroup_getObjects( # pylint: disable=no-member
					groupType="ProductGroup",
					groupId=includeProductGroupIds)]
				logger.debug("Only products with productIds: '%s' will be cached.", includeProductIds)

			if excludeProductGroupIds:
				excludeProductIds = [obj.objectId for obj in self._configService.objectToGroup_getObjects( # pylint: disable=no-member
					groupType="ProductGroup",
					groupId=excludeProductGroupIds)]
				logger.debug("Products with productIds: '%s' will be excluded.", excludeProductIds)

			productIds = []
			productOnClients = [poc for poc in self._configService.productOnClient_getObjects( # pylint: disable=no-member
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
				logger.notice("No product action request set => no products to cache")
			else:
				masterDepotId = config.get('depot_server', 'master_depot_id')
				# Get all productOnDepots!
				productOnDepots = self._configService.productOnDepot_getObjects(depotId=masterDepotId) # pylint: disable=no-member
				productOnDepotIds = [productOnDepot.productId for productOnDepot in productOnDepots]
				logger.debug("Product ids on depot %s: %s", masterDepotId, productOnDepotIds)
				errorProductIds = []
				for productOnClient in productOnClients:
					if not productOnClient.productId in productOnDepotIds:
						logger.error(
							"Requested product: '%s' not found on configured depot: '%s', please check your configuration, setting product to failed.",
							productOnClient.productId, masterDepotId
						)
						self._setProductCacheState(productOnClient.productId, "failure", "Product not found on configured depot.")
						errorProductIds.append(productOnClient.productId)

				productIds.append('opsi-winst')
				if 'mshotfix' in productIds:
					# Windows 8.1 Bugfix, with a helper exe.
					# Helper seems not to be needed with Python 3
					helper = None #os.path.join(config.get('global', 'base_dir'), 'utilities', 'getmsversioninfo.exe')
					additionalProductId = System.getOpsiHotfixName(helper)
					if "win10" in additionalProductId:
						releaseId = None
						subKey = None
						valueName = None
						try:
							subKey = "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion"
							valueName = "ReleaseID"
							releaseId = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, subKey, valueName)
						except Exception as reg_err: # pylint: disable=broad-except
							logger.error("Failed to read registry value %s %s: %s", subKey, valueName, reg_err)
						#Setting default to 1507-Build
						if not releaseId:
							releaseId = "1507"
						#Splitting Name of original Packagename and reverse result to get arch
						parts = additionalProductId.split("-")[::-1]
						releasePackageName = "mshotfix-win10-%s-%s-glb" % (releaseId, parts[1])

						logger.info("Searching for release-packageid: '%s'", releasePackageName)
						if releasePackageName in productOnDepotIds:
							logger.info("Releasepackage '%s' found on depot '%s'", releasePackageName, masterDepotId)
							additionalProductId = releasePackageName
						else:
							logger.info("Releasepackage '%s' not found on depot '%s'", releasePackageName, masterDepotId)
					logger.info(
						"Requested to cache product mshotfix => additionaly caching system specific mshotfix product: %s",
						additionalProductId
					)
					if additionalProductId not in productIds:
						productIds.append(additionalProductId)

				if errorProductIds:
					for index in range(len(productIds) - 1):
						if productIds[index] in errorProductIds:
							logger.error("ProductId: '%s' will not be cached.", productIds[index])
							del productIds[index]

				if len(productIds) == 1 and productIds[0] == 'opsi-winst':
					logger.notice(
						"Only opsi-winst is set to install, doing nothing, "
						"because a up- or downgrade from opsi-winst is only need if a other product is set to setup."
					)
				else:
					p_list = ', '.join(productIds)
					logger.notice("Caching products: %s", p_list)
					eventId = timeline.addEvent(
						title="Cache products",
						description=f"Caching products: {p_list}",
						category='product_caching',
						durationEvent=True
					)

					errorsOccured = []
					try:
						for productId in productIds:
							try:
								self._cacheProduct(productId, productIds)
							except Exception as err: # pylint: disable=broad-except
								errorsOccured.append(str(err))
								self._setProductCacheState(productId, 'failure', forceUnicode(err))
					except Exception as err: # pylint: disable=broad-except
						logger.error("%s", err, exc_info=True)
						errorsOccured.append(forceUnicode(err))

					if errorsOccured:
						e_list = ', '.join(errorsOccured)
						logger.error("Errors occurred while caching products %s: %s", p_list, e_list)
						timeline.addEvent(
							title="Failed to cache products",
							description=f"Errors occurred while caching products {p_list}: {e_list}",
							category="product_caching",
							isError=True
						)
					else:
						logger.notice("All products cached: %s", p_list)
						self._state['products_cached'] = True
						state.set('product_cache_service', self._state)

						for eventGenerator in getEventGenerators(generatorClass=SyncCompletedEventGenerator):
							eventGenerator.createAndFireEvent()
		except Exception as err: # pylint: disable=broad-except
			logger.error("Failed to cache products: %s", err, exc_info=True)
			timeline.addEvent(
				title="Failed to cache products",
				description=f"Failed to cache products: {err}",
				category="product_caching",
				isError=True
			)

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
		elif key == 'completed':
			actionProgress = 'cached'
		elif key == 'failure':
			actionProgress = f"Cache failure: {value}"
			installationStatus = 'unknown'
			actionResult = 'failed'
			if "MD5sum mismatch" in forceUnicode(value):
				actionRequest = 'none'

		if actionProgress and updateProductOnClient:
			self._configService.productOnClient_updateObjects([ # pylint: disable=no-member
				ProductOnClient(
					productId=productId,
					productType='LocalbootProduct',
					clientId=config.get('global', 'host_id'),
					actionProgress=actionProgress,
					installationStatus=installationStatus,
					actionResult=actionResult,
					actionRequest=actionRequest
				)
			])

	def _getRepository(self, productId):
		config.selectDepotserver(
			configService=self._configService,
			mode="sync",
			event=None,
			productIds=[productId]
		)
		if not config.get('depot_server', 'url'):
			raise Exception("Cannot cache product files: depot_server.url undefined")

		depotServerUsername = ''
		depotServerPassword = ''

		(scheme, host) = urlsplit(config.get('depot_server', 'url'))[0:2]
		if scheme.startswith('webdav'):
			depotServerUsername = config.get('global', 'host_id')
			depotServerPassword = config.get('global', 'opsi_host_key')

			kwargs = {}
			if scheme.startswith('webdavs'):
				certDir = config.get('global', 'server_cert_dir')
				kwargs['caCertFile'] = os.path.join(certDir, 'opsi-ca-cert.pem')
				kwargs['verifyServerCert'] = config.get('global', 'verify_server_cert')
				kwargs['serverCertFile'] = os.path.join(certDir, host + '.pem')
				kwargs['verifyServerCertByCa'] = config.get('global', 'verify_server_cert_by_ca')
				kwargs['proxyURL'] = config.get('global', 'proxy_url')

			return getRepository(config.get('depot_server', 'url'), username=depotServerUsername, password=depotServerPassword, **kwargs)

		if self._impersonation:
			try:
				self._impersonation.end()
			except Exception as err: # pylint: disable=broad-except
				logger.warning(err)

		(depotServerUsername, depotServerPassword) = config.getDepotserverCredentials(configService=self._configService)
		self._impersonation = System.Impersonate(username=depotServerUsername, password=depotServerPassword)
		self._impersonation.start(logonType='NEW_CREDENTIALS')
		return getRepository(config.get('depot_server', 'url'), username=depotServerUsername, password=depotServerPassword, mount=False)

	def _cacheProduct(self, productId, neededProducts): # pylint: disable=too-many-locals,too-many-branches,too-many-statements
		logger.notice("Caching product '%s' (max bandwidth: %s, dynamic bandwidth: %s)", productId, self._maxBandwidth, self._dynamicBandwidth)
		self._setProductCacheState(productId, 'started', time.time())
		self._setProductCacheState(productId, 'completed', None, updateProductOnClient=False)
		self._setProductCacheState(productId, 'failure', None, updateProductOnClient=False)

		eventId = None
		repository = None
		exception = None
		try:
			repository = self._getRepository(productId)
			masterDepotId = config.get('depot_server', 'master_depot_id')
			if not masterDepotId:
				raise ValueError("Cannot cache product files: depot_server.master_depot_id undefined")

			productOnDepots = self._configService.productOnDepot_getObjects( # pylint: disable=no-member
				depotId=masterDepotId,
				productId=productId
			)
			if not productOnDepots:
				raise Exception("Product '%s' not found on depot '%s'" % (productId, masterDepotId))

			self._setProductCacheState(productId, 'productVersion', productOnDepots[0].productVersion, updateProductOnClient=False)
			self._setProductCacheState(productId, 'packageVersion', productOnDepots[0].packageVersion, updateProductOnClient=False)

			if not os.path.exists(os.path.join(self._productCacheDir, productId)):
				os.mkdir(os.path.join(self._productCacheDir, productId))

			packageContentFile = f'{productId}/{productId}.files'
			localPackageContentFile = os.path.join(self._productCacheDir, productId, f'{productId}.files')
			repository.download(source=packageContentFile, destination=localPackageContentFile)
			packageInfo = PackageContentFile(localPackageContentFile).parse()
			productSize = 0
			fileCount = 0
			for value in packageInfo.values():
				if 'size' in value:
					fileCount += 1
					productSize += int(value['size'])

			logger.info(
				"Product '%s' contains %d files with a total size of %0.3f MB",
				productId, fileCount, float(productSize) / (1000 * 1000)
			)

			productCacheDirSize = 0
			if self._productCacheMaxSize > 0:
				productCacheDirSize = System.getDirectorySize(self._productCacheDir)
				curProductSize = 0
				curProductCacheDir = os.path.join(self._productCacheDir, productId)
				if os.path.exists(curProductCacheDir):
					curProductSize = System.getDirectorySize(curProductCacheDir)
				if productCacheDirSize + productSize - curProductSize > self._productCacheMaxSize:
					logger.info(
						"Product cache dir sizelimit of %0.3f MB exceeded. Current size: %0.3f MB, space needed for product '%s': %0.3f MB",
						float(self._productCacheMaxSize) / (1000 * 1000),
						float(productCacheDirSize) / (1000 * 1000),
						productId,
						float(productSize) / (1000 * 1000)
					)
					freeSpace = self._productCacheMaxSize - productCacheDirSize
					neededSpace = productSize - freeSpace + 1000
					self._freeProductCacheSpace(neededSpace=neededSpace, neededProducts=neededProducts)
					productCacheDirSize = System.getDirectorySize(self._productCacheDir)

			diskFreeSpace = System.getDiskSpaceUsage(self._productCacheDir)['available']
			if diskFreeSpace < productSize + 500 * 1000 * 1000:
				raise Exception(
					"Only %0.3f MB free space available on disk, refusing to cache product files" % (
						float(diskFreeSpace) / (1000 * 1000)
					)
				)

			eventId = timeline.addEvent(
				title=f"Cache product {productId}",
				description="Caching product '%s' of size %0.2f MB\nmax bandwidth: %s, dynamic bandwidth: %s" % (
					productId,
					float(productSize) / (1000 * 1000),
					self._maxBandwidth,
					self._dynamicBandwidth
				),
				category='product_caching',
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
				productSynchronizer.synchronize(
					productProgressObserver=self._productProgressObserver, overallProgressObserver=self._overallProgressObserver
				)
			finally:
				if self._dynamicBandwidth:
					repository.detachObserver(self)
				if self._dynamicBandwidthLimitEvent:
					timeline.setEventEnd(self._dynamicBandwidthLimitEvent)
					self._dynamicBandwidthLimitEvent = None
			logger.notice("Product '%s' cached", productId)
			self._setProductCacheState(productId, 'completed', time.time())
		except Exception as err: # pylint: disable=broad-except
			logger.error("Failed to cache product %s: %s", productId, err, exc_info=True)
			exception = err
			timeline.addEvent(
				title=f"Failed to cache product {productId}",
				description=f"Failed to cache product '{productId}': {err}",
				category="product_caching",
				isError=True
			)

		if eventId:
			timeline.setEventEnd(eventId)

		if repository:
			try:
				repository.disconnect()
			except Exception as err: # pylint: disable=broad-except
				logger.warning("Failed to disconnect from repository: %s", err)

		if self._impersonation:
			try:
				self._impersonation.end()
			except Exception as err: # pylint: disable=broad-except
				logger.warning(err)

		if exception is not None:
			raise exception
