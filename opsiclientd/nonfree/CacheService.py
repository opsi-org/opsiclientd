# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
"""
opsiclientd.nonfree.CacheService

@copyright:	uib GmbH <info@uib.de>
"""

from __future__ import annotations

import codecs
import collections
import os
import shutil
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from OPSI import System  # type: ignore[import]
from OPSI.Backend.Backend import ExtendedConfigDataBackend  # type: ignore[import]
from OPSI.Backend.BackendManager import BackendExtender  # type: ignore[import]
from OPSI.Backend.SQLite import (  # type: ignore[import]
	SQLiteBackend,
	SQLiteObjectBackendModificationTracker,
)
from OPSI.Util import randomString  # type: ignore[import]
from OPSI.Util.File.Opsi import PackageContentFile  # type: ignore[import]
from OPSI.Util.Repository import (  # type: ignore[import]
	DepotToLocalDirectorySychronizer,
	getRepository,
)
from opsicommon.logging import get_logger, log_context
from opsicommon.objects import LocalbootProduct, ProductOnClient
from opsicommon.types import (
	forceBool,
	forceInt,
	forceObjectIdList,
	forceProductIdList,
	forceUnicode,
	forceUnicodeList,
)
from packaging import version

from opsiclientd.Config import Config
from opsiclientd.Events.SyncCompleted import SyncCompletedEventGenerator
from opsiclientd.Events.Utilities.Generators import getEventGenerators
from opsiclientd.nonfree import verify_modules
from opsiclientd.nonfree.CacheBackend import (
	ClientCacheBackend,
	add_products_from_setup_after_install,
)
from opsiclientd.nonfree.RPCProductDependencyMixin import RPCProductDependencyMixin
from opsiclientd.OpsiService import ServiceConnection
from opsiclientd.State import State
from opsiclientd.SystemCheck import RUNNING_ON_DARWIN, RUNNING_ON_WINDOWS
from opsiclientd.Timeline import Timeline
from opsiclientd.utils import get_include_exclude_product_ids

if TYPE_CHECKING:
	from opsiclientd.Opsiclientd import Opsiclientd

__all__ = ["CacheService", "ConfigCacheService", "ProductCacheService"]

config = Config()
state = State()
timeline = Timeline()
sync_completed_lock = threading.Lock()
RETENTION_HEARTBEAT_INTERVAL_DIFF = 10.0
MIN_HEARTBEAT_INTERVAL = 1.0
logger = get_logger("opsiclientd")


class TransferSlotHeartbeat(threading.Thread):
	def __init__(self, service_connection: ServiceConnection, depot_id: str, client_id: str) -> None:
		super().__init__(daemon=True)
		self.should_stop = False
		self.service_connection = service_connection
		self.depot_id = depot_id
		self.client_id = client_id
		self.slot_id = None

	def acquire(self) -> dict[str, str | float]:
		response = self.service_connection.depot_acquireTransferSlot(self.depot_id, self.client_id, self.slot_id)  # type: ignore[attr-defined]
		self.slot_id = response.get("slot_id")
		logger.debug("Transfer slot Heartbeat %s, response: %s", self.slot_id, response)
		return response

	def release(self) -> None:
		response = self.service_connection.depot_releaseTransferSlot(self.depot_id, self.client_id, self.slot_id)  # type: ignore[attr-defined]
		logger.debug("releaseTransferSlot response: %s", response)

	def run(self) -> None:
		try:
			while not self.should_stop:
				response = self.acquire()
				if not response.get("retention"):
					logger.error("TransferSlotHeartbeat lost transfer slot (and did not get new one)")
					raise ConnectionError("TransferSlotHeartbeat lost transfer slot (and did not get new one)")
				wait_time = max(float(response["retention"]) - RETENTION_HEARTBEAT_INTERVAL_DIFF, MIN_HEARTBEAT_INTERVAL)
				logger.debug("Waiting %s seconds before reaquiring slot", wait_time)
				end = datetime.now() + timedelta(seconds=wait_time)
				while not self.should_stop and datetime.now() < end:
					time.sleep(1.0)
		finally:
			if self.slot_id:
				self.release()


