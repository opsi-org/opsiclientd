# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

"""
Connecting to a opsi service.
"""

from __future__ import annotations

import asyncio
import random
import re
import shutil
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from traceback import TracebackException
from types import TracebackType
from typing import TYPE_CHECKING, Callable

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.x509.oid import NameOID
from OPSI import System  # type: ignore[import]
from OPSI.Backend.JSONRPC import JSONRPCBackend  # type: ignore[import]
from OPSI.Util.Message import ChoiceSubject, MessageSubject  # type: ignore[import]
from OPSI.Util.Repository import WebDAVRepository  # type: ignore[import]
from OPSI.Util.Thread import KillableThread  # type: ignore[import]
from opsicommon.client.opsiservice import (
	MessagebusListener,
	ServiceClient,
	ServiceConnectionListener,
	ServiceVerificationFlags,
)
from opsicommon.exceptions import (
	OpsiServiceAuthenticationError,
	OpsiServiceVerificationError,
)
from opsicommon.logging import get_logger, log_context
from opsicommon.messagebus.file_transfer import process_messagebus_message as process_filetransfer_message
from opsicommon.messagebus.message import (
	Error,
	FileTransferMessage,
	FileUploadRequestMessage,
	GeneralErrorMessage,
	JSONRPCRequestMessage,
	JSONRPCResponseMessage,
	Message,
	ProcessMessage,
	TerminalMessage,
	TraceRequestMessage,
	TraceResponseMessage,
	timestamp,
)
from opsicommon.messagebus.process import process_messagebus_message as process_process_message
from opsicommon.messagebus.terminal import process_messagebus_message as process_terminal_message, terminals
from opsicommon.ssl import install_ca, load_cas, remove_ca
from opsicommon.system import lock_file
from opsicommon.types import (
	forceBool,
	forceFqdn,
	forceInt,
	forceProductId,
	forceString,
	forceUnicode,
)

from opsiclientd import __version__
from opsiclientd.Config import Config
from opsiclientd.Exceptions import CanceledByUserError
from opsiclientd.Localization import _

from opsiclientd.utils import log_network_status

if TYPE_CHECKING:
	from opsiclientd.Opsiclientd import Opsiclientd

config = Config()
cert_file_lock = threading.Lock()
SERVICE_CONNECT_TIMEOUT = 10  # Seconds

logger = get_logger()


def update_os_ca_store(allow_remove: bool = False) -> None:
	logger.info("Updating os CA cert store")

	ca_cert_file = Path(config.ca_cert_file)
	if not ca_cert_file.exists():
		return

	ca_certs: list[x509.Certificate] = []
	with open(ca_cert_file, "r", encoding="utf-8") as file:
		with lock_file(file=file, exclusive=False, timeout=5.0):
			data = file.read()
	for match in re.finditer(r"(-+BEGIN CERTIFICATE-+.*?-+END CERTIFICATE-+)", data, re.DOTALL):
		try:
			ca_certs.append(x509.load_pem_x509_certificate(match.group(1).encode("utf-8")))
		except Exception as err:
			logger.error(err, exc_info=True)
	if not ca_certs:
		return

	utc_now = datetime.now(tz=timezone.utc)
	install_ca_into_os_store = config.get("global", "install_opsi_ca_into_os_store")
	for ca_cert in ca_certs:
		subject_name = forceString(ca_cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value)
		if subject_name == "uib opsi CA":
			# uib opsi CA will not be installed into system cert store
			continue

		ca_cert_fingerprint = ca_cert.fingerprint(hashes.SHA1()).hex().upper()
		logger.debug("Handling CA '%s' (%s)", subject_name, ca_cert_fingerprint)

		add_ca = install_ca_into_os_store
		del_cas = []
		num_cas = 1
		try:
			# Iterate over all stored CAs, newest first
			for stored_ca in sorted(load_cas(subject_name), key=lambda x: x.not_valid_after_utc, reverse=True):
				stored_ca_fingerprint = stored_ca.fingerprint(hashes.SHA1()).hex().upper()
				if install_ca_into_os_store:
					if stored_ca_fingerprint == ca_cert_fingerprint:
						logger.info("CA '%s' (%s) already installed into system cert store", subject_name, ca_cert_fingerprint)
						add_ca = False
					elif stored_ca.not_valid_after_utc < utc_now and allow_remove:
						logger.info(
							"CA '%s' (%s) expired at %s, marking for removal from store",
							subject_name,
							stored_ca_fingerprint,
							stored_ca.not_valid_after_utc,
						)
						del_cas.append(stored_ca)
					elif num_cas >= 2:
						logger.info(
							"CA '%s' (%s) is valid until %s but %d newer certificates are in the store, marking for removal",
							subject_name,
							stored_ca_fingerprint,
							stored_ca.not_valid_after_utc,
							num_cas,
						)
						del_cas.append(stored_ca)
					else:
						logger.info(
							"Keeping CA '%s' (%s) which is valid until %s",
							subject_name,
							stored_ca_fingerprint,
							stored_ca.not_valid_after_utc,
						)
						num_cas += 1
				elif allow_remove:
					logger.info(
						"Removing CA '%s' (%s) from store because install_opsi_ca_into_os_store is false",
						subject_name,
						stored_ca_fingerprint,
					)
					del_cas.append(stored_ca)
		except Exception as err:
			logger.error("Failed to load CAs '%s' from system cert store: %s", subject_name, err, exc_info=True)

		for del_ca in del_cas:
			del_ca_fingerprint = del_ca.fingerprint(hashes.SHA1()).hex().upper()
			logger.debug("Removing CA '%s' (%s) from store", subject_name, del_ca_fingerprint)
			try:
				if remove_ca(subject_name, del_ca_fingerprint):
					logger.debug("CA '%s' (%s) successfully removed from system cert store", subject_name, del_ca_fingerprint)
			except Exception as err:
				logger.error("Failed to remove CA '%s' from system cert store: %s", subject_name, err, exc_info=True)

		if add_ca:
			logger.debug("Installing CA '%s' (%s) into system cert store", subject_name, ca_cert_fingerprint)
			try:
				install_ca(ca_cert)
				logger.debug("CA '%s' (%s) successfully installed into system cert store", subject_name, ca_cert_fingerprint)
			except Exception as err:
				logger.error(
					"Failed to install CA '%s' (%s) into system cert store: %s", subject_name, ca_cert_fingerprint, err, exc_info=True
				)


