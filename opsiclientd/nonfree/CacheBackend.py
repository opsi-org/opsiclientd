# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2025 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.

"""
Cache-Backend for Clients.
"""

import inspect
import json
import warnings
from collections import defaultdict
from types import MethodType
from typing import Any, Callable, Type, cast

from opsi_legacy.Backend.Backend import (
	Backend,  # type: ignore[import]
	BackendModificationListener,
	ConfigDataBackend,
	ModificationTrackingBackend,
)
from opsi_legacy.Backend.Base.Extended import get_function_signature_and_args  # type: ignore[import]
from opsi_legacy.Backend.Replicator import BackendReplicator  # type: ignore[import]
from opsi_legacy.Util import blowfishDecrypt  # type: ignore[import]
from opsicommon.exceptions import BackendConfigurationError, BackendMissingDataError, BackendUnaccomplishableError
from opsicommon.license import OPSI_MODULE_IDS
from opsicommon.logging import get_logger
from opsicommon.logging.constants import TRACE
from opsicommon.objects import *  # noqa  # required for dynamic class loading
from opsicommon.objects import (
	BaseObject,
	Config,
	ConfigState,
	LicenseOnClient,
	ProductOnClient,
	ProductPropertyState,
	get_ident_attributes,
	objects_differ,
	serialize,
)
from opsicommon.types import forceHostId

from opsiclientd.Config import Config as OCDConfig
from opsiclientd.OpsiService import ServiceClient

__all__ = ["ClientCacheBackend"]

config = OCDConfig()
logger = get_logger()


def add_products_from_setup_after_install(products: list[str], service_client: ServiceClient) -> list[str]:
	# setup_after_install is not treated as a formal dependency
	# Adding those products here, ignoring dependencies and hoping for the best
	# A construct big as death and twice as ugly
	add_products = []
	try:
		for product in ("opsi-client-agent", "opsi-linux-client-agent", "opsi-mac-client-agent"):
			if product in products:  # one at most
				setup_after_install_products = service_client.productPropertyState_getObjects(  # type: ignore[attr-defined]
					objectId=config.get("global", "host_id"),
					productId=product,
					propertyId="setup_after_install",
				)
				if setup_after_install_products:
					add_products += [
						sai_product
						for sai_product in setup_after_install_products[0].values
						if sai_product and sai_product not in products and sai_product not in add_products
					]
	except Exception as err:
		logger.warning("Failed to add setup_after_install products to filteredProductIds: %s", err)
	return add_products


