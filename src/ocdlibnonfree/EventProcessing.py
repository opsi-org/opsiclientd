# -*- coding: utf-8 -*-
"""
ocdlibnonfree.EventProcessing

opsiclientd is part of the desktop management solution opsi
(open pc server integration) http://www.opsi.org

Copyright (C) 2010 uib GmbH

http://www.uib.de/

All rights reserved.

@copyright:	uib GmbH <info@uib.de>
@author: Jan Schneider <j.schneider@uib.de>
"""

# Imports
import base64
import filecmp
import os
import shutil
import sys
from hashlib import md5

# Twisted imports
from twisted.conch.ssh import keys

# OPSI imports
from OPSI.Logger import *
from OPSI.Util import *
from OPSI.Util.Message import *
from OPSI.Types import *
from OPSI import System
from OPSI.Object import *

from ocdlib.Exceptions import *
from ocdlib.Events import *
from ocdlib.OpsiService import ServiceConnection
if (os.name == 'nt'):
	from ocdlib.Windows import *
if (os.name == 'posix'):
	from ocdlib.Posix import *
from ocdlib.Localization import _, setLocaleDir, getLanguage
from ocdlib.Config import Config
import ocdlib.EventProcessing

logger = Logger()
config = Config()

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                      EVENT PROCESSING THREAD                                      -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
#class EventProcessingThread(ocdlib.EventProcessing.EventProcessingThread, ServiceConnection):
#
#
#	def connectConfigServer(self):
#
#
#		if self._configService:
#			# Already connected
#			return
#
#		try:
#			getSharedServiceConnection() # @TODO
#		finally:
#			self._detailSubjectProxy.setMessage(u'')
#
#
#				self._configService = serviceConnectionThread.configService
#				self._configServiceUrl = url
#
#				if (serviceConnectionThread.getUsername() != config.get('global', 'host_id')):
#					config.set('global', 'host_id', serviceConnectionThread.getUsername().lower())
#					logger.info(u"Updated host_id to '%s'" % config.get('global', 'host_id'))
#
#				if self.event.eventConfig.updateConfigFile:
#					self.setStatusMessage( _(u"Updating config file") )
#					config.updateConfigFile()
#
#		except Exception, e:
#			self.disconnectConfigServer()
#			raise
#
#
#
#	def run(self):
#		try:
#			logger.notice(u"============= EventProcessingThread for occurcence of event '%s' started =============" % self.event)
#			self.running = True
#			self.eventCancelled = False
#			self.waitCancelled = False
#			if not self.event.eventConfig.blockLogin:
#				self.opsiclientd.setBlockLogin(False)
#
#			# Store current config service url and depot url
#			configServiceUrls = config.get('config_service', 'url')
#			depotServerUrl = config.get('depot_server', 'url')
#			depotDrive = config.get('depot_server', 'drive')
#			try:
#				self.startNotificationServer()
#				self.setActionProcessorInfo()
#
#				if self.event.eventConfig.useCachedConfig:
#					# Event needs cached config => initialize cache service
#					if self.opsiclientd._cacheService.getConfigSyncCompleted():
#						logger.notice(u"Event '%s' requires cached config and config sync is done" % self.event)
#						#########self.opsiclientd._cacheService.workWithLocalConfig()
#						cacheConfigServiceUrl = 'https://127.0.0.1:%s/rpc' % config.get('control_server', 'port')
#						logger.notice(u"Setting config service url to cache service url '%s'" % cacheConfigServiceUrl)
#						config.set('config_service', 'url', [ cacheConfigServiceUrl ])
#					else:
#						logger.notice(u"Event '%s' requires cached config but config sync is not done, exiting" % self.event)
#						self.running = False
#						return
#
#				self._messageSubject.setMessage(self.event.eventConfig.getActionMessage())
#				if self.event.eventConfig.warningTime:
#					choiceSubject = ChoiceSubject(id = 'choice')
#					if (self.event.eventConfig.cancelCounter < self.event.eventConfig.actionUserCancelable):
#						choiceSubject.setChoices([ _('Abort'), _('Start now') ])
#						choiceSubject.setCallbacks( [ self.abortEventCallback, self.startEventCallback ] )
#					else:
#						choiceSubject.setChoices([ _('Start now') ])
#						choiceSubject.setCallbacks( [ self.startEventCallback ] )
#					self._notificationServer.addSubject(choiceSubject)
#					try:
#						if self.event.eventConfig.eventNotifierCommand:
#							self.startNotifierApplication(
#									command      = self.event.eventConfig.eventNotifierCommand,
#									desktop      = self.event.eventConfig.eventNotifierDesktop )
#
#						timeout = int(self.event.eventConfig.warningTime)
#						endTime = time.time() + timeout
#						while (timeout > 0) and not self.eventCancelled and not self.waitCancelled:
#							now = time.time()
#							logger.info(u"Notifying user of event %s" % self.event)
#							self.setStatusMessage(_(u"Event %s: processing will start in %0.0f seconds") % (self.event.eventConfig.getName(), (endTime - now)))
#							if ((endTime - now) <= 0):
#								break
#							time.sleep(1)
#
#						if self.eventCancelled:
#							self.event.eventConfig.cancelCounter += 1
#							config.set('event_%s' % self.event.eventConfig.getName(), 'cancel_counter', self.event.eventConfig.cancelCounter)
#							config.updateConfigFile()
#							logger.notice(u"Event cancelled by user for the %d. time (max: %d)" \
#								% (self.event.eventConfig.cancelCounter, self.event.eventConfig.actionUserCancelable))
#							raise CanceledByUserError(u"Event cancelled by user")
#						else:
#							self.event.eventConfig.cancelCounter = 0
#							config.set('event_%s' % self.event.eventConfig.getName(), 'cancel_counter', self.event.eventConfig.cancelCounter)
#							config.updateConfigFile()
#					finally:
#						try:
#							if self._notificationServer:
#								self._notificationServer.requestEndConnections()
#								self._notificationServer.removeSubject(choiceSubject)
#						except Exception, e:
#							logger.logException(e)
#
#				self.setStatusMessage(_(u"Processing event %s") % self.event.eventConfig.getName())
#
#				if self.event.eventConfig.blockLogin:
#					self.opsiclientd.setBlockLogin(True)
#				else:
#					self.opsiclientd.setBlockLogin(False)
#				if self.event.eventConfig.logoffCurrentUser:
#					System.logoffCurrentUser()
#					time.sleep(15)
#				elif self.event.eventConfig.lockWorkstation:
#					System.lockWorkstation()
#					time.sleep(15)
#
#				if self.event.eventConfig.actionNotifierCommand:
#					self.startNotifierApplication(
#						command      = self.event.eventConfig.actionNotifierCommand,
#						desktop      = self.event.eventConfig.actionNotifierDesktop )
#
#				self.connectConfigServer()
#
#				if self.event.eventConfig.getConfigFromService:
#					self.getConfigFromService()
#				if self.event.eventConfig.updateConfigFile:
#					config.updateConfigFile()
#
#				if (self.event.eventConfig.actionType == 'login'):
#					self.processUserLoginActions()
#				else:
#					self.processProductActionRequests()
#
#			finally:
#				self._messageSubject.setMessage(u"")
#
#				if self.event.eventConfig.writeLogToService:
#					try:
#						self.writeLogToService()
#					except Exception, e:
#						logger.logException(e)
#
#				try:
#					# Disconnect has to be called, even if connect failed!
#					self.disconnectConfigServer()
#				except Exception, e:
#					logger.logException(e)
#
#				if self.event.eventConfig.processShutdownRequests:
#					try:
#						reboot   = self.opsiclientd.isRebootRequested()
#						shutdown = self.opsiclientd.isShutdownRequested()
#						if reboot or shutdown:
#							if reboot:
#								self.setStatusMessage(_(u"Reboot requested"))
#							else:
#								self.setStatusMessage(_(u"Shutdown requested"))
#
#							if self.event.eventConfig.shutdownWarningTime:
#								while True:
#									if reboot:
#										logger.info(u"Notifying user of reboot")
#									else:
#										logger.info(u"Notifying user of shutdown")
#
#									self.shutdownCancelled = False
#									self.shutdownWaitCancelled = False
#
#									self._messageSubject.setMessage(self.event.eventConfig.getShutdownWarningMessage())
#
#									choiceSubject = ChoiceSubject(id = 'choice')
#									if (self.event.eventConfig.shutdownCancelCounter < self.event.eventConfig.shutdownUserCancelable):
#										if reboot:
#											choiceSubject.setChoices([ _('Reboot now'), _('Later') ])
#										else:
#											choiceSubject.setChoices([ _('Shutdown now'), _('Later') ])
#										choiceSubject.setCallbacks( [ self.startShutdownCallback, self.abortShutdownCallback ] )
#									else:
#										if reboot:
#											choiceSubject.setChoices([ _('Reboot now') ])
#										else:
#											choiceSubject.setChoices([ _('Shutdown now') ])
#										choiceSubject.setCallbacks( [ self.startShutdownCallback ] )
#									self._notificationServer.addSubject(choiceSubject)
#
#									if self.event.eventConfig.shutdownNotifierCommand:
#										self.startNotifierApplication(
#												command      = self.event.eventConfig.shutdownNotifierCommand,
#												desktop      = self.event.eventConfig.shutdownNotifierDesktop )
#
#									timeout = int(self.event.eventConfig.shutdownWarningTime)
#									endTime = time.time() + timeout
#									while (timeout > 0) and not self.shutdownCancelled and not self.shutdownWaitCancelled:
#										now = time.time()
#										if reboot:
#											self.setStatusMessage(_(u"Reboot in %0.0f seconds") % (endTime - now))
#										else:
#											self.setStatusMessage(_(u"Shutdown in %0.0f seconds") % (endTime - now))
#										if ((endTime - now) <= 0):
#											break
#										time.sleep(1)
#
#									try:
#										if self._notificationServer:
#											self._notificationServer.requestEndConnections()
#											self._notificationServer.removeSubject(choiceSubject)
#									except Exception, e:
#										logger.logException(e)
#
#									self._messageSubject.setMessage(u"")
#									if self.shutdownCancelled:
#										self.event.eventConfig.shutdownCancelCounter += 1
#										logger.notice(u"Shutdown cancelled by user for the %d. time (max: %d)" \
#											% (self.event.eventConfig.shutdownCancelCounter, self.event.eventConfig.shutdownUserCancelable))
#
#										if (self.event.eventConfig.shutdownWarningRepetitionTime >= 0):
#											logger.info(u"Shutdown warning will be repeated in %d seconds" % self.event.eventConfig.shutdownWarningRepetitionTime)
#											time.sleep(self.event.eventConfig.shutdownWarningRepetitionTime)
#											continue
#									break
#							if reboot:
#								self.opsiclientd.rebootMachine()
#							elif shutdown:
#								self.opsiclientd.shutdownMachine()
#					except Exception, e:
#						logger.logException(e)
#
#				if self.opsiclientd.isShutdownTriggered():
#					self.setStatusMessage(_("Shutting down machine"))
#				elif self.opsiclientd.isRebootTriggered():
#					self.setStatusMessage(_("Rebooting machine"))
#				else:
#					self.setStatusMessage(_("Unblocking login"))
#
#				if not self.opsiclientd.isRebootTriggered() and not self.opsiclientd.isShutdownTriggered():
#					self.opsiclientd.setBlockLogin(False)
#
#				self.setStatusMessage(u"")
#
#				if self.event.eventConfig.useCachedConfig:
#					# Set config service url back to previous url
#					logger.notice(u"Setting config service url back to %s" % configServiceUrls)
#					config.set('config_service', 'url', configServiceUrls)
#					logger.notice("Setting depot server url back to '%s'" % depotServerUrl)
#					config.set('depot_server', 'url', depotServerUrl)
#					logger.notice(u"Setting depot drive back to '%s'" % depotDrive)
#					config.set('depot_server', 'drive', depotDrive)
#
#				# Stop notification server thread
#				if self._notificationServer:
#					try:
#						logger.info(u"Stopping notification server")
#						self._notificationServer.stop(stopReactor = False)
#					except Exception, e:
#						logger.logException(e)
#		except Exception, e:
#			logger.error(u"Failed to process event %s: %s" % (self.event, forceUnicode(e)))
#			logger.logException(e)
#			self.opsiclientd.setBlockLogin(False)
#
#		self.running = False
#		logger.notice(u"============= EventProcessingThread for event '%s' ended =============" % self.event)
#
#	def processProductActionRequests(self):
#		self.setStatusMessage(_(u"Getting action requests from config service"))
#
#		try:
#			bootmode = ''
#			try:
#				bootmode = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\general", "bootmode")
#			except Exception, e:
#				logger.warning(u"Failed to get bootmode from registry: %s" % forceUnicode(e))
#
#			if not self._configService:
#				raise Exception(u"Not connected to config service")
#
#			productIds = []
#			if self._configService.isLegacyOpsi():
#				productStates = []
#				if (self._configService.getLocalBootProductStates_hash.func_code.co_argcount == 2):
#					if self.event.eventConfig.serviceOptions:
#						logger.warning(u"Service cannot handle service options in method getLocalBootProductStates_hash")
#					productStates = self._configService.getLocalBootProductStates_hash(config.get('global', 'host_id'))
#					productStates = productStates.get(config.get('global', 'host_id'), [])
#				else:
#					productStates = self._configService.getLocalBootProductStates_hash(
#								config.get('global', 'host_id'),
#								self.event.eventConfig.serviceOptions )
#					productStates = productStates.get(config.get('global', 'host_id'), [])
#
#				logger.notice(u"Got product action requests from configservice")
#
#				for productState in productStates:
#					if (productState['actionRequest'] not in ('none', 'undefined')):
#						productIds.append(productState['productId'])
#						logger.notice("   [%2s] product %-20s %s" % (len(productIds), productState['productId'] + ':', productState['actionRequest']))
#			else:
#				for productOnClient in self._configService.productOnClient_getObjects(
#							productType   = 'LocalbootProduct',
#							clientId      = config.get('global', 'host_id'),
#							actionRequest = ['setup', 'uninstall', 'update', 'always', 'once', 'custom'],
#							attributes    = ['actionRequest']):
#					if not productOnClient.productId in productIds:
#						productIds.append(productOnClient.productId)
#						logger.notice("   [%2s] product %-20s %s" % (len(productIds), productOnClient.productId + u':', productOnClient.actionRequest))
#
#			if (len(productIds) == 0) and (bootmode == 'BKSTD'):
#				logger.notice(u"No product action requests set")
#				self.setStatusMessage( _(u"No product action requests set") )
#
#			else:
#				logger.notice(u"Start processing action requests")
#
#				#if not self.event.eventConfig.useCachedConfig and self.event.eventConfig.syncConfig:
#				#	logger.notice(u"Syncing config (products: %s)" % productIds)
#				#	self._cacheService.init()
#				#	self.setStatusMessage( _(u"Syncing config") )
#				#	self._cacheService.setCurrentConfigProgressObserver(self._currentProgressSubjectProxy)
#				#	self._cacheService.setOverallConfigProgressObserver(self._overallProgressSubjectProxy)
#				#	self._cacheService.syncConfig(productIds = productIds, waitForEnding = True)
#				#	self.setStatusMessage( _(u"Config synced") )
#				#	self._currentProgressSubjectProxy.setState(0)
#				#	self._overallProgressSubjectProxy.setState(0)
#
#				if self.event.eventConfig.cacheProducts:
#					logger.notice(u"Caching products: %s" % productIds)
#					self.setStatusMessage( _(u"Caching products") )
#					self.opsiclientd._cacheService.setCurrentProductSyncProgressObserver(self._currentProgressSubjectProxy)
#					self.opsiclientd._cacheService.setOverallProductSyncProgressObserver(self._overallProgressSubjectProxy)
#					self._currentProgressSubjectProxy.attachObserver(self._detailSubjectProxy)
#					try:
#						self.opsiclientd._cacheService.cacheProducts(
#							self._configService,
#							productIds,
#							waitForEnding = self.event.eventConfig.requiresCachedProducts)
#						self.setStatusMessage( _(u"Products cached") )
#					finally:
#						self._detailSubjectProxy.setMessage(u"")
#						self._currentProgressSubjectProxy.detachObserver(self._detailSubjectProxy)
#						self._currentProgressSubjectProxy.reset()
#						self._overallProgressSubjectProxy.reset()
#				else:
#					config.selectDepotserver(configService = self._configService, productIds = productIds)
#
#				savedDepotUrl = None
#				savedDepotDrive = None
#				if self.event.eventConfig.requiresCachedProducts:
#					# Event needs cached products => initialize cache service
#					if self.opsiclientd._cacheService.getProductSyncCompleted():
#						logger.notice(u"Event '%s' requires cached products and product sync is done" % self.event.eventConfig.getName())
#						savedDepotUrl = config.get('depot_server', 'url')
#						savedDepotDrive = config.get('depot_server', 'drive')
#						cacheDepotDir = self.opsiclientd._cacheService.getProductCacheDir().replace('\\', '/').replace('//', '/')
#						cacheDepotDrive = cacheDepotDir.split('/')[0]
#						cacheDepotUrl = 'smb://localhost/noshare/' + ('/'.join(cacheDepotDir.split('/')[1:]))
#						config.set('depot_server', 'url', cacheDepotUrl)
#						config.set('depot_server', 'drive', cacheDepotDrive)
#					else:
#						raise Exception(u"Event '%s' requires cached products but product sync is not done, exiting" % self.event.eventConfig.getName())
#
#				try:
#					self.runActions()
#				finally:
#					if savedDepotUrl:
#						config.set('depot_server', 'url', savedDepotUrl)
#					if savedDepotDrive:
#						config.set('depot_server', 'drive', savedDepotDrive)
#
#		except Exception, e:
#			logger.logException(e)
#			logger.error(u"Failed to process product action requests: %s" % forceUnicode(e))
#			self.setStatusMessage( _(u"Failed to process product action requests: %s") % forceUnicode(e) )
#
#		time.sleep(3)