class PermanentServiceConnection(threading.Thread, ServiceConnectionListener, MessagebusListener):  # type: ignore[misc]
	def __init__(self, opsiclientd: Opsiclientd) -> None:
		from opsiclientd.webserver.rpc.control import ControlInterface

		threading.Thread.__init__(self, name="PermanentServiceConnection")
		ServiceConnectionListener.__init__(self)
		MessagebusListener.__init__(self)
		self.daemon = True
		self.running = False
		self._should_stop = False
		self._control_interface = ControlInterface(opsiclientd)
		self._loop = asyncio.new_event_loop()

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

	async def _arun(self) -> None:
		logger.notice("Permanent service connection starting")
		# Initial connect, reconnect will be handled by ServiceClient
		connect_wait = 3
		while not self._should_stop:
			try:
				logger.info("Trying to connect")
				await self._loop.run_in_executor(None, self.service_client.connect)
				break
			except Exception as err:
				logger.info("Failed to connect: %s", err)
				logger.debug(err, exc_info=True)
			for _sec in range(connect_wait):
				if self._should_stop:
					return
				await asyncio.sleep(1)
			connect_wait = min(round(connect_wait * 1.5), 300)

		while not self._should_stop:
			await asyncio.sleep(1)

	def run(self) -> None:
		with log_context({"instance": "permanent service connection"}):
			self.running = True
			try:
				self._loop.run_until_complete(self._arun())
				self._loop.close()
			except Exception as err:
				logger.error(err, exc_info=True)
			self.running = False

	def stop(self) -> None:
		self._should_stop = True
		self.service_client.stop()

	def __enter__(self) -> PermanentServiceConnection:
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
				except Exception as err:
					logger.error(err)
				service_client.messagebus.register_messagebus_listener(self)
				service_client.connect_messagebus()
		except Exception as err:
			logger.error(err, exc_info=True)

	def connection_closed(self, service_client: ServiceClient) -> None:
		logger.notice("Connection to opsi service %s closed", service_client.base_url)

	def connection_failed(self, service_client: ServiceClient, exception: Exception) -> None:
		logger.notice("Connection to opsi service %s failed: %s", service_client.base_url, exception)

	def message_received(self, message: Message) -> None:
		try:
			asyncio.run_coroutine_threadsafe(self._process_message(message), self._loop)
		except Exception as err:
			logger.error(err, exc_info=True)
			response = GeneralErrorMessage(
				sender="@",
				channel=message.response_channel,
				ref_id=message.id,
				error=Error(code=0, message=str(err), details=str(traceback.format_exc())),
			)
			self.service_client.messagebus.send_message(response)

	async def _process_message(self, message: Message) -> None:
		# logger.devel("Message received: %s", message.to_dict())
		if isinstance(message, JSONRPCRequestMessage):
			response: Message = JSONRPCResponseMessage(sender="@", channel=message.back_channel or message.sender, rpc_id=message.rpc_id)
			try:
				if message.method.startswith("_"):
					raise ValueError("Invalid method")
				method = getattr(self._control_interface, message.method)
				response.result = method(*(message.params or tuple()))
			except Exception as err:
				response.error = {
					"code": 0,
					"message": str(err),
					"data": {"class": err.__class__.__name__, "details": traceback.format_exc()},
				}
			await self.service_client.messagebus.async_send_message(response)
		elif isinstance(message, TraceRequestMessage):
			response = TraceResponseMessage(
				sender="@",
				channel=message.back_channel or message.sender,
				ref_id=message.id,
				req_trace=message.trace,
				payload=message.payload,
				trace={"sender_ws_send": timestamp()},
			)
			await self.service_client.messagebus.async_send_message(response)
		elif isinstance(message, TerminalMessage):
			await process_terminal_message(message=message, send_message=self.service_client.messagebus.async_send_message)
		elif isinstance(message, FileTransferMessage):
			if isinstance(message, FileUploadRequestMessage):
				if message.terminal_id and not message.destination_dir:
					terminal = terminals.get(message.terminal_id)
					if terminal:
						destination_dir = terminal.get_cwd()
						message.destination_dir = str(destination_dir)
			await process_filetransfer_message(message=message, send_message=self.service_client.messagebus.async_send_message)
		elif isinstance(message, ProcessMessage):
			await process_process_message(message=message, send_message=self.service_client.messagebus.async_send_message)


