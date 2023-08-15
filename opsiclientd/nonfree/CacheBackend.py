# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
"""
Cache-Backend for Clients.
"""

import codecs
import collections
import inspect
import json
import time
from types import MethodType
from dataclasses import dataclass, field

from OPSI.Backend.Backend import (  # type: ignore[import]
	Backend,
	ConfigDataBackend,
	ModificationTrackingBackend,
)
from OPSI.Backend.Base.Extended import (  # type: ignore[import]
	get_function_signature_and_args,
)
from OPSI.Backend.Replicator import BackendReplicator  # type: ignore[import]
from OPSI.Util import blowfishDecrypt  # type: ignore[import]
from opsicommon.exceptions import (  # type: ignore[import]
	BackendConfigurationError,
	BackendMissingDataError,
	BackendUnaccomplishableError,
)
from opsicommon.license import OPSI_MODULE_IDS
from opsicommon.logging import logger
from opsicommon.logging.constants import TRACE
from opsicommon.objects import *  # required for dynamic class loading # pylint: disable=wildcard-import,unused-wildcard-import
from opsicommon.objects import (  # pylint: disable=reimported
	LicenseOnClient,
	ProductOnClient,
	get_ident_attributes,
	objects_differ,
	serialize,
	ProductDependency,
)
from opsicommon.types import forceHostId
from opsiclientd.Config import Config as OCDConfig

__all__ = ["ClientCacheBackend"]

config = OCDConfig()


@dataclass
class ProductActionGroup:
	priority: int = 0
	product_on_clients: list[ProductOnClient] = field(default_factory=list)
	priorities: dict[str, int] = field(default_factory=dict)
	dependencies: dict[str, list[ProductDependency]] = field(default_factory=lambda: collections.defaultdict(list))