class CacheService(threading.Thread):
	def __init__(self, opsiclientd):
		threading.Thread.__init__(self, name="CacheService")
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
			self._productCacheService = ProductCacheService(self._opsiclientd)
			self._productCacheService.start()

	def initializeConfigCacheService(self):
		if not self._configCacheService:
			self._configCacheService = ConfigCacheService(self._opsiclientd)
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
		except Exception as cacheInitError:
			logger.info(cacheInitError, exc_info=True)
			logger.error(cacheInitError)
			return False

		if not self._configCacheService.isWorking() and self._configCacheService.getState().get("config_cached", False):
			return True

		return False

	def getConfigBackend(self):
		self.initializeConfigCacheService()
		return self._configCacheService.getConfigBackend()

	def getConfigModifications(self):
		self.initializeConfigCacheService()
		return self._configCacheService._backendTracker.getModifications()

	def isProductCacheServiceWorking(self):
		self.initializeProductCacheService()
		return self._productCacheService.isWorking()

	def cacheProducts(
		self, waitForEnding=False, productProgressObserver=None, overallProgressObserver=None, dynamicBandwidth=True, maxBandwidth=0
	):
		self.initializeProductCacheService()
		if self._productCacheService.isWorking():
			logger.info("Already caching products")
			return

		if self._configCacheService and self._configCacheService.syncConfigToServerError:
			raise RuntimeError("Failed to cache products because config sync to server failed")

		logger.info("Trigger product caching")
		self._productCacheService.setDynamicBandwidth(dynamicBandwidth)
		self._productCacheService.setMaxBandwidth(maxBandwidth)
		self._productCacheService.cacheProducts(
			productProgressObserver=productProgressObserver, overallProgressObserver=overallProgressObserver
		)

		if waitForEnding:
			time.sleep(3)
			while self._productCacheService.isRunning() and self._productCacheService.isWorking():
				time.sleep(1)

	def productCacheCompleted(self, configService, productIds, checkCachedProductVersion=False):
		logger.debug("productCacheCompleted: configService=%s productIds=%s", configService, productIds)
		if not productIds:
			return True

		workingWithCachedConfig = bool(configService.hostname.lower() in ("localhost", "127.0.0.1", "::1"))

		self.initializeProductCacheService()

		masterDepotId = config.get("depot_server", "master_depot_id")
		if workingWithCachedConfig:
			depotIds = []
			for depot in configService.host_getObjects(type="OpsiDepotserver"):
				depotIds.append(depot.id)
			if masterDepotId not in depotIds:
				self.setConfigCacheFaulty()
				raise RuntimeError(
					f"Config cache problem: depot '{masterDepotId}' not available in cached depots: {depotIds}."
					" Probably the depot was switched after the last config sync from server."
				)

		productOnDepots = {
			productOnDepot.productId: productOnDepot
			for productOnDepot in configService.productOnDepot_getObjects(depotId=masterDepotId, productId=productIds)
		}
		logger.trace("productCacheCompleted: productOnDepots=%s", productOnDepots)

		pcsState = self._productCacheService.getState()
		logger.debug("productCacheCompleted: productCacheService state=%s", pcsState)
		productCacheState = pcsState.get("products", {})

		for productId in productIds:
			try:
				productOnDepot = productOnDepots[productId]
			except KeyError as err:
				# Problem with cached config
				if workingWithCachedConfig:
					self.setConfigCacheFaulty()
					raise RuntimeError(f"Config cache problem: product '{productId}' not available on depot '{masterDepotId}'") from err
				raise RuntimeError(f"Product '{productId}' not available on depot '{masterDepotId}'") from err

			productState = productCacheState.get(productId)
			if not productState:
				logger.info(
					"Caching of product '%s_%s-%s' not yet started", productId, productOnDepot.productVersion, productOnDepot.packageVersion
				)
				return False

			if not productState.get("completed"):
				logger.info(
					"Caching of product '%s_%s-%s' not yet completed (got state: %s)",
					productId,
					productOnDepot.productVersion,
					productOnDepot.packageVersion,
					productState,
				)
				return False

			if (productState.get("productVersion") != productOnDepot.productVersion) or (
				productState.get("packageVersion") != productOnDepot.packageVersion
			):
				logger.warning(
					"Product '%s_%s-%s' on depot but different version cached (got state: %s)",
					productId,
					productOnDepot.productVersion,
					productOnDepot.packageVersion,
					productState,
				)
				if checkCachedProductVersion:
					return False
				logger.warning("Ignoring version difference")

		return True

	def getProductCacheState(self) -> dict[str, Any]:
		self.initializeProductCacheService()
		return self._productCacheService.getState()

	def getConfigCacheState(self):
		self.initializeConfigCacheService()
		return self._configCacheService.getState()

	def getProductCacheDir(self):
		self.initializeProductCacheService()
		return self._productCacheService.getProductCacheDir()

	def clear_product_cache(self):
		self.initializeProductCacheService()
		return self._productCacheService.clear_cache()


class ConfigCacheServiceBackendExtension42(RPCProductDependencyMixin):
	def accessControl_authenticated(self):
		return True