class ServiceConnection:
	def __init__(self, opsiclientd: Opsiclientd | None = None):
		self.opsiclientd = opsiclientd
		self._loadBalance = False
		self._configServiceUrl: str | None = None
		self._configService: JSONRPCBackend | None = None
		self._should_stop = False

	def connectionThreadOptions(self) -> dict[str, str]:
		return {}

	def connectionStart(self, configServiceUrl: str) -> None:
		pass

	def connectionCancelable(self, stopConnectionCallback: Callable) -> None:
		pass

	def connectionTimeoutChanged(self, timeout: float) -> None:
		pass

	def connectionCanceled(self) -> None:
		error = f"Failed to connect to config service '{self._configServiceUrl}': cancelled by user"
		logger.error(error)
		raise CanceledByUserError(error)

	def connectionTimedOut(self) -> None:
		error = (
			f"Failed to connect to config service '{self._configServiceUrl}': "
			f"timed out after {config.get('config_service', 'connection_timeout')} seconds"
		)
		logger.error(error)
		raise RuntimeError(error)

	def connectionFailed(self, error: str) -> None:
		error = f"Failed to connect to config service '{self._configServiceUrl}': {error}"
		logger.error(error)
		raise RuntimeError(error)

	def connectionEstablished(self) -> None:
		pass

	def getConfigService(self) -> JSONRPCBackend:
		if not self._configService:
			raise RuntimeError("No config service connected")
		return self._configService

	def getConfigServiceUrl(self) -> str | None:
		return self._configServiceUrl

	def isConfigServiceConnected(self) -> bool:
		return bool(self._configService)

	def stop(self) -> None:
		self._should_stop = True
		self.disconnectConfigService()

	def update_information_from_header(self) -> None:
		assert self._configService
		if not self._configService.service.new_host_id or self._configService.service.new_host_id == config.get("global", "host_id"):
			return

		assert self.opsiclientd
		logger.notice("Received new opsi host id %r", self._configService.service.new_host_id)
		config.set("global", "host_id", forceUnicode(self._configService.service.new_host_id))
		config.updateConfigFile(force=True)
		if config.get("config_service", "permanent_connection"):
			logger.info("Reestablishing permanent service connection")
			self.opsiclientd.stop_permanent_service_connection()
			self.opsiclientd.start_permanent_service_connection()

		if self.opsiclientd:
			logger.info("Cleaning config cache after host information change")
			try:
				cache_service = self.opsiclientd.getCacheService()
				cache_service.setConfigCacheFaulty()
			except RuntimeError:  # No cache_service currently running
				from opsiclientd.nonfree.CacheService import ConfigCacheService

				ConfigCacheService.delete_cache_dir()
		else:  # Called from SoftwareOnDemand or download_from_depot without opsiclientd context
			config_cache = Path(config.get("cache_service", "storage_dir")) / "config"
			if config_cache.exists():
				shutil.rmtree(config_cache)

	def connectConfigService(self, allowTemporaryConfigServiceUrls: bool = True) -> None:
		try:
			configServiceUrls = config.getConfigServiceUrls(allowTemporaryConfigServiceUrls=allowTemporaryConfigServiceUrls)
			if not configServiceUrls:
				raise RuntimeError("No service url defined")

			if self._loadBalance and (len(configServiceUrls) > 1):
				random.shuffle(configServiceUrls)

			for urlIndex, configServiceURL in enumerate(configServiceUrls):
				self._configServiceUrl = configServiceURL
				assert self._configServiceUrl

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
					self.connectionFailed(serviceConnectionThread.connectionError or "Unknown error")

				if serviceConnectionThread.connected and forceBool(config.get("config_service", "sync_time_from_service")):
					logger.info("Syncing local system time from service")
					try:
						assert serviceConnectionThread._configService
						System.setLocalSystemTime(serviceConnectionThread._configService.getServiceTime(utctime=True))
					except Exception as err:
						logger.error("Failed to sync time: '%s'", err)

				self._configService = serviceConnectionThread._configService
				self.update_information_from_header()

				if self._configService and "localhost" not in configServiceURL and "127.0.0.1" not in configServiceURL:
					try:
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

				self.connectionEstablished()
				break
		except Exception:
			self.disconnectConfigService()
			raise

	def disconnectConfigService(self) -> None:
		if self._configService:
			try:
				# stop_running_processes()?  #TODO cleanup
				self._configService.backend_exit()
			except Exception as exit_error:
				logger.error("Failed to disconnect config service: %s", exit_error)

		self._configService = None