class ClientCacheBackend(ConfigDataBackend, ModificationTrackingBackend):
	def __init__(self, **kwargs: Any) -> None:
		ConfigDataBackend.__init__(self, **kwargs)

		self._masterBackend: ServiceClient | None = None
		self._workBackend: ConfigDataBackend | None = None
		self._snapshotBackend: ConfigDataBackend | None = None
		self._clientId: str | None = None
		self._depotId: str | None = None
		self._backendInfo: dict[str, Any] = {}
		self._configValuesCacheFile: str | None = None
		self._productPropertyValuesCacheFile: str | None = None
		self._backendChangeListeners: list[BackendModificationListener] = []

		for option, value in kwargs.items():
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
			elif option == "configvaluescachefile":
				self._configValuesCacheFile = value
			elif option == "productpropertyvaluescachefile":
				self._productPropertyValuesCacheFile = value
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

	@property
	def depotId(self) -> str | None:
		return self._depotId

	@depotId.setter
	def depotId(self, depotId: str) -> None:
		self._depotId = forceHostId(depotId)

	def backend_getLicensingInfo(
		self, licenses: bool = False, legacy_modules: bool = False, dates: bool = False, allow_cache: bool = True
	) -> dict[str, tuple[str, ...]]:
		return {"available_modules": OPSI_MODULE_IDS}

	def backend_info(self) -> dict[str, Any]:
		return self._backendInfo

	def log_write(self, logType: str, data: str, objectId: str | None = None, append: bool = False) -> None:
		pass

	def licenseOnClient_getObjects(self, attributes: list[str] | None = None, **filter: Any) -> list[LicenseOnClient]:
		assert self._workBackend
		licenseOnClients = self._workBackend.licenseOnClient_getObjects(attributes, **filter)
		logger.info("licenseOnClient_getObjects called with filter %s, %s LicenseOnClients found", filter, len(licenseOnClients))
		for licenseOnClient in licenseOnClients:
			# Recreate for later sync to server
			self.licenseOnClient_insertObject(licenseOnClient)
		return licenseOnClients

	def config_getObjects(self, attributes: list[str] | None = None, **filter: Any) -> list[Config]:
		configs = self._backend.config_getObjects(attributes, **filter)
		for idx, _config in enumerate(configs):
			if _config.id == "clientconfig.depot.id":
				configs[idx].defaultValues = [self._depotId]
		logger.trace("config_getObjects returning %s", configs)
		return configs

	def configState_getObjects(self, attributes: list[str] | None = None, **filter: Any) -> list[ConfigState]:
		config_states = self._backend.configState_getObjects(attributes, **filter)
		for idx, config_state in enumerate(config_states):
			if config_state.configId == "clientconfig.depot.id":
				config_states[idx].values = [self._depotId]
		logger.trace("configState_getObjects returning %s", config_states)
		return config_states

	def configState_getValues(
		self,
		config_ids: list[str] | str | None = None,
		object_ids: list[str] | str | None = None,
		with_defaults: bool = True,
	) -> dict[str, dict[str, list[Any]]]:
		try:
			logger.debug("Reading config values from cache file '%s'", self._configValuesCacheFile)
			assert self._configValuesCacheFile
			with open(self._configValuesCacheFile, "r", encoding="utf-8") as file:
				data: dict[str, dict[str, list[Any]]] = json.loads(file.read())

			if not config_ids:
				return data

			if not isinstance(config_ids, list):
				config_ids = [config_ids]

			filtered_data: dict[str, dict[str, list[Any]]] = {}
			for object_id, values1 in data.items():
				for config_id, values2 in values1.items():
					if config_id not in config_ids:
						continue
					if object_id not in filtered_data:
						filtered_data[object_id] = {}
					filtered_data[object_id][config_id] = values2

			return data
		except Exception as err:
			logger.error("Failed to read config values cache file '%s': %s", self._configValuesCacheFile, err)
		return {}

	def productPropertyState_getValues(
		self,
		product_ids: list[str] | str | None = None,
		property_ids: list[str] | str | None = None,
		object_ids: list[str] | str | None = None,
		with_defaults: bool = True,
	) -> dict[str, dict[str, dict[str, list[Any]]]]:
		try:
			logger.debug("Reading product property values from cache file '%s'", self._productPropertyValuesCacheFile)
			assert self._productPropertyValuesCacheFile
			with open(self._productPropertyValuesCacheFile, "r", encoding="utf-8") as file:
				data: dict[str, dict[str, dict[str, list[Any]]]] = json.loads(file.read())

			if not property_ids and not product_ids:
				return data

			if product_ids and not isinstance(product_ids, list):
				product_ids = [product_ids]
			if property_ids and not isinstance(property_ids, list):
				property_ids = [property_ids]

			filtered_data: dict[str, dict[str, dict[str, list[Any]]]] = {}
			for object_id, values1 in data.items():
				for product_id, values2 in values1.items():
					if product_ids and product_id not in product_ids:
						continue
					for property_id, values3 in values2.items():
						if property_ids and property_id not in property_ids:
							continue
						if object_id not in filtered_data:
							filtered_data[object_id] = {}
						if product_id not in filtered_data[object_id]:
							filtered_data[object_id][product_id] = {}
						filtered_data[object_id][product_id][property_id] = values3
			return filtered_data
		except Exception as err:
			logger.error("Failed to read product property values cache file '%s': %s", self._productPropertyValuesCacheFile, err)
		return {}

	def _setMasterBackend(self, masterBackend: ServiceClient) -> None:
		self._masterBackend = masterBackend

	def _syncModifiedObjectsWithMaster(
		self,
		objectClass: Type[BaseObject],
		modifiedObjects: list[dict[str, Any]],
		getFilter: dict[str, Any],
		objectsDifferFunction: Callable,
		createUpdateObjectFunction: Callable,
		mergeObjectsFunction: Callable,
	) -> None:
		meth = getattr(self._masterBackend, f"{objectClass.backendMethodPrefix}_getObjects")
		masterObjects: dict[str, BaseObject] = {obj.getIdent(): obj for obj in meth(**getFilter)}

		deleteObjects: list[BaseObject] = []
		updateObjects: list[BaseObject] = []
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

	def _updateMasterFromWorkBackend(self, modifications: list[dict[str, Any]] | None = None) -> None:
		if not self._masterBackend:
			raise BackendConfigurationError("Master backend undefined")
		if not self._workBackend:
			raise BackendConfigurationError("Work backend undefined")

		modifications = modifications or []
		modifiedObjects = defaultdict(list)
		logger.notice("Updating master from work backend (%d modifications)", len(modifications))

		if logger.isEnabledFor(TRACE):
			logger.trace("workBackend: auditHardware_getObjects: %s", serialize(self._workBackend.auditHardware_getObjects()))
			logger.trace("workBackend: auditHardwareOnHost_getObjects: %s", serialize(self._workBackend.auditHardwareOnHost_getObjects()))

		for modification in modifications:
			try:
				ObjectClass = eval(modification["objectClass"])
				identValues = modification["ident"].split(ObjectClass.identSeparator)
				identAttributes: tuple[str, ...] = tuple()
				if modification["objectClass"] == "AuditHardware":
					identAttributes = tuple(["hardwareClass"] + sorted(ObjectClass.hardware_attributes[identValues[0]]))
				elif modification["objectClass"] == "AuditHardwareOnHost":
					identAttributes = tuple(["hostId", "hardwareClass"] + sorted(ObjectClass.hardware_attributes[identValues[1]]))
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
			except Exception as modify_error:
				logger.error("Failed to sync backend modification %s: %s", modification, modify_error, exc_info=True)
				continue

		logger.info("modifiedObjects: %r", {m: len(modifiedObjects[m]) for m in modifiedObjects})
		if "AuditHardwareOnHost" in modifiedObjects:
			self._masterBackend.auditHardwareOnHost_setObsolete(self._clientId)  # type: ignore[attr-defined]
			self._masterBackend.auditHardwareOnHost_updateObjects([mo["object"] for mo in modifiedObjects["AuditHardwareOnHost"]])  # type: ignore[attr-defined]

		if "AuditSoftware" in modifiedObjects:
			self._masterBackend.auditSoftware_updateObjects([mo["object"] for mo in modifiedObjects["AuditSoftware"]])  # type: ignore[attr-defined]

		if "AuditSoftwareOnClient" in modifiedObjects:
			self._masterBackend.auditSoftwareOnClient_setObsolete(self._clientId)  # type: ignore[attr-defined]
			self._masterBackend.auditSoftwareOnClient_updateObjects([mo["object"] for mo in modifiedObjects["AuditSoftwareOnClient"]])  # type: ignore[attr-defined]

		if "OpsiClient" in modifiedObjects:
			for mo in modifiedObjects["OpsiClient"]:
				logger.debug("Modified OpsiClient object: %s", mo["object"])
				if mo["object"].id != self._clientId:
					continue
				client_objs = self._masterBackend.host_getObjects(type="OpsiClient", id=self._clientId)  # type: ignore[attr-defined]
				if not client_objs:
					logger.error("Failed to get OpsiClient %r from master backend", self._clientId)
					break
				if mo["object"].systemUUID and mo["object"].systemUUID != client_objs[0].systemUUID:
					logger.info(
						"Client systemUUID changed from %r to %r, updating in master backend",
						client_objs[0].systemUUID,
						mo["object"].systemUUID,
					)
					client_objs[0].setSystemUUID(mo["object"].systemUUID)
					self._masterBackend.host_updateObject(client_objs[0])  # type: ignore[attr-defined]

		if "ProductOnClient" in modifiedObjects:

			def objectsDifferFunction_poc(snapshotObj: BaseObject, masterObj: BaseObject) -> bool:
				return objects_differ(
					snapshotObj, masterObj, exclude_attributes=["modificationTime", "actionProgress", "actionResult", "lastAction"]
				)

			def createUpdateObjectFunction_poc(modifiedObj: BaseObject) -> BaseObject:
				return modifiedObj.clone(identOnly=False)

			def mergeObjectsFunction_poc(
				snapshotObj: ProductOnClient,
				updateObj: ProductOnClient,
				masterObj: ProductOnClient,
				snapshotBackend: ConfigDataBackend,
				workBackend: ConfigDataBackend,
				masterBackend: ConfigDataBackend,
			) -> ProductOnClient:
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
				objectsDifferFunction_poc,
				createUpdateObjectFunction_poc,
				mergeObjectsFunction_poc,
			)

		if "LicenseOnClient" in modifiedObjects:

			def objectsDifferFunction_loc(snapshotObj: BaseObject, masterObj: BaseObject) -> bool:
				return objects_differ(snapshotObj, masterObj)

			def createUpdateObjectFunction_loc(modifiedObj: BaseObject) -> BaseObject:
				return modifiedObj.clone(identOnly=False)

			def mergeObjectsFunction_loc(
				snapshotObj: BaseObject,
				updateObj: BaseObject,
				masterObj: BaseObject,
				snapshotBackend: ConfigDataBackend,
				workBackend: ConfigDataBackend,
				masterBackend: ConfigDataBackend,
			) -> BaseObject:
				return updateObj

			self._syncModifiedObjectsWithMaster(
				LicenseOnClient,
				modifiedObjects["LicenseOnClient"],
				{"clientId": self._clientId},
				objectsDifferFunction_loc,
				createUpdateObjectFunction_loc,
				mergeObjectsFunction_loc,
			)

		for objectClassName in ("ProductPropertyState", "ConfigState"):

			def objectsDifferFunction_pcs(snapshotObj: BaseObject, masterObj: BaseObject) -> bool:
				return objects_differ(snapshotObj, masterObj)

			def createUpdateObjectFunction_pcs(modifiedObj: BaseObject) -> BaseObject:
				return modifiedObj.clone()

			def mergeObjectsFunction_pcs(
				snapshotObj: ProductPropertyState | ConfigState,
				updateObj: ProductPropertyState | ConfigState,
				masterObj: ProductPropertyState | ConfigState,
				snapshotBackend: ConfigDataBackend,
				workBackend: ConfigDataBackend,
				masterBackend: ConfigDataBackend,
			) -> ProductPropertyState | ConfigState | None:
				if len(snapshotObj.values or []) != len(masterObj.values or []):
					logger.info("Values of %s changed on server since last sync, not updating values", snapshotObj)
					return None

				if snapshotObj.values:
					for val in snapshotObj.values:
						if val not in (masterObj.values or []):
							logger.info("Values of %s changed on server since last sync, not updating values", snapshotObj)
							return None

				if masterObj.values:
					for val in masterObj.values:
						if val not in (snapshotObj.values or []):
							logger.info("Values of %s changed on server since last sync, not updating values", snapshotObj)
							return None

				return updateObj

			if objectClassName in modifiedObjects:
				self._syncModifiedObjectsWithMaster(
					eval(objectClassName),
					modifiedObjects[objectClassName],
					{"objectId": self._clientId},
					objectsDifferFunction_pcs,
					createUpdateObjectFunction_pcs,
					mergeObjectsFunction_pcs,
				)

	def _replicateMasterToWorkBackend(self) -> None:
		if not self._masterBackend:
			raise BackendConfigurationError("Master backend undefined")
		if not self._workBackend:
			raise BackendConfigurationError("Work backend undefined")
		if not self._snapshotBackend:
			raise BackendConfigurationError("Snapshot backend undefined")

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
		for productOnClient in self._masterBackend.productOnClient_getObjects(clientId=self._clientId):  # type: ignore[attr-defined]
			productOnClients[productOnClient.productId] = productOnClient
			if productOnClient.productId and productOnClient.actionRequest not in (None, "none"):
				product_ids_with_action.append(productOnClient.productId)

		if productOnClients and product_ids_with_action:
			updateProductOnClients = []
			for productDependency in self._masterBackend.productDependency_getObjects(productId=product_ids_with_action):  # type: ignore[attr-defined]
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
					productOnClients[productDependency.requiredProductId].actionRequest = productDependency.requiredAction
					updateProductOnClients.append(productOnClients[productDependency.requiredProductId])
					if productDependency.requiredProductId not in product_ids_with_action:
						product_ids_with_action.append(productDependency.requiredProductId)
			if updateProductOnClients:
				# Update is sufficient, creating a ProductOnClient is not required (see comment above)
				self._masterBackend.productOnClient_updateObjects(updateProductOnClients)  # type: ignore[attr-defined]

		filterProductIds = []
		if config.get("cache_service", "sync_products_with_actions_only"):
			filterProductIds = product_ids_with_action
			filterProductIds += add_products_from_setup_after_install(filterProductIds, self._masterBackend)

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
		br = BackendReplicator(readBackend=cast(Backend, self._masterBackend), writeBackend=self._workBackend)
		assert self._clientId and self._depotId
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

		try:
			logger.debug("Writing config values to cache file '%s'", self._configValuesCacheFile)
			assert self._configValuesCacheFile
			with open(self._configValuesCacheFile, "w", encoding="utf-8") as file:
				file.write(
					json.dumps(
						self._masterBackend.configState_getValues(  # type: ignore[attr-defined]
							config_ids=["clientconfig.*", "opsiclientd.*"], object_ids=self._clientId, with_defaults=True
						)
					)
				)
		except Exception as err:
			logger.error("Failed to write config values cache file '%s': %s", self._configValuesCacheFile, err)

		try:
			logger.debug("Writing product property values to cache file '%s'", self._productPropertyValuesCacheFile)
			assert self._productPropertyValuesCacheFile
			with open(self._productPropertyValuesCacheFile, "w", encoding="utf-8") as file:
				file.write(
					json.dumps(
						self._masterBackend.productPropertyState_getValues(  # type: ignore[attr-defined]
							product_ids=filterProductIds, object_ids=self._clientId, with_defaults=True
						)
					)
				)
		except Exception as err:
			logger.error("Failed to write product property values cache file '%s': %s", self._productPropertyValuesCacheFile, err)

		self._snapshotBackend.backend_deleteBase()

		licenseOnClients = self._masterBackend.licenseOnClient_getObjects(clientId=self._clientId)  # type: ignore[attr-defined]
		for productOnClient in self._workBackend.productOnClient_getObjects(clientId=self._clientId):
			if productOnClient.actionRequest in (None, "none"):
				continue

			licensePools = self._masterBackend.licensePool_getObjects(productIds=[productOnClient.productId])  # type: ignore[attr-defined]
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
					licenseOnClient = self._masterBackend.licenseOnClient_getOrCreateObject(  # type: ignore[attr-defined]
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
					for licensePool in self._masterBackend.licensePool_getObjects(id=licenseOnClient.licensePoolId):  # type: ignore[attr-defined]
						logger.debug("Storing LicensePool: %s", licensePool)
						self._workBackend.licensePool_insertObject(licensePool)
						statistics["licensePools"] += 1

					for softwareLicense in self._masterBackend.softwareLicense_getObjects(id=licenseOnClient.softwareLicenseId):  # type: ignore[attr-defined]
						logger.debug("Storing SoftwareLicense: %s", softwareLicense)
						for licenseContract in self._masterBackend.licenseContract_getObjects(id=softwareLicense.licenseContractId):  # type: ignore[attr-defined]
							logger.debug("Storing LicenseContract: %s", licenseContract)
							self._workBackend.licenseContract_insertObject(licenseContract)
							statistics["licenseContracts"] += 1

						self._workBackend.softwareLicense_insertObject(softwareLicense)
						statistics["softwareLicenses"] += 1

					logger.debug("Storing LicenseOnClient: %s", licenseOnClient)
					self._workBackend.licenseOnClient_insertObject(licenseOnClient)

					logger.notice("LicenseOnClient stored for product '%s', %s", productOnClient.productId, statistics)
			except Exception as license_sync_error:
				logger.error("Failed to acquire license for product '%s': %s", productOnClient.productId, license_sync_error)

		self._snapshotBackend.backend_createBase()
		br = BackendReplicator(readBackend=self._workBackend, writeBackend=self._snapshotBackend)
		br.replicate()

		if self._clientId != config.get("global", "host_id"):
			logger.error("Client id '%s' does not match config global.host_id '%s'", self._clientId, config.get("global", "host_id"))

		clients = self._workBackend.host_getObjects(id=self._clientId)
		if not clients:
			raise BackendMissingDataError(f"Host '{self._clientId}' not found in replicated backend")

		opsiHostKey = clients[0].getOpsiHostKey()
		if opsiHostKey != config.get("global", "opsi_host_key"):
			logger.error(
				"Host key '%s' from work backend does not match config global.opsi_host_key '%s'",
				opsiHostKey,
				config.get("global", "opsi_host_key"),
			)

		password = self._masterBackend.user_getCredentials(username="pcpatch", hostId=self._clientId)  # type: ignore[attr-defined]
		password = password["password"]
		logger.notice("Creating opsi passwd file '%s' using opsi host key '%s...'", self._opsiPasswdFile, opsiHostKey[:10])
		self.user_setCredentials(username="pcpatch", password=blowfishDecrypt(opsiHostKey, password))
		auditHardwareConfig = self._masterBackend.auditHardware_getConfig()  # type: ignore[attr-defined]
		with open(self._auditHardwareConfigFile, "w", encoding="utf8") as file:
			file.write(json.dumps(auditHardwareConfig))

		self._workBackend._setAuditHardwareConfig(auditHardwareConfig)  # type: ignore[attr-defined]
		self._workBackend.backend_createBase()

	def _createInstanceMethods(self) -> None:
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
				logger.trace("Adding method '%s' to execute on work backend", methodName)
				try:
					sig, arg = get_function_signature_and_args(funcRef)
					sig = "(self)" if sig == "()" else f"(self, {sig[1:]}"

					exec_locals: dict[str, Callable] = {}
					with warnings.catch_warnings():
						exec(
							f'def {methodName}{sig}: return self._executeMethod("{methodName}", {arg})',
							None,
							exec_locals,
						)

					new_function = exec_locals[methodName]
					setattr(self, methodName, MethodType(new_function, self))
				except Exception as err:
					logger.error("Failed to create method '%s': %s", methodName, err)
				except Exception as err:
					logger.error("Failed to create method '%s': %s", methodName, err)
				except Exception as err:
					logger.error("Failed to create method '%s': %s", methodName, err)
				except Exception as err:
					logger.error("Failed to create method '%s': %s", methodName, err)
