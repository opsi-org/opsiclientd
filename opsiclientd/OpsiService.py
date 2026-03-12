# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2025 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0-only

"""
Connecting to a opsi service.
"""

from __future__ import annotations

import abc  # Add this import
import asyncio
import os
import re
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from traceback import TracebackException
from types import TracebackType
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.x509.oid import NameOID
from opsicommon.client.opsiservice import MessagebusListener, ServiceClient, ServiceConnectionListener
from opsicommon.exceptions import OpsiServiceAuthenticationError, OpsiServiceTimeoutError
from opsicommon.logging import get_logger, log_context
from opsicommon.logging.constants import TRACE
from opsicommon.messagebus.file_transfer import process_messagebus_message as process_filetransfer_message
from opsicommon.messagebus.message import (
	Error,
	FileDownloadRequestMessage,
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
from opsicommon.messagebus.process import stop_running_processes
from opsicommon.messagebus.terminal import process_messagebus_message as process_terminal_message
from opsicommon.messagebus.terminal import stop_running_terminals, terminals
from opsicommon.ssl import install_ca, load_cas, remove_ca
from opsicommon.system import lock_file
from opsicommon.system.network import get_fqdn
from opsicommon.types import forceProductId, forceString
from opsicommon.utils import Singleton, replace_placeholders

from opsiclientd import __version__
from opsiclientd.Config import Config
from opsiclientd.utils import log_network_status

if TYPE_CHECKING:
	from opsiclientd.Opsiclientd import Opsiclientd
	from opsiclientd.webserver.rpc.control import ControlInterface

config = Config()
cert_file_lock = threading.Lock()

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


def get_service_client(address: str | list[str] | None = None, connect_timeout: float = 10.0) -> ServiceClient:
	if not address:
		address = config.get("config_service", "url")
	logger.info("Using config service address: %r", address)

	return ServiceClient(
		address=address,
		username=config.get("global", "host_id"),
		password=config.get("global", "opsi_host_key"),
		ca_cert_file=config.ca_cert_file,
		verify=config.service_verification_flags,
		proxy_url=config.get("global", "proxy_url"),
		user_agent=f"opsiclientd/{__version__}",
		connect_timeout=connect_timeout,
		max_time_diff=5.0,
		jsonrpc_create_methods=True,
		jsonrpc_create_objects=True,
	)


class CombinedSingletonABCMeta(Singleton, abc.ABCMeta):
	pass


class PermanentServiceConnection(threading.Thread, ServiceConnectionListener, MessagebusListener, metaclass=CombinedSingletonABCMeta):
	_initialized = False
	opsiclientd: Opsiclientd | None = None

	def __init__(self, opsiclientd: Opsiclientd | None = None) -> None:
		if opsiclientd and not self.opsiclientd:
			self.opsiclientd = opsiclientd
		if self._initialized:
			return
		self._initialized = True
		threading.Thread.__init__(self, name="PermanentServiceConnection")
		ServiceConnectionListener.__init__(self)
		MessagebusListener.__init__(self)
		self.daemon = True
		self.running = False
		self._temp_host_id = None
		self._should_stop = False
		self._loop = asyncio.new_event_loop()
		self._control_interface: ControlInterface | None = None
		self._should_connect = False
		self._temporary_service_client: ServiceClient | None = None
		with log_context({"instance": "permanent service connection"}):
			self._service_client = get_service_client()
			self._service_client.register_connection_listener(self)

	@property
	def main_service_client(self) -> ServiceClient:
		return self._service_client

	@property
	def service_client(self) -> ServiceClient:
		if self._temporary_service_client:
			return self._temporary_service_client
		return self._service_client

	def set_temporary_service_url(self, temporary_service_url: str | None) -> None:
		with log_context({"instance": "permanent service connection"}):
			if temporary_service_url:
				if not self._temporary_service_client or self._temporary_service_client.base_url != temporary_service_url:
					logger.notice("Setting temporary service URL to %r", temporary_service_url)
					self._temporary_service_client = get_service_client(temporary_service_url)
					self._temporary_service_client.connect(connect_messagebus=False)
			else:
				if self._temporary_service_client:
					logger.notice("Removing temporary service URL")
					self._temporary_service_client.stop()
				self._temporary_service_client = None

	def assert_connected(self) -> None:
		if self._temporary_service_client:
			self._temporary_service_client.assert_connected()
			return

		if not self._service_client.connected:
			self._should_connect = True

	@property
	def control_interface(self) -> ControlInterface:
		if not self._control_interface:
			if not self.opsiclientd:
				raise RuntimeError("No opsiclientd instance available")
			from opsiclientd.webserver.rpc.control import ControlInterface

			self._control_interface = ControlInterface(self.opsiclientd)
		return self._control_interface

	async def _arun(self) -> None:
		logger.notice("Permanent service connection starting")
		# Initial connect, reconnect will be handled by ServiceClient
		connect_wait = 1
		while not self._should_stop:
			if self._should_connect:
				try:
					await self._loop.run_in_executor(None, self._connect)
					# Successfully connected, reset wait time to 1 seconds
					self._should_connect = False
					connect_wait = 1
				except Exception as err:
					logger.info("Failed to connect: %s", err)
					logger.debug(err, exc_info=True)
					for _sec in range(connect_wait):
						if self._should_stop:
							return
						await asyncio.sleep(1)
					connect_wait = min(round(connect_wait * 1.5), 300)

			await asyncio.sleep(1)

	def _connect(self) -> None:
		with log_context({"instance": "permanent service connection"}):
			logger.info("Trying to connect to service: %s", self._service_client.addresses)
			self._service_client.connect()

	def run(self) -> None:
		with log_context({"instance": "permanent service connection"}):
			logger.notice("Permanent service connection started")
			self.running = True
			self._should_connect = True
			try:
				self._loop.run_until_complete(self._arun())
				self._loop.close()
			except Exception as err:
				logger.error(err, exc_info=True)
			self.running = False

	def stop(self) -> None:
		asyncio.run_coroutine_threadsafe(stop_running_terminals(), self._loop).result(5)
		asyncio.run_coroutine_threadsafe(stop_running_processes(), self._loop).result(5)
		time.sleep(3)
		self._should_stop = True
		self._service_client.stop()
		if self._temporary_service_client:
			self._temporary_service_client.stop()

	def __enter__(self) -> PermanentServiceConnection:
		self.start()
		return self

	def __exit__(self, exc_type: Exception, exc_value: TracebackException, exc_traceback: TracebackType) -> None:
		self.stop()

	def connection_open(self, service_client: ServiceClient) -> None:
		logger.notice("Opening connection to opsi service %s", service_client.addresses)
		log_network_status()

	def update_host_id(self) -> None:
		if self._temporary_service_client:
			logger.debug("Temporary service client, not updating host id")
			return

		assert self._service_client
		new_host_id = self._service_client.username
		if self._service_client.new_host_id:
			new_host_id = self._service_client.new_host_id
			logger.info("Received new opsi host id %r", new_host_id)

		if not new_host_id or new_host_id == config.get("global", "host_id"):
			return

		logger.notice("Changing opsi host id from %r to %r", config.get("global", "host_id"), new_host_id)
		config.set("global", "host_id", new_host_id)
		config.updateConfigFile(force=True)

		if self.opsiclientd:
			logger.info("Cleaning config cache after host information change")
			try:
				cache_service = self.opsiclientd.getCacheService()
				cache_service.setConfigCacheFaulty()
			except RuntimeError:
				# No cache_service currently running
				pass

		from opsiclientd.nonfree.CacheService import ConfigCacheService

		ConfigCacheService.delete_cache_dir()

	def connection_established(self, service_client: ServiceClient) -> None:
		logger.notice(
			"Connected to config server '%s' (name=%s, version=%s)",
			service_client.base_url,
			service_client.server_name,
			service_client.server_version,
		)

		if not service_client.service_is_opsiclientd():
			try:
				update_os_ca_store(allow_remove=True)
			except Exception as err:
				logger.error("Failed to update CA store: %s", err, exc_info=True)

			self.update_host_id()

			try:
				client_to_depotservers = service_client.configState_getClientToDepotserver(  # type: ignore[attr-defined]
					clientIds=config.get("global", "host_id")
				)
				if not client_to_depotservers:
					raise RuntimeError(f"Failed to get depotserver for client '{config.get('global', 'host_id')}'")
				depot_id = client_to_depotservers[0]["depotId"]
				config.set("depot_server", "master_depot_id", depot_id)
				config.updateConfigFile()
			except Exception as err:
				logger.warning(err)

			try:
				if service_client.messagebus_available:
					logger.notice("Message bus available, connecting")
					if config.get("config_service", "permanent_connection"):
						try:
							service_client.messagebus.reconnect_wait_min = int(config.get("config_service", "reconnect_wait_min"))
							service_client.messagebus.reconnect_wait_max = int(config.get("config_service", "reconnect_wait_max"))
						except Exception as err:
							logger.error(err)
						service_client.messagebus.register_messagebus_listener(self)
						service_client.connect_messagebus()
					else:
						logger.info("Permanent connection disabled in config")
			except Exception as err:
				logger.error(err, exc_info=True)

	def connection_closed(self, service_client: ServiceClient) -> None:
		logger.notice("Connection to opsi service %s closed", service_client.base_url)

	def connection_failed(self, service_client: ServiceClient, exception: Exception) -> None:
		logger.error("Connection to opsi service %s failed: %s", service_client.base_url, exception)
		if isinstance(exception, OpsiServiceTimeoutError):
			if self._service_client._connect_timeout < 90:
				logger.info("Connection timed out, increasing connect_timeout")
				self._service_client._connect_timeout = int(self._service_client._connect_timeout * 1.5)
		if isinstance(exception, OpsiServiceAuthenticationError) and not service_client.service_is_opsiclientd():
			logger.debug("Authentication failed, trying to get FQDN from OS")
			try:
				fqdn = get_fqdn()
				logger.debug("FQDN: %s, username: %s", fqdn, service_client.username)
				if service_client.username != fqdn:
					logger.notice("Connect failed with username '%s', got FQDN '%s' from OS, trying FQDN", service_client.username, fqdn)
					# If connect succeeds, the new host id will be set in connection_established() / update_host_id()
					service_client.username = fqdn
			except Exception as exc:
				logger.warning("Failed to get FQDN: %s", exc)

	def message_received(self, message: Message) -> None:
		if logger.isEnabledFor(TRACE):
			logger.trace("Message received: %s", message.to_dict())
		try:
			asyncio.run_coroutine_threadsafe(self._process_message(message), self._loop).result()
		except Exception as err:
			logger.error(err, exc_info=True)
			response = GeneralErrorMessage(
				sender="@",
				channel=message.response_channel,
				ref_id=message.id,
				error=Error(code=0, message=str(err), details=str(traceback.format_exc())),
			)
			self._service_client.messagebus.send_message(response)

	async def _process_message(self, message: Message) -> None:
		if isinstance(message, JSONRPCRequestMessage):
			response = JSONRPCResponseMessage(sender="@", channel=message.back_channel or message.sender, rpc_id=message.rpc_id)
			try:
				if message.method.startswith("_"):
					raise ValueError("Invalid method")
				method = getattr(self.control_interface, message.method)
				response.result = await self._loop.run_in_executor(None, method, *(message.params or tuple()))
			except Exception as err:
				response.error = {
					"code": 0,
					"message": str(err),
					"data": {"class": err.__class__.__name__, "details": traceback.format_exc()},
				}
			if logger.isEnabledFor(TRACE):
				logger.trace("Sending response: %s", response.to_dict())
			await self._service_client.messagebus.async_send_message(response)
		elif isinstance(message, TraceRequestMessage):
			await self._service_client.messagebus.async_send_message(
				TraceResponseMessage(
					sender="@",
					channel=message.back_channel or message.sender,
					ref_id=message.id,
					req_trace=message.trace,
					payload=message.payload,
					trace={"sender_ws_send": timestamp()},
				)
			)
		elif isinstance(message, TerminalMessage):
			await process_terminal_message(message=message, send_message=self._service_client.messagebus.async_send_message)
		elif isinstance(message, FileTransferMessage):
			if isinstance(message, FileUploadRequestMessage):
				if message.terminal_id and not message.destination_dir:
					terminal = terminals.get(message.terminal_id)
					if terminal:
						destination_dir = terminal.get_cwd()
						message.destination_dir = str(destination_dir)
			elif isinstance(message, FileDownloadRequestMessage):
				if message.path:
					message.path = replace_placeholders(
						message.path,
						{
							"{OPSICLIENTD_LOG_FILE_PATH}": config.get("global", "log_file"),
							"{OPSI_SCRIPT_LOG_FILE_PATH}": os.path.join(config.get("global", "log_dir"), "opsi-script", "opsi-script.log"),
						},
					)
			await process_filetransfer_message(message=message, send_message=self._service_client.messagebus.async_send_message)
		elif isinstance(message, ProcessMessage):
			await process_process_message(message=message, send_message=self._service_client.messagebus.async_send_message)


def download_from_depot(
	product_id: str, destination: str | Path, sub_path: str | None = None, service_client: ServiceClient | None = None
) -> None:
	product_id = forceProductId(product_id)
	if isinstance(destination, str):
		destination = Path(destination).resolve()

	disconnect = False
	if not service_client:
		service_client = get_service_client()
		service_client.connect()
		disconnect = True

	try:
		product_idents = service_client.product_getIdents(id=product_id)  # type: ignore[attr-defined]
		if not product_idents:
			raise ValueError(f"Product {product_id!r} not available")

		selected_depot = config.getDepot(configService=service_client, productIds=[product_id], forceDepotProtocol="webdav")[0]

		if not selected_depot:
			raise ValueError(f"Failed to get depot server for product {product_id!r}")

		if not selected_depot.depotWebdavUrl:
			raise ValueError(f"Failed to get webdav url for depot {selected_depot!r} from service")

		logger.info("Using depot %r, webdav url %r", selected_depot, selected_depot.depotWebdavUrl)
		url = urlparse(selected_depot.depotWebdavUrl.replace("webdavs://", "https://"))
	finally:
		if disconnect:
			service_client.stop()

	if not destination.is_dir():
		destination.mkdir(parents=True)

	path = f"{url.path.rstrip('/')}/{product_id}{('/' + sub_path.lstrip('/') if sub_path else '')}"
	logger.notice("Downloading '%s' to '%s' from depot %r", path, destination, url)

	depot_client = get_service_client(url.geturl()[: len(url.path) * -1])
	depot_client.download(source=path, destination=destination)
	depot_client.disconnect()

	logger.info("Download completed")
