# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2026 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.

"""
opsiclientd.nonfree.CacheService

@copyright:	uib GmbH <info@uib.de>
"""

from __future__ import annotations

import collections
import os
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Type
from urllib.parse import urlparse

from opsi.crypt.secret import SecretAlphabet, generate_secret
from opsi_legacy import System
from opsi_legacy.Backend.Backend import Backend, ExtendedConfigDataBackend
from opsi_legacy.Backend.BackendManager import BackendExtender
from opsi_legacy.Backend.SQLite import SQLiteBackend, SQLiteObjectBackendModificationTracker
from opsi_legacy.Util.File.Opsi import PackageContentFile
from opsi_legacy.Util.Message import ProgressSubjectProxy
from opsi_legacy.Util.Repository import Repository, getRepository
from opsi.logging import get_logger, log_context
from opsi.opsi.service.model.object import LocalbootProduct, ProductOnClient
from opsi.opsi.service.model.type import to_bool, to_int, to_product_id_list
from packaging import version

from opsiclientd.Config import Config
from opsiclientd.Events.SyncCompleted import SyncCompletedEventGenerator
from opsiclientd.Events.Utilities.Generators import getEventGenerators
from opsiclientd.Events.Windows.WinRT import WinRTNetworkStatusMonitor
from opsiclientd.nonfree.CacheBackend import ClientCacheBackend, add_products_from_setup_after_install
from opsiclientd.nonfree.DepotSync import DepotToLocalDirectorySynchronizer
from opsiclientd.nonfree.RPCProductDependencyMixin import RPCProductDependencyMixin
from opsiclientd.OpsiService import PermanentServiceConnection, ServiceClient
from opsiclientd.State import State
from opsiclientd.SystemCheck import RUNNING_ON_DARWIN, RUNNING_ON_WINDOWS
from opsiclientd.Timeline import Timeline
from opsiclientd.utils import get_directory_size, get_disk_space_usage, get_include_exclude_product_ids, get_mshotfix_package_name

if TYPE_CHECKING:
	from opsiclientd.Opsiclientd import Opsiclientd

__all__ = ["CacheService", "ConfigCacheService", "ProductCacheService"]

config = Config()
state = State()
timeline = Timeline()
sync_completed_lock = threading.Lock()
RETENTION_HEARTBEAT_INTERVAL_DIFF = 10.0
MIN_HEARTBEAT_INTERVAL = 1.0
logger = get_logger()


