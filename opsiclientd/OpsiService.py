# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org

# Copyright (C) 2006-2019 uib GmbH <info@uib.de>
# All rights reserved.

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
Connecting to a opsi service.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:author: Erol Ueluekmen <e.ueluekmen@uib.de>
@author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU Affero General Public License version 3
"""

import os
import random
import time
import socket
from http.client import HTTPConnection, HTTPSConnection
from OpenSSL import crypto

from OPSI import System
from OPSI.Exceptions import OpsiAuthenticationError, OpsiServiceVerificationError
from OPSI.Util.Thread import KillableThread
from OPSI.Util.HTTP import (
	urlsplit, non_blocking_connect_http, non_blocking_connect_https
)
from OPSI.Backend.JSONRPC import JSONRPCBackend
from OPSI.Types import forceBool, forceFqdn, forceInt, forceUnicode

import opsicommon.logging
from opsicommon.logging import logger

from opsiclientd import __version__
from opsiclientd.Config import Config, OPSI_CA
from opsiclientd.Exceptions import CanceledByUserError
from opsiclientd.Localization import _
from opsiclientd.nonfree import verify_modules

config = Config()


def isConfigServiceReachable(timeout=5):
	for url in config.getConfigServiceUrls():
		try:
			logger.info("Trying connection to config service '%s'", url)
			(scheme, host, port) = urlsplit(url)[:3]
			conn = None
			if scheme.endswith('s'):
				conn = HTTPSConnection(host=host, port=port)
				non_blocking_connect_https(conn, timeout)
			else:
				conn = HTTPConnection(host=host, port=port)
				non_blocking_connect_http(conn, timeout)
			if not conn:
				continue
			try:
				conn.sock.close()
				conn.close()
			except socket.error:
				pass
			return True

		except Exception as err: # pylint: disable=broad-except
			logger.info(err)

	return False


class ServiceConnection:
	def __init__(self, loadBalance=False):
		self._loadBalance = forceBool(loadBalance)
		self._configServiceUrl = None
		self._configService = None

	def connectionThreadOptions(self): # pylint: disable=no-self-use
		return {}

	def connectionStart(self, configServiceUrl): # pylint: disable=no-self-use
		pass

	def connectionCancelable(self, stopConnectionCallback): # pylint: disable=no-self-use
		pass

	def connectionTimeoutChanged(self, timeout): # pylint: disable=no-self-use
		pass

	def connectionCanceled(self):
		error = "Failed to connect to config service '%s': cancelled by user" % self._configServiceUrl
		logger.error(error)
		raise CanceledByUserError(error)

	def connectionTimedOut(self):
		error = "Failed to connect to config service '%s': timed out after %d seconds" % (
			self._configServiceUrl, config.get('config_service', 'connection_timeout')
		)
		logger.error(error)
		raise Exception(error)

	def connectionFailed(self, error):
		error = "Failed to connect to config service '%s': %s" % (self._configServiceUrl, error)
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

	def isConfigServiceReachable(self, timeout=15): # pylint: disable=no-self-use
		return isConfigServiceReachable(timeout=timeout)

	def stop(self): # pylint: disable=no-self-use
		logger.warning("stop() not implemented")
		#logger.debug(u"Stopping thread")
		#self.cancelled = True
		#self.running = False
		#for i in range(10):
		#	if not self.is_alive():
		#		break
		#	self.terminate()
		#	time.sleep(0.5)

	def connectConfigService(self, allowTemporaryConfigServiceUrls=True): # pylint: disable=too-many-locals,too-many-branches,too-many-statements
		try: # pylint: disable=too-many-nested-blocks
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
				while serviceConnectionThread.running and (timeout > 0):
					logger.debug("Waiting for ServiceConnectionThread (timeout: %d, alive: %s, cancellable in: %d)",
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

				if serviceConnectionThread.running:
					serviceConnectionThread.stop()
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
						System.setLocalSystemTime(serviceConnectionThread.configService.getServiceTime(utctime=True)) # pylint: disable=no-member
					except Exception as err: # pylint: disable=broad-except
						logger.error("Failed to sync time: '%s'", err)

				if (
					"localhost" not in configServiceURL and
					"127.0.0.1" not in configServiceURL
				):
					try:
						config.set(
							'depot_server', 'master_depot_id',
							serviceConnectionThread.configService.getDepotId(config.get('global', 'host_id')) # pylint: disable=no-member
						)
						config.updateConfigFile()
					except Exception as err: # pylint: disable=broad-except
						logger.warning(err)

				if urlIndex > 0:
					backend_info = serviceConnectionThread.configService.backend_info()
					try:
						verify_modules(backend_info, ['high_availability'])
					except RuntimeError as err:
						self.connectionFailed(err)

				self._configService = serviceConnectionThread.configService
				self.connectionEstablished()
		except Exception:
			self.disconnectConfigService()
			raise

	def disconnectConfigService(self):
		if self._configService:
			try:
				self._configService.backend_exit()
			except Exception as exit_error: # pylint: disable=broad-except
				logger.error("Failed to disconnect config service: %s", exit_error)

		self._configService = None
		self._configServiceUrl = None


class ServiceConnectionThread(KillableThread): # pylint: disable=too-many-instance-attributes
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
			raise Exception(u"No config service url given")

	def setStatusMessage(self, message):
		if not self._statusSubject:
			return
		self._statusSubject.setMessage(message)

	def getUsername(self):
		return self._username

	def updateCACert(self):
		logger.info("Updating CA cert")
		try:
			certDir = config.get('global', 'server_cert_dir')
			if not os.path.isdir(certDir):
				os.makedirs(certDir)
			response = self.configService.httpRequest("GET", "/ssl/opsi-cacert.pem")
			if response.status != 200:
				raise RuntimeError(f"Failed to fetch opsi-cacert.pem: {response.status} - {response.data}")
			caCert = crypto.load_certificate(crypto.FILETYPE_PEM, response.data.decode("utf-8"))
			with open(os.path.join(certDir, 'cacert.pem'), "wb") as file:
				file.write(crypto.dump_certificate(crypto.FILETYPE_PEM, caCert))
			logger.info("CA cert updated successfully")
		except Exception as sslCAErr: # pylint: disable=broad-except
			logger.warning("Failed to load CA: %s", sslCAErr)

	def run(self): # pylint: disable=too-many-locals,too-many-branches,too-many-statements
		with opsicommon.logging.log_context({'instance' : 'service connection'}):
			logger.debug("ServiceConnectionThread started...")
			self.running = True
			self.connected = False
			self.cancelled = False

			try: # pylint: disable=too-many-nested-blocks
				certDir = config.get('global', 'server_cert_dir')
				verifyServerCert = config.get('global', 'verify_server_cert')

				proxyMode = config.get('global', 'proxy_mode')
				proxyURL = config.get('global', 'proxy_url')
				if proxyMode == 'system':
					logger.notice(u'not implemented yet')
					proxyURL = System.getSystemProxySetting() # pylint: disable=assignment-from-no-return
				elif proxyMode == 'static':
					proxyURL = config.get('global', 'proxy_url')

				host = urlsplit(self._configServiceUrl)[1]
				serverCertFile = os.path.join(certDir, host + '.pem')
				if verifyServerCert:
					logger.info("Server verification enabled, using cert file '%s'", serverCertFile)

				caCertFile = os.path.join(certDir, 'cacert.pem')
				verifyServerCertByCa = config.get('global', 'verify_server_cert_by_ca')
				if verifyServerCertByCa:
					logger.info("Server verification by CA enabled, using CA cert file '%s'", caCertFile)

				tryNum = 0
				while not self.cancelled and not self.connected:
					tryNum += 1
					try:
						logger.notice("Connecting to config server '%s' #%d", self._configServiceUrl, tryNum)
						self.setStatusMessage(_("Connecting to config server '%s' #%d") % (self._configServiceUrl, tryNum))
						if len(self._username.split('.')) < 3:
							raise Exception(f"Domain missing in username '{self._username}'")

						compression = True
						if "localhost" in self._configServiceUrl or "127.0.0.1" in self._configServiceUrl:
							compression = False
							if proxyURL:
								logger.debug("Connecting to localhost, connecting directly without proxy")
								proxyURL = None

						self.configService = JSONRPCBackend(
							address=self._configServiceUrl,
							username=self._username,
							password=self._password,
							serverCertFile=serverCertFile,
							verifyServerCert=verifyServerCert,
							caCertFile=caCertFile,
							verifyServerCertByCa=verifyServerCertByCa,
							proxyURL=proxyURL,
							application='opsiclientd/%s' % __version__,
							compression=compression
						)

						self.configService.accessControl_authenticated() # pylint: disable=no-member
						self.configService.setCompression(True)
						self.connected = True
						self.connectionError = None
						serverVersion = self.configService.serverVersion
						self.setStatusMessage(_(u"Connected to config server '%s'") % self._configServiceUrl)
						logger.notice(
							"Connected to config server '%s' (name=%s, version=%s)",
							self._configServiceUrl,
							self.configService.serverName,
							serverVersion
						)

						if serverVersion and (serverVersion[0] > 4 or (serverVersion[0] == 4 and serverVersion[1] > 1)):
							curCA = ""
							if os.path.exists(caCertFile):
								with open(caCertFile, 'r') as file:
									curCA = file.read()
							if not os.path.exists(caCertFile) or curCA == OPSI_CA or verifyServerCertByCa:
								# Renew CA if not exists or connection is verified
								self.updateCACert()
						else:
							with open(caCertFile, 'w') as file:
								file.write(OPSI_CA)
					except OpsiServiceVerificationError as verificationError:
						self.connectionError = forceUnicode(verificationError)
						self.setStatusMessage(_("Failed to connect to config server '%s': Service verification failure") % self._configServiceUrl)
						logger.error("Failed to connect to config server '%s': %s", self._configServiceUrl, verificationError)
						break
					except Exception as error: # pylint: disable=broad-except
						self.connectionError = forceUnicode(error)
						self.setStatusMessage(_("Failed to connect to config server '%s': %s") % (self._configServiceUrl, forceUnicode(error)))
						logger.error("Failed to connect to config server '%s': %s", self._configServiceUrl, error)
						logger.error(error, exc_info=True)

						if isinstance(error, OpsiAuthenticationError):
							fqdn = System.getFQDN()
							try:
								fqdn = forceFqdn(fqdn)
							except Exception as fqdnError: # pylint: disable=broad-except
								logger.warning("Failed to get fqdn from os, got '%s': %s", fqdn, fqdnError)
								break

							if self._username != fqdn:
								logger.notice("Connect failed with username '%s', got fqdn '%s' from os, trying fqdn", self._username, fqdn)
								self._username = fqdn
							else:
								break

						if 'is not supported by the backend' in self.connectionError.lower():
							try:
								from cryptography.hazmat.backends import default_backend  # pylint: disable=import-outside-toplevel
								logger.debug("Got the following crypto backends: %s", default_backend()._backends) # pylint: disable=no-member,protected-access
							except Exception as cryptoCheckError: # pylint: disable=broad-except
								logger.debug("Failed to get info about installed crypto modules: %s", cryptoCheckError)

						for _unused in range(3):  # Sleeping before the next retry
							time.sleep(1)
			except Exception as err:# pylint: disable=broad-except
				logger.error(err, exc_info=True)
			finally:
				self.running = False

	def stopConnectionCallback(self, choiceSubject): # pylint: disable=unused-argument
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
