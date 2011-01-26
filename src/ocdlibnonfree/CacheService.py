# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = = = = = = = =
   =   ocdlibnonfree.CacheService                  =
   = = = = = = = = = = = = = = = = = = = = = = = = =
   
   opsiclientd is part of the desktop management solution opsi
   (open pc server integration) http://www.opsi.org
   
   Copyright (C) 2010 uib GmbH
   
   http://www.uib.de/
   
   All rights reserved.
   
   @copyright:	uib GmbH <info@uib.de>
   @author: Jan Schneider <j.schneider@uib.de>
"""

# Import
import threading, base64, time
from hashlib import md5
from twisted.conch.ssh import keys

# OPSI imports
from OPSI.Logger import *
from OPSI.Types import *
from OPSI.Object import *
from OPSI.Util.Repository import *
from OPSI.Util import md5sum
from OPSI import System
from OPSI.Util.HTTP import urlsplit
from OPSI.Backend.Backend import ExtendedConfigDataBackend, BackendModificationListener
from OPSI.Backend.BackendManager import BackendExtender
from OPSI.Backend.Cache import ClientCacheBackend
from OPSI.Backend.SQLite import SQLiteBackend, SQLiteObjectBackendModificationTracker

from ocdlib.Config import Config
from ocdlib.State import State
from ocdlib.Events import getEventGenerators
from ocdlib.Localization import _
from ocdlib.OpsiService import ServiceConnection

logger = Logger()
config = Config()
state = State()

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
	
	def syncConfig(self, waitForEnding = False):
		self.initializeConfigCacheService()
		if self._configCacheService.isWorking():
			logger.info(u"Already syncing config")
		else:
			self._configCacheService.syncConfig()
		if waitForEnding:
			time.sleep(3)
			while self._configCacheService.isRunning() and self._configCacheService.isWorking():
				time.sleep(1)
	
	def syncConfigToServer(self, waitForEnding = False):
		self.initializeConfigCacheService()
		if self._configCacheService.isWorking():
			logger.info(u"Already syncing config")
		else:
			self._configCacheService.syncConfigToServer()
		if waitForEnding:
			time.sleep(3)
			while self._configCacheService.isRunning() and self._configCacheService.isWorking():
				time.sleep(1)
	
	def configCacheCompleted(self):
		self.initializeConfigCacheService()
		if not self._configCacheService.isWorking() and self._configCacheService.getState().get('config_cached', False):
			return True
		return False
	
	def getConfigBackend(self):
		self.initializeConfigCacheService()
		return self._configCacheService.getConfigBackend()
	
	def getConfigModifications(self):
		self.initializeConfigCacheService()
		return self._configCacheService._backendTracker.getModifications()
	
	def cacheProducts(self, configService, productIds, waitForEnding = False):
		self.initializeProductCacheService()
		if self._productCacheService.isWorking():
			logger.info(u"Already caching products")
		else:
			self._productCacheService.setConfigService(configService)
			self._productCacheService.setProductIdsToCache(productIds)
		if waitForEnding:
			time.sleep(3)
			while self._productCacheService.isRunning() and self._productCacheService.isWorking():
				time.sleep(1)
	
	def productCacheCompleted(self, configService, productIds):
		if not productIds:
			return True
		self.initializeProductCacheService()
		
		clientToDepotservers = configService.configState_getClientToDepotserver(
				clientIds  = [ config.get('global', 'host_id') ],
				masterOnly = True,
				productIds = productIds)
		if not clientToDepotservers:
			raise Exception(u"Failed to get depot config from service")
		depotId = [ clientToDepotservers[0]['depotId'] ]
		productOnDepots = {}
		for productOnDepot in configService.productOnDepot_getObjects(depotId = depotId, productId = productIds):
			productOnDepots[productOnDepot.productId] = productOnDepot
		
		for productId in productIds:
			productOnDepot = productOnDepots.get(productId)
			if not productOnDepot:
				raise Exception(u"Product '%s' not available on depot '%s'" % productId)
			productState = self._productCacheService.getState().get('products', {}).get(productId)
			if not productState:
				logger.debug(u"No products cached")
				return False
			if not productState.get('completed') or (productState.get('productVersion') != productOnDepot.productVersion) or (productState.get('packageVersion') != productOnDepot.packageVersion):
				logger.debug(u"Product '%s_%s-%s' not yet cached (got state: %s)" % (productId, productOnDepot.productVersion, productOnDepot.packageVersion, productState))
				return False
		return True
	
	def getProductCacheState(self):
		self.initializeProductCacheService()
		return self._productCacheService.getState()
	
	def getOverallProductCacheProgressSubject(self):
		self.initializeProductCacheService()
		return self._productCacheService.getOverallProgressSubject()
	
	def getCurrentProductCacheProgressSubject(self):
		self.initializeProductCacheService()
		return self._productCacheService.getCurrentProgressSubject()


class ConfigCacheServiceBackendExtension(object):
	def accessControl_authenticated(self):
		return True
	
class ConfigCacheService(ServiceConnection, threading.Thread):
	def __init__(self):
		threading.Thread.__init__(self)
		ServiceConnection.__init__(self)
		moduleName = u' %-30s' % (u'config cache service')
		logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)
		
		self._configCacheDir = os.path.join(config.get('cache_service', 'storage_dir'), 'config')
		
		self._stopped = False
		self._running = False
		self._working = False
		self._state   = {}
		
		self._syncConfigFromServerRequested = False
		self._syncConfigToServerRequested = False
		
		if not os.path.exists(self._configCacheDir):
			logger.notice(u"Creating config cache dir '%s'" % self._configCacheDir)
			os.makedirs(self._configCacheDir)
		
		backendArgs = {
			'opsiModulesFile':         os.path.join(self._configCacheDir, 'cached_modules'),
			'opsiVersionFile':         os.path.join(self._configCacheDir, 'cached_version'),
			'opsiPasswdFile':          os.path.join(self._configCacheDir, 'cached_passwd'),
			'auditHardwareConfigFile': os.path.join(self._configCacheDir, 'cached_opsihwaudit.json')
		}
		self._workBackend = SQLiteBackend(
			#database    = ':memory:',
			database    = os.path.join(self._configCacheDir, 'work.sqlite'),
			synchronous = False,
			**backendArgs
		)
		self._workBackend.backend_createBase()
		
		self._snapshotBackend = SQLiteBackend(
			#database    = ':memory:',
			database    = os.path.join(self._configCacheDir, 'snapshot.sqlite'),
			synchronous = False,
			**backendArgs
		)
		self._snapshotBackend.backend_createBase()
		
		self._cacheBackend = ClientCacheBackend(
			workBackend     = self._workBackend,
			snapshotBackend = self._snapshotBackend,
			depotId         = config.get('depot_server', 'depot_id'),
			clientId        = config.get('global', 'host_id'),
			**backendArgs
		)
		
		self._configBackend = BackendExtender(
			backend = ExtendedConfigDataBackend(
				configDataBackend = self._cacheBackend
			),
			extensionClass     = ConfigCacheServiceBackendExtension,
			extensionConfigDir = config.get('cache_service', 'extension_config_dir')
		)
		self._backendTracker = SQLiteObjectBackendModificationTracker(
			#database    = ':memory:',
			database             = os.path.join(self._configCacheDir, 'tracker.sqlite'),
			synchronous          = False,
			lastModificationOnly = True
		)
		self._cacheBackend.addBackendChangeListener(self._backendTracker)
		
		ccss = state.get('config_cache_service')
		if ccss:
			self._state = ccss
	
	def getConfigBackend(self):
		return self._configBackend
	
	def getState(self):
		return self._state
	
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
				logger.essential(u"======== working: %s _syncConfigToServerRequested: %s _syncConfigFromServerRequested: %s ======" % (self._working, self._syncConfigToServerRequested, self._syncConfigFromServerRequested))
				if not self._working:
					if self._syncConfigToServerRequested:
						self._syncConfigFromServerRequested = False
						logger.notice(u"============================= syncConfigToServerRequested =========================================")
						self._syncConfigToServer()
					elif self._syncConfigFromServerRequested:
						self._syncConfigToServerRequested = False
						logger.notice(u"============================= syncConfigFromServer =========================================")
						self._syncConfigFromServer()
				time.sleep(1)
		except Exception, e:
			logger.logException(e)
		logger.notice(u"Config cache service ended")
		self._running = False
	
	def syncConfig(self):
		self._syncConfigToServerRequested = True
		self._syncConfigFromServerRequested = True
		
	def syncConfigToServer(self):
		self._syncConfigToServerRequested = True
	
	def _syncConfigToServer(self):
		self._working = True
		try:
			modifications = self._backendTracker.getModifications()
			if not modifications:
				logger.notice(u"Cache backend was not modified, no sync to server required")
			else:
				logger.notice(u"Cache backend was modified, starting sync to server")
				if not self._configService:
					self.connectConfigService()
				self._cacheBackend._setMasterBackend(self._configService)
				self._cacheBackend._updateMasterFromWorkBackend(modifications)
				logger.notice(u"Config synced to server")
		except Exception, e:
			logger.logException(e)
			logger.error(u"Errors occured while syncing config to server: %s" % e)
			# Do not sync from server in this case!
			self._syncConfigFromServerRequested = False
		if self._configService:
			try:
				self.disconnectConfigService()
			except Exception, e:
				logger.notice(u"Failed to diconnect from config service: %s" % e)
		self._working = False
		
	def _syncConfigFromServer(self):
		self._working = True
		try:
			if not self._configService:
				self.connectConfigService()
			productOnClients = self._configService.productOnClient_getObjects(
				productType   = 'LocalbootProduct',
				clientId      = config.get('global', 'host_id'),
				actionRequest = ['setup', 'uninstall', 'update', 'always', 'once', 'custom'],
				attributes    = ['actionRequest'])
			if not productOnClients:
				logger.notice(u"No product action(s) set on config service, no sync from server required")
			else:
				productIds = []
				for productOnClient in productOnClients:
					productIds.append(productOnClient.productId)
				logger.notice(u"Product action(s) set on config service (%s), sync from server required" % u','.join(productIds))
				self._cacheBackend._setMasterBackend(self._configService)
				self._state['config_cached'] = False
				state.set('config_cache_service', self._state)
				self._backendTracker.clearModifications()
				self._cacheBackend._replicateMasterToWorkBackend()
				logger.notice(u"Config synced from server")
				self._state['config_cached'] = True
				state.set('config_cache_service', self._state)
		except Exception, e:
			logger.logException(e)
			logger.error(u"Errors occured while syncing config from server: %s" % e)
		if self._configService:
			try:
				self.disconnectConfigService()
			except Exception, e:
				logger.notice(u"Failed to diconnect from config service: %s" % e)
		self._working = False
	
class ProductCacheService(threading.Thread):
	def __init__(self):
		threading.Thread.__init__(self)
		moduleName = u' %-30s' % (u'product cache service')
		logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)
		
		self._storageDir          = config.get('cache_service', 'storage_dir')
		self._tempDir             = os.path.join(self._storageDir, 'tmp')
		self._productCacheDir     = os.path.join(self._storageDir, 'depot')
		self._productCacheMaxSize = forceInt(config.get('cache_service', 'product_cache_max_size'))
		
		self._stopped = False
		self._running = False
		self._working = False
		self._state   = {}
		
		self._productIdsToCache = []
		self._configService = None
		
		self._overallProgressSubject = ProgressSubject(id = 'overall', type = 'product_cache')
		self._currentProgressSubject = ProgressSubject(id = 'current', type = 'product_cache')
		
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
	
	def getOverallProgressSubject(self):
		return self._overallProgressSubject
	
	def getCurrentProgressSubject(self):
		return self._currentProgressSubject
	
	def getState(self):
		return self._state
	
	def isRunning(self):
		return self._running
	
	def isWorking(self):
		return self._working
	
	def stop(self):
		self._stopped = True
	
	def run(self):
		self._running = True
		logger.notice(u"Product cache service started")
		try:
			while not self._stopped:
				if self._productIdsToCache and not self._working:
					self._cacheProducts()
				time.sleep(1)
		except Exception, e:
			logger.logException(e)
		logger.notice(u"Product cache service ended")
		self._running = False
	
	def setProductIdsToCache(self, productIds):
		self._productIdsToCache = forceProductIdList(productIds)
	
	def setConfigService(self, configService):
		modules = None
		if configService.isOpsi35():
			modules = configService.backend_info()['modules']
		else:
			modules = configService.getOpsiInformation_hash()['modules']
		
		if not modules.get('vpn'):
			raise Exception(u"Cannot sync products: VPN module currently disabled")
		
		if not modules.get('customer'):
			raise Exception(u"Cannot sync products: No customer in modules file")
			
		if not modules.get('valid'):
			raise Exception(u"Cannot sync products: modules file invalid")
		
		if (modules.get('expires', '') != 'never') and (time.mktime(time.strptime(modules.get('expires', '2000-01-01'), "%Y-%m-%d")) - time.time() <= 0):
			raise Exception(u"Cannot sync products: modules file expired")
		
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
			raise Exception(u"Cannot sync products: modules file invalid")
		logger.notice(u"Modules file signature verified (customer: %s)" % modules.get('customer'))
		self._configService = configService
		
	def _getConfigService(self):
		if not self._configService:
			raise Exception(u"Not connected to config service")
		return self._configService
	
	def _freeProductCacheSpace(self, neededSpace = 0, neededProducts = []):
		try:
			# neededSpace in byte
			neededSpace    = forceInt(neededSpace)
			neededProducts = forceProductIdList(neededProducts)
			
			maxFreeableSize = 0
			productDirSizes = {}
			for product in os.listdir(self._productCacheDir):
				if not product in neededProducts:
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
						logger.info(u"Package content file '%s' not found, deleting product cache to free disk space")
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
			logger.notice(u"%0.3f MB of product cache freed" % (float(freedSpace)/(1024*1024)))
		except Exception, e:
			raise Exception(u"Failed to free enough disk space for product cache: %s" % forceUnicode(e))
	
	def _cacheProducts(self):
		self._working = True
		self._state['products_cached'] = False
		self._state['products'] = {}
		state.set('product_cache_service', self._state)
		
		logger.notice(u"Caching products: %s" % ', '.join(self._productIdsToCache))
		self._overallProgressSubject.setEnd(len(self._productIdsToCache))
		self._overallProgressSubject.setMessage( _(u'Caching products') )
		
		try:
			errorsOccured = []
			for productId in self._productIdsToCache:
				try:
					self._overallProgressSubject.setMessage( _(u'Caching product: %s') % productId )
					self._cacheProduct(productId)
				except Exception, e:
					logger.logException(e, LOG_INFO)
					errorsOccured.append(forceUnicode(e))
					self._setProductCacheState(productId, 'failure', forceUnicode(e))
				self._overallProgressSubject.addToState(1)
		except Exception, e:
			logger.logException(e)
			errorsOccured.append(forceUnicode(e))
		if errorsOccured:
			logger.error(u"Errors occured while caching products %s: %s" % (', '.join(self._productIdsToCache), ', '.join(errorsOccured)))
		else:
			logger.notice(u"All products cached: %s" % ', '.join(self._productIdsToCache))
			self._state['products_cached'] = True
			state.set('product_cache_service', self._state)
			#for eventGenerator in getEventGenerators(generatorClass = ProductSyncCompletedEventGenerator):
			#	eventGenerator.fireEvent()
		self._productIdsToCache = []
		self._working = False
	
	def _setProductCacheState(self, productId, key, value):
		if not self._state.has_key('products'):
			self._state['products'] = {}
		if not self._state['products'].has_key(productId):
			self._state['products'][productId] = {}
		self._state['products'][productId][key] = value
		state.set('product_cache_service', self._state)
		if self._getConfigService():
			actionProgress = None
			if   (key == 'started'):
				actionProgress = 'caching'
			elif (key == 'completed'):
				actionProgress = 'cached'
			elif (key == 'failure'):
				actionProgress = forceUnicode(value)
			if actionProgress:
				self._getConfigService().productOnClient_updateObjects([
					ProductOnClient(
						productId      = productId,
						productType    = u'LocalbootProduct',
						clientId       = config.get('global', 'host_id'),
						actionProgress = actionProgress
					)
				])
	
	def _getRepository(self, productId):
		configService = self._getConfigService()
		config.selectDepotserver(configService = configService, event = None, productIds = [ productId ], cifsOnly = False)
		if not config.get('depot_server', 'url'):
			raise Exception(u"Cannot cache product files: depot_server.url undefined")
		(depotServerUsername, depotServerPassword) = (u'', u'')
		if urlsplit(config.get('depot_server', 'url'))[0].startswith('webdav'):
			(depotServerUsername, depotServerPassword) = (config.get('global', 'host_id'), config.get('global', 'opsi_host_key'))
		else:
			(depotServerUsername, depotServerPassword) = config.getDepotserverCredentials(configService = configService)
		return getRepository(config.get('depot_server', 'url'), username = depotServerUsername, password = depotServerPassword)
		
	def _cacheProduct(self, productId):
		logger.notice(u"Caching product '%s'" % productId)
		self._setProductCacheState(productId, 'started',   time.time())
		self._setProductCacheState(productId, 'completed', None)
		self._setProductCacheState(productId, 'failure',   None)
		
		repository = self._getRepository(productId)
		if not config.get('depot_server', 'depot_id'):
			raise Exception(u"Cannot cache product files: depot_server.depot_id undefined")
		configService = self._getConfigService()
		productOnDepots = configService.productOnDepot_getObjects(depotId = config.get('depot_server', 'depot_id'), productId = productId)
		if not productOnDepots:
			raise Exception(u"Product '%s' not found on depot '%s'" % (productId, config.get('depot_server', 'depot_id')))
		
		self._setProductCacheState(productId, 'productVersion', productOnDepots[0].productVersion)
		self._setProductCacheState(productId, 'packageVersion', productOnDepots[0].packageVersion)
		
		try:
			tempPackageContentFile = os.path.join(self._tempDir, u'%s.files' % productId)
			packageContentFile = u'%s/%s.files' % (productId, productId)
			logger.info(u"Downloading package content file '%s' of product '%s' from depot '%s' to '%s'" % (packageContentFile, productId, repository, tempPackageContentFile))
			repository.download(source = packageContentFile, destination = tempPackageContentFile)
			
			packageContentFile = os.path.join(self._productCacheDir, productId, u'%s.files' % productId)
			if os.path.exists(packageContentFile) and (md5sum(tempPackageContentFile) == md5sum(packageContentFile)):
				logger.info(u"Package content file unchanged, assuming that product is up to date")
				self._setProductCacheState(productId, 'completed', time.time())
				repository.disconnect()
				return
			
			if not os.path.exists(os.path.join(self._productCacheDir, productId)):
				os.mkdir(os.path.join(self._productCacheDir, productId))
			logger.debug(u"Moving package content file from '%s' to '%s'" % (tempPackageContentFile, packageContentFile))
			if os.path.exists(packageContentFile):
				os.unlink(packageContentFile)
			os.rename(tempPackageContentFile, packageContentFile)
			packageInfo = PackageContentFile(packageContentFile).parse()
			productSize = 0
			fileCount = 0
			for value in packageInfo.values():
				if value.has_key('size'):
					fileCount += 1
					productSize += int(value['size'])
			
			logger.info(u"Product '%s' contains %d files with a total size of %0.3f MB" \
				% ( productId, fileCount, (float(productSize)/(1024*1024)) ) )
			
			productCacheDirSize = 0
			if (self._productCacheMaxSize > 0):
				productCacheDirSize = System.getDirectorySize(self._productCacheDir)
				if (productCacheDirSize + productSize > self._productCacheMaxSize):
					logger.info(u"Product cache dir sizelimit of %0.3f MB exceeded. Current size: %0.3f MB, space needed for product '%s': %0.3f MB" \
							% ( (float(self._productCacheMaxSize)/(1024*1024)), (float(productCacheDirSize)/(1024*1024)), \
							    productId, (float(productSize)/(1024*1024)) ) )
					self._freeProductCacheSpace(neededSpace = productSize, neededProducts = self._productIds)
					productCacheDirSize = System.getDirectorySize(self._productCacheDir)
			
			diskFreeSpace = System.getDiskSpaceUsage(self._productCacheDir)['available']
			if (diskFreeSpace < productSize + 500*1024*1024):
				raise Exception(u"Only %0.3f MB free space available on disk, refusing to cache product files" \
							% (float(diskFreeSpace)/(1024*1024)))
			
			productSynchronizer = DepotToLocalDirectorySychronizer(
				sourceDepot          = repository,
				destinationDirectory = self._productCacheDir,
				productIds           = [ productId ],
				maxBandwidth         = 0,
				dynamicBandwidth     = False
			)
			productSynchronizer.synchronize(productProgressObserver = self._currentProgressSubject)
			logger.notice(u"Product '%s' cached" % productId)
			self._setProductCacheState(productId, 'completed', time.time())
		finally:
			repository.disconnect()
	