class ClientCacheBackend(ConfigDataBackend, ModificationTrackingBackend):  # pylint: disable=too-many-instance-attributes
	def __init__(self, **kwargs):  # pylint: disable=super-init-not-called
		ConfigDataBackend.__init__(self, **kwargs)

		self._workBackend = None
		self._masterBackend = None
		self._snapshotBackend = None
		self._clientId = None
		self._depotId = None
		self._backendChangeListeners = []

		for (option, value) in kwargs.items():
			option = option.lower()
			if option == "workbackend":
				self._workBackend = value
			elif option == "snapshotbackend":
				self._snapshotBackend = value
			elif option == "masterbackend":
				self._masterBackend = value
			elif option == "clientid":
				self._clientId = forceHostId(value)
			elif option == "depotid":
				self._depotId = forceHostId(value)
			elif option == "backendinfo":
				self._backendInfo = value

		if not self._workBackend:
			raise BackendConfigurationError("Work backend undefined")
		if not self._snapshotBackend:
			raise BackendConfigurationError("Snapshot backend undefined")
		if not self._clientId:
			raise BackendConfigurationError("Client id undefined")
		if not self._depotId:
			raise BackendConfigurationError("Depot id undefined")

		self._workBackend._setContext(self)
		self._backend = self._workBackend
		self._createInstanceMethods()

	def backend_getLicensingInfo(self, licenses: bool = False, legacy_modules: bool = False, dates: bool = False, allow_cache: bool = True):
		return {"available_modules": OPSI_MODULE_IDS}

	def log_write(self, logType, data, objectId=None, append=False):
		pass

	def licenseOnClient_getObjects(self, attributes=[], **filter):  # pylint: disable=dangerous-default-value,redefined-builtin
		licenseOnClients = self._workBackend.licenseOnClient_getObjects(attributes, **filter)
		logger.info("licenseOnClient_getObjects called with filter %s, %s LicenseOnClients found", filter, len(licenseOnClients))
		for licenseOnClient in licenseOnClients:
			# Recreate for later sync to server
			self.licenseOnClient_insertObject(licenseOnClient)
		return licenseOnClients

	def config_getObjects(self, attributes=[], **filter):  # pylint: disable=dangerous-default-value,redefined-builtin
		configs = self._backend.config_getObjects(attributes, **filter)
		for idx, _config in enumerate(configs):
			if _config.id == "clientconfig.depot.id":
				configs[idx].defaultValues = [self._depotId]
		logger.trace("config_getObjects returning %s", configs)
		return configs

	def configState_getObjects(self, attributes=[], **filter):  # pylint: disable=dangerous-default-value,redefined-builtin
		config_states = self._backend.configState_getObjects(attributes, **filter)
		for idx, config_state in enumerate(config_states):
			if config_state.configId == "clientconfig.depot.id":
				config_states[idx].values = [self._depotId]
		logger.trace("configState_getObjects returning %s", config_states)
		return config_states

	def _setMasterBackend(self, masterBackend):
		self._masterBackend = masterBackend

	def _syncModifiedObjectsWithMaster(  # pylint: disable=too-many-arguments,too-many-locals,too-many-branches,too-many-statements
		self, objectClass, modifiedObjects, getFilter, objectsDifferFunction, createUpdateObjectFunction, mergeObjectsFunction
	):
		meth = getattr(self._masterBackend, f"{objectClass.backendMethodPrefix}_getObjects")
		masterObjects = {obj.getIdent(): obj for obj in meth(**getFilter)}

		deleteObjects = []
		updateObjects = []
		for mo in modifiedObjects:
			logger.debug("Processing modified object: %s", mo)
			masterObj = masterObjects.get(mo["object"].getIdent())

			command = mo["command"].lower()
			if command == "delete":
				if not masterObj:
					logger.info("No need to delete object %s because object has been deleted on server since last sync", mo["object"])
					continue

				meth = getattr(self._snapshotBackend, f"{objectClass.backendMethodPrefix}_getObjects")
				snapshotObj = meth(**(mo["object"].getIdent(returnType="dict")))
				if not snapshotObj:
					logger.info("Deletion of object %s prevented because object has been created on server since last sync", mo["object"])
					continue

				snapshotObj = snapshotObj[0]
				if objectsDifferFunction(snapshotObj, masterObj):
					logger.info("Deletion of object %s prevented because object has been modified on server since last sync", mo["object"])
					continue

				logger.info("Object %s marked for deletion", mo["object"])
				deleteObjects.append(mo["object"])
			elif command in ("update", "insert"):
				logger.debug("Modified object: %s", mo["object"].toHash())
				updateObj = createUpdateObjectFunction(mo["object"])

				if masterObj:
					logger.debug("Master object: %s", masterObj.toHash())
					meth = getattr(self._snapshotBackend, f"{objectClass.backendMethodPrefix}_getObjects")
					snapshotObj = meth(**(updateObj.getIdent(returnType="dict")))
					if snapshotObj:
						snapshotObj = snapshotObj[0]
						logger.debug("Snapshot object: %s", snapshotObj.toHash())
						updateObj = mergeObjectsFunction(
							snapshotObj, updateObj, masterObj, self._snapshotBackend, self._workBackend, self._masterBackend
						)

				if updateObj:
					logger.info("Object %s marked for update", mo["object"])
					updateObjects.append(updateObj)

		if deleteObjects:
			meth = getattr(self._masterBackend, f"{objectClass.backendMethodPrefix}_deleteObjects")
			try:
				meth(deleteObjects)
			except Exception as delete_err:
				logger.error("Failed to delete objects %s: %s", deleteObjects, delete_err)
				raise

		if updateObjects:
			meth = getattr(self._masterBackend, f"{objectClass.backendMethodPrefix}_updateObjects")
			try:
				meth(updateObjects)
			except Exception as update_err:
				logger.error("Failed to update objects %s: %s", updateObjects, update_err)
				raise

	# pylint: disable=dangerous-default-value,too-many-locals,too-many-statements,too-many-branches
	def _updateMasterFromWorkBackend(self, modifications=[]):
		modifiedObjects = collections.defaultdict(list)
		logger.notice("Updating master from work backend (%d modifications)", len(modifications))

		if logger.isEnabledFor(TRACE):
			logger.trace("workBackend: auditHardware_getObjects: %s", serialize(self._workBackend.auditHardware_getObjects()))
			logger.trace("workBackend: auditHardwareOnHost_getObjects: %s", serialize(self._workBackend.auditHardwareOnHost_getObjects()))

		for modification in modifications:
			try:
				ObjectClass = eval(modification["objectClass"])  # pylint: disable=eval-used
				identValues = modification["ident"].split(ObjectClass.identSeparator)
				identAttributes = tuple()
				if modification["objectClass"] == "AuditHardware":
					identAttributes = ("hardwareClass",) + tuple(sorted(ObjectClass.hardware_attributes[identValues[0]]))
				elif modification["objectClass"] == "AuditHardwareOnHost":
					identAttributes = ("hostId", "hardwareClass") + tuple(sorted(ObjectClass.hardware_attributes[identValues[1]]))
				else:
					identAttributes = get_ident_attributes(ObjectClass)
				objectFilter = {}
				for index, attribute in enumerate(identAttributes):
					if index >= len(identValues):
						raise BackendUnaccomplishableError(f"Bad ident '{identValues}' for objectClass '{modification['objectClass']}'")
					val = identValues[index]
					if val in ("", None):
						val = ["", None]
					objectFilter[attribute] = val

				backend = self._snapshotBackend if modification["command"] == "delete" else self._workBackend
				meth = getattr(backend, ObjectClass.backendMethodPrefix + "_getObjects")
				objects = meth(**objectFilter)
				if objects:
					modification["object"] = objects[0]
					modifiedObjects[modification["objectClass"]].append(modification)
					logger.debug("Modified object appended: %s", modification)
					logger.trace(modification["object"].to_hash())
			except Exception as modify_error:  # pylint: disable=broad-except
				logger.error("Failed to sync backend modification %s: %s", modification, modify_error, exc_info=True)
				continue

		if "AuditHardwareOnHost" in modifiedObjects:
			self._masterBackend.auditHardwareOnHost_setObsolete(self._clientId)
			self._masterBackend.auditHardwareOnHost_updateObjects([mo["object"] for mo in modifiedObjects["AuditHardwareOnHost"]])

		if "AuditSoftware" in modifiedObjects:
			self._masterBackend.auditSoftware_updateObjects([mo["object"] for mo in modifiedObjects["AuditSoftware"]])

		if "AuditSoftwareOnClient" in modifiedObjects:
			self._masterBackend.auditSoftwareOnClient_setObsolete(self._clientId)
			self._masterBackend.auditSoftwareOnClient_updateObjects([mo["object"] for mo in modifiedObjects["AuditSoftwareOnClient"]])

		if "ProductOnClient" in modifiedObjects:

			def objectsDifferFunction(snapshotObj, masterObj):
				return objects_differ(
					snapshotObj, masterObj, exclude_attributes=["modificationTime", "actionProgress", "actionResult", "lastAction"]
				)

			def createUpdateObjectFunction(modifiedObj):
				return modifiedObj.clone(identOnly=False)

			def mergeObjectsFunction(
				snapshotObj, updateObj, masterObj, snapshotBackend, workBackend, masterBackend
			):  # pylint: disable=unused-argument,too-many-arguments
				masterVersions = sorted(
					[
						f"{p.productVersion}-{p.packageVersion}"
						for p in masterBackend.productOnDepot_getObjects(
							["productVersion", "packageVersion"], productId=snapshotObj.productId, depotId=self._depotId
						)
					]
				)
				snapshotVersions = sorted(
					[
						f"{p.productVersion}-{p.packageVersion}"
						for p in snapshotBackend.productOnDepot_getObjects(
							["productVersion", "packageVersion"], productId=snapshotObj.productId, depotId=self._depotId
						)
					]
				)

				logger.info(
					"Syncing ProductOnClient %s (product versions local=%s, server=%s)", updateObj, snapshotVersions, masterVersions
				)
				if snapshotVersions != masterVersions:
					logger.notice(
						"Product %s changed on server since last sync, not updating actionRequest (local=%s, server=%s)",
						snapshotObj.productId,
						snapshotVersions,
						masterVersions,
					)
					updateObj.actionRequest = None
					updateObj.targetConfiguration = None
				return updateObj

			logger.debug("Syncing modified ProductOnClients with master: %s", modifiedObjects["ProductOnClient"])
			self._syncModifiedObjectsWithMaster(
				ProductOnClient,
				modifiedObjects["ProductOnClient"],
				{"clientId": self._clientId},
				objectsDifferFunction,
				createUpdateObjectFunction,
				mergeObjectsFunction,
			)

		if "LicenseOnClient" in modifiedObjects:

			def objectsDifferFunction(snapshotObj, masterObj):  # pylint: disable=function-redefined
				return objects_differ(snapshotObj, masterObj)

			def createUpdateObjectFunction(modifiedObj):  # pylint: disable=function-redefined
				return modifiedObj.clone(identOnly=False)

			def mergeObjectsFunction(
				snapshotObj, updateObj, masterObj, snapshotBackend, workBackend, masterBackend
			):  # pylint: disable=function-redefined,unused-argument,too-many-arguments
				return updateObj

			self._syncModifiedObjectsWithMaster(
				LicenseOnClient,
				modifiedObjects["LicenseOnClient"],
				{"clientId": self._clientId},
				objectsDifferFunction,
				createUpdateObjectFunction,
				mergeObjectsFunction,
			)

		for objectClassName in ("ProductPropertyState", "ConfigState"):

			def objectsDifferFunction(snapshotObj, masterObj):  # pylint: disable=function-redefined
				return objects_differ(snapshotObj, masterObj)

			def createUpdateObjectFunction(modifiedObj):  # pylint: disable=function-redefined
				return modifiedObj.clone()

			def mergeObjectsFunction(
				snapshotObj, updateObj, masterObj, snapshotBackend, workBackend, masterBackend
			):  # pylint: disable=function-redefined,unused-argument,too-many-arguments
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
					eval(objectClassName),  # pylint: disable=eval-used
					modifiedObjects[objectClassName],
					{"objectId": self._clientId},
					objectsDifferFunction,
					createUpdateObjectFunction,
					mergeObjectsFunction,
				)

	def _replicateMasterToWorkBackend(self):  # pylint: disable=too-many-branches,too-many-locals,too-many-statements
		if not self._masterBackend:
			raise BackendConfigurationError("Master backend undefined")

		# This is needed for the following situation:
		#  - package1 is set to "setup" which defines a dependency to package2 "setup after"
		#  - opsiclientd processes these actions with cached config
		#  - before opsiclientd config sync returns the results back to config service, package3 is set to "setup"
		#  - package3 also defines a dependency to package2 "setup after"
		#  - so package3 will be set to setup on service side too
		#  - now the sync starts again and the actions for package1 and package2 will be set to "none" on service side
		#  - setup of packgage2 which is required by package3 will not be exceuted

		productOnClients = {}
		product_ids_with_action = []
		for productOnClient in self._masterBackend.productOnClient_getObjects(clientId=self._clientId):
			productOnClients[productOnClient.productId] = productOnClient
			if productOnClient.actionRequest not in (None, "none"):
				product_ids_with_action.append(productOnClient.productId)

		if productOnClients and product_ids_with_action:
			updateProductOnClients = []
			for productDependency in self._masterBackend.productDependency_getObjects(productId=product_ids_with_action):
				if (
					productDependency.requiredAction not in (None, "")
					and productDependency.productId in productOnClients
					and productOnClients[productDependency.productId].actionRequest == productDependency.productAction
					and productDependency.requiredProductId in productOnClients
					and productOnClients[productDependency.requiredProductId].actionRequest != productDependency.requiredAction
				):
					logger.notice(
						"Setting missing required action for dependency %s/%s %s/%s",
						productDependency.productId,
						productDependency.productAction,
						productDependency.requiredProductId,
						productDependency.requiredAction,
					)
					productOnClients[productDependency.requiredProductId].actionRequest = productDependency.productAction
					updateProductOnClients.append(productOnClients[productDependency.requiredProductId])
					if productDependency.requiredProductId not in product_ids_with_action:
						product_ids_with_action.append(productDependency.requiredProductId)
			if updateProductOnClients:
				# Update is sufficient, creating a ProductOnClient is not required (see comment above)
				self._masterBackend.productOnClient_updateObjects(updateProductOnClients)

		self._cacheBackendInfo(self._masterBackend.backend_info())

		filterProductIds = []
		if config.get("cache_service", "sync_products_with_actions_only"):
			filterProductIds = product_ids_with_action
		# Need opsi-script PoC in cached backend for update_action_processor!
		if filterProductIds and "opsi-script" not in filterProductIds:
			filterProductIds.append("opsi-script")

		logger.notice(
			"sync_products_with_actions_only=%r, filterProductIds=%r",
			config.get("cache_service", "sync_products_with_actions_only"),
			filterProductIds,
		)

		self._workBackend.backend_deleteBase()
		self._workBackend.backend_createBase()
		br = BackendReplicator(readBackend=self._masterBackend, writeBackend=self._workBackend)
		br.replicate(
			serverIds=[],
			depotIds=[self._depotId],
			clientIds=[self._clientId],
			groupIds=[],
			productIds=filterProductIds,
			productTypes=["LocalbootProduct"],
			audit=False,
			licenses=False,
		)

		self._snapshotBackend.backend_deleteBase()

		licenseOnClients = self._masterBackend.licenseOnClient_getObjects(clientId=self._clientId)
		for productOnClient in self._workBackend.productOnClient_getObjects(clientId=self._clientId):
			if productOnClient.actionRequest in (None, "none"):
				continue

			licensePools = self._masterBackend.licensePool_getObjects(productIds=[productOnClient.productId])
			if not licensePools:
				logger.debug("No license pool found for product '%s'", productOnClient.productId)
				continue

			licensePool = licensePools[0]
			try:
				licenseOnClient = None
				for loc in licenseOnClients:
					if loc.licensePoolId == licensePool.id:
						licenseOnClient = loc
						logger.notice("Reusing existing licenseOnClient '%s'", licenseOnClient)
						break
				else:
					logger.notice("Acquiring license for product '%s'", productOnClient.productId)
					licenseOnClient = self._masterBackend.licenseOnClient_getOrCreateObject(
						clientId=self._clientId, productId=productOnClient.productId
					)

				if licenseOnClient:
					# Fake deletion
					# This will delete the licenseOnClient (free the license) while syncing config back to server
					# In case licenseOnClient_getObjects will be called on the CacheBackend the licenseOnClients
					# will be recreated, so the objects will be recreated after deletion
					self._fireEvent("objectsDeleted", [licenseOnClient])
					self._fireEvent("backendModified")

					statistics = {"licensePools": 0, "softwareLicenses": 0, "licenseContracts": 0}
					for licensePool in self._masterBackend.licensePool_getObjects(id=licenseOnClient.licensePoolId):
						logger.debug("Storing LicensePool: %s", licensePool)
						self._workBackend.licensePool_insertObject(licensePool)
						statistics["licensePools"] += 1

					for softwareLicense in self._masterBackend.softwareLicense_getObjects(id=licenseOnClient.softwareLicenseId):
						logger.debug("Storing SoftwareLicense: %s", softwareLicense)
						for licenseContract in self._masterBackend.licenseContract_getObjects(id=softwareLicense.licenseContractId):
							logger.debug("Storing LicenseContract: %s", licenseContract)
							self._workBackend.licenseContract_insertObject(licenseContract)
							statistics["licenseContracts"] += 1

						self._workBackend.softwareLicense_insertObject(softwareLicense)
						statistics["softwareLicenses"] += 1

					logger.debug("Storing LicenseOnClient: %s", licenseOnClient)
					self._workBackend.licenseOnClient_insertObject(licenseOnClient)

					logger.notice("LicenseOnClient stored for product '%s', %s", productOnClient.productId, statistics)
			except Exception as license_sync_error:  # pylint: disable=broad-except
				logger.error("Failed to acquire license for product '%s': %s", productOnClient.productId, license_sync_error)

		self._snapshotBackend.backend_createBase()
		br = BackendReplicator(readBackend=self._workBackend, writeBackend=self._snapshotBackend)
		br.replicate()

		if self._clientId != config.get("global", "host_id"):
			logger.error("Client id '%s' does not match config global.host_id '%s'", self._clientId, config.get("global", "host_id"))

		clients = self._workBackend.host_getObjects(id=self._clientId)
		if not clients:
			raise BackendMissingDataError("Host '{self._clientId}' not found in replicated backend")

		opsiHostKey = clients[0].getOpsiHostKey()
		if opsiHostKey != config.get("global", "opsi_host_key"):
			logger.error(
				"Host key '%s' from work backend does not match config global.opsi_host_key '%s'",
				opsiHostKey,
				config.get("global", "opsi_host_key"),
			)

		password = self._masterBackend.user_getCredentials(username="pcpatch", hostId=self._clientId)
		password = password["password"]
		logger.notice("Creating opsi passwd file '%s' using opsi host key '%s...'", self._opsiPasswdFile, opsiHostKey[:10])
		self.user_setCredentials(username="pcpatch", password=blowfishDecrypt(opsiHostKey, password))
		auditHardwareConfig = self._masterBackend.auditHardware_getConfig()
		with codecs.open(self._auditHardwareConfigFile, "w", "utf8") as file:
			file.write(json.dumps(auditHardwareConfig))

		self._workBackend._setAuditHardwareConfig(auditHardwareConfig)  # pylint: disable=protected-access
		self._workBackend.backend_createBase()

	def _createInstanceMethods(self):
		for Class in (Backend, ConfigDataBackend):
			for methodName, funcRef in inspect.getmembers(Class, inspect.isfunction):
				if methodName.startswith("_") or methodName in (
					"backend_info",
					"backend_getLicensingInfo",
					"user_getCredentials",
					"user_setCredentials",
					"log_write",
					"licenseOnClient_getObjects",
					"configState_getObjects",
					"config_getObjects",
					"getProductOrdering",
				):
					continue

				sig, arg = get_function_signature_and_args(funcRef)
				sig = "(self)" if sig == "()" else f"(self, {sig[1:]}"
				logger.trace("Adding method '%s' to execute on work backend", methodName)
				exec(f'def {methodName}{sig}: return self._executeMethod("{methodName}", {arg})')  # pylint: disable=exec-used
				setattr(self, methodName, MethodType(eval(methodName), self))  # pylint: disable=eval-used

	def _cacheBackendInfo(self, backendInfo):
		with codecs.open(self._opsiModulesFile, "w", "utf-8") as file:
			modules = backendInfo["modules"]
			helpermodules = backendInfo["realmodules"]
			for (module, state) in modules.items():
				if helpermodules in ("customer", "expires"):
					continue
				if module in helpermodules:
					state = helpermodules[module]
				else:
					if state:
						state = "yes"
					else:
						state = "no"
				file.write(f"{module.lower()} = {state}\n")
			file.write(f"customer = {modules.get('customer', '')}\n")
			file.write(f"expires = {modules.get('expires', time.strftime('%Y-%m-%d', time.localtime(time.time())))}\n")
			file.write(f"signature = {modules.get('signature', '')}\n")