class TransferSlotHeartbeat(threading.Thread):
	def __init__(self, depot_id: str, client_id: str) -> None:
		super().__init__(daemon=True)
		self.should_stop = False
		self.depot_id = depot_id
		self.client_id = client_id
		self.slot_id = None

	@property
	def service_client(self) -> ServiceClient:
		return PermanentServiceConnection().service_client

	def acquire(self) -> dict[str, str | float]:
		response = self.service_client.depot_acquireTransferSlot(self.depot_id, self.client_id, self.slot_id)  # ty: ignore[unresolved-attribute]
		self.slot_id = response.get("slot_id")
		logger.debug("Transfer slot Heartbeat %s, response: %s", self.slot_id, response)
		return response

	def release(self) -> None:
		response = self.service_client.depot_releaseTransferSlot(self.depot_id, self.client_id, self.slot_id)  # ty: ignore[unresolved-attribute]
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
	def __init__(self, opsiclientd: Opsiclientd) -> None:
		threading.Thread.__init__(self, name="CacheService")
		self._opsiclientd = opsiclientd
		self._productCacheService: ProductCacheService | None = None
		self._configCacheService: ConfigCacheService | None = None

	@property
	def service_client(self) -> ServiceClient:
		return PermanentServiceConnection(self._opsiclientd).service_client

	def stop(self) -> None:
		if self._productCacheService:
			self._productCacheService.stop()
		if self._configCacheService:
			self._configCacheService.stop()

	def initializeProductCacheService(self) -> None:
		if not self._productCacheService:
			self._productCacheService = ProductCacheService(self._opsiclientd)
			self._productCacheService.start()

	def initializeConfigCacheService(self) -> None:
		if not self._configCacheService:
			self._configCacheService = ConfigCacheService(self._opsiclientd)
			self._configCacheService.start()

	def setConfigCacheObsolete(self) -> None:
		self.initializeConfigCacheService()
		assert self._configCacheService
		self._configCacheService.setObsolete()

	def setConfigCacheFaulty(self) -> None:
		self.initializeConfigCacheService()
		assert self._configCacheService
		self._configCacheService.setFaulty()

	def syncConfig(self, waitForEnding: bool = False, force: bool = False) -> None:
		self.initializeConfigCacheService()
		assert self._configCacheService
		if self._configCacheService.isWorking():
			logger.info("Already syncing config")
		else:
			logger.info("Trigger config sync")
			self._configCacheService.syncConfig(force)

		if waitForEnding:
			time.sleep(3)
			while self._configCacheService.isRunning() and self._configCacheService.isWorking():
				time.sleep(1)

	def syncConfigToServer(self, waitForEnding: bool = False) -> None:
		self.initializeConfigCacheService()
		assert self._configCacheService
		if self._configCacheService.isWorking():
			logger.info("Already syncing config")
			return
		logger.info("Trigger config sync to server")
		self._configCacheService.syncConfigToServer()

		if waitForEnding:
			time.sleep(3)
			while self._configCacheService.isRunning() and self._configCacheService.isWorking():
				time.sleep(1)

	def isConfigCacheServiceWorking(self) -> bool:
		self.initializeConfigCacheService()
		assert self._configCacheService
		return self._configCacheService.isWorking()

	def syncConfigFromServer(self, waitForEnding: bool = False) -> None:
		self.initializeConfigCacheService()
		assert self._configCacheService
		if self._configCacheService.isWorking():
			logger.info("Already syncing config")
			return

		logger.info("Trigger config sync from server")
		self._configCacheService.syncConfigFromServer()

		if waitForEnding:
			time.sleep(3)
			while self._configCacheService.isRunning() and self._configCacheService.isWorking():
				time.sleep(1)

	def configCacheCompleted(self) -> bool:
		try:
			self.initializeConfigCacheService()
		except Exception as cacheInitError:
			logger.info(cacheInitError, exc_info=True)
			logger.error(cacheInitError)
			return False

		assert self._configCacheService
		if not self._configCacheService.isWorking() and self._configCacheService.getState().get("config_cached", False):
			return True

		return False

	def getConfigBackend(self) -> Backend:
		self.initializeConfigCacheService()
		assert self._configCacheService
		return self._configCacheService.getConfigBackend()

	def getConfigModifications(self) -> dict[str, Any]:
		self.initializeConfigCacheService()
		assert self._configCacheService
		return self._configCacheService._backendTracker.getModifications()

	def isProductCacheServiceWorking(self) -> bool:
		self.initializeProductCacheService()
		assert self._productCacheService
		return self._productCacheService.isWorking()

	def cacheProducts(
		self,
		waitForEnding: bool = False,
		productProgressObserver: ProgressSubjectProxy | None = None,
		overallProgressObserver: ProgressSubjectProxy | None = None,
		dynamicBandwidth: bool = True,
		maxBandwidth: int = 0,
		fireSyncCompletedEvent: bool = True,
	) -> None:
		self.initializeProductCacheService()
		assert self._productCacheService
		if self._productCacheService.isWorking():
			logger.info("Already caching products")
			return

		if self._configCacheService and self._configCacheService.syncConfigToServerError:
			raise RuntimeError("Failed to cache products because config sync to server failed")

		logger.info("Trigger product caching")
		self._productCacheService.setDynamicBandwidth(dynamicBandwidth)
		self._productCacheService.setMaxBandwidth(maxBandwidth)
		self._productCacheService.cacheProducts(
			productProgressObserver=productProgressObserver,
			overallProgressObserver=overallProgressObserver,
			fireSyncCompletedEvent=fireSyncCompletedEvent,
		)

		if waitForEnding:
			time.sleep(3)
			while self._productCacheService.isRunning() and self._productCacheService.isWorking():
				time.sleep(1)

	def productCacheCompleted(self, configService: ServiceClient, productIds: list[str], checkCachedProductVersion: bool = False) -> bool:
		logger.debug("productCacheCompleted: configService=%s productIds=%s", configService, productIds)
		if not productIds:
			return True

		workingWithCachedConfig = configService.service_is_opsiclientd()

		self.initializeProductCacheService()
		assert self._productCacheService

		masterDepotId = config.get("depot_server", "master_depot_id")
		if workingWithCachedConfig:
			depotIds = []
			for depot in configService.host_getObjects(type="OpsiDepotserver"):  # ty: ignore[unresolved-attribute]
				depotIds.append(depot.id)
			if masterDepotId not in depotIds:
				self.setConfigCacheFaulty()
				raise RuntimeError(
					f"Config cache problem: depot '{masterDepotId}' not available in cached depots: {depotIds}."
					" Probably the depot was switched after the last config sync from server."
				)

		productOnDepots = {
			productOnDepot.productId: productOnDepot
			for productOnDepot in configService.productOnDepot_getObjects(depotId=masterDepotId, productId=productIds)  # ty: ignore[unresolved-attribute]
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
		assert self._productCacheService
		return self._productCacheService.getState()

	def getConfigCacheState(self) -> dict[str, Any]:
		self.initializeConfigCacheService()
		assert self._configCacheService
		return self._configCacheService.getState()

	def getProductCacheDir(self) -> str:
		self.initializeProductCacheService()
		assert self._productCacheService
		return self._productCacheService.getProductCacheDir()

	def clear_product_cache(self) -> None:
		self.initializeProductCacheService()
		assert self._productCacheService
		return self._productCacheService.clear_cache()


class ConfigCacheServiceBackendExtension42(RPCProductDependencyMixin):
	def accessControl_authenticated(self) -> bool:
		return True


class ConfigCacheServiceBackendExtension43(RPCProductDependencyMixin):
	def accessControl_authenticated(self) -> bool:
		return True

	def productOnClient_getActionGroups(self, clientId: str) -> list[dict[str, Any]]:
		"""
		Get product action groups of action requests set for a client.
		"""
		product_on_clients = self.productOnClient_getObjects(clientId=clientId)  # ty: ignore[unresolved-attribute]

		action_groups: list[dict] = []
		for group in self.get_product_action_groups(product_on_clients).get(clientId, []):
			group.product_on_clients = [  # ty: ignore[invalid-assignment]
				poc.to_hash() for poc in group.product_on_clients if poc.actionRequest and poc.actionRequest != "none"
			]
			if group.product_on_clients:
				group.dependencies = {  # ty: ignore[invalid-assignment]
					product_id: [d.to_hash() for d in dep] for product_id, dep in group.dependencies.items()
				}
				action_groups.append(group)  # ty: ignore[invalid-argument-type]

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
			return self.productOnClient_getObjects(attributes, **filter)  # ty: ignore[unresolved-attribute]

		product_on_clients = self.productOnClient_getObjects(attributes, **filter)  # ty: ignore[unresolved-attribute]
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
		for product in self.product_getObjects(type="LocalbootProduct"):  # ty: ignore[unresolved-attribute]
			products_by_id_and_version[(product.id, product.productVersion, product.packageVersion)] = product

		product_ids = []
		product_on_clients = []
		for product_on_depot in self.productOnDepot_getObjects(depotId=depotId, productType="LocalbootProduct"):  # ty: ignore[unresolved-attribute]
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


def init_from_service(service_client: ServiceClient) -> None:
	try:
		info = service_client.backend_getLicensingInfo(licenses=False, legacy_modules=False, dates=False)  # ty: ignore[unresolved-attribute]
		logger.debug("Got licensing info from service: %s", info)
		if "vpn" not in info["available_modules"]:
			raise RuntimeError("WAN/VPN module not licensed")
	except Exception as err:
		raise RuntimeError(f"Cannot sync config: {err}") from err

	try:
		if not service_client.service_is_opsiclientd():
			client_to_depotservers = service_client.configState_getClientToDepotserver(  # ty: ignore[unresolved-attribute]
				clientIds=config.get("global", "host_id")
			)
			if not client_to_depotservers:
				raise RuntimeError(f"Failed to get depotserver for client '{config.get('global', 'host_id')}'")
			depot_id = client_to_depotservers[0]["depotId"]
			config.set("depot_server", "master_depot_id", depot_id)
			config.updateConfigFile()
	except Exception as err:
		logger.warning(err)


class ConfigCacheService(threading.Thread):
	def __init__(self, opsiclientd: Opsiclientd) -> None:
		try:
			threading.Thread.__init__(self, name="ConfigCacheService")
			self.opsiclientd = opsiclientd

			self._configBackend: Backend | None = None
			self._configCacheDir = os.path.join(config.get("cache_service", "storage_dir"), "config")
			self._opsiPasswdFile = os.path.join(self._configCacheDir, "cached_passwd")
			self._auditHardwareConfigFile = os.path.join(self._configCacheDir, "cached_opsihwaudit.json")
			self._configValuesCacheFile = os.path.join(self._configCacheDir, "cached_configvalues.json")
			self._productPropertyValuesCacheFile = os.path.join(self._configCacheDir, "cached_productpropertyvalues.json")

			self._stopped = False
			self._running = False
			self._working = False
			self._state: dict[str, Any] = {}

			self._syncConfigFromServerRequested = False
			self._syncConfigToServerError: Exception | None = None
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
	def service_client(self) -> ServiceClient:
		return PermanentServiceConnection(self.opsiclientd).main_service_client

	@property
	def syncConfigToServerError(self) -> Exception | None:
		return self._syncConfigToServerError

	def initBackends(self) -> None:
		clientId = config.get("global", "host_id")
		depot_id = config.get("depot_server", "master_depot_id") or config.get("depot_server", "depot_id")
		backendArgs = {
			"opsiPasswdFile": self._opsiPasswdFile,
			"auditHardwareConfigFile": self._auditHardwareConfigFile,
			"configValuesCacheFile": self._configValuesCacheFile,
			"productPropertyValuesCacheFile": self._productPropertyValuesCacheFile,
			"depotId": depot_id,
		}
		self._workBackend = SQLiteBackend(database=os.path.join(self._configCacheDir, "work.sqlite"), **backendArgs)
		self._workBackend.backend_createBase()

		self._snapshotBackend = SQLiteBackend(database=os.path.join(self._configCacheDir, "snapshot.sqlite"), **backendArgs)
		self._snapshotBackend.backend_createBase()

		self._cacheBackend = ClientCacheBackend(
			workBackend=self._workBackend,
			snapshotBackend=self._snapshotBackend,
			clientId=clientId,
			backendInfo={"opsiVersion": self._state.get("server_version", "4.3.0.0"), "modules": {"valid": False}, "realmodules": {}},
			**backendArgs,
		)

		self._createConfigBackend()

		self._backendTracker = SQLiteObjectBackendModificationTracker(
			database=os.path.join(self._configCacheDir, "tracker.sqlite"), lastModificationOnly=True
		)
		self._cacheBackend.addBackendChangeListener(self._backendTracker)

	def _createConfigBackend(self) -> None:
		extension_class: Type[ConfigCacheServiceBackendExtension43] | Type[ConfigCacheServiceBackendExtension42] = (
			ConfigCacheServiceBackendExtension43
		)
		server_version = version.parse(self._state.get("server_version", "4.3.0.0"))
		if server_version < version.parse("4.3"):
			extension_class = ConfigCacheServiceBackendExtension42
		logger.notice("Using extension class %r for server version %s", extension_class, server_version)

		self._configBackend = BackendExtender(
			backend=ExtendedConfigDataBackend(configDataBackend=self._cacheBackend),
			extensionClass=extension_class,
			extensionConfigDir=config.get("cache_service", "extension_config_dir"),
			extensionReplaceMethods=False,
		)

	def getConfigBackend(self) -> Backend:
		assert self._configBackend
		return self._configBackend

	def getState(self) -> dict[str, Any]:
		_state = self._state
		_state["running"] = self.isRunning()
		_state["working"] = self.isWorking()
		return _state

	def setObsolete(self) -> None:
		self._state["config_cached"] = False
		state.set("config_cache_service", self._state)

	def setFaulty(self) -> None:
		self._forceSync = True
		self.setObsolete()

	def isRunning(self) -> bool:
		return self._running

	def isWorking(self) -> bool:
		return self._working

	def stop(self) -> None:
		self._stopped = True

	def run(self) -> None:
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

	def syncConfig(self, force: bool = False) -> None:
		self._forceSync = bool(force)
		self._syncConfigToServerRequested = True
		self._syncConfigFromServerRequested = True

	def syncConfigToServer(self) -> None:
		self._syncConfigToServerRequested = True

	def syncConfigFromServer(self) -> None:
		self._syncConfigFromServerRequested = True

	def _syncConfigToServer(self) -> None:
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
					init_from_service(service_client=self.service_client)
					self._cacheBackend._setMasterBackend(self.service_client)
					self._cacheBackend._updateMasterFromWorkBackend(modifications)
					logger.info("Clearing modifications in tracker")
					self._backendTracker.clearModifications()
					try:
						instlog = os.path.join(config.get("global", "log_dir"), "opsi-script.log")
						if not RUNNING_ON_WINDOWS:
							# for posix, instlogs are collected in opsi-script directory
							instlog = os.path.join(config.get("global", "log_dir"), "opsi-script", "opsi-script.log")
						logger.debug("Checking if a custom logfile is given in global action_processor section")
						try:
							commandParts = config.get("action_processor", "command").split()
							if "/logfile" in commandParts:
								instlog = commandParts[commandParts.index("/logfile") + 1]
							if "-logfile" in commandParts:
								instlog = commandParts[commandParts.index("-logfile") + 1]
						except Exception:
							logger.warning("Failed to get custom logfile from action_processor command")

						if os.path.isfile(instlog):
							logger.info("Syncing instlog %s", instlog)
							with open(instlog, "r", encoding="utf-8", errors="replace") as file:
								data = file.read()

							self.service_client.log_write("instlog", data=data, objectId=config.get("global", "host_id"), append=False)  # ty: ignore[unresolved-attribute]
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
		self._working = False

	def _syncConfigFromServer(self) -> None:
		self._working = True
		try:
			if self._syncConfigToServerError:
				raise RuntimeError("Sync config to server failed")
			self.setObsolete()
			init_from_service(service_client=self.service_client)

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
					self.service_client,
					config.get("cache_service", "include_product_group_ids"),
					config.get("cache_service", "exclude_product_group_ids"),
				)

				productOnClients = [
					poc
					for poc in self.service_client.productOnClient_getObjects(  # ty: ignore[unresolved-attribute]
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
					self._cacheBackend._setMasterBackend(self.service_client)
					logger.info("Clearing modifications in tracker")
					self._backendTracker.clearModifications()
					self._cacheBackend._replicateMasterToWorkBackend()
					logger.notice("Config synced from server")
					self._state["server_version"] = str(self.service_client.server_version)
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

		self._working = False

	@classmethod
	def delete_cache_dir(cls) -> None:
		config_cache = Path(config.get("cache_service", "storage_dir")) / "config"
		if config_cache.exists():
			shutil.rmtree(config_cache)


class ProductCacheException(Exception):
	ExceptionShortDescription = "Product cache error"

	def __init__(self, message: str, *, product_id: str | None = None) -> None:
		super().__init__(message)
		self.message = message
		self.product_id = product_id

	def __str__(self) -> str:
		if self.product_id:
			return f"{self.message} ({self.product_id})"
		return self.message

	def __repr__(self) -> str:
		return f"{self.__class__.__name__}({str(self)})"


class ProductCacheInsufficientCacheSpaceException(ProductCacheException):
	ExceptionShortDescription = "Insufficient space for product cache"


class ProductCacheService(threading.Thread):
	_storage_dir: Path
	_temp_dir: Path
	_product_cache_dir: Path
	_product_cache_max_size: int
	min_free_disk_space = 500_000_000

	def __init__(self, opsiclientd: Opsiclientd) -> None:
		threading.Thread.__init__(self, name="ProductCacheService")
		self.opsiclientd = opsiclientd

		self._updateConfig()

		self._stopped = False
		self._running = False
		self._working = False
		self._state: dict[str, Any] = {}
		self._cache_dir_sizes: dict[str, int] = {}
		self._cache_dir_lock = threading.Lock()
		self.last_errors: list[Exception] = []

		self._impersonation: System.Impersonate | None = None
		self._cache_products_requested = False
		self._fire_sync_completed_event = True

		self._max_bandwidth = 0
		self._dynamic_andwidth = True

		self._product_progress_observer: ProgressSubjectProxy | None = None
		self._overall_progress_observer: ProgressSubjectProxy | None = None

		self._repository: Repository | None = None

		self._continue_event = threading.Event()
		self._continue_event.set()
		self._pause_event_id = 0
		self._pause_on_metered = config.get("cache_service", "pause_on_metered")
		self._network_monitor: WinRTNetworkStatusMonitor | None = None

		if not self._storage_dir.exists():
			logger.notice("Creating cache service storage dir '%s'", self._storage_dir)
			self._storage_dir.mkdir(parents=True)
		if not self._temp_dir.exists():
			logger.notice("Creating cache service temp dir '%s'", self._temp_dir)
			self._temp_dir.mkdir(parents=True)
		if not self._product_cache_dir.exists():
			logger.notice("Creating cache service product cache dir '%s'", self._product_cache_dir)
			self._product_cache_dir.mkdir(parents=True)

		pcss = state.get("product_cache_service")
		if pcss:
			self._state = pcss

		self.update_cache_dir_sizes(force=True)

	@property
	def service_client(self) -> ServiceClient:
		return PermanentServiceConnection(self.opsiclientd).service_client

	def _updateConfig(self) -> None:
		self._storage_dir = Path(config.get("cache_service", "storage_dir"))
		self._temp_dir = self._storage_dir / "tmp"
		self._product_cache_dir = self._storage_dir / "depot"
		self._product_cache_max_size = to_int(config.get("cache_service", "product_cache_max_size"))

	def update_cache_dir_sizes(self, *, product_id: str | None = None, force: bool = False) -> None:
		with self._cache_dir_lock:
			if force:
				if product_id:
					self._cache_dir_sizes.pop(product_id, None)
				else:
					self._cache_dir_sizes = {}
			for product_cache_dir in self._product_cache_dir.iterdir():
				if (
					product_cache_dir.is_dir()
					and product_cache_dir.name not in self._cache_dir_sizes
					and (not product_id or product_id == product_cache_dir.name)
				):
					self._cache_dir_sizes[product_cache_dir.name] = get_directory_size(product_cache_dir)

	def get_cache_dir_size(self, product_id: str | None = None) -> int:
		self.update_cache_dir_sizes()
		with self._cache_dir_lock:
			if product_id:
				return self._cache_dir_sizes.get(product_id, 0)
			return sum(self._cache_dir_sizes.values())

	def getProductCacheDir(self) -> str:
		return str(self._product_cache_dir)

	def getState(self) -> dict[str, Any]:
		_state = self._state
		_state["running"] = self.isRunning()
		_state["working"] = self.isWorking()
		_state["maxBandwidth"] = self._max_bandwidth
		_state["dynamicBandwidth"] = self._dynamic_andwidth
		return _state

	def isRunning(self) -> bool:
		return self._running

	def isWorking(self) -> bool:
		return self._working

	def stop(self) -> None:
		self._stopped = True
		if self._network_monitor:
			self._network_monitor.stop()
			self._network_monitor = None

	def setMaxBandwidth(self, maxBandwidth: int) -> None:
		self._max_bandwidth = to_int(maxBandwidth)

	def setDynamicBandwidth(self, dynamicBandwidth: bool) -> None:
		self._dynamic_andwidth = to_bool(dynamicBandwidth)

	def start_caching_or_get_waiting_time(self) -> float:
		try_after_seconds: float = 0.0
		heartbeat_thread = None

		depot_id = self.service_client.configState_getClientToDepotserver(clientIds=config.get("global", "host_id"))[0]["depotId"]  # ty: ignore[unresolved-attribute]
		try:
			if hasattr(self.service_client, "depot_acquireTransferSlot"):
				heartbeat_thread = TransferSlotHeartbeat(depot_id, config.get("global", "host_id"))
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
				self._cache_products_requested = False
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

	def pause_caching(self, reason: str) -> None:
		if not self._continue_event.is_set():
			# Already paused
			return
		self._continue_event.clear()
		msg = f"Product caching paused because {reason}."
		self._pause_event_id = timeline.addEvent(
			title="Product caching paused",
			description=msg,
			category="product_caching",
			durationEvent=True,
		)
		with log_context({"instance": "product cache service"}):
			logger.notice(msg)

	def resume_caching(self, reason: str) -> None:
		if self._continue_event.is_set():
			# Not paused
			return
		self._continue_event.set()
		msg = f"Product caching resumed because {reason}."
		add_event = True
		if self._pause_event_id:
			add_event = timeline.setEventEnd(self._pause_event_id) <= 0
			self._pause_event_id = 0
		if add_event:
			# Failed to end previous event (event ID missing or not found in DB), add a new one
			timeline.addEvent(
				title="Product caching resumed",
				description=msg,
				category="product_caching",
			)
		with log_context({"instance": "product cache service"}):
			logger.notice(msg)

	def _on_network_status_change(self, connected: bool, metered: bool) -> None:
		"""
		Callback for network status changes.
		Pauses or resumes product caching based on the network state.
		"""
		with log_context({"instance": "product cache service"}):
			logger.info(f"Network status changed: connected={connected}, metered={metered}")
			if not connected or metered:
				self.pause_caching(reason="the network is disconnected" if not connected else "the network is metered")
			else:
				self.resume_caching(reason="the network is connected and unmetered")

	def run(self) -> None:
		with log_context({"instance": "product cache service"}):
			self._running = True
			logger.notice("Product cache service started")
			try:
				while not self._stopped:
					sleep_time = 1.0
					if self._cache_products_requested and not self._working and self._continue_event.is_set():
						init_from_service(service_client=self.service_client)
						sleep_time = self.start_caching_or_get_waiting_time()
					time.sleep(sleep_time)
			except Exception as err:
				logger.error(err, exc_info=True)

			logger.notice("Product cache service ended")
			self._running = False

	def clear_cache(self) -> None:
		timeline.addEvent(title="Clear product cache", description="Product cache deleted", category="product_caching")
		if self._product_cache_dir.exists():
			with self._cache_dir_lock:
				for product_cache_dir in self._product_cache_dir.iterdir():
					shutil.rmtree(product_cache_dir)
				self._cache_dir_sizes = {}
				self._state["products"] = {}
				self._state["products_cached"] = False
				state.set("product_cache_service", self._state)

	def cacheProducts(
		self,
		productProgressObserver: ProgressSubjectProxy | None = None,
		overallProgressObserver: ProgressSubjectProxy | None = None,
		fireSyncCompletedEvent: bool = True,
	) -> None:
		if self._pause_on_metered and RUNNING_ON_WINDOWS and not self._network_monitor:
			try:
				self._network_monitor = WinRTNetworkStatusMonitor(self._on_network_status_change)
			except Exception as err:
				logger.error("Failed to initialize network monitor: %s", err)
				self._network_monitor = None
		self._fire_sync_completed_event = fireSyncCompletedEvent
		self._cache_products_requested = True
		self._product_progress_observer = productProgressObserver
		self._overall_progress_observer = overallProgressObserver

	def _freeProductCacheSpace(self, needed_space: int = 0, needed_products: list[str] | None = None) -> None:
		"""
		Free up space in the product cache directory by deleting old products.
		needed_space: The amount of space to free up in bytes.
		needed_products: A list of product IDs that should not be deleted.
		"""
		needed_space = to_int(needed_space)
		needed_products = to_product_id_list(needed_products or [])
		self.update_cache_dir_sizes()
		cache_dir_size = self.get_cache_dir_size()

		with self._cache_dir_lock:

			@dataclass
			class DeletableProduct:
				product_id: str
				size: int
				mtime: float = 0.0

			deletable_products: list[DeletableProduct] = []
			for product_cache_dir in self._product_cache_dir.iterdir():
				product_id = product_cache_dir.name
				if product_id in needed_products:
					logger.trace("Product '%s' is needed, skipping", product_id)
					continue

				deletable_product = DeletableProduct(
					product_id=product_id,
					size=self._cache_dir_sizes.get(product_id, 0),
				)
				package_content_file = product_cache_dir / f"{product_id}.files"
				if package_content_file.exists():
					deletable_product.mtime = package_content_file.stat().st_mtime

				deletable_products.append(deletable_product)

			max_freeable_size = sum(p.size for p in deletable_products)
			if max_freeable_size < needed_space:
				raise ProductCacheInsufficientCacheSpaceException(
					"Failed to free enough product cache space: "
					f"Needed space: {(needed_space / 1_000_000):0.2f} MB, "
					f"maximum freeable space: {(max_freeable_size / 1_000_000):0.2f} MB, "
					f"current product cache size: {(cache_dir_size / 1_000_000):0.2f} MB, "
					f"max product cache size: {(self._product_cache_max_size / 1_000_000):0.0f} MB",
				)

			# Sort deletable products by mtime (older first)
			deletable_products.sort(key=lambda p: p.mtime)

			freed_space = 0
			while freed_space < needed_space:
				if not deletable_products:
					raise ProductCacheInsufficientCacheSpaceException(
						"Failed to free enough product cache space: No more products which can be deleted"
					)

				delete_product = deletable_products.pop(0)
				delete_dir = self._product_cache_dir / delete_product.product_id
				if delete_dir.exists():
					logger.notice("Deleting product cache directory '%s'", delete_dir)
					shutil.rmtree(delete_dir)
				else:
					logger.warning("Product cache directory '%s' does not exist", delete_dir)
				self._cache_dir_sizes.pop(delete_product.product_id, None)
				freed_space += delete_product.size
				if self._state["products"] and self._state["products"].pop(delete_product.product_id, None):
					state.set("product_cache_service", self._state)

		logger.notice("%0.2f MB of product cache freed", freed_space / 1_000_000)

	def _cacheProducts(self) -> None:
		self._updateConfig()
		self._working = True
		self._state["products_cached"] = False
		self._state["products"] = {}
		state.set("product_cache_service", self._state)
		eventId = None

		try:
			includeProductIds, excludeProductIds = get_include_exclude_product_ids(
				self.service_client,
				config.get("cache_service", "include_product_group_ids"),
				config.get("cache_service", "exclude_product_group_ids"),
			)

			productIds = []
			productOnClients = [
				poc
				for poc in self.service_client.productOnClient_getObjects(  # ty: ignore[unresolved-attribute]
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

			productIds += add_products_from_setup_after_install(productIds, self.service_client)

			if not productIds:
				logger.notice("No product action request set => no products to cache")
			else:
				masterDepotId = config.get("depot_server", "master_depot_id")

				# Get all productOnDepots!
				productOnDepots = self.service_client.productOnDepot_getObjects(depotId=masterDepotId)  # ty: ignore[unresolved-attribute]
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

				if config.action_processor_name not in productIds:
					productIds.append(config.action_processor_name)

				if "mshotfix" in productIds:
					# Determine correct mshotfix package for the system
					additional_mshotfix_package = get_mshotfix_package_name()
					logger.info("Determined system specific mshotfix package: %s", additional_mshotfix_package)
					if additional_mshotfix_package and additional_mshotfix_package in productOnDepotIds:
						logger.debug("Releasepackage '%s' found on depot '%s'", additional_mshotfix_package, masterDepotId)
						logger.info(
							"Requested to cache product mshotfix => additionaly caching system specific mshotfix product: %s",
							additional_mshotfix_package,
						)
						if additional_mshotfix_package not in productIds:
							productIds.append(additional_mshotfix_package)
					else:
						logger.error("Did not find release-specific mshotfix package")

				if errorProductIds:
					for index in range(len(productIds) - 1):
						if productIds[index] in errorProductIds:
							logger.error("ProductId: '%s' will not be cached", productIds[index])
							del productIds[index]

				if len(productIds) == 1 and productIds[0] == config.action_processor_name:
					logger.notice("Only the action processor product has an action set, nothing to cache.")
				else:
					p_list = ", ".join(productIds)
					logger.notice("Caching products: %s", p_list)
					eventId = timeline.addEvent(
						title="Cache products", description=f"Caching products: {p_list}", category="product_caching", durationEvent=True
					)

					self.last_errors = []
					for productId in productIds:
						try:
							self._cacheProduct(productId, productIds)
						except Exception as err:
							if isinstance(err, ProductCacheInsufficientCacheSpaceException):
								err.product_id = productId

							logger.info("Failed to cache product '%s': %s", productId, err)
							self.last_errors.append(err)
							try:
								self._setProductCacheState(productId, "failure", str(err))
							except Exception as err2:
								logger.error(err2, exc_info=True)
								self.last_errors.append(err)

							if isinstance(err, ProductCacheInsufficientCacheSpaceException):
								break

					if self.last_errors:
						e_list = "\n".join(str(exc) for exc in self.last_errors)
						logger.error("Errors occurred while caching products %s:\n%s", p_list, e_list)
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

							if self._fire_sync_completed_event:
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

	def _setProductCacheState(self, productId: str, key: str, value: Any, updateProductOnClient: bool = True) -> None:
		if "products" not in self._state:
			self._state["products"] = {}
		if productId not in self._state["products"]:
			self._state["products"][productId] = {}

		self._state["products"][productId][key] = value
		state.set("product_cache_service", self._state)
		actionProgress = None
		actionResult = None

		if key == "started":
			actionProgress = "caching"
		elif key == "completed":
			actionProgress = "cached"
		elif key == "failure":
			actionProgress = f"Cache failure: {value}"
			if len(actionProgress) > 250:
				actionProgress = f"{actionProgress[:249]}…"
			actionResult = "failed"

		if actionProgress and updateProductOnClient:
			self.service_client.productOnClient_updateObjects(  # ty: ignore[unresolved-attribute]
				[
					ProductOnClient(
						productId=productId,
						productType="LocalbootProduct",
						clientId=config.get("global", "host_id"),
						actionProgress=actionProgress,
						actionResult=actionResult,
					)
				]
			)

	def _getRepository(self, productId: str) -> Repository:
		config.selectDepotserver(configService=self.service_client, mode="sync", event=None, productIds=[productId])
		if not config.get("depot_server", "url"):
			raise RuntimeError("Cannot cache product files: depot_server.url undefined")

		depotServerUsername = ""
		depotServerPassword = ""

		url = urlparse(config.get("depot_server", "url"))
		if str(url.scheme).startswith("webdav"):
			depotServerUsername = config.get("global", "host_id")
			depotServerPassword = config.get("global", "opsi_host_key")

			kwargs: dict[str, Any] = {"username": depotServerUsername, "password": depotServerPassword}
			if str(url.scheme).startswith("webdavs"):
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

		(depotServerUsername, depotServerPassword) = config.getDepotserverCredentials(configService=self.service_client)
		mount = True
		if RUNNING_ON_WINDOWS:
			self._impersonation = System.Impersonate(username=depotServerUsername, password=depotServerPassword)
			self._impersonation.start(logonType="NEW_CREDENTIALS")
			mount = False
		mount_point = None
		if RUNNING_ON_DARWIN:
			mount_point = str(
				Path(config.get("depot_server", "drive")).parent
				/ f".cifs-mount.{generate_secret(5, alphabet=SecretAlphabet.ASCII_LETTERS)}"
			)
		self._repository = getRepository(
			config.get("depot_server", "url"),
			username=depotServerUsername,
			password=depotServerPassword,
			mount=mount,
			mountPoint=mount_point,
		)
		return self._repository

	def _rename_product_cache_dir(self, product_id: str, new_product_id: str) -> None:
		if product_id == new_product_id:
			return

		with self._cache_dir_lock:
			product_cache_dir = self._product_cache_dir / product_id
			if not product_cache_dir.exists():
				raise ProductCacheException(f"Product cache dir '{product_cache_dir}' does not exist")

			new_product_cache_dir = self._product_cache_dir / new_product_id
			if new_product_cache_dir.exists():
				logger.info("Product cache dir '%s' already exists, deleting it before rename", new_product_cache_dir)
				shutil.rmtree(new_product_cache_dir)

			logger.info("Renaming product cache dir '%s' to '%s'", product_cache_dir, new_product_cache_dir)
			product_cache_dir.rename(new_product_cache_dir)
			self._cache_dir_sizes[new_product_id] = self._cache_dir_sizes.pop(product_id, 0)

	def _cacheProduct(self, productId: str, neededProducts: list[str]) -> None:
		logger.notice(
			"Caching product '%s' (max bandwidth: %s, dynamic bandwidth: %s)", productId, self._max_bandwidth, self._dynamic_andwidth
		)
		self._setProductCacheState(productId, "started", time.time())
		self._setProductCacheState(productId, "completed", None, updateProductOnClient=False)
		self._setProductCacheState(productId, "failure", None, updateProductOnClient=False)

		event_id = None
		repository = None
		exception = None
		product_version = None
		try:
			repository = self._getRepository(productId)
			masterDepotId = config.get("depot_server", "master_depot_id")
			if not masterDepotId:
				raise ValueError("Cannot cache product files: depot_server.master_depot_id undefined")

			productOnDepots = self.service_client.productOnDepot_getObjects(depotId=masterDepotId, productId=productId)  # ty: ignore[unresolved-attribute]
			if not productOnDepots:
				raise RuntimeError(f"Product '{productId}' not found on depot '{masterDepotId}'")
			product_version = f"{productOnDepots[0].productVersion}-{productOnDepots[0].packageVersion}"
			products = self.service_client.product_getObjects(  # ty: ignore[unresolved-attribute]
				attributes=["id", "productVersion", "packageVersion", "name"],
				id=productId,
				productVersion=productOnDepots[0].productVersion,
				packageVersion=productOnDepots[0].packageVersion,
			)
			if not products:
				raise RuntimeError(f"Product '{productId}' ({product_version}) not found")
			self._setProductCacheState(productId, "productVersion", products[0].productVersion, updateProductOnClient=False)
			self._setProductCacheState(productId, "packageVersion", products[0].packageVersion, updateProductOnClient=False)
			self._setProductCacheState(productId, "name", products[0].name, updateProductOnClient=False)

			# 7zip--rfc156094_24.09-1.opsi
			base_product_id = productId.split("--")[0]
			cur_product_cache_dir: Path | None = None
			similar_product_cache_dir: Path | None = None
			for product_cache_dir in self._product_cache_dir.iterdir():
				if product_cache_dir.name == productId:
					logger.debug("Found product cache dir: %s", product_cache_dir)
					cur_product_cache_dir = product_cache_dir
					# Exact match found, no need to continue
					break
				elif product_cache_dir.name.startswith(f"{base_product_id}--"):
					logger.debug("Found similar product cache dir: %s", product_cache_dir)
					similar_product_cache_dir = product_cache_dir

			if not cur_product_cache_dir:
				with self._cache_dir_lock:
					cur_product_cache_dir = self._product_cache_dir / productId
					self._cache_dir_sizes[productId] = 0
				if similar_product_cache_dir:
					logger.info("Using similar product cache dir: %s", similar_product_cache_dir)
					self._rename_product_cache_dir(similar_product_cache_dir.name, productId)

			assert cur_product_cache_dir
			if not cur_product_cache_dir.exists():
				with self._cache_dir_lock:
					cur_product_cache_dir.mkdir(parents=True)

			package_content_file = f"{productId}/{productId}.files"
			local_package_content_file = os.path.join(self._product_cache_dir, productId, f"{productId}.files")
			repository.download(source=package_content_file, destination=local_package_content_file)
			packageInfo = PackageContentFile(local_package_content_file).parse()
			product_size = 0
			file_count = 0
			for value in packageInfo.values():
				if "size" in value:
					file_count += 1
					product_size += int(value["size"])

			logger.info("Product '%s' contains %d files with a total size of %0.2f MB", productId, file_count, product_size / 1_000_000)

			total_cache_dir_size = self.get_cache_dir_size()
			product_cache_dir_size = self.get_cache_dir_size(productId)
			additional_size = product_size - product_cache_dir_size
			new_total_cache_dir_size = total_cache_dir_size + additional_size
			disk_free_space = get_disk_space_usage(self._product_cache_dir).available
			new_disk_free_space = disk_free_space - additional_size

			logger.info(
				"Product cache info:\n"
				"  Product to cache: %s\n"
				"  Product size: %0.2f MB\n"
				"  Current product cache dir size: %0.2f MB\n"
				"  Current total cache dir size: %0.2f MB\n"
				"  Current free disk space: %0.2f MB\n"
				"  New total cache dir size: %0.2f MB\n"
				"  New free disk space: %0.2f MB\n"
				"  Max product cache size: %0.2f MB\n"
				"  Min free disk space: %0.2f MB\n",
				productId,
				product_size / 1_000_000,
				product_cache_dir_size / 1_000_000,
				total_cache_dir_size / 1_000_000,
				disk_free_space / 1_000_000,
				new_total_cache_dir_size / 1_000_000,
				new_disk_free_space / 1_000_000,
				self._product_cache_max_size / 1_000_000,
				self.min_free_disk_space / 1_000_000,
			)

			needed_space_disk = self.min_free_disk_space - new_disk_free_space
			if needed_space_disk > 0:
				logger.info(
					"Free disk space will be below %0.2f MB, need to free %0.2f MB",
					self.min_free_disk_space / 1_000_000,
					needed_space_disk / 1_000_000,
				)

			needed_space_limit = new_total_cache_dir_size - self._product_cache_max_size
			if needed_space_limit > 0:
				logger.info(
					"Product cache dir will exceed max size of %0.2f MB, need to free %0.2f MB",
					self._product_cache_max_size / 1_000_000,
					needed_space_limit / 1_000_000,
				)

			needed_space = max(needed_space_disk, needed_space_limit)
			if needed_space > 0:
				self._freeProductCacheSpace(needed_space=needed_space, needed_products=neededProducts)

			event_id = timeline.addEvent(
				title=f"Cache product {productId} {product_version}",
				description=(
					f"Caching product '{productId}' ({product_version}) of size {(float(product_size) / (1000 * 1000)):0.2f} MB\n"
					f"max bandwidth: {self._max_bandwidth}, dynamic bandwidth: {self._dynamic_andwidth}"
				),
				category="product_caching",
				durationEvent=True,
			)

			productSynchronizer = DepotToLocalDirectorySynchronizer(
				sourceDepot=repository,
				destinationDirectory=str(self._product_cache_dir),
				productIds=[productId],
				maxBandwidth=self._max_bandwidth,
				dynamicBandwidth=self._dynamic_andwidth,
				continue_event=self._continue_event,
			)
			productSynchronizer.synchronize(
				productProgressObserver=self._product_progress_observer, overallProgressObserver=self._overall_progress_observer
			)
			logger.notice("Product '%s' (%s) cached", productId, product_version)
			self._setProductCacheState(productId, "completed", time.time())
			self.update_cache_dir_sizes(product_id=productId, force=True)
		except Exception as err:
			logger.error("Failed to cache product %s: %s", productId, err, exc_info=True)
			exception = err
			timeline.addEvent(
				title=f"Failed to cache product {productId}",
				description=f"Failed to cache product '{productId}': {err}",
				category="product_caching",
				isError=True,
			)

		if event_id:
			timeline.setEventEnd(event_id)

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
