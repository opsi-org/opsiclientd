# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi
#    (open pc server integration) http://www.opsi.org
# Copyright (C) 2010-2016 uib GmbH <info@uib.de>

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
The Functionality for Software-on-Demand

Functionality to work with certificates.
Certificates play an important role in the encrypted communication
between servers and clients.

.. versionadded:: 4.0.4

:copyright: uib GmbH <info@uib.de>
:author: Erol Ülükmen <e.ueluekmen@uib.de>
:author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU Affero General Public License version 3
"""

import base64
import cgi
from hashlib import md5
from twisted.conch.ssh import keys
from twisted.internet import defer

from OPSI.web2 import responsecode, http, stream
from OPSI.Logger import *
from OPSI.Types import *
from OPSI.Object import *
from OPSI.Service.Worker import WorkerOpsi, WorkerOpsiJsonRpc
from OPSI.Service.Resource import ResourceOpsi

from ocdlib.OpsiService import ServiceConnection
from ocdlib.Config import Config
from ocdlib.Events import SwOnDemandEventGenerator, getEventGenerators
from ocdlib.Localization import _
from ocdlib.Timeline import Timeline

logger = Logger()
config = Config()
timeline = Timeline()

mainpage = u'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
	<title>%(hostname)s opsi software on demand</title>
	<link rel="stylesheet" type="text/css" href="/opsiclientd.css" />
	<meta http-equiv="Content-Type" content="text/xhtml; charset=utf-8" />
	<script type="text/javascript">
	// <![CDATA[
	window.onload = init;
	function init () {
		var inputs = document.getElementsByTagName("input");
		for (var i = 0, input; input = inputs[i]; i++) {
			if (input.type != "radio")
				continue;
			input.onclick = radioclick;
			input.mostRecentlyChecked = input.checked;
		}
	}
	function radioclick () {
		this.checked = !this.mostRecentlyChecked;
		var arr = this.form.elements[this.name];
		for (var i = 0; i < arr.length; i++) {
			arr[i].mostRecentlyChecked = false;
		}
		this.mostRecentlyChecked = this.checked;
	}
	// ]]>
	</script>
</head>
<body>
	<p id="title">opsi software on demand</p>
	<form action="/swondemand" method="post">
		%(result)s
	</form>
</body>
</html>
'''


class WorkerSoftwareOnDemand(WorkerOpsi, ServiceConnection):
	def __init__(self, service, request, resource):
		moduleName = u' %-30s' % (u'software on demand')
		logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)
		WorkerOpsi.__init__(self, service, request, resource)
		ServiceConnection.__init__(self)
		self._swOnDemandProductIds = []
		self._showDetails = False

	def _getCredentials(self):
		(user, password) = self._getAuthorization()
		if not user:
			user = config.get('global', 'host_id')
		return (user, password)

	def _authenticate(self, result):
		if (self.request.remoteAddr.host == '127.0.0.1'):
			self.session.authenticated = False
			return result
		try:
			(self.session.user, self.session.password) = self._getCredentials()

			logger.notice(u"Authorization request from %s@%s (application: %s)" % (self.session.user, self.session.ip, self.session.userAgent))

			if not self.session.password:
				raise Exception(u"No password from %s (application: %s)" % (self.session.ip, self.session.userAgent))

			if (self.session.user.lower() == config.get('global', 'host_id').lower()) and (self.session.password == config.get('global', 'opsi_host_key')):
				return result
			if (os.name == 'nt'):
				if (self.session.user.lower() == 'administrator'):
					import win32security
					# The LogonUser function will raise an Exception on logon failure
					win32security.LogonUser(self.session.user, 'None', self.session.password, win32security.LOGON32_LOGON_NETWORK, win32security.LOGON32_PROVIDER_DEFAULT)
					# No exception raised => user authenticated
					return result

			raise Exception(u"Invalid credentials")
		except Exception, e:
			raise OpsiAuthenticationError(u"Forbidden: %s" % forceUnicode(e))
		return result

	def _processQuery(self, result):
		self._decodeQuery(result)
		query = {}
		for part in self.query.split('&'):
			part = part.strip()
			if not part:
				continue
			k = part
			if (part.find('=') != -1):
				(k, v) = part.split('=', 1)
			k = k.strip().lower()
			v = v.strip().lower()
			if query.has_key(k):
				query[k] = forceUnicodeList(query[k])
				query[k].append(v)
			else:
				query[k] = v
		self.query = query
		logger.debug(u"Query: %s" % self.query)

	def connectConfigService(self):
		ServiceConnection.connectConfigService(self)

	def _getSwOnDemandConfig(self):
		self._swOnDemandProductIds = []
		self._showDetails = False
		logger.debug(u"Getting software-on-demand configs from service")
		self._configService.backend_setOptions({"addConfigStateDefaults": True})
		for configState in self._configService.configState_getObjects(
					configId = ["software-on-demand.*"],
					objectId = config.get('global', 'host_id')):

			logger.debug("Config found: '%s'" % configState.toHash())

			if (configState.getConfigId() == "software-on-demand.product-group-ids"):
				onDemandGroupIds = forceUnicodeLowerList(configState.getValues())
				if onDemandGroupIds:
					for objectToGroup in self._configService.objectToGroup_getObjects(groupType = "ProductGroup", groupId = onDemandGroupIds):
						logger.info(u"On demand product found: '%s'" % objectToGroup.objectId)
						if not objectToGroup.objectId in self._swOnDemandProductIds:
							self._swOnDemandProductIds.append(objectToGroup.objectId)

			elif (configState.getConfigId() == "software-on-demand.show-details"):
				self._showDetails = forceBool(configState.getValues()[0])

			elif (configState.getConfigId() == "software-on-demand.active"):
				if not forceBool(configState.getValues()[0]):
					raise Exception(u"Software on demand deactivated")

	def _processProducts(self, productOnClients):
		modifiedProductOnClients = []
		setupProductIds          = []
		uninstallProductIds      = []
		productIds               = []

		def addToModified(modifiedProductOnClients, productOnClient):
			remove = -1
			for i in range(len(modifiedProductOnClients)):
				if (modifiedProductOnClients[i].productId == productOnClient.productId):
					remove = i
					break
			if (remove > -1):
				modifiedProductOnClients.pop(remove)
			modifiedProductOnClients.append(productOnClient)
			return modifiedProductOnClients

		for (key, value) in self.query.items():
			if not key.startswith('product_'):
				continue
			productId = forceProductId(key.split('product_', 1)[1])
			if (value == 'setup'):
				setupProductIds.append(productId)
				productIds.append(productId)
			elif (value == 'uninstall'):
				uninstallProductIds.append(productId)
				productIds.append(productId)

		for productId in productIds:
			if not productId in self._swOnDemandProductIds:
				raise Exception(u"Product '%s' not available for on-demand" % productId)
			index = -1
			for i in range(len(productOnClients)):
				if (productOnClients[i].productId == productId):
					index = i
					break
			if (index == -1):
				# ProductOnClient does not exist => create
				productOnClient = ProductOnClient(
					productId          = productId,
					productType        = 'LocalbootProduct',
					clientId           = config.get('global', 'host_id'),
					installationStatus = 'not_installed'
				)
				productOnClients.append(productOnClient)
				index = len(productOnClients) - 1
			if (productId in setupProductIds) and (productOnClients[index].getActionRequest() != 'setup'):
				productOnClients[index].setActionRequest('setup')
				modifiedProductOnClients = addToModified(modifiedProductOnClients, productOnClients[index])
			if (productId in uninstallProductIds) and (productOnClients[index].getActionRequest() != 'uninstall'):
				productOnClients[index].setActionRequest('uninstall')
				modifiedProductOnClients = addToModified(modifiedProductOnClients, productOnClients[index])

		for productId in self._swOnDemandProductIds:
			if not productId in productIds:
				for index in range(len(productOnClients)):
					if (productOnClients[index].productId == productId):
						if productOnClients[index].actionRequest in ('setup', 'uninstall'):
							productOnClients[index].setActionRequest('none')
							modifiedProductOnClients = addToModified(modifiedProductOnClients, productOnClients[index])
						break

		productOnClientsWithDependencies = []
		if modifiedProductOnClients:
			logger.info(u"ProductOnClients modified, adding dependencies")
			productOnClientsWithDependencies = self._configService.productOnClient_addDependencies(productOnClients)

		return (modifiedProductOnClients, productOnClients, productOnClientsWithDependencies)

	def _processAction(self, modifiedProductOnClients, productOnClients, productOnClientsWithDependencies):
		logger.notice(u"Action '%s' was sent" % self.query.get('action'))

		productIds = []
		selectedProducts = []
		dependendProducts = []
		otherProducts = []
		for t in ('selected', 'other', 'depend'):
			pocs = []
			if (t == 'selected'):
				pocs = modifiedProductOnClients
			elif (t == 'other'):
				pocs = productOnClients
			elif (t == 'depend'):
				pocs = productOnClientsWithDependencies
			for productOnClient in pocs:
				if productOnClient.actionRequest not in ('none', None) and not productOnClient.productId in productIds:
					productIds.append(productOnClient.productId)
					row = u'<li class="swondemand-summary-product-action">%s (%s)</li>' \
						% (productOnClient.productId, productOnClient.actionRequest)
					if (t == 'selected'):
						selectedProducts.append(row)
						selectedProducts.append(u'<input type="hidden" name="product_%s" value="%s" />' % (productOnClient.productId, productOnClient.actionRequest))
					elif (t == 'other'):
						otherProducts.append(row)
					elif (t == 'depend'):
						dependendProducts.append(row)

		html = []
		if selectedProducts:
			html.append(u'<div class="swondemand-summary-box">')
			html.append(u'<p class="swondemand-summary-title">%s</p><ul>' \
				% _(u'You selected to execute the following product actions:'))
			html.extend(selectedProducts)
			html.append(u'</ul>')
			if self._showDetails:
				if dependendProducts:
					html.append(u'<p class="swondemand-summary-title">%s</p><ul>' \
						% _(u'The following product actions have been added to fulfill dependencies:'))
					html.extend(dependendProducts)
					html.append(u'</ul>')
				if otherProducts:
					html.append(u'<p class="swondemand-summary-title">%s</p><ul>' \
						% _(u'Other pending product actions:'))
					html.extend(otherProducts)
					html.append(u'</ul>')
			html.append(u'</div>')

		buttons = [ u'<button class="swondemand-action-button" type="submit" name="action" value="back">&lt; %s</button>' % _(u"back") ]
		if (self.query.get('action') == "next"):
			if selectedProducts:
				buttons.append(u'<button class="swondemand-action-button" type="submit" name="action" value="onrestart">%s</button>' % _(u"process on next boot"))
				if getEventGenerators(generatorClass = SwOnDemandEventGenerator):
					buttons.append(u'<button class="swondemand-action-button" type="submit" name="action" value="ondemand">%s</button>' % _(u"process now"))
			else:
				html.append(u'<div class="swondemand-summary-message-box">%s</div>' % (_(u'Nothing selected')))

		elif (self.query.get('action') == "ondemand"):
			html.append(u'<div class="swondemand-summary-message-box">%s</div>' % _(u'Starting to process actions now.'))

		elif (self.query.get('action') == "onrestart"):
			html.append(u'<div class="swondemand-summary-message-box">%s</div>' % _(u'Actions will be processed on next boot.'))

		html.append(u'<div class="swondemand-summary-button-box">')
		html.extend(buttons)
		html.append(u'</div>')

		html = mainpage % {
			'result': forceUnicode(u'\n'.join(html)),
			'hostname': config.get('global','host_id'),
		}

		if self.query.get('action') in ('ondemand', 'onrestart'):
			description  = u"Software on demand action '%s' executed\n" % self.query.get('action')
			description += u'Modified product actions:\n'
			for poc in modifiedProductOnClients:
				description += u'   %s: %s\n' % (poc.productId, poc.actionRequest)
			description += u'Product action updates:\n'
			for poc in productOnClientsWithDependencies:
				description += u'   %s: %s\n' % (poc.productId, poc.actionRequest)

			timeline.addEvent(
				title       = u"Software on demand",
				description = description,
				category    = u"user_interaction")
			if modifiedProductOnClients:
				logger.info(u"Updating productOnClients")
				self._configService.productOnClient_updateObjects(productOnClientsWithDependencies)
			if (self.query.get('action') == 'ondemand'):
				for eventGenerator in getEventGenerators(generatorClass = SwOnDemandEventGenerator):
					eventGenerator.createAndFireEvent()

		return html

	def _generateResponse(self, result):
		if not isinstance(result, http.Response):
			result = http.Response()

		html = u''
		try:
			self.connectConfigService()
			self._getSwOnDemandConfig()

			productOnClients = []
			modifiedProductOnClients = []
			productOnClientsWithDependencies = []
			products = []
			productOnDepots = []
			if self._swOnDemandProductIds:
				self._configService.setAsync(True)
				jsonrpc1 = self._configService.productOnClient_getObjects(clientId=config.get('global', 'host_id'))
				jsonrpc2 = self._configService.product_getObjects(id=self._swOnDemandProductIds)
				jsonrpc3 = self._configService.productOnDepot_getObjects(
					depotId=config.get('depot_server', 'depot_id'),
					productId=self._swOnDemandProductIds
				)
				productOnClients = jsonrpc1.waitForResult()
				products = jsonrpc2.waitForResult()
				productOnDepots = jsonrpc3.waitForResult()
				self._configService.setAsync(False)

			for key in self.query.keys():
				if key.startswith('product_'):
					(modifiedProductOnClients, productOnClients, productOnClientsWithDependencies) = self._processProducts(productOnClients)
					logger.debug(u"Modified productOnClients:")
					for poc in modifiedProductOnClients:
						logger.debug(u"   %s" % poc)
					logger.debug(u"Current productOnClients:")
					for poc in productOnClients:
						logger.debug(u"   %s" % poc)
					logger.debug(u"ProductOnClients with dependencies:")
					for poc in productOnClientsWithDependencies:
						logger.debug(u"   %s" % poc)
					break

			if self.query.get('action') in ('next', 'ondemand', 'onrestart'):
				html = self._processAction(modifiedProductOnClients, productOnClients, productOnClientsWithDependencies)

			elif self._swOnDemandProductIds:
				html = []

				# sort productIds by productnames
				productsByProductName = {}
				for productId in self._swOnDemandProductIds:
					for p in products:
						if p.id == productId:
							if p.name not in productsByProductName:
								productsByProductName[p.name] = p
							break
					else:
						logger.error(u"Product with productId '%s' not found." % (productId))

				sortedProductIds = [productsByProductName[name].id for name in
									sorted(productsByProductName.keys(), key=unicode.lower)]

				for productId in sortedProductIds:
					productOnDepot = None
					for pod in productOnDepots:
						if (pod.productId == productId):
							productOnDepot = pod
							break
					else:
						logger.error(u"Product '%s' not found on depot '%s'" % (productId, config.get('depot_server', 'depot_id')))
						continue

					product = None
					for p in products:
						if (p.id == productOnDepot.productId) and (p.productVersion == productOnDepot.productVersion) and (p.packageVersion == productOnDepot.packageVersion):
							product = p
							break
					else:
						logger.error(u"Product '%s' not found" % productId)

					productOnClient = None
					for poc in productOnClients:
						if (poc.productId == productId):
							productOnClient = poc
							break

					installationStatus = None
					state = _('not installed')
					stateclass = u"swondemand-product-state-not_installed"
					setupChecked = u''
					uninstallChecked = u''
					if productOnClient:
						logger.debug(u"Product on client to display: %s" % productOnClient)
						installationStatus = productOnClient.installationStatus
						if (productOnClient.actionRequest == 'setup'):
							setupChecked = u'checked="checked"'
						elif (productOnClient.actionRequest == 'uninstall'):
							uninstallChecked = u'checked="checked"'
						if (productOnClient.installationStatus == "installed"):
							stateclass = "swondemand-product-state-installed"
							state = u"%s (%s: %s-%s)" % ( _('installed'), _('version'), productOnClient.productVersion, productOnClient.packageVersion )

					html.append(u'<div class="swondemand-product-box"><table>')
					html.append(u'<tr><td colspan="2" class="swondemand-product-name">%s (%s-%s)</td></tr>' \
							% (product.name, productOnDepot.productVersion, productOnDepot.packageVersion))
					description = cgi.escape(product.description) or u''
					html.append(u'<tr><td class="swondemand-product-attribute-name">%s:</td>' % _(u'description'))
					html.append(u'    <td class="swondemand-product-attribute-value">%s</td></tr>' \
								% description.replace(u'\n', u'<br />') )

					if self._showDetails:
						html.append(u'<tr><td class="swondemand-product-attribute-name">%s:</td>' % _(u'state'))
						html.append(u'    <td class="swondemand-product-attribute-value %s">%s</td></tr>' \
								% (stateclass, state) )

						advice = cgi.escape(product.advice) or u''
						html.append(u'<tr><td class="swondemand-product-attribute-name">%s:</td>' % _(u'advice'))
						html.append(u'    <td class="swondemand-product-attribute-value">%s</td></tr>' \
								% advice.replace(u'\n', u'<br />') )

					if (installationStatus == 'installed'):
						html.append(u'<tr><td colspan="2" class="swondemand-product-setup-radiobox">')
						html.append(u'       <input type="radio" name="product_%s" value="setup" %s />%s</td></tr>' \
								% ( productId, setupChecked, _('reinstall') ) )
						if product.uninstallScript:
							html.append(u'<tr><td colspan="2" class="swondemand-product-uninstall-radiobox">')
							html.append(u'       <input type="radio" name="product_%s" value="uninstall" %s />%s</td></tr>' \
									% ( productId, uninstallChecked, _('uninstall') ) )
					else:
						html.append(u'<tr><td colspan="2" class="swondemand-product-setup-radiobox">')
						html.append(u'       <input type="radio" name="product_%s" value="setup" %s />%s</td></tr>' \
								% ( productId, setupChecked, _('install') ) )
					html.append(u'</table></div>')
				html.append(u'<div class="swondemand-button-box">')
				html.append(u'<button class="swondemand-action-button" type="submit" name="action" value="next">&gt; %s</button>' % _(u'next'))
				html.append(u'</div>')
				html = mainpage % {
					'result': forceUnicode(u'\n'.join(html)),
					'hostname': config.get('global','host_id')
				}
			else:
				raise Exception(u"No products found")
		except Exception, e:
			logger.logException(e)
			html = mainpage % {
				'result': u'<div class="swondemand-summary-message-box">%s</div>' % e,
				'hostname': config.get('global','host_id'),
			}

		self.disconnectConfigService()
		result.stream = stream.IByteStream(html.encode('utf-8'))
		return result


class ResourceSoftwareOnDemand(ResourceOpsi):
	WorkerClass = WorkerSoftwareOnDemand

class WorkerKioskJsonRpc(WorkerOpsiJsonRpc, ServiceConnection):
	def __init__(self, service, request, resource):
		moduleName = u' %-30s' % (u'software on demand')
		logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)
		self._allowedMethods = self._getAllowedMethods()
		self._fireEvent = False
		WorkerOpsiJsonRpc.__init__(self, service, request, resource)
		ServiceConnection.__init__(self)

	def _getAllowedMethods(self):
		return [
			"backend_exit",
			"backend_setOptions",
			"configState_getObjects",
			"fireEvent_software_on_demand",
			"getDepotId",
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

	def _getCallInstance(self, result):
		#self._getBackend(result)
		self._callInstance = self._configService
		self._callInterface = self._configService.getInterface()

	def _getCredentials(self):
		(user, password) = self._getAuthorization()
		if not user:
			user = config.get('global', 'host_id')
		return (user, password)

	def _authenticate(self, result):
		if (self.request.remoteAddr.host == '127.0.0.1'):
			self.session.authenticated = False
			return result
		try:
			(self.session.user, self.session.password) = self._getCredentials()

			logger.notice(u"Authorization request from %s@%s (application: %s)" % (self.session.user, self.session.ip, self.session.userAgent))

			if not self.session.password:
				raise Exception(u"No password from %s (application: %s)" % (self.session.ip, self.session.userAgent))

			if (self.session.user.lower() == config.get('global', 'host_id').lower()) and (self.session.password == config.get('global', 'opsi_host_key')):
				return result
			if (os.name == 'nt'):
				if (self.session.user.lower() == 'administrator'):
					import win32security
					# The LogonUser function will raise an Exception on logon failure
					win32security.LogonUser(self.session.user, 'None', self.session.password, win32security.LOGON32_LOGON_NETWORK, win32security.LOGON32_PROVIDER_DEFAULT)
					# No exception raised => user authenticated
					return result

			raise Exception(u"Invalid credentials")
		except Exception as e:
			raise OpsiAuthenticationError(u"Forbidden: %s" % forceUnicode(e))
		return result

	def _checkRpcs(self, result):
		if not self._rpcs:
			raise Exception("No rpcs to check")
		for rpc in self._rpcs:
			if not rpc.method in self._allowedMethods:
				raise Exception("You are not allowed to execute the method: '%s'" % rpc.method)
			elif rpc.method == "fireEvent_software_on_demand":
				self._fireEvent = True
				self._rpcs.remove(rpc)
			elif rpc.method == "backend_exit":
				self._rpcs.remove(rpc)
		return result

	def _processQuery(self, result):
		deferred = defer.Deferred()
		deferred.addCallback(self._openConnection)
		deferred.addCallback(self._decodeQuery)
		deferred.addCallback(self._getCallInstance)
		deferred.addCallback(self._getRpcs)
		deferred.addCallback(self._checkRpcs)
		deferred.addCallback(self._executeRpcs)
		#TODO: Let the connection open and let it expire on server
		#deferred.addCallback(self._closeConnection)
		deferred.addCallback(self._checkFireEvent)
		deferred.addErrback(self._errback)
		deferred.callback(None)
		return deferred


	def _openConnection(self, result):
		ServiceConnection.connectConfigService(self)
		return result

	def _closeConnection(self, result):
		self.disconnectConfigService()
		return result

	def _checkFireEvent(self, result):
		if self._fireEvent:
			for eventGenerator in getEventGenerators(generatorClass = SwOnDemandEventGenerator):
				eventGenerator.createAndFireEvent()
			self._fireEvent = False
		return result

class ResourceKioskJsonRpc(ResourceOpsi):
	WorkerClass = WorkerKioskJsonRpc


