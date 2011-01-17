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
import threading, base64
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
from OPSI.Backend.Cache import ClientCacheBackend
from OPSI.Backend.SQLite import SQLiteBackend

from ocdlib.Config import Config
from ocdlib.State import State
from ocdlib.Events import *
from ocdlib.Localization import _
from ocdlib.OpsiService import ServiceConnectionThread

logger = Logger()
config = Config()
state = State()

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                            CACHE SERVICE                                            -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

'''
class CacheService(threading.Thread):
	def __init__(self, opsiclientd):
		threading.Thread.__init__(self)
		moduleName = u' %-30s' % (u'cache service')
		logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)
		self._opsiclientd = opsiclientd
		self._storageDir = config.get('cache_service', 'storage_dir')
		self._tempDir = os.path.join(self._storageDir, 'tmp')
		self._productCacheDir = os.path.join(self._storageDir, 'depot')
		self._productCacheMaxSize = forceInt(config.get('cache_service', 'product_cache_max_size'))
		self._configCacheDir = os.path.join(self._storageDir, 'config')
		
		self._stopped = False
		self._running = False
		
		self._state = {
			'product':  {},
			'config':   {}
		}
		
		self._configService = None
		self._productIds = []
		
		self._cacheProductsRequested = False
		self._cacheProductsRunning = False
		self._cacheProductsEnded = threading.Event()
		
		self._cacheConfigRequested = False
		self._cacheConfigRunning = False
		self._cacheConfigEnded = threading.Event()
		
		self._currentProductSyncProgressObserver = None
		self._overallProductSyncProgressObserver = None
		self._initialized = False
		
		self._cacheBackend = None
		
	def initialize(self):
		if self._initialized:
			return
		#self.readStateFile()
		self._initialized = True
		if not os.path.exists(self._storageDir):
			logger.notice(u"Creating cache service storage dir '%s'" % self._storageDir)
			os.makedirs(self._storageDir)
		if not os.path.exists(self._tempDir):
			logger.notice(u"Creating cache service temp dir '%s'" % self._tempDir)
			os.makedirs(self._tempDir)
		if not os.path.exists(self._productCacheDir):
			logger.notice(u"Creating cache service product cache dir '%s'" % self._productCacheDir)
			os.makedirs(self._productCacheDir)
		if not os.path.exists(self._configCacheDir):
			logger.notice(u"Creating cache service config cache dir '%s'" % self._configCacheDir)
			os.makedirs(self._configCacheDir)
		
		workBackend = SQLiteBackend(database = os.path.join(self._configCacheDir, 'work.sqlite'))
		# @TODO:
		workBackend._sql.execute('PRAGMA synchronous=OFF')
		workBackend.backend_createBase()
		
		self._cacheBackend = ClientCacheBackend(
			workBackend     = workBackend,
			depotId         = config.get('depot_server', 'depot_id'),
			clientId        = config.get('global', 'host_id'),
			opsiModulesFile = os.path.join(self._configCacheDir, 'cached_modules'),
			opsiVersionFile = os.path.join(self._configCacheDir, 'cached_version'),
		)
	
	def getConfigBackend(self):
		return self._cacheBackend
	
	def setCurrentProductSyncProgressObserver(self, currentProductSyncProgressObserver):
		self._currentProductSyncProgressObserver = currentProductSyncProgressObserver
	
	def setOverallProductSyncProgressObserver(self, overallProductSyncProgressObserver):
		self._overallProductSyncProgressObserver = overallProductSyncProgressObserver
	
	def getProductCacheDir(self):
		return self._productCacheDir
		
	def getProductSyncCompleted(self):
		self.initialize()
		if not self._state['product']:
			logger.info(u"No products cached")
			return False
		productSyncCompleted = True
		for (productId, state) in self._state['product'].items():
			if state.get('sync_completed'):
				logger.debug(u"Product '%s': sync completed" % productId)
			else:
				productSyncCompleted = False
				logger.debug(u"Product '%s': sync not completed" % productId)
		return productSyncCompleted
	
	def getConfigSyncCompleted(self):
		self.initialize()
		if not self._state['config']:
			logger.info(u"No config cached")
			return False
		return False
	
	def triggerCacheConfig(self, configService, waitForEnding=False):
		if self._cacheConfigRunning:
			logger.info(u"Already caching config")
		else:
			self.initialize()
			self._cacheConfigRequested = True
			self._cacheConfigEnded.clear()
			#if not configService:
			#	url = config.get('config_service', 'url')[0]
			#	serviceConnectionThread = ServiceConnectionThread(
			#		configServiceUrl = url,
			#		username         = config.get('global', 'host_id'),
			#		password         = config.get('global', 'opsi_host_key') )
			#	serviceConnectionThread.start()
			#	for i in range(5):
			#		if serviceConnectionThread.running:
			#			break
			#		time.sleep(1)
			#	logger.debug(u"ServiceConnectionThread started")
			#	timeout = 30
			#	while serviceConnectionThread.running and (timeout > 0):
			#		time.sleep(1)
			#		timeout -= 1
			#	if serviceConnectionThread.running:
			#		serviceConnectionThread.stop()
			#		raise Exception(u"Failed to connect to config service '%s': timed out" % url)
			#	if not serviceConnectionThread.connected:
			#		raise Exception(u"Failed to connect to config service '%s': %s" % (url, serviceConnectionThread.connectionError))
			#	configService = serviceConnectionThread.configService
			#self._cacheBackend._setMasterBackend(configService)
			#self._cacheBackend._replicateMasterToWorkBackend()
		if waitForEnding:
			self._cacheConfigEnded.wait()
			#for productId in self._state['product'].keys():
			#	if self._state['product'][productId]['sync_failure']:
			#		raise Exception(u"Failed to cache product '%s': %s" % (productId, self._state['product'][productId]['sync_failure']))
		
	def triggerCacheProducts(self, configService, productIds, waitForEnding=False):
		if self._cacheProductsRunning:
			logger.info(u"Already caching products")
		else:
			self.initialize()
			self._configService = configService
			self._productIds = productIds
			if 'mshotfix' in self._productIds:
				additionalProductId = getOpsiHotfixName()
				logger.info(u"Requested to cache product mshotfix => additionaly caching system specific mshotfix product: %s" % additionalProductId)
				if not additionalProductId in self._productIds:
					self._productIds.append(additionalProductId)
			self._cacheProductsRequested = True
			self._cacheProductsEnded.clear()
			for productId in self._productIds:
				if not self._state['product'].has_key(productId):
					self._state['product'][productId] = {'sync_started': '', 'sync_completed': '', 'sync_failure': '' }
		if waitForEnding:
			self._cacheProductsEnded.wait()
			for productId in self._state['product'].keys():
				if self._state['product'][productId]['sync_failure']:
					raise Exception(u"Failed to cache product '%s': %s" % (productId, self._state['product'][productId]['sync_failure']))
	
	def cacheProducts(self):
		self._cacheProductsRunning = True
		try:
			logger.notice(u"Caching products: %s" % ', '.join(self._productIds))
			self.initialize()
			
			if not self._configService:
				raise Exception(u"Not connected to config service")
			
			modules = None
			if self._configService.isOpsi35():
				modules = self._configService.backend_info()['modules']
			else:
				modules = self._configService.getOpsiInformation_hash()['modules']
			
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
			
			logger.info(u"Synchronizing %d product(s):" % len(self._productIds))
			for productId in self._productIds:
				logger.info("   %s" % productId)
			
			overallProgressSubject = ProgressSubject(id = 'sync_products_overall', type = 'product_sync', end = len(self._productIds))
			overallProgressSubject.setMessage( _(u'Synchronizing products') )
			if self._overallProductSyncProgressObserver:
				overallProgressSubject.attachObserver(self._overallProductSyncProgressObserver)
			
			productCacheDirSize = 0
			if (self._productCacheMaxSize > 0):
				productCacheDirSize = System.getDirectorySize(self._productCacheDir)
			diskFreeSpace = System.getDiskSpaceUsage(self._productCacheDir)['available']
			
			errorsOccured = []
			for productId in self._productIds:
				logger.notice(u"Syncing files of product '%s'" % productId)
				self._state['product'][productId]['sync_started']   = time.time()
				self._state['product'][productId]['sync_completed'] = ''
				self._state['product'][productId]['sync_failure']   = ''
				
				self._configService.productOnClient_updateObjects([
					ProductOnClient(
						productId      = productId,
						productType    = u'LocalbootProduct',
						clientId       = config.get('global', 'host_id'),
						actionProgress = u'caching'
					)
				])
				
				config.selectDepotserver(configService = self._configService, productIds = [ productId ], cifsOnly = False)
				depotUrl = config.get('depot_server', 'url')
				if not depotUrl:
					raise Exception(u"Cannot sync files, depot_server.url undefined")
				(depotServerUsername, depotServerPassword) = (u'', u'')
				if urlsplit(depotUrl)[0].startswith('webdav'):
					(depotServerUsername, depotServerPassword) = (config.get('global', 'host_id'), config.get('global', 'opsi_host_key'))
				else:
					(depotServerUsername, depotServerPassword) = config.getDepotserverCredentials(configService = self._configService)
				repository = getRepository(config.get('depot_server', 'url'), username = depotServerUsername, password = depotServerPassword)
				
				#self.writeStateFile()
				try:
					tempPackageContentFile = os.path.join(self._tempDir, u'%s.files' % productId)
					packageContentFile = u'%s/%s.files' % (productId, productId)
					logger.info(u"Downloading package content file '%s' of product '%s' from depot '%s' to '%s'" % (packageContentFile, productId, repository, tempPackageContentFile))
					repository.download(source = packageContentFile, destination = tempPackageContentFile)
					
					packageContentFile = os.path.join(self._productCacheDir, productId, u'%s.files' % productId)
					if os.path.exists(packageContentFile) and (md5sum(tempPackageContentFile) == md5sum(packageContentFile)):
						logger.info(u"Package content file unchanged, assuming that product is up to date")
						self._state['product'][productId]['sync_completed'] = time.time()
						overallProgressSubject.addToState(1)
						repository.disconnect()
						continue
					
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
					
					if (self._productCacheMaxSize > 0) and (productCacheDirSize + productSize > self._productCacheMaxSize):
						logger.info(u"Product cache dir sizelimit of %0.3f MB exceeded. Current size: %0.3f MB, space needed for product '%s': %0.3f MB" \
								% ( (float(self._productCacheMaxSize)/(1024*1024)), (float(productCacheDirSize)/(1024*1024)), \
								    productId, (float(productSize)/(1024*1024)) ) )
						self.freeProductCacheSpace(neededSpace = productSize, neededProducts = self._productIds)
						productCacheDirSize = System.getDirectorySize(self._productCacheDir)
					
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
					productSynchronizer.synchronize(productProgressObserver = self._currentProductSyncProgressObserver)
					self._state['product'][productId]['sync_completed'] = time.time()
					logger.notice(u"Product '%s' synced" % productId)
					productCacheDirSize += productSize
					diskFreeSpace -= productSize
					self._configService.productOnClient_updateObjects([
						ProductOnClient(
							productId      = productId,
							productType    = u'LocalbootProduct',
							clientId       = config.get('global', 'host_id'),
							actionProgress = u'cached'
						)
					])
				except Exception, e:
					logger.logException(e)
					logger.error("Failed to sync product '%s': %s" % (productId, forceUnicode(e)))
					errorsOccured.append( u'%s: %s' % (productId, forceUnicode(e)) )
					self._state['product'][productId]['sync_failure'] = forceUnicode(e)
					self._configService.productOnClient_updateObjects([
						ProductOnClient(
							productId      = productId,
							productType    = u'LocalbootProduct',
							clientId       = config.get('global', 'host_id'),
							actionProgress = u'failed to cache: %s' % forceUnicode(e)
						)
					])
				repository.disconnect()
				#self.writeStateFile()
				overallProgressSubject.addToState(1)
			
			if self._overallProductSyncProgressObserver:
				overallProgressSubject.detachObserver(self._overallProductSyncProgressObserver)
			
			#for productId in self._productIds:
			#	if self._state['product'][productId]['sync_failed']:
			#		raise Exception(self._state['product'][productId]['sync_failed'])
			
			if errorsOccured:
				logger.error(u"Errors occured while caching products %s: %s" % (', '.join(self._productIds), ', '.join(errorsOccured)))
			else:
				logger.notice(u"All products cached: %s" % ', '.join(self._productIds))
				for eventGenerator in getEventGenerators(generatorClass = ProductSyncCompletedEventGenerator):
					eventGenerator.fireEvent()
		finally:
			#self.writeStateFile()
			self._cacheProductsRunning = False
			self._cacheProductsEnded.set()
	
	def cacheConfig(self):
		self._cacheConfigRunning = True
		try:
			self.initialize()
			self._cacheBackend._setMasterBackend(self._configService)
			self._cacheBackend._replicateMasterToWorkBackend()
		finally:
			#self.writeStateFile()
			self._cacheConfigRunning = False
			self._cacheConfigEnded.set()
		
	def stop(self):
		self._stopped = True
		
	def run(self):
		self._running = True
		while not self._stopped:
			try:
				if self._cacheProductsRequested:
					self._cacheProductsRequested = False
					try:
						self.cacheProducts()
					except Exception, e:
						logger.logException(e)
						logger.error(u"Failed to cache products: %s" % forceUnicode(e))
				
				if self._cacheConfigRequested:
					self._cacheConfigRequested = False
					try:
						self.cacheConfig()
					except Exception, e:
						logger.logException(e)
						logger.error(u"Failed to cache config: %s" % forceUnicode(e))
			except Exception, e:
				logger.logException(e)
			time.sleep(3)
		self._running = False
'''
class CacheService(threading.Thread):
	def __init__(self, opsiclientd):
		threading.Thread.__init__(self)
		self._productCacheService = None
	
	def cacheProducts(self, configService, productIds, waitForEnding = False):
		if not self._productCacheService:
			self._productCacheService = ProductCacheService()
			self._productCacheService.start()
		
		if self._productCacheService.isWorking():
			logger.info(u"Already caching products")
		else:
			self._productCacheService.setConfigService(configService)
			self._productCacheService.setProductIdsToCache(productIds)
		if waitForEnding:
			time.sleep(3)
			while self._productCacheService.isRunning() and self._productCacheService.isWorking():
				time.sleep(1)
		
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
	
	def isRunning(self):
		return self._running
	
	def isWorking(self):
		return self._working
	
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
	
	def stop(self):
		self._stopped = True
	
	def run(self):
		self._running = True
		logger.notice(u"Product cache service started")
		try:
			while not self._stopped:
				if self._productIdsToCache:
					self._cacheProducts()
				time.sleep(1)
		except Exception, e:
			logger.logException(e)
		logger.notice(u"Product cache service ended")
		self._running = False
	
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
			logger.notice(u"%0.3f MB of product cache freed" % (float(freedSpace)/(1024*1024)))
		except Exception, e:
			raise Exception(u"Failed to free enough disk space for product cache: %s" % forceUnicode(e))
	
	def _cacheProducts(self):
		self._working = True
		self._state['products_cached'] = False
		state.set('product_cache_service', self._state)
		logger.notice(u"Caching products: %s" % ', '.join(self._productIdsToCache))
		try:
			errorsOccured = []
			for productId in self._productIdsToCache:
				try:
					self._cacheProduct(productId)
					#overallProgressSubject.addToState(1)
				except Exception, e:
					logger.logException(e, LOG_INFO)
					errorsOccured.append(forceUnicode(e))
					self._setProductCacheState(productId, 'failure', forceUnicode(e))
		except Exception, e:
			logger.logException(e)
			errorsOccured.append(forceUnicode(e))
		if errorsOccured:
			logger.error(u"Errors occured while caching products %s: %s" % (', '.join(self._productIdsToCache), ', '.join(errorsOccured)))
		else:
			logger.notice(u"All products cached: %s" % ', '.join(productIds))
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
		config.selectDepotserver(configService = configService, productIds = [ productId ], cifsOnly = False)
		depotUrl = config.get('depot_server', 'url')
		if not depotUrl:
			raise Exception(u"Cannot sync files, depot_server.url undefined")
		(depotServerUsername, depotServerPassword) = (u'', u'')
		if urlsplit(depotUrl)[0].startswith('webdav'):
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
			productSynchronizer.synchronize()#productProgressObserver = self._currentProductSyncProgressObserver)
			logger.notice(u"Product '%s' cached" % productId)
			self._setProductCacheState(productId, 'completed', time.time())
		finally:
			repository.disconnect()
		
	#def hide(delf):
	#		logger.notice(u"Caching products: %s" % ', '.join(self._productIds))
	#		self.initialize()
	#				
	#		logger.info(u"Synchronizing %d product(s):" % len(self._productIds))
	#		for productId in self._productIds:
	#			logger.info("   %s" % productId)
	#		
	#		overallProgressSubject = ProgressSubject(id = 'sync_products_overall', type = 'product_sync', end = len(self._productIds))
	#		overallProgressSubject.setMessage( _(u'Synchronizing products') )
	#		if self._overallProductSyncProgressObserver:
	#			overallProgressSubject.attachObserver(self._overallProductSyncProgressObserver)
	#		
	#		
	#		
	#		
	#		for productId in self._productIds:
	#			
	#			
	#			#self.writeStateFile()
	#			try:
	#				
	#			except Exception, e:
	#				logger.logException(e)
	#				logger.error("Failed to sync product '%s': %s" % (productId, forceUnicode(e)))
	#				errorsOccured.append( u'%s: %s' % (productId, forceUnicode(e)) )
	#				self._state['product'][productId]['sync_failure'] = forceUnicode(e)
	#				self._configService.productOnClient_updateObjects([
	#					ProductOnClient(
	#						productId      = productId,
	#						productType    = u'LocalbootProduct',
	#						clientId       = config.get('global', 'host_id'),
	#						actionProgress = u'failed to cache: %s' % forceUnicode(e)
	#					)
	#				])
	#			repository.disconnect()
	#			#self.writeStateFile()
	#			overallProgressSubject.addToState(1)
	#		
	#		if self._overallProductSyncProgressObserver:
	#			overallProgressSubject.detachObserver(self._overallProductSyncProgressObserver)
	#		
	#		#for productId in self._productIds:
	#		#	if self._state['product'][productId]['sync_failed']:
	#		#		raise Exception(self._state['product'][productId]['sync_failed'])
	#		
	#		if errorsOccured:
	#			logger.error(u"Errors occured while caching products %s: %s" % (', '.join(self._productIds), ', '.join(errorsOccured)))
	#		else:
	#			logger.notice(u"All products cached: %s" % ', '.join(self._productIds))
	#			for eventGenerator in getEventGenerators(generatorClass = ProductSyncCompletedEventGenerator):
	#				eventGenerator.fireEvent()
	#	finally:
	#		#self.writeStateFile()
	#		self._cacheProductsRunning = False
	#		self._cacheProductsEnded.set()
	














