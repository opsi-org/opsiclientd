# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org

# Copyright (C) 2019 uib GmbH <info@uib.de>
# http://www.uib.de/
# All rights reserved.
"""
Cache-Backend for Clients.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:author: Erol Ueluekmen <e.ueluekmen@uib.de>
:author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU Affero General Public License version 3
"""

import codecs
import collections
import inspect
import json
import time
from types import MethodType

from OPSI.Backend.Backend import (
	getArgAndCallString, Backend, ConfigDataBackend, ModificationTrackingBackend)
from OPSI.Backend.Replicator import BackendReplicator
from OPSI.Exceptions import (
	BackendConfigurationError, BackendUnaccomplishableError)
from opsicommon.logging import logger
from OPSI.Object import getIdentAttributes, objectsDiffer
from OPSI.Object import LicenseOnClient, ProductOnClient
from OPSI.Object import *  # required for dynamic class loading
from OPSI.Types import forceHostId
from OPSI.Util import blowfishDecrypt

from opsiclientd.Config import Config

__all__ = ['ClientCacheBackend']

config = Config()


class ClientCacheBackend(ConfigDataBackend, ModificationTrackingBackend):

	def __init__(self, **kwargs):
		ConfigDataBackend.__init__(self, **kwargs)

		self._workBackend = None
		self._masterBackend = None
		self._snapshotBackend = None
		self._clientId = None
		self._depotId = None
		self._backendChangeListeners = []

		for (option, value) in kwargs.items():
			option = option.lower()
			if option == 'workbackend':
				self._workBackend = value
			elif option == 'snapshotbackend':
				self._snapshotBackend = value
			elif option == 'masterbackend':
				self._masterBackend = value
			elif option == 'clientid':
				self._clientId = forceHostId(value)
			elif option == 'depotid':
				self._depotId = forceHostId(value)
			elif option == 'backendinfo':
				self._backendInfo = value

		if not self._workBackend:
			raise BackendConfigurationError(u"Work backend undefined")
		if not self._snapshotBackend:
			raise BackendConfigurationError(u"Snapshot backend undefined")
		if not self._clientId:
			raise BackendConfigurationError(u"Client id undefined")
		if not self._depotId:
			raise BackendConfigurationError(u"Depot id undefined")

		self._workBackend._setContext(self)
		self._backend = self._workBackend
		self._createInstanceMethods()

	def log_write(self, logType, data, objectId=None, append=False):
		pass

	def licenseOnClient_getObjects(self, attributes=[], **filter):
		licenseOnClients = self._workBackend.licenseOnClient_getObjects(attributes, **filter)
		for licenseOnClient in licenseOnClients:
			# Recreate for later sync to server
			self.licenseOnClient_insertObject(licenseOnClient)
		return licenseOnClients

	def _setMasterBackend(self, masterBackend):
		self._masterBackend = masterBackend

	def _syncModifiedObjectsWithMaster(self, objectClass, modifiedObjects, getFilter, objectsDifferFunction, createUpdateObjectFunction, mergeObjectsFunction):
		meth = getattr(self._masterBackend, '%s_getObjects' % objectClass.backendMethodPrefix)
		masterObjects = {obj.getIdent(): obj for obj in meth(**getFilter)}

		deleteObjects = []
		updateObjects = []
		for mo in modifiedObjects:
			logger.debug("Processing modified object: %s", mo)
			masterObj = masterObjects.get(mo['object'].getIdent())

			command = mo['command'].lower()
			if command == 'delete':
				if not masterObj:
					logger.info(u"No need to delete object %s because object has been deleted on server since last sync" % mo['object'])
					continue

				meth = getattr(self._snapshotBackend, '%s_getObjects' % objectClass.backendMethodPrefix)
				snapshotObj = meth(**(mo['object'].getIdent(returnType='dict')))
				if not snapshotObj:
					logger.info(u"Deletion of object %s prevented because object has been created on server since last sync" % mo['object'])
					continue

				snapshotObj = snapshotObj[0]
				if objectsDifferFunction(snapshotObj, masterObj):
					logger.info(u"Deletion of object %s prevented because object has been modified on server since last sync" % mo['object'])
					continue

				logger.debug(u"Object %s marked for deletion" % mo['object'])
				deleteObjects.append(mo['object'])
			elif command in ('update', 'insert'):
				logger.debug(u"Modified object: %s" % mo['object'].toHash())
				updateObj = createUpdateObjectFunction(mo['object'])

				if masterObj:
					logger.debug(u"Master object: %s" % masterObj.toHash())
					meth = getattr(self._snapshotBackend, '%s_getObjects' % objectClass.backendMethodPrefix)
					snapshotObj = meth(**(updateObj.getIdent(returnType='dict')))
					if snapshotObj:
						snapshotObj = snapshotObj[0]
						logger.debug(u"Snapshot object: %s" % snapshotObj.toHash())
						updateObj = mergeObjectsFunction(snapshotObj, updateObj, masterObj, self._snapshotBackend, self._workBackend, self._masterBackend)

				if updateObj:
					logger.debug(u"Object %s marked for update" % mo['object'])
					updateObjects.append(updateObj)

		if deleteObjects:
			meth = getattr(self._masterBackend, '%s_deleteObjects' % objectClass.backendMethodPrefix)
			meth(deleteObjects)

		if updateObjects:
			meth = getattr(self._masterBackend, '%s_updateObjects' % objectClass.backendMethodPrefix)
			meth(updateObjects)

	def _updateMasterFromWorkBackend(self, modifications=[]):
		modifiedObjects = collections.defaultdict(list)
		logger.info("Updating master from work backend (%d modifications)", len(modifications))

		for modification in modifications:
			try:
				ObjectClass = eval(modification['objectClass'])
				identValues = modification['ident'].split(ObjectClass.identSeparator)
				identAttributes = getIdentAttributes(ObjectClass)
				objectFilter = {}
				for index, attribute in enumerate(identAttributes):
					if index >= len(identValues):
						raise BackendUnaccomplishableError(u"Bad ident '%s' for objectClass '%s'" % (identValues, modification['objectClass']))

					objectFilter[attribute] = identValues[index]

				meth = getattr(self._workBackend, ObjectClass.backendMethodPrefix + '_getObjects')
				modification['object'] = meth(**objectFilter)[0]
				modifiedObjects[modification['objectClass']].append(modification)
			except Exception as modifyError:
				logger.error(u"Failed to sync backend modification %s: %s" % (modification, modifyError))
				continue

		if 'AuditHardwareOnHost' in modifiedObjects:
			self._masterBackend.auditHardwareOnHost_setObsolete(self._clientId)
			self._masterBackend.auditHardwareOnHost_updateObjects([mo['object'] for mo in modifiedObjects['AuditHardwareOnHost']])

		if 'AuditSoftware' in modifiedObjects:
			self._masterBackend.auditSoftware_updateObjects([mo['object'] for mo in modifiedObjects['AuditSoftware']])

		if 'AuditSoftwareOnClient' in modifiedObjects:
			self._masterBackend.auditSoftwareOnClient_setObsolete(self._clientId)
			self._masterBackend.auditSoftwareOnClient_updateObjects(
				[mo['object'] for mo in modifiedObjects['AuditSoftwareOnClient']]
			)

		if 'ProductOnClient' in modifiedObjects:
			def objectsDifferFunction(snapshotObj, masterObj):
				return objectsDiffer(snapshotObj, masterObj, excludeAttributes=['modificationTime', 'actionProgress', 'actionResult', 'lastAction'])

			def createUpdateObjectFunction(modifiedObj):
				return modifiedObj.clone(identOnly=False)

			def mergeObjectsFunction(snapshotObj, updateObj, masterObj, snapshotBackend, workBackend, masterBackend):
				masterVersions = sorted([
					f"{p.productVersion}-{p.packageVersion}" for p in
					masterBackend.product_getObjects(["productVersion", "packageVersion"], id=snapshotObj.productId)
				])
				snapshotVersions = sorted([
					f"{p.productVersion}-{p.packageVersion}" for p in
					snapshotBackend.product_getObjects(["productVersion", "packageVersion"], id=snapshotObj.productId)
				])
				
				logger.info("Syncing ProductOnClient %s (product versions local=%s, server=%s)",
					updateObj, snapshotVersions, masterVersions
				)
				if snapshotVersions != masterVersions:
					logger.notice("Product %s changed on server since last sync, not updating actionRequest (local=%s, server=%s)",
						snapshotObj.productId, snapshotVersions, masterVersions
					)
					updateObj.actionRequest = None
					updateObj.targetConfiguration = None
				return updateObj

			logger.debug("Syncing modified ProductOnClients with master: %s", modifiedObjects['ProductOnClient'])
			self._syncModifiedObjectsWithMaster(
				ProductOnClient,
				modifiedObjects['ProductOnClient'],
				{"clientId": self._clientId},
				objectsDifferFunction,
				createUpdateObjectFunction,
				mergeObjectsFunction
			)

		if 'LicenseOnClient' in modifiedObjects:
			def objectsDifferFunction(snapshotObj, masterObj):
				return objectsDiffer(snapshotObj, masterObj)

			def createUpdateObjectFunction(modifiedObj):
				return modifiedObj.clone(identOnly=False)

			def mergeObjectsFunction(snapshotObj, updateObj, masterObj, snapshotBackend, workBackend, masterBackend):
				return updateObj

			self._syncModifiedObjectsWithMaster(
				LicenseOnClient,
				modifiedObjects['LicenseOnClient'],
				{"clientId": self._clientId},
				objectsDifferFunction,
				createUpdateObjectFunction,
				mergeObjectsFunction
			)

		for objectClassName in ('ProductPropertyState', 'ConfigState'):
			def objectsDifferFunction(snapshotObj, masterObj):
				return objectsDiffer(snapshotObj, masterObj)

			def createUpdateObjectFunction(modifiedObj):
				return modifiedObj.clone()

			def mergeObjectsFunction(snapshotObj, updateObj, masterObj, snapshotBackend, workBackend, masterBackend):
				if len(snapshotObj.values) != len(masterObj.values):
					logger.info(u"Values of %s changed on server since last sync, not updating values" % snapshotObj)
					return None

				if snapshotObj.values:
					for v in snapshotObj.values:
						if v not in masterObj.values:
							logger.info(u"Values of %s changed on server since last sync, not updating values" % snapshotObj)
							return None

				if masterObj.values:
					for v in masterObj.values:
						if v not in snapshotObj.values:
							logger.info(u"Values of %s changed on server since last sync, not updating values" % snapshotObj)
							return None

				return updateObj

			if objectClassName in modifiedObjects:
				self._syncModifiedObjectsWithMaster(
					eval(objectClassName),
					modifiedObjects[objectClassName],
					{"objectId": self._clientId},
					objectsDifferFunction,
					createUpdateObjectFunction,
					mergeObjectsFunction
				)

	def _replicateMasterToWorkBackend(self):
		if not self._masterBackend:
			raise BackendConfigurationError(u"Master backend undefined")

		self._cacheBackendInfo(self._masterBackend.backend_info())

		self._workBackend.backend_deleteBase()
		self._workBackend.backend_createBase()
		br = BackendReplicator(
			readBackend=self._masterBackend,
			writeBackend=self._workBackend
		)
		br.replicate(
			serverIds=[],
			depotIds=[self._depotId],
			clientIds=[self._clientId],
			groupIds=[],
			productIds=[],
			productTypes=['LocalbootProduct'],
			audit=False,
			licenses=False
		)

		self._snapshotBackend.backend_deleteBase()

		licenseOnClients = self._masterBackend.licenseOnClient_getObjects(clientId=self._clientId)
		for productOnClient in self._workBackend.productOnClient_getObjects(clientId=self._clientId):
			if productOnClient.actionRequest in (None, 'none'):
				continue

			licensePools = self._masterBackend.licensePool_getObjects(productIds=[productOnClient.productId])
			if not licensePools:
				logger.debug(u"No license pool found for product '%s'" % productOnClient.productId)
				continue

			licensePool = licensePools[0]
			try:
				for loc in licenseOnClients:
					if loc.licensePoolId == licensePool.id:
						licenseOnClient = loc
						logger.notice(u"Reusing existing licenseOnClient '%s'" % licenseOnClient)
						break
				else:
					logger.notice(u"Acquiring license for product '%s'" % productOnClient.productId)
					licenseOnClient = self._masterBackend.licenseOnClient_getOrCreateObject(
						clientId=self._clientId,
						productId=productOnClient.productId
					)

					# Fake deletion for later sync to server
					self._fireEvent('objectsDeleted', [licenseOnClient])
					self._fireEvent('backendModified')

				for licensePool in self._masterBackend.licensePool_getObjects(id=licenseOnClient.licensePoolId):
					self._workBackend.licensePool_insertObject(licensePool)

				for softwareLicense in self._masterBackend.softwareLicense_getObjects(id=licenseOnClient.softwareLicenseId):
					for licenseContract in self._masterBackend.licenseContract_getObjects(id=softwareLicense.licenseContractId):
						self._workBackend.licenseContract_insertObject(licenseContract)

					self._workBackend.softwareLicense_insertObject(softwareLicense)

				self._workBackend.licenseOnClient_insertObject(licenseOnClient)
			except Exception as licenseSyncError:
				logger.error(u"Failed to acquire license for product '%s': %s" % (productOnClient.productId, licenseSyncError))

		self._snapshotBackend.backend_createBase()
		br = BackendReplicator(
			readBackend=self._workBackend,
			writeBackend=self._snapshotBackend
		)
		br.replicate()

		if self._clientId != config.get('global', 'host_id'):
			logger.error(
				"Client id '%s' does not match config global.host_id '%s'",
				self._clientId, config.get('global', 'host_id')
			)
		opsiHostKey = self._workBackend.host_getObjects(id=self._clientId)[0].getOpsiHostKey()
		if opsiHostKey != config.get('global', 'opsi_host_key'):
			logger.error(
				"Host key '%s' from work backend does not match config global.opsi_host_key '%s'",
				opsiHostKey, config.get('global', 'opsi_host_key')
			)
		
		password = self._masterBackend.user_getCredentials(
			username='pcpatch',
			hostId=self._clientId
		)
		password = password['password']
		logger.notice("Creating opsi passwd file '%s' using opsi host key '%s...'",
			self._opsiPasswdFile, opsiHostKey[:10]
		)
		self.user_setCredentials(
			username='pcpatch',
			password=blowfishDecrypt(opsiHostKey, password)
		)
		auditHardwareConfig = self._masterBackend.auditHardware_getConfig()
		with codecs.open(self._auditHardwareConfigFile, 'w', 'utf8') as f:
			f.write(json.dumps(auditHardwareConfig))

		self._workBackend._setAuditHardwareConfig(auditHardwareConfig)
		self._workBackend.backend_createBase()

	def _createInstanceMethods(self):
		for Class in (Backend, ConfigDataBackend):
			for methodName, funcRef in inspect.getmembers(Class, inspect.isfunction):
				if methodName.startswith('_') or methodName in ('backend_info', 'user_getCredentials', 'user_setCredentials', 'log_write', 'licenseOnClient_getObjects'):
					continue

				(argString, callString) = getArgAndCallString(funcRef)

				logger.debug2(u"Adding method '%s' to execute on work backend" % methodName)
				exec(u'def %s(self, %s): return self._executeMethod("%s", %s)' % (methodName, argString, methodName, callString))
				setattr(self, methodName, MethodType(eval(methodName), self))

	def _cacheBackendInfo(self, backendInfo):
		with codecs.open(self._opsiModulesFile, 'w', 'utf-8') as f:
			modules = backendInfo['modules']
			helpermodules = backendInfo['realmodules']
			for (module, state) in modules.items():
				if helpermodules in ('customer', 'expires'):
					continue
				if module in helpermodules:
					state = helpermodules[module]
				else:
					if state:
						state = 'yes'
					else:
						state = 'no'
				f.write('%s = %s\n' % (module.lower(), state))
			f.write('customer = %s\n' % modules.get('customer', ''))
			f.write('expires = %s\n' % modules.get('expires', time.strftime("%Y-%m-%d", time.localtime(time.time()))))
			f.write('signature = %s\n' % modules.get('signature', ''))