class ConfigCacheServiceBackendExtension43(RPCProductDependencyMixin):
	def accessControl_authenticated(self):
		return True

	def configState_getValues(
		self,
		config_ids: list[str] | str | None = None,
		object_ids: list[str] | str | None = None,
		with_defaults: bool = True,
	) -> dict[str, dict[str, list[Any]]]:
		config_ids = forceUnicodeList(config_ids or [])
		object_ids = forceObjectIdList(object_ids or [])
		res: dict[str, dict[str, list[Any]]] = {}
		if with_defaults:
			configserver_id = self.host_getIdents(type="OpsiConfigserver")[0]  # type: ignore[attr-defined]
			defaults = {c.id: c.defaultValues for c in self.config_getObjects(id=config_ids)}  # type: ignore[attr-defined]
			res = {h.id: defaults.copy() for h in self.host_getObjects(attributes=["id"], id=object_ids)}  # type: ignore[attr-defined]
			client_id_to_depot_id = {
				ctd.getObjectId(): ctd.getValues()[0]
				for ctd in self.configState_getObjects(objectId=object_ids, configId="clientconfig.depot.id")  # type: ignore[attr-defined]
			}
			depot_values: dict[str, dict[str, list[Any]]] = defaultdict(lambda: defaultdict(list))
			depot_ids = list(set(client_id_to_depot_id.values()))
			if configserver_id not in depot_ids:
				depot_ids.append(configserver_id)
			if depot_ids:
				for config_state in self.configState_getObjects(configId=config_ids, objectId=depot_ids):  # type: ignore[attr-defined]
					depot_values[config_state.getObjectId()][config_state.getConfigId()] = config_state.values
			for host in self.host_getObjects(attributes=["id"], id=object_ids):  # type: ignore[attr-defined]
				host_id = host.id
				depot_id = client_id_to_depot_id.get(host_id)
				if depot_id and depot_id in depot_values:
					res[host_id].update(depot_values[depot_id])
				elif not depot_id and configserver_id in depot_values:
					res[host_id].update(depot_values[configserver_id])
		for config_state in self.configState_getObjects(configId=config_ids, objectId=object_ids):  # type: ignore[attr-defined]
			if config_state.objectId not in res:
				res[config_state.objectId] = {}
			res[config_state.objectId][config_state.configId] = config_state.values
		return res

	def productOnClient_getActionGroups(self, clientId: str) -> list[dict[str, Any]]:
		"""
		Get product action groups of action requests set for a client.
		"""
		product_on_clients = self.productOnClient_getObjects(clientId=clientId)  # type: ignore[attr-defined]

		action_groups: list[dict] = []
		for group in self.get_product_action_groups(product_on_clients).get(clientId, []):
			group.product_on_clients = [
				poc.to_hash()  # type: ignore[misc]
				for poc in group.product_on_clients
				if poc.actionRequest and poc.actionRequest != "none"
			]
			if group.product_on_clients:
				group.dependencies = {
					product_id: [d.to_hash() for d in dep]  # type: ignore[misc]
					for product_id, dep in group.dependencies.items()
				}
				action_groups.append(group)  # type: ignore[arg-type]

		return action_groups

	def productOnClient_generateSequence(self, productOnClients: list[ProductOnClient]) -> list[ProductOnClient]:
		"""
		Takes a list of ProductOnClient objects.
		Returns the same list of in the order in which the actions must be processed.
		Please also check if `productOnClient_addDependencies` is more suitable.
		"""
		product_ids_by_client_id: dict[str, list[str]] = collections.defaultdict(list)
		for poc in productOnClients:
			product_ids_by_client_id[poc.clientId].append(poc.productId)

		return [
			poc
			for group in self.get_product_action_groups(productOnClients).values()
			for g in group
			for poc in g.product_on_clients
			if poc.productId in product_ids_by_client_id.get(poc.clientId, [])
		]

	def productOnClient_getObjectsWithSequence(
		self,
		attributes: list[str] | None = None,
		**filter: Any,
	) -> list[ProductOnClient]:
		"""
		Like productOnClient_getObjects, but return objects in order and with attribute actionSequence set.
		Will not add dependent ProductOnClients!
		If attributes are passed and `actionSequence` is not included in the list of attributes,
		the method behaves like `productOnClient_getObjects` (which is faster).
		"""
		if attributes and "actionSequence" not in attributes:
			return self.productOnClient_getObjects(attributes, **filter)  # type: ignore[attr-defined]

		product_on_clients = self.productOnClient_getObjects(attributes, **filter)  # type: ignore[attr-defined]
		action_requests = {(poc.clientId, poc.productId): poc.actionRequest for poc in product_on_clients}
		product_on_clients = self.productOnClient_generateSequence(product_on_clients)
		for poc in product_on_clients:
			if action_request := action_requests.get((poc.clientId, poc.productId)):
				poc.actionRequest = action_request
				if not poc.actionRequest or poc.actionRequest == "none":
					poc.actionSequence = -1
		return product_on_clients

	def getProductOrdering(self, depotId: str, sortAlgorithm: str | None = None) -> dict[str, list]:
		if sortAlgorithm and sortAlgorithm != "algorithm1":
			raise ValueError(f"Invalid sort algorithm {sortAlgorithm!r}")

		products_by_id_and_version: dict[tuple[str, str, str], LocalbootProduct] = {}
		for product in self.product_getObjects(type="LocalbootProduct"):  # type: ignore[attr-defined]
			products_by_id_and_version[(product.id, product.productVersion, product.packageVersion)] = product

		product_ids = []
		product_on_clients = []
		for product_on_depot in self.productOnDepot_getObjects(depotId=depotId, productType="LocalbootProduct"):  # type: ignore[attr-defined]
			product = products_by_id_and_version.get(
				(product_on_depot.productId, product_on_depot.productVersion, product_on_depot.packageVersion)
			)
			if not product:
				continue

			product_ids.append(product.id)

			for action in ("setup", "always", "once", "custom", "uninstall"):
				if getattr(product, f"{action}Script"):
					product_on_clients.append(
						ProductOnClient(
							productId=product_on_depot.productId,
							productType=product_on_depot.productType,
							clientId=depotId,
							installationStatus="not_installed",
							actionRequest=action,
						)
					)
					break

		product_ids.sort()
		sorted_ids = [
			poc.productId
			for actions in self.get_product_action_groups(product_on_clients).values()
			for a in actions
			for poc in a.product_on_clients
		]
		return {"not_sorted": product_ids, "sorted": sorted_ids}


