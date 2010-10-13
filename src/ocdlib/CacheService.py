# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = = = =
   =   ocdlib.CacheService                 =
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

# Import
import threading, base64
from hashlib import md5
from twisted.conch.ssh import keys

# OPSI imports
from OPSI.Logger import *
from OPSI.Types import *
from OPSI.Util.Repository import *
from OPSI.Util import md5sum
from OPSI import System

from ocdlib.Config import Config
from ocdlib.Events import *
from ocdlib.Localization import _

logger = Logger()
config = Config()

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                        CACHED CONFIG SERVICE                                      -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

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
		
		self._currentProductSyncProgressObserver = None
		self._overallProductSyncProgressObserver = None
		self._initialized = False
	
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
		
	def cacheProducts(self, configService, productIds, waitForEnding=False):
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
	
	def freeProductCacheSpace(self, neededSpace = 0, neededProducts = []):
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
		
	def stop(self):
		self._stopped = True
		
	def run(self):
		self._running = True
		while not self._stopped:
			try:
				if self._cacheProductsRequested:
					self._cacheProductsRequested = False
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
							
							config.selectDepot(configService = self._configService, productIds = productId)
							if not config.get('depot_server', 'url'):
								raise Exception(u"Cannot sync files, depot_server.url undefined")
							(depotServerUsername, depotServerPassword) = config.getDepotserverCredentials(configService = self._configService)
							repository = getRepository(config.get('depot_server', 'url'), username = depotServerUsername, password = depotServerPassword)
							
							#self.writeStateFile()
							try:
								tempPackageContentFile = os.path.join(self._tempDir, u'%s.files' % productId)
								packageContentFile = u'%s/%s.files' % (productId, productId)
								logger.info(u"Downloading package content file '%s' of product '%s' from depot '%s'" % (packageContentFile, productId, repository))
								repository.download(source = packageContentFile, destination = tempPackageContentFile)
								
								packageContentFile = os.path.join(self._productCacheDir, productId, u'%s.files' % productId)
								if os.path.exists(packageContentFile) and (md5sum(tempPackageContentFile) == md5sum(packageContentFile)):
									logger.info(u"Package content file unchanged, assuming that product is up to date")
									self._state['product'][productId]['sync_completed'] = time.time()
									overallProgressSubject.addToState(1)
									repository = None
									continue
								
								packageInfo = PackageContentFile(tempPackageContentFile).parse()
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
							except Exception, e:
								logger.logException(e)
								logger.error("Failed to sync product '%s': %s" % (productId, forceUnicode(e)))
								errorsOccured.append( u'%s: %s' % (productId, forceUnicode(e)) )
								self._state['product'][productId]['sync_failure'] = forceUnicode(e)
							repository = None
							#self.writeStateFile()
							overallProgressSubject.addToState(1)
							self._configService.productOnClient_updateObjects([
								ProductOnClient(
									productId      = productId,
									productType    = u'LocalbootProduct',
									clientId       = config.get('global', 'host_id'),
									actionProgress = u'cached'
								)
							])
						
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
							
					except Exception, e:
						logger.logException(e)
						logger.error(u"Failed to cache products: %s" % forceUnicode(e))
					
					#self.writeStateFile()
					self._cacheProductsRunning = False
					self._cacheProductsEnded.set()
			
			except Exception, e:
				logger.logException(e)
			time.sleep(3)
			
		self._running = False
		

