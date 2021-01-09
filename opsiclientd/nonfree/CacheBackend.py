# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org

# Copyright (C) 2019 uib GmbH <info@uib.de>
# http://www.uib.de/
# All rights reserved.
"""
Cache-Backend for Clients.

:copyright: uib GmbH <info@uib.de>
:license: GNU Affero General Public License version 3
"""

import codecs
import collections
import inspect
import json
import time
from types import MethodType

from OPSI.Backend.Backend import (
	getArgAndCallString, Backend, ConfigDataBackend, ModificationTrackingBackend
)
from OPSI.Backend.Replicator import BackendReplicator
from OPSI.Exceptions import (
	BackendConfigurationError, BackendUnaccomplishableError
)
from OPSI.Object import (
	getIdentAttributes, objectsDiffer, LicenseOnClient, ProductOnClient
)
from OPSI.Object import * # required for dynamic class loading # pylint: disable=wildcard-import,unused-wildcard-import
from OPSI.Types import forceHostId
from OPSI.Util import blowfishDecrypt

from opsicommon.logging import logger

from opsiclientd.Config import Config

__all__ = ['ClientCacheBackend']

config = Config()


class ClientCacheBackend(ConfigDataBackend, ModificationTrackingBackend): # pylint: disable=too-many-instance-attributes

	def __init__(self, **kwargs): # pylint: disable=super-init-not-called
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
		self._backend.configState_getClientToDepotserver = self.configState_getClientToDepotserver

	def log_write(self, logType, data, objectId=None, append=False):
		pass

	def licenseOnClient_getObjects(self, attributes=[], **filter): # pylint: disable=dangerous-default-value,redefined-builtin
		licenseOnClients = self._workBackend.licenseOnClient_getObjects(attributes, **filter)
		for licenseOnClient in licenseOnClients:
			# Recreate for later sync to server
			self.licenseOnClient_insertObject(licenseOnClient)
		return licenseOnClients

	def configState_getClientToDepotserver(self, depotIds=[], clientIds=[], masterOnly=True, productIds=[]): # pylint: disable=dangerous-default-value,unused-argument
		result = [{
			'depotId': self._depotId,
			'clientId': self._clientId,
			'alternativeDepotIds': []
		}]
		logger.info("configState_getClientToDepotserver returning %s", result)
		return result

	def _setMasterBackend(self, masterBackend):
		self._masterBackend = masterBackend

	def _syncModifiedObjectsWithMaster( # pylint: disable=too-many-arguments,too-many-locals
		self, objectClass, modifiedObjects, getFilter, objectsDifferFunction, createUpdateObjectFunction, mergeObjectsFunction
	):
		meth = getattr(self._masterBackend, f'{objectClass.backendMethodPrefix}_getObjects')
		masterObjects = {obj.getIdent(): obj for obj in meth(**getFilter)}

		deleteObjects = []
		updateObjects = []
		for mo in modifiedObjects:
			logger.debug("Processing modified object: %s", mo)
			masterObj = masterObjects.get(mo['object'].getIdent())

			command = mo['command'].lower()
			if command == 'delete':
				if not masterObj:
					logger.info("No need to delete object %s because object has been deleted on server since last sync", mo['object'])
					continue

				meth = getattr(self._snapshotBackend, '%s_getObjects' % objectClass.backendMethodPrefix)
				snapshotObj = meth(**(mo['object'].getIdent(returnType='dict')))
				if not snapshotObj:
					logger.info("Deletion of object %s prevented because object has been created on server since last sync", mo['object'])
					continue

				snapshotObj = snapshotObj[0]
				if objectsDifferFunction(snapshotObj, masterObj):
					logger.info("Deletion of object %s prevented because object has been modified on server since last sync", mo['object'])
					continue

				logger.debug("Object %s marked for deletion", mo['object'])
				deleteObjects.append(mo['object'])
			elif command in ('update', 'insert'):
				logger.debug("Modified object: %s", mo['object'].toHash())
				updateObj = createUpdateObjectFunction(mo['object'])

				if masterObj:
					logger.debug("Master object: %s", masterObj.toHash())
					meth = getattr(self._snapshotBackend, f'{objectClass.backendMethodPrefix}_getObjects')
					snapshotObj = meth(**(updateObj.getIdent(returnType='dict')))
					if snapshotObj:
						snapshotObj = snapshotObj[0]
						logger.debug("Snapshot object: %s", snapshotObj.toHash())
						updateObj = mergeObjectsFunction(snapshotObj, updateObj, masterObj, self._snapshotBackend, self._workBackend, self._masterBackend)

				if updateObj:
					logger.debug("Object %s marked for update", mo['object'])
					updateObjects.append(updateObj)

		if deleteObjects:
			meth = getattr(self._masterBackend, f'{objectClass.backendMethodPrefix}_deleteObjects')
			meth(deleteObjects)

		if updateObjects:
			meth = getattr(self._masterBackend, f'{objectClass.backendMethodPrefix}_updateObjects')
			meth(updateObjects)

	def _updateMasterFromWorkBackend(self, modifications=[]): # pylint: disable=dangerous-default-value,too-many-locals
		modifiedObjects = collections.defaultdict(list)
		logger.info("Updating master from work backend (%d modifications)", len(modifications))

		for modification in modifications:
			try:
				ObjectClass = eval(modification['objectClass']) # pylint: disable=eval-used
				identValues = modification['ident'].split(ObjectClass.identSeparator)
				identAttributes = getIdentAttributes(ObjectClass)
				objectFilter = {}
				for index, attribute in enumerate(identAttributes):
					if index >= len(identValues):
						raise BackendUnaccomplishableError(u"Bad ident '%s' for objectClass '%s'" % (identValues, modification['objectClass']))

					objectFilter[attribute] = identValues[index]

				meth = getattr(self._workBackend, ObjectClass.backendMethodPrefix + '_getObjects')
				objects = meth(**objectFilter)
				if objects:
					modification['object'] = objects[0]
					modifiedObjects[modification['objectClass']].append(modification)
			except Exception as modify_error: # pylint: disable=broad-except
				logger.error("Failed to sync backend modification %s: %s", modification, modify_error, exc_info=True)
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

			def mergeObjectsFunction(snapshotObj, updateObj, masterObj, snapshotBackend, workBackend, masterBackend): # pylint: disable=unused-argument,too-many-arguments
				masterVersions = sorted([
					f"{p.productVersion}-{p.packageVersion}" for p in
					masterBackend.productOnDepot_getObjects(
						["productVersion", "packageVersion"],
						productId=snapshotObj.productId,
						depotId=self._depotId
					)
				])
				snapshotVersions = sorted([
					f"{p.productVersion}-{p.packageVersion}" for p in
					snapshotBackend.productOnDepot_getObjects(
						["productVersion", "packageVersion"],
						productId=snapshotObj.productId,
						depotId=self._depotId
					)
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
			def objectsDifferFunction(snapshotObj, masterObj): # pylint: disable=function-redefined
				return objectsDiffer(snapshotObj, masterObj)

			def createUpdateObjectFunction(modifiedObj): # pylint: disable=function-redefined
				return modifiedObj.clone(identOnly=False)

			def mergeObjectsFunction(snapshotObj, updateObj, masterObj, snapshotBackend, workBackend, masterBackend): # pylint: disable=function-redefined,unused-argument,too-many-arguments
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
			def objectsDifferFunction(snapshotObj, masterObj): # pylint: disable=function-redefined
				return objectsDiffer(snapshotObj, masterObj)

			def createUpdateObjectFunction(modifiedObj): # pylint: disable=function-redefined
				return modifiedObj.clone()

			def mergeObjectsFunction(snapshotObj, updateObj, masterObj, snapshotBackend, workBackend, masterBackend): # pylint: disable=function-redefined,unused-argument,too-many-arguments
				if len(snapshotObj.values) != len(masterObj.values):
					logger.info("Values of %s changed on server since last sync, not updating values", snapshotObj)
					return None

				if snapshotObj.values:
					for val in snapshotObj.values:
						if val not in masterObj.values:
							logger.info("Values of %s changed on server since last sync, not updating values", snapshotObj)
							return None

				if masterObj.values:
					for val in masterObj.values:
						if val not in snapshotObj.values:
							logger.info("Values of %s changed on server since last sync, not updating values", snapshotObj)
							return None

				return updateObj

			if objectClassName in modifiedObjects:
				self._syncModifiedObjectsWithMaster(
					eval(objectClassName), # pylint: disable=eval-used
					modifiedObjects[objectClassName],
					{"objectId": self._clientId},
					objectsDifferFunction,
					createUpdateObjectFunction,
					mergeObjectsFunction
				)

	def _replicateMasterToWorkBackend(self): # pylint: disable=too-many-branches
		if not self._masterBackend:
			raise BackendConfigurationError("Master backend undefined")

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
				logger.debug("No license pool found for product '%s'", productOnClient.productId)
				continue

			licensePool = licensePools[0]
			try:
				for loc in licenseOnClients:
					if loc.licensePoolId == licensePool.id:
						licenseOnClient = loc
						logger.notice("Reusing existing licenseOnClient '%s'", licenseOnClient)
						break
				else:
					logger.notice("Acquiring license for product '%s'", productOnClient.productId)
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
			except Exception as license_sync_error: # pylint: disable=broad-except
				logger.error("Failed to acquire license for product '%s': %s", productOnClient.productId, license_sync_error)

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
		with codecs.open(self._auditHardwareConfigFile, 'w', 'utf8') as file:
			file.write(json.dumps(auditHardwareConfig))

		self._workBackend._setAuditHardwareConfig(auditHardwareConfig) # pylint: disable=protected-access
		self._workBackend.backend_createBase()

	def _createInstanceMethods(self):
		for Class in (Backend, ConfigDataBackend):
			for methodName, funcRef in inspect.getmembers(Class, inspect.isfunction):
				if methodName.startswith('_') or methodName in (
					'backend_info', 'user_getCredentials', 'user_setCredentials', 'log_write', 'licenseOnClient_getObjects'
				):
					continue

				(argString, callString) = getArgAndCallString(funcRef)

				logger.debug2(u"Adding method '%s' to execute on work backend" % methodName)
				exec(u'def %s(self, %s): return self._executeMethod("%s", %s)' % (methodName, argString, methodName, callString)) # pylint: disable=exec-used
				setattr(self, methodName, MethodType(eval(methodName), self)) # pylint: disable=eval-used

	def _cacheBackendInfo(self, backendInfo):
		with codecs.open(self._opsiModulesFile, 'w', 'utf-8') as file:
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
				file.write('%s = %s\n' % (module.lower(), state))
			file.write('customer = %s\n' % modules.get('customer', ''))
			file.write('expires = %s\n' % modules.get('expires', time.strftime("%Y-%m-%d", time.localtime(time.time()))))
			file.write('signature = %s\n' % modules.get('signature', ''))
