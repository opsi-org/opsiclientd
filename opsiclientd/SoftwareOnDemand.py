# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
Self-service functionality.
"""

import os

from OPSI.Service.Resource import ResourceOpsi
from OPSI.Service.Worker import WorkerOpsiJsonRpc
from opsicommon.exceptions import OpsiServiceAuthenticationError
from opsicommon.logging import log_context, logger
from twisted.internet import defer

from opsiclientd.Config import Config
from opsiclientd.Events.SwOnDemand import SwOnDemandEventGenerator
from opsiclientd.Events.Utilities.Generators import getEventGenerators
from opsiclientd.OpsiService import ServiceConnection

config = Config()  # pylint: disable=invalid-name
service_connection = ServiceConnection()  # pylint: disable=invalid-name


class WorkerKioskJsonRpc(WorkerOpsiJsonRpc):  # pylint: disable=too-few-public-methods
	_allowedMethods = [
		"getClientId",
		"fireEvent_software_on_demand",
		"processActionRequests",
		"getConfigDataFromOpsiclientd",
		"backend_setOptions",
		"configState_getObjects",
		"getDepotId",
		"configState_getClientToDepotserver",
		"getGeneralConfigValue",
		"getKioskProductInfosForClient",
		"hostControlSafe_fireEvent",
		"objectToGroup_getObjects",
		"product_getObjects",
		"productDependency_getObjects",
		"productOnClient_getObjects",
		"productOnDepot_getObjects",
		"setProductActionRequestWithDependencies",
	]

	def __init__(self, service, request, resource):
		with log_context({"instance": "software on demand"}):
			WorkerOpsiJsonRpc.__init__(self, service, request, resource)
			self._auth_module = None
			if os.name == "posix":
				import OPSI.Backend.Manager.Authentication.PAM  # pylint: disable=import-outside-toplevel

				self._auth_module = OPSI.Backend.Manager.Authentication.PAM.PAMAuthentication()
			elif os.name == "nt":
				import OPSI.Backend.Manager.Authentication.NT  # pylint: disable=import-outside-toplevel

				self._auth_module = OPSI.Backend.Manager.Authentication.NT.NTAuthentication("S-1-5-32-544")

	def _getCallInstance(self, result):
		self._callInstance = service_connection.getConfigService()
		self._callInterface = self._callInstance.backend_getInterface()

	def _getCredentials(self):
		user, password = self._getAuthorization()
		if not user:
			user = config.get("global", "host_id")

		return (user, password)

	def _authenticate(self, result):
		if self.request.getClientIP() in ("127.0.0.1", "::ffff:127.0.0.1", "::1"):
			self.session.authenticated = False
			return result

		try:
			self.session.user, self.session.password = self._getCredentials()

			logger.notice("Authorization request from %s@%s (application: %s)", self.session.user, self.session.ip, self.session.userAgent)

			if not self.session.password:
				raise RuntimeError(f"No password from {self.session.ip} (application: {self.session.userAgent})")

			if self.session.user.lower() == config.get("global", "host_id").lower() and self.session.password == config.get(
				"global", "opsi_host_key"
			):
				return result

			if self._auth_module:
				self._auth_module.authenticate(self.session.user, self.session.password)
				logger.info(
					"Authentication successful for user '%s', groups '%s' (admin group: %s)",
					self.session.user,
					",".join(self._auth_module.get_groupnames(self.session.user)),
					self._auth_module.get_admin_groupname(),
				)
				if not self._auth_module.user_is_admin(self.session.user):
					raise RuntimeError("Not an admin user")
				return result

			raise RuntimeError("Invalid credentials")
		except Exception as err:  # pylint: disable=broad-except
			raise OpsiServiceAuthenticationError(f"Forbidden: {err}") from err

	def _executeRpcs(self, result):  # pylint: disable=unused-argument
		deferred = defer.Deferred()
		for rpc in self._rpcs:
			if rpc.method not in self._allowedMethods:
				raise RuntimeError(f"Access to method '{rpc.method}' denied")
			if rpc.method == "getClientId":
				rpc.result = config.get("global", "host_id")
			elif rpc.method == "processActionRequests":
				self.service._opsiclientdRpcInterface.processActionRequests()  # pylint: disable=protected-access
			elif rpc.method == "fireEvent_software_on_demand":
				for eventGenerator in getEventGenerators(generatorClass=SwOnDemandEventGenerator):
					# Allow event cancellation for new events called via the Kiosk
					eventGenerator.createAndFireEvent(can_cancel=True)
			elif rpc.method == "getConfigDataFromOpsiclientd":
				rpc.result = self.service._opsiclientdRpcInterface.getConfigDataFromOpsiclientd()  # pylint: disable=protected-access
			else:
				deferred.addCallback(self._executeRpc, rpc)
		deferred.callback(None)
		return deferred

	def _processQuery(self, result):
		deferred = defer.Deferred()
		deferred.addCallback(self._decodeQuery)
		deferred.addCallback(self._openConnection)
		deferred.addCallback(self._getCallInstance)
		deferred.addCallback(self._getRpcs)
		deferred.addCallback(self._executeRpcs)
		deferred.callback(None)
		return deferred

	def _openConnection(self, result):
		if not service_connection.isConfigServiceConnected():
			service_connection.connectConfigService()
		return result

	def _closeConnection(self, result):
		if service_connection.isConfigServiceConnected():
			service_connection.disconnectConfigService()
		return result


class ResourceKioskJsonRpc(ResourceOpsi):
	WorkerClass = WorkerKioskJsonRpc