class ConfigCacheService(ServiceConnection, threading.Thread):
	def __init__(self, opsiclientd: Opsiclientd) -> None:
		try:
			threading.Thread.__init__(self, name="ConfigCacheService")
			ServiceConnection.__init__(self, opsiclientd)

			self._configBackend = None
			self._configCacheDir = os.path.join(config.get("cache_service", "storage_dir"), "config")
			self._opsiModulesFile = os.path.join(self._configCacheDir, "cached_modules")
			self._opsiPasswdFile = os.path.join(self._configCacheDir, "cached_passwd")
			self._auditHardwareConfigFile = os.path.join(self._configCacheDir, "cached_opsihwaudit.json")

			self._stopped = False
			self._running = False
			self._working = False
			self._state: dict[str, Any] = {}

			self._syncConfigFromServerRequested = False
			self._syncConfigToServerError = None
			self._syncConfigToServerRequested = False
			self._forceSync = False

			if not os.path.exists(self._configCacheDir):
				logger.notice("Creating config cache dir '%s'", self._configCacheDir)
				os.makedirs(self._configCacheDir)

			ccss = state.get("config_cache_service")
			if ccss:
				self._state = ccss

			self.initBackends()
		except Exception as err:
			logger.error(err, exc_info=True)
			try:
				self.setObsolete()
			except Exception:
				pass
			raise err

	@property
	def syncConfigToServerError(self):
		return self._syncConfigToServerError

	def initBackends(self):
		clientId = config.get("global", "host_id")
		masterDepotId = config.get("depot_server", "master_depot_id")

		backendArgs = {
			"opsiModulesFile": self._opsiModulesFile,
			"opsiPasswdFile": self._opsiPasswdFile,
			"auditHardwareConfigFile": self._auditHardwareConfigFile,
			"depotId": masterDepotId,
		}
		self._workBackend = SQLiteBackend(database=os.path.join(self._configCacheDir, "work.sqlite"), **backendArgs)
		self._workBackend.backend_createBase()

		self._snapshotBackend = SQLiteBackend(database=os.path.join(self._configCacheDir, "snapshot.sqlite"), **backendArgs)
		self._snapshotBackend.backend_createBase()

		self._cacheBackend = ClientCacheBackend(
			workBackend=self._workBackend, snapshotBackend=self._snapshotBackend, clientId=clientId, **backendArgs
		)

		self._createConfigBackend()

		self._backendTracker = SQLiteObjectBackendModificationTracker(
			database=os.path.join(self._configCacheDir, "tracker.sqlite"), lastModificationOnly=True
		)
		self._cacheBackend.addBackendChangeListener(self._backendTracker)

	def connectConfigService(self, allowTemporaryConfigServiceUrls=True):
		ServiceConnection.connectConfigService(self, allowTemporaryConfigServiceUrls=False)

		try:
			try:
				if hasattr(self._configService, "backend_getLicensingInfo"):
					info = self._configService.backend_getLicensingInfo(licenses=False, legacy_modules=False, dates=False)
					logger.debug("Got licensing info from service: %s", info)
					if "vpn" not in info["available_modules"]:
						raise RuntimeError("Module 'vpn' not licensed")
				else:
					verify_modules(self._configService.backend_info(), ["vpn"])
			except Exception as err:
				raise RuntimeError(f"Cannot sync products: {err}") from err

			try:
				if self._configService.hostname.lower() not in ("localhost", "127.0.0.1", "::1"):
					client_to_depotservers = self._configService.configState_getClientToDepotserver(
						clientIds=config.get("global", "host_id")
					)
					if not client_to_depotservers:
						raise RuntimeError(f"Failed to get depotserver for client '{config.get('global', 'host_id')}'")
					depot_id = client_to_depotservers[0]["depotId"]
					config.set("depot_server", "master_depot_id", depot_id)
					config.updateConfigFile()
			except Exception as err:
				logger.warning(err)
		except Exception:
			self.disconnectConfigService()
			raise

	def _createConfigBackend(self):
		extension_class = ConfigCacheServiceBackendExtension43
		server_version = version.parse(self._state.get("server_version", "4.2.0.0"))
		if server_version < version.parse("4.3"):
			extension_class = ConfigCacheServiceBackendExtension42
		logger.notice("Using extension class %r for server version %s", extension_class, server_version)

		self._configBackend = BackendExtender(
			backend=ExtendedConfigDataBackend(configDataBackend=self._cacheBackend),
			extensionClass=extension_class,
			extensionConfigDir=config.get("cache_service", "extension_config_dir"),
			extensionReplaceMethods=False,
		)

	def getConfigBackend(self):
		return self._configBackend

	def getState(self) -> dict[str, Any]:
		_state = self._state
		_state["running"] = self.isRunning()
		_state["working"] = self.isWorking()
		return _state

	def setObsolete(self):
		self._state["config_cached"] = False
		state.set("config_cache_service", self._state)

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
		with log_context({"instance": "config cache service"}):
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
			except Exception as error:
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
		try:
			modifications = self._backendTracker.getModifications()
			if not modifications:
				logger.notice("Cache backend was not modified, no sync to server required")
			else:
				try:
					logger.debug("Tracked modifications: %s", modifications)
					logger.notice("Cache backend was modified, starting sync to server")
					eventId = timeline.addEvent(
						title="Config sync to server", description="Syncing config to server", category="config_sync", durationEvent=True
					)
					if not self._configService:
						self.connectConfigService()
					self._cacheBackend._setMasterBackend(self._configService)
					self._cacheBackend._updateMasterFromWorkBackend(modifications)
					logger.info("Clearing modifications in tracker")
					self._backendTracker.clearModifications()
					try:
						instlog = os.path.join(config.get("global", "log_dir"), "opsi-script.log")
						logger.debug("Checking if a custom logfile is given in global action_processor section")
						try:
							commandParts = config.get("action_processor", "command").split()
							if "/logfile" in commandParts:
								instlog = commandParts[commandParts.index("/logfile") + 1]
						except Exception:
							pass

						if os.path.isfile(instlog):
							logger.info("Syncing instlog %s", instlog)
							with codecs.open(instlog, "r", "utf-8", "replace") as file:
								data = file.read()

							self._configService.log_write("instlog", data=data, objectId=config.get("global", "host_id"), append=False)
					except Exception as err:
						logger.error("Failed to sync instlog: %s", err)

					logger.notice("Config synced to server")
				except Exception as err:
					logger.error(err, exc_info=True)
					timeline.addEvent(
						title="Failed to sync config to server",
						description=f"Failed to sync config to server: {err}",
						category="config_sync",
						isError=True,
					)
					raise
			self._syncConfigToServerError = None
		except Exception as err:
			logger.error("Errors occurred while syncing config to server: %s", err)
			self._syncConfigToServerError = err
		if eventId:
			timeline.setEventEnd(eventId)
		self.disconnectConfigService()
		self._working = False

	def _syncConfigFromServer(self):
		self._working = True
		try:
			if self._syncConfigToServerError:
				raise RuntimeError("Sync config to server failed")
			self.setObsolete()
			if not self._configService:
				self.connectConfigService()

			masterDepotId = config.get("depot_server", "master_depot_id")

			needSync = False
			if self._forceSync:
				logger.notice("Forced sync from server")
				needSync = True

			if not needSync:
				cachedDepotIds = []
				try:
					for depot in self._cacheBackend.host_getObjects(type="OpsiDepotserver"):
						cachedDepotIds.append(depot.id)
				except Exception as depError:
					logger.warning(depError)
				if cachedDepotIds and masterDepotId not in cachedDepotIds:
					logger.notice(
						f"Depot '{masterDepotId}' not available in cached depots: {cachedDepotIds}."
						" Probably the depot was switched after the last config sync from server. New sync required."
					)
					needSync = True

			self._cacheBackend.depotId = masterDepotId

			if not needSync:
				includeProductIds, excludeProductIds = get_include_exclude_product_ids(
					self._configService,
					config.get("cache_service", "include_product_group_ids"),
					config.get("cache_service", "exclude_product_group_ids"),
				)

				productOnClients = [
					poc
					for poc in self._configService.productOnClient_getObjects(
						productType="LocalbootProduct",
						clientId=config.get("global", "host_id"),
						# Exclude 'always'!
						actionRequest=["setup", "uninstall", "update", "once", "custom"],
						attributes=["actionRequest"],
						productId=includeProductIds,
					)
					if poc.productId not in excludeProductIds
				]

				logger.info("Product on clients: %s", productOnClients)
				if not productOnClients:
					logger.notice("No product action requests set on config service, no sync from server required")
				else:
					localProductOnClientsByProductId = {}
					for productOnClient in self._cacheBackend.productOnClient_getObjects(
						productType="LocalbootProduct",
						clientId=config.get("global", "host_id"),
						actionRequest=["setup", "uninstall", "update", "always", "once", "custom"],
						attributes=["actionRequest"],
					):
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
						description="Syncing config from server",
						category="config_sync",
						durationEvent=True,
					)
					self._cacheBackend._setMasterBackend(self._configService)
					logger.info("Clearing modifications in tracker")
					self._backendTracker.clearModifications()
					self._cacheBackend._replicateMasterToWorkBackend()
					logger.notice("Config synced from server")
					self._state["server_version"] = str(self._configService.service.server_version)
					with sync_completed_lock:
						self._state["config_cached"] = True
						state.set("config_cache_service", self._state)
						self._createConfigBackend()
						timeline.setEventEnd(eventId)
						# IDEA: only fire sync_completed if pending action requests?
						for eventGenerator in getEventGenerators(generatorClass=SyncCompletedEventGenerator):
							eventGenerator.createAndFireEvent()
				except Exception as err:
					logger.error(err, exc_info=True)
					timeline.addEvent(
						title="Failed to sync config from server",
						description=f"Failed to sync config from server: {err}",
						category="config_sync",
						isError=True,
					)
					if eventId:
						timeline.setEventEnd(eventId)
					self.setFaulty()
					raise
			else:
				self._state["config_cached"] = True
				state.set("config_cache_service", self._state)

		except Exception as err:
			logger.error("Errors occurred while syncing config from server: %s", err, exc_info=True)

		self.disconnectConfigService()
		self._working = False

	@classmethod
	def delete_cache_dir(cls) -> None:
		config_cache = Path(config.get("cache_service", "storage_dir")) / "config"
		if config_cache.exists():
			shutil.rmtree(config_cache)


