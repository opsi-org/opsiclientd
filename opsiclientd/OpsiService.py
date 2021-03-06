# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
Connecting to a opsi service.
"""

import os
import random
import re
import threading
import time
from pathlib import Path
from typing import Union

from OpenSSL.crypto import FILETYPE_PEM, dump_certificate, load_certificate
from OPSI import System
from OPSI.Backend.JSONRPC import JSONRPCBackend
from OPSI.Exceptions import OpsiAuthenticationError, OpsiServiceVerificationError
from OPSI.Types import forceBool, forceFqdn, forceInt, forceProductId, forceUnicode
from OPSI.Util.Repository import WebDAVRepository
from OPSI.Util.Thread import KillableThread
from opsicommon.client.jsonrpc import JSONRPCClient
from opsicommon.logging import log_context, logger
from opsicommon.ssl import install_ca, load_ca, remove_ca

from opsiclientd import __version__
from opsiclientd.Config import UIB_OPSI_CA, Config
from opsiclientd.Exceptions import CanceledByUserError
from opsiclientd.Localization import _
from opsiclientd.utils import log_network_status

config = Config()
cert_file_lock = threading.Lock()
SERVICE_CONNECT_TIMEOUT = 10  # Seconds


def update_ca_cert(config_service: JSONRPCClient, allow_remove: bool = False):  # pylint: disable=too-many-branches
	logger.info("Updating CA cert")
	ca_certs = []
	try:
		if not os.path.isdir(os.path.dirname(config.ca_cert_file)):
			os.makedirs(os.path.dirname(config.ca_cert_file))

		try:  # pylint: disable=broad-except
			response = config_service.get("/ssl/opsi-ca-cert.pem")
		except Exception as err:
			raise RuntimeError(f"Failed to fetch opsi-ca-cert.pem: {err}") from err

		for match in re.finditer(r"(-+BEGIN CERTIFICATE-+.*?-+END CERTIFICATE-+)", response.text, re.DOTALL):
			try:
				ca_certs.append(load_certificate(FILETYPE_PEM, match.group(1).encode("utf-8")))
			except Exception as err:  # pylint: disable=broad-except
				logger.error(err, exc_info=True)

		with open(config.ca_cert_file, "w", encoding="utf-8") as file:
			for cert in ca_certs:
				file.write(dump_certificate(FILETYPE_PEM, cert).decode("utf-8"))
			if config.get('global', 'trust_uib_opsi_ca'):
				file.write(UIB_OPSI_CA)

		logger.info("CA cert file %s successfully updated", config.ca_cert_file)
	except Exception as err:  # pylint: disable=broad-except
		logger.error("Failed to update CA cert: %s", err)

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

		if config.get('global', 'install_opsi_ca_into_os_store'):
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


class ServiceConnection:
	def __init__(self):
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
		raise Exception(error)

	def connectionFailed(self, error):
		error = f"Failed to connect to config service '{self._configServiceUrl}': {error}"
		logger.error(error)
		raise Exception(error)

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

	def connectConfigService(self, allowTemporaryConfigServiceUrls=True):  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
		try:  # pylint: disable=too-many-nested-blocks
			configServiceUrls = config.getConfigServiceUrls(allowTemporaryConfigServiceUrls=allowTemporaryConfigServiceUrls)
			if not configServiceUrls:
				raise Exception("No service url defined")

			if self._loadBalance and (len(configServiceUrls) > 1):
				random.shuffle(configServiceUrls)

			for urlIndex, configServiceURL in enumerate(configServiceUrls):
				self._configServiceUrl = configServiceURL

				kwargs = self.connectionThreadOptions()
				logger.debug("Creating ServiceConnectionThread (url: %s)", self._configServiceUrl)
				serviceConnectionThread = ServiceConnectionThread(
					configServiceUrl=self._configServiceUrl,
					username=config.get('global', 'host_id'),
					password=config.get('global', 'opsi_host_key'),
					**kwargs
				)
				serviceConnectionThread.daemon = True

				self.connectionStart(self._configServiceUrl)

				cancellableAfter = forceInt(config.get('config_service', 'user_cancelable_after'))
				timeout = forceInt(config.get('config_service', 'connection_timeout'))
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
						timeout, serviceConnectionThread.is_alive(), cancellableAfter
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

				if serviceConnectionThread.connected and (serviceConnectionThread.getUsername() != config.get('global', 'host_id')):
					config.set('global', 'host_id', serviceConnectionThread.getUsername().lower())
					logger.info("Updated host_id to '%s'", config.get('global', 'host_id'))
					config.updateConfigFile()

				if serviceConnectionThread.connected and forceBool(config.get('config_service', 'sync_time_from_service')):
					logger.info("Syncing local system time from service")
					try:
						System.setLocalSystemTime(serviceConnectionThread.configService.getServiceTime(utctime=True))  # pylint: disable=no-member
					except Exception as err:  # pylint: disable=broad-except
						logger.error("Failed to sync time: '%s'", err)

				if (
					"localhost" not in configServiceURL and
					"127.0.0.1" not in configServiceURL
				):
					try:
						config.set(
							'depot_server', 'master_depot_id',
							serviceConnectionThread.configService.getDepotId(config.get('global', 'host_id'))  # pylint: disable=no-member
						)
						config.updateConfigFile()
					except Exception as err:  # pylint: disable=broad-except
						logger.warning(err)

				self._configService = serviceConnectionThread.configService
				self.connectionEstablished()
		except Exception:
			self.disconnectConfigService()
			raise

	def disconnectConfigService(self):
		if self._configService:
			try:
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
		self.configService = None
		self.running = False
		self.connected = False
		self.cancelled = False
		self.connectionError = None
		if not self._configServiceUrl:
			raise Exception("No config service url given")

	def setStatusMessage(self, message):
		if not self._statusSubject:
			return
		self._statusSubject.setMessage(message)

	def getUsername(self):
		return self._username

	def prepare_ca_cert_file(self):
		certs = ""
		with cert_file_lock:
			if os.path.exists(config.ca_cert_file):
				# Read all certs from file except UIB_OPSI_CA
				uib_opsi_ca_cert = load_certificate(FILETYPE_PEM, UIB_OPSI_CA.encode("ascii"))
				with open(config.ca_cert_file, "r", encoding="utf-8") as file:
					for match in re.finditer(r"(-+BEGIN CERTIFICATE-+.*?-+END CERTIFICATE-+)", file.read(), re.DOTALL):
						cert = load_certificate(FILETYPE_PEM, match.group(1).encode("ascii"))
						if cert.get_subject().CN != uib_opsi_ca_cert.get_subject().CN:
							certs += dump_certificate(FILETYPE_PEM, cert).decode("ascii")
			if not certs:
				if os.path.exists(config.ca_cert_file):
					# Accept all server certs on the next connection attempt
					os.remove(config.ca_cert_file)
				return

			if config.get('global', 'trust_uib_opsi_ca'):
				certs += UIB_OPSI_CA

			with open(config.ca_cert_file, "w", encoding="utf-8") as file:
				file.write(certs)

	def run(self):  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
		with log_context({'instance': 'service connection'}):
			logger.debug("ServiceConnectionThread started...")
			self.running = True
			self.connected = False
			self.cancelled = False

			try:  # pylint: disable=too-many-nested-blocks
				verify_server_cert = (
					config.get('global', 'verify_server_cert') or
					config.get('global', 'verify_server_cert_by_ca')
				)
				ca_cert_file = config.ca_cert_file
				try:
					self.prepare_ca_cert_file()
				except PermissionError as perm_error:
					logger.error("Not allowed to prepare ca_cert_file: %s", perm_error, exc_info=True)

				compression = config.get('config_service', 'compression')
				if "localhost" in self._configServiceUrl or "127.0.0.1" in self._configServiceUrl:
					compression = False
					verify_server_cert = False

				if verify_server_cert:
					if os.path.exists(ca_cert_file):
						logger.info("Server verification enabled, using CA cert file '%s'", ca_cert_file)
					else:
						logger.error(
							"Server verification enabled, but CA cert file '%s' not found, skipping verification",
							ca_cert_file
						)
						ca_cert_file = None
						verify_server_cert = False

				log_network_status()
				tryNum = 0
				while not self.cancelled and not self.connected:
					tryNum += 1
					try:
						logger.notice("Connecting to config server '%s' #%d", self._configServiceUrl, tryNum)
						self.setStatusMessage(_("Connecting to config server '%s' #%d") % (self._configServiceUrl, tryNum))
						if len(self._username.split('.')) < 3:
							raise Exception(f"Domain missing in username '{self._username}'")

						logger.debug(
							"JSONRPCBackend address=%s, verify_server_cert=%s, ca_cert_file=%s, proxy_url=%s, application=%s",
							self._configServiceUrl, verify_server_cert, ca_cert_file,
							config.get('global', 'proxy_url'), f"opsiclientd/{__version__}"
						)

						self.configService = JSONRPCBackend(
							address=self._configServiceUrl,
							username=self._username,
							password=self._password,
							verify_server_cert=verify_server_cert,
							ca_cert_file=ca_cert_file,
							proxy_url=config.get('global', 'proxy_url'),
							application=f"opsiclientd/{__version__}",
							compression=compression,
							ip_version=config.get('global', 'ip_version'),
							connect_timeout=SERVICE_CONNECT_TIMEOUT,
						)
						self.configService.accessControl_authenticated()  # pylint: disable=no-member
						self.connected = True
						self.connectionError = None
						serverVersion = self.configService.serverVersion
						self.setStatusMessage(_("Connected to config server '%s'") % self._configServiceUrl)
						logger.notice(
							"Connected to config server '%s' (name=%s, version=%s)",
							self._configServiceUrl,
							self.configService.serverName,
							serverVersion
						)

						if serverVersion and (serverVersion[0] > 4 or (serverVersion[0] == 4 and serverVersion[1] > 1)):
							if not os.path.exists(config.ca_cert_file) or verify_server_cert or config.get('global', 'install_opsi_ca_into_os_store'):
								# Renew CA if not exists or connection is verified
								try:
									update_ca_cert(self.configService, allow_remove=True)
								except Exception as err:  # pylint: disable=broad-except
									logger.error(err, exc_info=True)
					except OpsiServiceVerificationError as verificationError:
						self.connectionError = forceUnicode(verificationError)
						self.setStatusMessage(_("Failed to connect to config server '%s': Service verification failure") % self._configServiceUrl)
						logger.error("Failed to connect to config server '%s': %s", self._configServiceUrl, verificationError)
						break
					except Exception as error:  # pylint: disable=broad-except
						self.connectionError = forceUnicode(error)
						self.setStatusMessage(_("Failed to connect to config server '%s'") % (self._configServiceUrl))
						logger.info("Failed to connect to config server '%s': %s", self._configServiceUrl, error)
						logger.debug(error, exc_info=True)

						if isinstance(error, OpsiAuthenticationError):
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

						if 'is not supported by the backend' in self.connectionError.lower():
							try:
								from cryptography.hazmat.backends import (  # pylint: disable=import-outside-toplevel
									default_backend,
								)
								logger.debug("Got the following crypto backends: %s", default_backend()._backends)  # pylint: disable=no-member,protected-access
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


def download_from_depot(product_id: str, destination: Union[str, Path], sub_path: str = None):
	product_id = forceProductId(product_id)
	if isinstance(destination, str):
		destination = Path(destination).resolve()

	service_connection = ServiceConnection()
	service_connection.connectConfigService()

	product_idents = service_connection.getConfigService().execute_rpc("product_getIdents", ["hash", {"id": product_id}])
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
		ip_version=config.get("global", "ip_version")
	)
	repository.copy(path, str(destination))
	repository.disconnect()

	logger.info("Download completed")