class ServiceConnectionThread(KillableThread):
	def __init__(self, configServiceUrl: str, username: str, password: str, statusSubject: MessageSubject | None = None) -> None:
		KillableThread.__init__(self)
		self._configServiceUrl = configServiceUrl
		self._username = username
		self._password = password
		self._statusSubject = statusSubject
		self._configService = None
		self.running = False
		self.connected = False
		self.cancelled = False
		self.connectionError: str | None = None
		if not self._configServiceUrl:
			raise RuntimeError("No config service url given")

	def setStatusMessage(self, message: str) -> None:
		if not self._statusSubject:
			return
		self._statusSubject.setMessage(message)

	def getUsername(self) -> str:
		return self._username

	def run(self) -> None:
		with log_context({"instance": "service connection"}):
			logger.debug("ServiceConnectionThread started...")
			self.running = True
			self.connected = False
			self.cancelled = False

			try:
				compression = config.get("config_service", "compression")
				verify = config.service_verification_flags
				if "localhost" in self._configServiceUrl or "127.0.0.1" in self._configServiceUrl:
					compression = False
					verify = [ServiceVerificationFlags.ACCEPT_ALL]

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
						assert self._configService
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
						except Exception as err:
							logger.error(err, exc_info=True)
					except OpsiServiceVerificationError as verificationError:
						self.connectionError = forceUnicode(verificationError)
						self.setStatusMessage(
							_("Failed to connect to config server '%s': Service verification failure") % self._configServiceUrl
						)
						logger.error("Failed to connect to config server '%s': %s", self._configServiceUrl, verificationError)
						break
					except Exception as error:
						self.connectionError = forceUnicode(error)
						self.setStatusMessage(_("Failed to connect to config server '%s'") % (self._configServiceUrl))
						logger.info("Failed to connect to config server '%s': %s", self._configServiceUrl, error)
						logger.debug(error, exc_info=True)

						if isinstance(error, OpsiServiceAuthenticationError):
							fqdn = System.getFQDN()
							try:
								fqdn = forceFqdn(fqdn)
							except Exception as fqdnError:
								logger.warning("Failed to get fqdn from os, got '%s': %s", fqdn, fqdnError)
								break

							if self._username != fqdn:
								logger.notice("Connect failed with username '%s', got fqdn '%s' from os, trying fqdn", self._username, fqdn)
								self._username = fqdn
							else:
								break

						if "is not supported by the backend" in self.connectionError.lower():
							try:
								from cryptography.hazmat.backends import default_backend

								logger.debug(
									"Got the following crypto backends: %s",
									default_backend()._backends,
								)
							except Exception as cryptoCheckError:
								logger.debug("Failed to get info about installed crypto modules: %s", cryptoCheckError)

						for _unused in range(3):  # Sleeping before the next retry
							time.sleep(1)
			except Exception as err:
				logger.error(err, exc_info=True)
			finally:
				self.running = False

	def stopConnectionCallback(self, choiceSubject: ChoiceSubject) -> None:
		logger.notice("Connection cancelled by user")
		self.stop()

	def stop(self) -> None:
		logger.debug("Stopping thread")
		self.cancelled = True
		self.running = False


def download_from_depot(product_id: str, destination: str | Path, sub_path: str | None = None) -> None:
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
