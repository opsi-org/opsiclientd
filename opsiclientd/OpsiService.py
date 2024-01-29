# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
Connecting to a opsi service.
"""

import random
import re
import shutil
import threading
import time
import traceback
from pathlib import Path
from traceback import TracebackException
from types import TracebackType
from typing import Union

from cryptography import x509
from OPSI import System
from OPSI.Backend.JSONRPC import JSONRPCBackend
from OPSI.Util.Repository import WebDAVRepository
from OPSI.Util.Thread import KillableThread
from opsicommon.client.opsiservice import (
	MessagebusListener,
	ServiceClient,
	ServiceConnectionListener,
)
from opsicommon.exceptions import (
	OpsiServiceAuthenticationError,
	OpsiServiceVerificationError,
)
from opsicommon.logging import log_context, logger
from opsicommon.messagebus import (
	FileMessage,
	GeneralErrorMessage,
	JSONRPCRequestMessage,
	JSONRPCResponseMessage,
	Message,
	TerminalMessage,
	TraceRequestMessage,
	TraceResponseMessage,
	timestamp,
)
from opsicommon.ssl import install_ca, load_ca, remove_ca
from opsicommon.system import lock_file
from opsicommon.types import (
	forceBool,
	forceFqdn,
	forceInt,
	forceProductId,
	forceUnicode,
)

from opsiclientd import __version__
from opsiclientd.Config import Config
from opsiclientd.Exceptions import CanceledByUserError
from opsiclientd.Localization import _
from opsiclientd.messagebus.filetransfer import (
	process_messagebus_message as process_filetransfer_message,
)
from opsiclientd.messagebus.process import (
	process_messagebus_message as process_process_message,
)
from opsiclientd.messagebus.terminal import (
	process_messagebus_message as process_terminal_message,
)
from opsiclientd.utils import log_network_status

config = Config()
cert_file_lock = threading.Lock()
SERVICE_CONNECT_TIMEOUT = 10  # Seconds


def update_os_ca_store(allow_remove: bool = False):  # pylint: disable=too-many-branches
	logger.info("Updating os CA cert store")

	ca_certs = []
	ca_cert_file = Path(config.ca_cert_file)
	if ca_cert_file.exists():
		with open(ca_cert_file, "r", encoding="utf-8") as file:
			with lock_file(file=file, exclusive=False, timeout=5.0):
				data = file.read()
		for match in re.finditer(r"(-+BEGIN CERTIFICATE-+.*?-+END CERTIFICATE-+)", data, re.DOTALL):
			try:
				ca_certs.append(x509.load_pem_x509_certificate(match.group(1).encode("utf-8")))
			except Exception as err:  # pylint: disable=broad-except
				logger.error(err, exc_info=True)

	for _idx, ca_cert in enumerate(ca_certs):
		name = ca_cert.get_subject().CN
		if name == "uib opsi CA":
			continue

		logger.debug("Handling CA '%s'", name)
		present_ca = None
		outdated = True
		try:
			present_ca = load_ca(name)
			if present_ca:
				outdated = present_ca.digest("sha1") != ca_cert.digest("sha1")
				logger.info("CA '%s' exists in system store and is %s", name, "outdated" if outdated else "up to date")
			else:
				logger.info("CA '%s' not found in system store", name)
		except Exception as err:  # pylint: disable=broad-except
			logger.error("Failed to load CA '%s' from system cert store: %s", name, err, exc_info=True)

		if config.get("global", "install_opsi_ca_into_os_store"):
			if outdated or not present_ca:
				# Add or replace CA
				try:
					install_ca(ca_cert)
					logger.info("CA '%s' successfully installed into system cert store", name)
				except Exception as err:  # pylint: disable=broad-except
					logger.error("Failed to install CA '%s' into system cert store: %s", name, err, exc_info=True)
		elif present_ca and allow_remove:
			logger.info("Removing present CA %s from store because global.install_opsi_ca_into_os_store is false", name)
			try:
				if remove_ca(name):
					logger.info("CA '%s' successfully removed from system cert store", name)
			except Exception as err:  # pylint: disable=broad-except
				logger.error("Failed to remove CA '%s' from system cert store: %s", name, err, exc_info=True)


class PermanentServiceConnection(threading.Thread, ServiceConnectionListener, MessagebusListener):  # type: ignore[misc]
	def __init__(self, rpc_interface) -> None:
		threading.Thread.__init__(self)
		ServiceConnectionListener.__init__(self)
		MessagebusListener.__init__(self)
		self.daemon = True
		self.running = False
		self._should_stop = False
		self._rpc_interface = rpc_interface

		with log_context({"instance": "permanent service connection"}):
			self.service_client = ServiceClient(
				address=config.getConfigServiceUrls(allowTemporaryConfigServiceUrls=False),
				username=config.get("global", "host_id"),
				password=config.get("global", "opsi_host_key"),
				ca_cert_file=config.ca_cert_file,
				verify=config.service_verification_flags,
				proxy_url=config.get("global", "proxy_url"),
				user_agent=f"opsiclientd/{__version__}",
				connect_timeout=config.get("config_service", "connection_timeout"),
				max_time_diff=5.0,
			)
			self.service_client.register_connection_listener(self)

	def run(self):
		self.running = True
		with log_context({"instance": "permanent service connection"}):
			logger.notice("Permanent service connection starting")
			# Initial connect, reconnect will be handled by ServiceClient
			connect_wait = 3
			while not self._should_stop:
				try:
					logger.info("Trying to connect")
					self.service_client.connect()
					break
				except Exception as err:  # pylint: disable=broad-except
					logger.info("Failed to connect: %s", err)
					logger.debug(err, exc_info=True)
				for _sec in range(connect_wait):
					if self._should_stop:
						return
					time.sleep(1)
				connect_wait = min(round(connect_wait * 1.5), 300)

			while not self._should_stop:
				time.sleep(1)
		self.running = False

	def stop(self):
		self._should_stop = True
		self.service_client.stop()

	def __enter__(self) -> "PermanentServiceConnection":
		self.start()
		return self

	def __exit__(self, exc_type: Exception, exc_value: TracebackException, exc_traceback: TracebackType) -> None:
		self.stop()

	def connection_open(self, service_client: ServiceClient) -> None:
		logger.notice("Opening connection to opsi service %s", service_client.base_url)

	def connection_established(self, service_client: ServiceClient) -> None:
		logger.notice("Connection to opsi service %s established", service_client.base_url)
		try:
			if service_client.messagebus_available:
				logger.notice("OPSI message bus available")
				try:
					service_client.messagebus.reconnect_wait_min = int(config.get("config_service", "reconnect_wait_min"))
					service_client.messagebus.reconnect_wait_max = int(config.get("config_service", "reconnect_wait_max"))
				except Exception as err:  # pylint: disable=broad-except
					logger.error(err)
				service_client.messagebus.register_messagebus_listener(self)
				service_client.connect_messagebus()
		except Exception as err:  # pylint: disable=broad-except
			logger.error(err, exc_info=True)

	def connection_closed(self, service_client: ServiceClient) -> None:
		logger.notice("Connection to opsi service %s closed", service_client.base_url)

	def connection_failed(self, service_client: ServiceClient, exception: Exception) -> None:
		logger.notice("Connection to opsi service %s failed: %s", service_client.base_url, exception)

	def message_received(self, message: Message) -> None:
		try:
			self._process_message(message)
		except Exception as err:  # pylint: disable=broad-except
			logger.error(err, exc_info=True)
			response = GeneralErrorMessage(
				sender="@",
				channel=message.back_channel or message.sender,
				ref_id=message.id,
				error={"code": 0, "message": str(err), "details": str(traceback.format_exc())},
			)
			self.service_client.messagebus.send_message(response)

	def _process_message(self, message: Message) -> None:
		# logger.devel("Message received: %s", message.to_dict())
		if isinstance(message, JSONRPCRequestMessage):
			response: Message = JSONRPCResponseMessage(sender="@", channel=message.back_channel or message.sender, rpc_id=message.rpc_id)
			try:
				if message.method.startswith("_"):
					raise ValueError("Invalid method")
				method = getattr(self._rpc_interface, message.method)
				response.result = method(*(message.params or tuple()))
			except Exception as err:  # pylint: disable=broad-except
				response.error = {
					"code": 0,
					"message": str(err),
					"data": {"class": err.__class__.__name__, "details": traceback.format_exc()},
				}
			self.service_client.messagebus.send_message(response)
		elif isinstance(message, TraceRequestMessage):
			response = TraceResponseMessage(
				sender="@",
				channel=message.back_channel or message.sender,
				ref_id=message.id,
				req_trace=message.trace,
				payload=message.payload,
				trace={"sender_ws_send": timestamp()},
			)
			self.service_client.messagebus.send_message(response)
		elif isinstance(message, TerminalMessage):
			process_terminal_message(message, self.service_client.messagebus.send_message)
		elif isinstance(message, FileMessage):
			process_filetransfer_message(message, self.service_client.messagebus.send_message)
		elif message.type.startswith("process_"):
			process_process_message(message, self.service_client.messagebus.send_message, self.messagebus.async_send_message)


class ServiceConnection:
	def __init__(self, opsiclientd=None):
		self.opsiclientd = opsiclientd
		self._loadBalance = False
		self._configServiceUrl = None
		self._configService = None
		self._should_stop = False

	def connectionThreadOptions(self):
		return {}

	def connectionStart(self, configServiceUrl):
		pass

	def connectionCancelable(self, stopConnectionCallback):
		pass

	def connectionTimeoutChanged(self, timeout):
		pass

	def connectionCanceled(self):
		error = f"Failed to connect to config service '{self._configServiceUrl}': cancelled by user"
		logger.error(error)
		raise CanceledByUserError(error)

	def connectionTimedOut(self):
		error = (
			f"Failed to connect to config service '{self._configServiceUrl}': "
			f"timed out after {config.get('config_service', 'connection_timeout')} seconds"
		)
		logger.error(error)
		raise RuntimeError(error)

	def connectionFailed(self, error):
		error = f"Failed to connect to config service '{self._configServiceUrl}': {error}"
		logger.error(error)
		raise RuntimeError(error)

	def connectionEstablished(self):
		pass

	def getConfigService(self):
		return self._configService

	def getConfigServiceUrl(self):
		return self._configServiceUrl

	def isConfigServiceConnected(self):
		return bool(self._configService)

	def stop(self):
		self._should_stop = True
		self.disconnectConfigService()

	def update_information_from_header(self) -> None:
		if self._configService.service.new_host_id and self._configService.service.new_host_id != config.get("global", "host_id"):
			logger.notice("Received new opsi host id %r.", self._configService.service.new_host_id)
			config.set("global", "host_id", forceUnicode(self._configService.service.new_host_id))
			config.updateConfigFile(force=True)
			if config.get("config_service", "permanent_connection"):
				logger.info("Reestablishing permanent service connection")
				self.opsiclientd.stop_permanent_service_connection()
				self.opsiclientd.start_permanent_service_connection()

			if self.opsiclientd:
				logger.info("Cleaning config cache after host information change.")
				try:
					cache_service = self.opsiclientd.getCacheService()
					cache_service.setConfigCacheFaulty()
				except RuntimeError:  # No cache_service currently running
					from opsiclientd.nonfree.CacheService import (  # pylint: disable=import-outside-toplevel
						ConfigCacheService,
					)

					ConfigCacheService.delete_cache_dir()
			else:  # Called from SoftwareOnDemand or download_from_depot without opsiclientd context
				config_cache = Path(config.get("cache_service", "storage_dir")) / "config"
				if config_cache.exists():
					shutil.rmtree(config_cache)

	def connectConfigService(self, allowTemporaryConfigServiceUrls=True):  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
		try:  # pylint: disable=too-many-nested-blocks
			configServiceUrls = config.getConfigServiceUrls(allowTemporaryConfigServiceUrls=allowTemporaryConfigServiceUrls)
			if not configServiceUrls:
				raise RuntimeError("No service url defined")

			if self._loadBalance and (len(configServiceUrls) > 1):
				random.shuffle(configServiceUrls)

			for urlIndex, configServiceURL in enumerate(configServiceUrls):
				self._configServiceUrl = configServiceURL

				kwargs = self.connectionThreadOptions()
				logger.debug("Creating ServiceConnectionThread (url: %s)", self._configServiceUrl)
				serviceConnectionThread = ServiceConnectionThread(
					configServiceUrl=self._configServiceUrl,
					username=config.get("global", "host_id"),
					password=config.get("global", "opsi_host_key"),
					**kwargs,
				)
				serviceConnectionThread.daemon = True

				self.connectionStart(self._configServiceUrl)

				cancellableAfter = forceInt(config.get("config_service", "user_cancelable_after"))
				timeout = forceInt(config.get("config_service", "connection_timeout"))
				logger.info("Starting ServiceConnectionThread, timeout is %d seconds", timeout)
				serviceConnectionThread.start()
				for _unused in range(5):
					if serviceConnectionThread.running:
						break
					time.sleep(1)

				logger.debug("ServiceConnectionThread started")
				while serviceConnectionThread.running and timeout > 0:
					if self._should_stop:
						return
					logger.debug(
						"Waiting for ServiceConnectionThread (timeout: %d, alive: %s, cancellable in: %d)",
						timeout,
						serviceConnectionThread.is_alive(),
						cancellableAfter,
					)
					self.connectionTimeoutChanged(timeout)
					if cancellableAfter > 0:
						cancellableAfter -= 1
					if cancellableAfter == 0:
						self.connectionCancelable(serviceConnectionThread.stopConnectionCallback)
					time.sleep(1)
					timeout -= 1

				if serviceConnectionThread.cancelled:
					self.connectionCanceled()
				elif serviceConnectionThread.running:
					serviceConnectionThread.stop()
					if urlIndex + 1 < len(configServiceUrls):
						# Try next url
						continue
					self.connectionTimedOut()

				if not serviceConnectionThread.connected:
					self.connectionFailed(serviceConnectionThread.connectionError)

				if serviceConnectionThread.connected and forceBool(config.get("config_service", "sync_time_from_service")):
					logger.info("Syncing local system time from service")
					try:
						System.setLocalSystemTime(
							serviceConnectionThread._configService.getServiceTime(  # pylint: disable=no-member,protected-access
								utctime=True
							)
						)
					except Exception as err:  # pylint: disable=broad-except
						logger.error("Failed to sync time: '%s'", err)

				self._configService = serviceConnectionThread._configService  # pylint: disable=protected-access
				self.update_information_from_header()

				if "localhost" not in configServiceURL and "127.0.0.1" not in configServiceURL:
					try:
						client_to_depotservers = self._configService.configState_getClientToDepotserver(  # pylint: disable=no-member
							clientIds=config.get("global", "host_id")
						)
						if not client_to_depotservers:
							raise RuntimeError(f"Failed to get depotserver for client '{config.get('global', 'host_id')}'")
						depot_id = client_to_depotservers[0]["depotId"]
						config.set("depot_server", "master_depot_id", depot_id)
						config.updateConfigFile()
					except Exception as err:  # pylint: disable=broad-except
						logger.warning(err)

				self.connectionEstablished()
				break
		except Exception:
			self.disconnectConfigService()
			raise

	def disconnectConfigService(self):
		if self._configService:
			try:
				# stop_running_processes()?  #TODO cleanup
				self._configService.backend_exit()
			except Exception as exit_error:  # pylint: disable=broad-except
				logger.error("Failed to disconnect config service: %s", exit_error)

		self._configService = None


class ServiceConnectionThread(KillableThread):  # pylint: disable=too-many-instance-attributes
	def __init__(self, configServiceUrl, username, password, statusSubject=None):
		KillableThread.__init__(self)
		self._configServiceUrl = configServiceUrl
		self._username = username
		self._password = password
		self._statusSubject = statusSubject
		self._configService = None
		self.running = False
		self.connected = False
		self.cancelled = False
		self.connectionError = None
		if not self._configServiceUrl:
			raise RuntimeError("No config service url given")

	def setStatusMessage(self, message):
		if not self._statusSubject:
			return
		self._statusSubject.setMessage(message)

	def getUsername(self):
		return self._username

	def run(self):  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
		with log_context({"instance": "service connection"}):
			logger.debug("ServiceConnectionThread started...")
			self.running = True
			self.connected = False
			self.cancelled = False

			try:  # pylint: disable=too-many-nested-blocks
				compression = config.get("config_service", "compression")
				verify = config.service_verification_flags
				if "localhost" in self._configServiceUrl or "127.0.0.1" in self._configServiceUrl:
					compression = False
					verify = "accept_all"

				log_network_status()
				tryNum = 0
				while not self.cancelled and not self.connected:
					tryNum += 1
					try:
						logger.notice("Connecting to config server '%s' #%d", self._configServiceUrl, tryNum)
						self.setStatusMessage(_("Connecting to config server '%s' #%d") % (self._configServiceUrl, tryNum))
						if len(self._username.split(".")) < 3:
							raise RuntimeError(f"Domain missing in username '{self._username}'")

						logger.debug(
							"JSONRPCBackend address=%s, verify=%s, ca_cert_file=%s, proxy_url=%s, application=%s",
							self._configServiceUrl,
							verify,
							config.ca_cert_file,
							config.get("global", "proxy_url"),
							f"opsiclientd/{__version__}",
						)

						self._configService = JSONRPCBackend(
							address=self._configServiceUrl,
							username=self._username,
							password=self._password,
							verify=verify,
							ca_cert_file=config.ca_cert_file,
							proxy_url=config.get("global", "proxy_url"),
							application=f"opsiclientd/{__version__}",
							compression=compression,
							ip_version=config.get("global", "ip_version"),
							connect_timeout=SERVICE_CONNECT_TIMEOUT,
						)
						self.connected = True
						self.connectionError = None
						server_version = self._configService.service.server_version
						self.setStatusMessage(_("Connected to config server '%s'") % self._configServiceUrl)
						logger.notice(
							"Connected to config server '%s' (name=%s, version=%s)",
							self._configServiceUrl,
							self._configService.service.server_name,
							server_version,
						)
						try:
							update_os_ca_store(allow_remove=True)
						except Exception as err:  # pylint: disable=broad-except
							logger.error(err, exc_info=True)
					except OpsiServiceVerificationError as verificationError:
						self.connectionError = forceUnicode(verificationError)
						self.setStatusMessage(
							_("Failed to connect to config server '%s': Service verification failure") % self._configServiceUrl
						)
						logger.error("Failed to connect to config server '%s': %s", self._configServiceUrl, verificationError)
						break
					except Exception as error:  # pylint: disable=broad-except
						self.connectionError = forceUnicode(error)
						self.setStatusMessage(_("Failed to connect to config server '%s'") % (self._configServiceUrl))
						logger.info("Failed to connect to config server '%s': %s", self._configServiceUrl, error)
						logger.debug(error, exc_info=True)

						if isinstance(error, OpsiServiceAuthenticationError):
							fqdn = System.getFQDN()
							try:
								fqdn = forceFqdn(fqdn)
							except Exception as fqdnError:  # pylint: disable=broad-except
								logger.warning("Failed to get fqdn from os, got '%s': %s", fqdn, fqdnError)
								break

							if self._username != fqdn:
								logger.notice("Connect failed with username '%s', got fqdn '%s' from os, trying fqdn", self._username, fqdn)
								self._username = fqdn
							else:
								break

						if "is not supported by the backend" in self.connectionError.lower():
							try:
								from cryptography.hazmat.backends import (  # pylint: disable=import-outside-toplevel
									default_backend,
								)

								logger.debug(
									"Got the following crypto backends: %s",
									default_backend()._backends,  # pylint: disable=no-member,protected-access
								)
							except Exception as cryptoCheckError:  # pylint: disable=broad-except
								logger.debug("Failed to get info about installed crypto modules: %s", cryptoCheckError)

						for _unused in range(3):  # Sleeping before the next retry
							time.sleep(1)
			except Exception as err:  # pylint: disable=broad-except
				logger.error(err, exc_info=True)
			finally:
				self.running = False

	def stopConnectionCallback(self, choiceSubject):  # pylint: disable=unused-argument
		logger.notice("Connection cancelled by user")
		self.stop()

	def stop(self):
		logger.debug("Stopping thread")
		self.cancelled = True
		self.running = False
		for _unused in range(10):
			if not self.is_alive():
				break
			self.terminate()
			time.sleep(0.5)


def download_from_depot(product_id: str, destination: Union[str, Path], sub_path: str | None = None):
	product_id = forceProductId(product_id)
	if isinstance(destination, str):
		destination = Path(destination).resolve()

	service_connection = ServiceConnection()
	service_connection.connectConfigService()

	product_idents = service_connection.getConfigService().service.jsonrpc(method="product_getIdents", params=["hash", {"id": product_id}])
	if not product_idents:
		raise ValueError(f"Product {product_id!r} not available")

	selected_depot, _depot_protocol = config.getDepot(
		configService=service_connection.getConfigService(), productIds=[product_id], forceDepotProtocol="webdav"
	)

	if not selected_depot:
		raise ValueError(f"Failed to get depot server for product {product_id!r}")

	url = selected_depot.depotWebdavUrl
	if not url:
		raise ValueError(f"Failed to get webdav url for depot {selected_depot!r} from service")
	logger.info("Using depot %r, webdav url %r", selected_depot, url)

	service_connection.disconnectConfigService()

	if not destination.is_dir():
		destination.mkdir(parents=True)

	path = f"/{product_id}{('/' + sub_path.lstrip('/') if sub_path else '')}"
	logger.notice("Downloading '%s' to '%s' from depot %r", path, destination, url)
	repository = WebDAVRepository(
		url,
		username=config.get("global", "host_id"),
		password=config.get("global", "opsi_host_key"),
		verify_server_cert=config.get("global", "verify_server_cert") or config.get("global", "verify_server_cert_by_ca"),
		ca_cert_file=config.ca_cert_file,
		proxy_url=config.get("global", "proxy_url"),
		ip_version=config.get("global", "ip_version"),
	)
	repository.copy(path, str(destination))
	repository.disconnect()

	logger.info("Download completed")