class ProductCacheService(ServiceConnection, threading.Thread):
	def __init__(self, opsiclientd: Opsiclientd) -> None:
		threading.Thread.__init__(self, name="ProductCacheService")
		ServiceConnection.__init__(self, opsiclientd)

		self._updateConfig()

		self._stopped = False
		self._running = False
		self._working = False
		self._state: dict[str, Any] = {}

		self._impersonation = None
		self._cacheProductsRequested = False

		self._maxBandwidth = 0
		self._dynamicBandwidth = True

		self._productProgressObserver = None
		self._overallProgressObserver = None

		self._repository = None

		if not os.path.exists(self._storageDir):
			logger.notice("Creating cache service storage dir '%s'", self._storageDir)
			os.makedirs(self._storageDir)
		if not os.path.exists(self._tempDir):
			logger.notice("Creating cache service temp dir '%s'", self._tempDir)
			os.makedirs(self._tempDir)
		if not os.path.exists(self._productCacheDir):
			logger.notice("Creating cache service product cache dir '%s'", self._productCacheDir)
			os.makedirs(self._productCacheDir)

		pcss = state.get("product_cache_service")
		if pcss:
			self._state = pcss

	def _updateConfig(self):
		self._storageDir = config.get("cache_service", "storage_dir")
		self._tempDir = os.path.join(self._storageDir, "tmp")
		self._productCacheDir = os.path.join(self._storageDir, "depot")
		self._productCacheMaxSize = forceInt(config.get("cache_service", "product_cache_max_size"))

	def getProductCacheDir(self):
		return self._productCacheDir

	def getState(self) -> dict[str, Any]:
		_state = self._state
		_state["running"] = self.isRunning()
		_state["working"] = self.isWorking()
		_state["maxBandwidth"] = self._maxBandwidth
		_state["dynamicBandwidth"] = self._dynamicBandwidth
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

	def start_caching_or_get_waiting_time(self) -> float:
		try_after_seconds: float = 0.0
		heartbeat_thread = None

		depot_id = self._configService.configState_getClientToDepotserver(clientIds=config.get("global", "host_id"))[0]["depotId"]
		try:
			if hasattr(self._configService, "depot_acquireTransferSlot"):
				heartbeat_thread = TransferSlotHeartbeat(self._configService, depot_id, config.get("global", "host_id"))
				logger.notice("Acquiring transfer slot")
				response = heartbeat_thread.acquire()
				try_after_seconds = float(response.get("retry_after") or 0.0)
				logger.debug("depot_acquireTransferSlot produced response %s", response)
			if not try_after_seconds:
				if heartbeat_thread:
					logger.info("Starting transfer slot heartbeat thread")
					heartbeat_thread.start()
				logger.notice("Starting to cache products")
				self._cacheProducts()
				self._cacheProductsRequested = False
				logger.info("Finished caching products")
				return 1.0  # check again in 1 second if we have to cache
			logger.notice("Did not cache Products, server suggested waiting time of %s", try_after_seconds)
			return try_after_seconds
		finally:
			if heartbeat_thread:
				logger.debug("Releasing transfer slot %s", heartbeat_thread.slot_id)
				heartbeat_thread.should_stop = True
				if heartbeat_thread.is_alive():
					logger.debug("Joining transfer slot heartbeat thread")
					heartbeat_thread.join()

	def run(self):
		with log_context({"instance": "product cache service"}):
			self._running = True
			logger.notice("Product cache service started")
			try:
				while not self._stopped:
					sleep_time = 1.0
					if self._cacheProductsRequested and not self._working:
						if not self._configService:
							self.connectConfigService()
						sleep_time = self.start_caching_or_get_waiting_time()
					time.sleep(sleep_time)
			except Exception as err:
				logger.error(err, exc_info=True)
			finally:
				self.disconnectConfigService()
			logger.notice("Product cache service ended")
			self._running = False

	def clear_cache(self):
		timeline.addEvent(title="Clear product cache", description="Product cache deleted", category="product_caching")
		productCacheDir = self.getProductCacheDir()
		if os.path.exists(productCacheDir):
			for product in os.listdir(productCacheDir):
				deleteDir = os.path.join(productCacheDir, product)
				shutil.rmtree(deleteDir)
			self._state["products"] = {}
			self._state["products_cached"] = False
			state.set("product_cache_service", self._state)

	def cacheProducts(self, productProgressObserver=None, overallProgressObserver=None):
		self._cacheProductsRequested = True
		self._productProgressObserver = productProgressObserver
		self._overallProgressObserver = overallProgressObserver

	def connectConfigService(self, allowTemporaryConfigServiceUrls=True):
		ServiceConnection.connectConfigService(self, allowTemporaryConfigServiceUrls=False)
		try:
			try:
				if hasattr(self._configService, "backend_getLicensingInfo"):
					info = self._configService.backend_getLicensingInfo(licenses=False, legacy_modules=False, dates=False)
					logger.debug("Got licensing info from service: %s", info)
					if "vpn" not in info["available_modules"]:
						raise RuntimeError("Module 'vpn' not licensed")
				else:
					verify_modules(self._configService.backend_info(), ["vpn"])
			except Exception as err:
				raise RuntimeError("Cannot cache config: {err}") from err

			try:
				if self._configService.hostname.lower() not in ("localhost", "127.0.0.1", "::1"):
					client_to_depotservers = self._configService.configState_getClientToDepotserver(
						clientIds=config.get("global", "host_id")
					)
					if not client_to_depotservers:
						raise RuntimeError(f"Failed to get depotserver for client '{config.get('global', 'host_id')}'")
					depot_id = client_to_depotservers[0]["depotId"]
					config.set("depot_server", "master_depot_id", depot_id)
					config.updateConfigFile()
			except Exception as err:
				logger.warning(err)
		except Exception:
			self.disconnectConfigService()
			raise

	def _freeProductCacheSpace(self, neededSpace=0, neededProducts=[]):
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
				raise RuntimeError(
					f"Needed space: {(float(neededSpace) / (1000 * 1000)):0.3f} MB, "
					f"maximum freeable space: {(float(maxFreeableSize) / (1000 * 1000)):0.3f} MB "
					f"(max product cache size: {(float(self._productCacheMaxSize) / (1000 * 1000)):0.0f} MB)"
				)

			freedSpace = 0
			while freedSpace < neededSpace:
				deleteProduct = None
				eldestTime = None
				for product, _size in productDirSizes.items():
					packageContentFile = os.path.join(self._productCacheDir, product, f"{product}.files")
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
					raise RuntimeError("Internal error")

				deleteDir = os.path.join(self._productCacheDir, deleteProduct)
				logger.notice("Deleting product cache directory '%s'", deleteDir)
				if not os.path.exists(deleteDir):
					raise RuntimeError(f"Directory '{deleteDir}' not found")

				shutil.rmtree(deleteDir)
				freedSpace += productDirSizes[deleteProduct]
				if self._state.get("products", {}).get(deleteProduct):
					del self._state["products"][deleteProduct]
					state.set("product_cache_service", self._state)

				del productDirSizes[deleteProduct]

			logger.notice("%0.3f MB of product cache freed", float(freedSpace) / (1000 * 1000))
		except Exception as err:
			raise RuntimeError(f"Failed to free enough disk space for product cache: {err}") from err

	def _cacheProducts(self):
		self._updateConfig()
		self._working = True
		self._state["products_cached"] = False
		self._state["products"] = {}
		state.set("product_cache_service", self._state)
		eventId = None

		try:
			if not self._configService:
				self.connectConfigService()

			includeProductIds, excludeProductIds = get_include_exclude_product_ids(
				self._configService,
				config.get("cache_service", "include_product_group_ids"),
				config.get("cache_service", "exclude_product_group_ids"),
			)

			productIds = []
			productOnClients = [
				poc
				for poc in self._configService.productOnClient_getObjects(
					productType="LocalbootProduct",
					clientId=config.get("global", "host_id"),
					actionRequest=["setup", "uninstall", "update", "always", "once", "custom"],
					attributes=["actionRequest"],
					productId=includeProductIds,
				)
				if poc.productId not in excludeProductIds
			]

			for productOnClient in productOnClients:
				if productOnClient.productId not in productIds:
					productIds.append(productOnClient.productId)

			productIds += add_products_from_setup_after_install(productIds, self._configService)

			if not productIds:
				logger.notice("No product action request set => no products to cache")
			else:
				masterDepotId = config.get("depot_server", "master_depot_id")

				# Get all productOnDepots!
				productOnDepots = self._configService.productOnDepot_getObjects(depotId=masterDepotId)
				productOnDepotIds = [productOnDepot.productId for productOnDepot in productOnDepots]
				logger.debug("Product ids on depot %s: %s", masterDepotId, productOnDepotIds)
				errorProductIds = []
				for productOnClient in productOnClients:
					if productOnClient.productId not in productOnDepotIds:
						logger.error(
							"Requested product: '%s' not found on configured depot: '%s', please check your configuration, setting product to failed.",
							productOnClient.productId,
							masterDepotId,
						)
						self._setProductCacheState(productOnClient.productId, "failure", "Product not found on configured depot.")
						errorProductIds.append(productOnClient.productId)

				productIds.append(config.action_processor_name)
				if "mshotfix" in productIds:
					additionalProductId = System.getOpsiHotfixName()
					if "win10" in additionalProductId or "win11" in additionalProductId:
						releaseId = None
						currentBuild = None
						subKey = "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion"
						try:
							currentBuild = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, subKey, "CurrentBuild")
						except Exception as reg_err:
							logger.error("Failed to read registry value %s %s: %s", subKey, "CurrentBuild", reg_err)
						try:
							releaseId = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, subKey, "ReleaseID")
						except Exception as reg_err:
							logger.error("Failed to read registry value %s %s: %s", subKey, "ReleaseID", reg_err)

						releasePackageName = None
						if currentBuild == "20348":
							releasePackageName = "mshotfix-win2022"
						elif currentBuild == "22000":
							releasePackageName = "mshotfix-win11-21h2"
						elif currentBuild == "22621":
							releasePackageName = "mshotfix-win11-22h2"
						elif int(currentBuild) > 22621:
							logger.warning(
								"Unknown windows build %s. Maybe update opsi-client-agent. Using fallback mshotfix-win11-22h2", currentBuild
							)
							releasePackageName = "mshotfix-win11-22h2"
						else:  # win10
							# Setting default to 1507-Build
							if not releaseId:
								releaseId = "1507"
							arch = additionalProductId.split("-")[-2]  # id is like f"mshotfix-{_os}-{arch}-{lang}"
							releasePackageName = f"mshotfix-win10-{releaseId}-{arch}-glb"
						if releasePackageName and releasePackageName in productOnDepotIds:
							logger.info("Releasepackage '%s' found on depot '%s'", releasePackageName, masterDepotId)
							additionalProductId = releasePackageName
						else:
							logger.error("Did not find release-specific mshotfix package.")
							additionalProductId = None
					if additionalProductId:
						logger.info(
							"Requested to cache product mshotfix => additionaly caching system specific mshotfix product: %s",
							additionalProductId,
						)
						if additionalProductId not in productIds:
							productIds.append(additionalProductId)

				if errorProductIds:
					for index in range(len(productIds) - 1):
						if productIds[index] in errorProductIds:
							logger.error("ProductId: '%s' will not be cached.", productIds[index])
							del productIds[index]

				if len(productIds) == 1 and productIds[0] == config.action_processor_name:
					logger.notice(
						"Only opsi-script is set to install, doing nothing, "
						"because a up- or downgrade from opsi-script is only need if a other product is set to setup."
					)
				else:
					p_list = ", ".join(productIds)
					logger.notice("Caching products: %s", p_list)
					eventId = timeline.addEvent(
						title="Cache products", description=f"Caching products: {p_list}", category="product_caching", durationEvent=True
					)

					errorsOccured = []
					try:
						for productId in productIds:
							try:
								self._cacheProduct(productId, productIds)
							except Exception as err:
								errorsOccured.append(str(err))
								self._setProductCacheState(productId, "failure", forceUnicode(err))
					except Exception as err:
						logger.error("%s", err, exc_info=True)
						errorsOccured.append(forceUnicode(err))

					if errorsOccured:
						e_list = ", ".join(errorsOccured)
						logger.error("Errors occurred while caching products %s: %s", p_list, e_list)
						timeline.addEvent(
							title="Failed to cache products",
							description=f"Errors occurred while caching products {p_list}: {e_list}",
							category="product_caching",
							isError=True,
						)
					else:
						logger.notice("All products cached: %s", p_list)
						with sync_completed_lock:
							self._state["products_cached"] = True
							state.set("product_cache_service", self._state)

							for eventGenerator in getEventGenerators(generatorClass=SyncCompletedEventGenerator):
								eventGenerator.createAndFireEvent()
		except Exception as err:
			logger.error("Failed to cache products: %s", err, exc_info=True)
			timeline.addEvent(
				title="Failed to cache products", description=f"Failed to cache products: {err}", category="product_caching", isError=True
			)

		if eventId:
			timeline.setEventEnd(eventId)

		self._working = False
		if self._repository:
			self._repository.disconnect()
			self._repository = None

	def _setProductCacheState(self, productId, key, value, updateProductOnClient=True):
		if "products" not in self._state:
			self._state["products"] = {}
		if productId not in self._state["products"]:
			self._state["products"][productId] = {}

		self._state["products"][productId][key] = value
		state.set("product_cache_service", self._state)
		actionProgress = None
		installationStatus = None
		actionResult = None
		actionRequest = None

		if key == "started":
			actionProgress = "caching"
		elif key == "completed":
			actionProgress = "cached"
		elif key == "failure":
			actionProgress = f"Cache failure: {value}"
			installationStatus = "unknown"
			actionResult = "failed"
			if "MD5sum mismatch" in forceUnicode(value):
				actionRequest = "none"

		if actionProgress and updateProductOnClient:
			self._configService.productOnClient_updateObjects(
				[
					ProductOnClient(
						productId=productId,
						productType="LocalbootProduct",
						clientId=config.get("global", "host_id"),
						actionProgress=actionProgress,
						installationStatus=installationStatus,
						actionResult=actionResult,
						actionRequest=actionRequest,
					)
				]
			)

	def _getRepository(self, productId):
		config.selectDepotserver(configService=self._configService, mode="sync", event=None, productIds=[productId])
		if not config.get("depot_server", "url"):
			raise RuntimeError("Cannot cache product files: depot_server.url undefined")

		depotServerUsername = ""
		depotServerPassword = ""

		url = urlparse(config.get("depot_server", "url"))
		if url.scheme.startswith("webdav"):
			depotServerUsername = config.get("global", "host_id")
			depotServerPassword = config.get("global", "opsi_host_key")

			kwargs = {"username": depotServerUsername, "password": depotServerPassword}
			if url.scheme.startswith("webdavs"):
				kwargs["verify_server_cert"] = (
					config.get("global", "verify_server_cert") or config.get("global", "verify_server_cert_by_ca")
				) and os.path.exists(config.ca_cert_file)
				kwargs["ca_cert_file"] = config.ca_cert_file if kwargs["verify_server_cert"] else None
				kwargs["proxy_url"] = config.get("global", "proxy_url")
				kwargs["ip_version"] = config.get("global", "ip_version")

			return getRepository(config.get("depot_server", "url"), **kwargs)

		if self._impersonation:
			try:
				self._impersonation.end()
			except Exception as err:
				logger.warning(err)

		(depotServerUsername, depotServerPassword) = config.getDepotserverCredentials(configService=self._configService)
		mount = True
		if RUNNING_ON_WINDOWS:
			self._impersonation = System.Impersonate(username=depotServerUsername, password=depotServerPassword)
			self._impersonation.start(logonType="NEW_CREDENTIALS")
			mount = False
		mount_point = None
		if RUNNING_ON_DARWIN:
			mount_point = str(Path(config.get("depot_server", "drive")).parent / f".cifs-mount.{randomString(5)}")
		self._repository = getRepository(
			config.get("depot_server", "url"),
			username=depotServerUsername,
			password=depotServerPassword,
			mount=mount,
			mountPoint=mount_point,
		)
		return self._repository

	def _cacheProduct(self, productId, neededProducts):
		logger.notice(
			"Caching product '%s' (max bandwidth: %s, dynamic bandwidth: %s)", productId, self._maxBandwidth, self._dynamicBandwidth
		)
		self._setProductCacheState(productId, "started", time.time())
		self._setProductCacheState(productId, "completed", None, updateProductOnClient=False)
		self._setProductCacheState(productId, "failure", None, updateProductOnClient=False)

		eventId = None
		repository = None
		exception = None
		product_version = None
		try:
			repository = self._getRepository(productId)
			masterDepotId = config.get("depot_server", "master_depot_id")
			if not masterDepotId:
				raise ValueError("Cannot cache product files: depot_server.master_depot_id undefined")

			productOnDepots = self._configService.productOnDepot_getObjects(depotId=masterDepotId, productId=productId)
			if not productOnDepots:
				raise RuntimeError(f"Product '{productId}' not found on depot '{masterDepotId}'")

			product_version = f"{productOnDepots[0].productVersion}-{productOnDepots[0].packageVersion}"
			self._setProductCacheState(productId, "productVersion", productOnDepots[0].productVersion, updateProductOnClient=False)
			self._setProductCacheState(productId, "packageVersion", productOnDepots[0].packageVersion, updateProductOnClient=False)

			if not os.path.exists(os.path.join(self._productCacheDir, productId)):
				os.mkdir(os.path.join(self._productCacheDir, productId))

			packageContentFile = f"{productId}/{productId}.files"
			localPackageContentFile = os.path.join(self._productCacheDir, productId, f"{productId}.files")
			repository.download(source=packageContentFile, destination=localPackageContentFile)
			packageInfo = PackageContentFile(localPackageContentFile).parse()
			productSize = 0
			fileCount = 0
			for value in packageInfo.values():
				if "size" in value:
					fileCount += 1
					productSize += int(value["size"])

			logger.info(
				"Product '%s' contains %d files with a total size of %0.3f MB", productId, fileCount, float(productSize) / (1000 * 1000)
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
						float(productSize) / (1000 * 1000),
					)
					freeSpace = self._productCacheMaxSize - productCacheDirSize
					neededSpace = productSize - freeSpace + 1000
					self._freeProductCacheSpace(neededSpace=neededSpace, neededProducts=neededProducts)
					productCacheDirSize = System.getDirectorySize(self._productCacheDir)

			diskFreeSpace = System.getDiskSpaceUsage(self._productCacheDir)["available"]
			if diskFreeSpace < productSize + 500 * 1000 * 1000:
				raise RuntimeError(
					f"Only {(float(diskFreeSpace) / (1000 * 1000)):0.3f} MB free space available on disk, failed to cache product files"
				)

			eventId = timeline.addEvent(
				title=f"Cache product {productId} {product_version}",
				description=(
					f"Caching product '{productId}' ({product_version}) of size {(float(productSize) / (1000 * 1000)):0.2f} MB\n"
					f"max bandwidth: {self._maxBandwidth}, dynamic bandwidth: {self._dynamicBandwidth}"
				),
				category="product_caching",
				durationEvent=True,
			)

			productSynchronizer = DepotToLocalDirectorySychronizer(
				sourceDepot=repository,
				destinationDirectory=self._productCacheDir,
				productIds=[productId],
				maxBandwidth=self._maxBandwidth,
				dynamicBandwidth=self._dynamicBandwidth,
			)
			productSynchronizer.synchronize(
				productProgressObserver=self._productProgressObserver, overallProgressObserver=self._overallProgressObserver
			)
			logger.notice("Product '%s' (%s) cached", productId, product_version)
			self._setProductCacheState(productId, "completed", time.time())
		except Exception as err:
			logger.error("Failed to cache product %s: %s", productId, err, exc_info=True)
			exception = err
			timeline.addEvent(
				title=f"Failed to cache product {productId}",
				description=f"Failed to cache product '{productId}': {err}",
				category="product_caching",
				isError=True,
			)

		if eventId:
			timeline.setEventEnd(eventId)

		if repository:
			try:
				repository.disconnect()
			except Exception as err:
				logger.warning("Failed to disconnect from repository: %s", err)

		if self._impersonation:
			try:
				self._impersonation.end()
			except Exception as err:
				logger.warning(err)

		if exception is not None:
			raise exception
