# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = =
   =   ocdlibnonfree                   =
   = = = = = = = = = = = = = = = = = = =
   
   This module is part of the desktop management solution opsi
   (open pc server integration) http://www.opsi.org
   
   Copyright (C) 2010 uib GmbH
   
   http://www.uib.de/
   
   All rights reserved.
   
   @copyright:	uib GmbH <info@uib.de>
   @author: Erol Ülükmen <e.ueluekmen@uib.de>
"""
# Import
import base64, cgi
from hashlib import md5
from twisted.conch.ssh import keys

# OPSI imports
from OPSI.web2 import responsecode, http, stream
from OPSI.Logger import *
from OPSI.Types import *
from OPSI.Object import *
from OPSI.Service.Worker import WorkerOpsi
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
	<title>opsi software on demand</title>
	<link rel="stylesheet" type="text/css" href="/opsiclientd.css" />
	<meta http-equiv="Content-Type" content="text/xhtml; charset=utf-8" />
</head>
<body>
	<div id="title-image"></div>
	<div id="title-text">opsi software on demand</div>
	<form action="/swondemand" method="post">
		%result%
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
	
	def connectConfigService(self):
		ServiceConnection.connectConfigService(self)
		modules = self._configService.backend_info()['modules']
		
		if not modules.get('swondemand'):
			raise Exception(u"SoftwareOnDemand not available: swondemand module currently disabled")
		
		if not modules.get('customer'):
			raise Exception(u"SoftwareOnDemand not available: No customer in modules file")
			
		if not modules.get('valid'):
			raise Exception(u"SoftwareOnDemand not available: modules file invalid")
		
		if (modules.get('expires', '') != 'never') and (time.mktime(time.strptime(modules.get('expires', '2000-01-01'), "%Y-%m-%d")) - time.time() <= 0):
			raise Exception(u": modules file expired")
		
		logger.info(u"Verifying modules file signature")
		publicKey = keys.Key.fromString(data = base64.decodestring('AAAAB3NzaC1yc2EAAAADAQABAAABAQCAD/I79Jd0eKwwfuVwh5B2z+S8aV0C5suItJa18RrYip+d4P0ogzqoCfOoVWtDojY96FDYv+2d73LsoOckHCnuh55GA0mtuVMWdXNZIE8Avt/RzbEoYGo/H0weuga7I8PuQNC/nyS8w3W8TH4pt+ZCjZZoX8S+IizWCYwfqYoYTMLgB0i+6TCAfJj3mNgCrDZkQ24+rOFS4a8RrjamEz/b81noWl9IntllK1hySkR+LbulfTGALHgHkDUlk0OSu+zBPw/hcDSOMiDQvvHfmR4quGyLPbQ2FOVm1TzE0bQPR+Bhx4V8Eo2kNYstG2eJELrz7J1TJI0rCjpB+FQjYPsP')).keyObject
		data = u''
		mks = modules.keys()
		mks.sort()
		for module in mks:
			if module in ('valid', 'signature'):
				continue
			val = modules[module]
			if (val == False): val = 'no'
			if (val == True):  val = 'yes'
			data += u'%s = %s\r\n' % (module.lower().strip(), val)
		if not bool(publicKey.verify(md5(data).digest(), [ long(modules['signature']) ])):
			raise Exception(u"SoftwareOnDemand not available: modules file invalid")
	
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
	
	def _processProducts(self):
		productOnClients = self._configService.productOnClient_getObjects(clientId = config.get('global', 'host_id'))
		modifiedProductOnClients = []
		
		productIds = forceProductIdList(self.query.get('product', []))
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
			if (productOnClients[index].getActionRequest() != 'setup'):
				productOnClients[index].setActionRequest('setup')
				modifiedProductOnClients.append(productOnClients[index])
			
		for productId in self._swOnDemandProductIds:
			if not productId in productIds:
				for i in range(len(productOnClients)):
					if (productOnClients[i].productId == productId):
						productOnClients[i].setActionRequest('none')
						modifiedProductOnClients.append(productOnClients[i])
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
						selectedProducts.append(u'<input type="hidden" name="product" value="%s" />' % productOnClient.productId)
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
		
		html = mainpage.replace('%result%', forceUnicode(u'\n'.join(html)))
		
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
			productOnClients = []
			modifiedProductOnClients = []
			productOnClientsWithDependencies = []
			
			self.connectConfigService()
			self._getSwOnDemandConfig()
		
			if self.query.get('product'):
				(modifiedProductOnClients, productOnClients, productOnClientsWithDependencies) = self._processProducts()
				logger.debug(u"Modified productOnClients:")
				for poc in modifiedProductOnClients:
					logger.debug(u"   %s" % poc)
				logger.debug(u"Current productOnClients:")
				for poc in productOnClients:
					logger.debug(u"   %s" % poc)
				logger.debug(u"ProductOnClients with dependencies:")
				for poc in productOnClientsWithDependencies:
					logger.debug(u"   %s" % poc)
				
			if self.query.get('action') in ('next', 'ondemand', 'onrestart'):
				html = self._processAction(modifiedProductOnClients, productOnClients, productOnClientsWithDependencies)
			
			elif self._swOnDemandProductIds:
				self._configService.setAsync(True)
				jsonrpc1 = self._configService.productOnClient_getObjects(clientId = config.get('global', 'host_id'))
				jsonrpc2 = self._configService.product_getObjects(id = self._swOnDemandProductIds)
				jsonrpc3 = self._configService.productOnDepot_getObjects(depotId = config.get('depot_server', 'depot_id'), productId = self._swOnDemandProductIds)
				productOnClients = jsonrpc1.waitForResult()
				products = jsonrpc2.waitForResult()
				productOnDepots = jsonrpc3.waitForResult()
				self._configService.setAsync(False)
				
				html = []
				for productId in self._swOnDemandProductIds:
					html.append(u'<div class="swondemand-product-box"><table>')
					productOnClient = None
					for poc in productOnClients:
						if (poc.productId == productId):
							productOnClient = poc
							break
					
					productOnDepot = None
					for pod in productOnDepots:
						if (pod.productId == productId):
							productOnDepot = pod
							break
					if not productOnDepot:
						logger.error(u"Product '%s' not found on depot '%s'" % (productId, config.get('depot_server', 'depot_id')))
					
					product = None
					for p in products:
						if (p.id == productOnDepot.productId) and (p.productVersion == productOnDepot.productVersion) and (p.packageVersion == productOnDepot.packageVersion):
							product = p
							break
					if not product:
						logger.error(u"Product '%s' not found" % productId)
					
					state = _('not installed')
					stateclass = u"swondemand-product-state-not_installed"
					checked = u''
					for poc in modifiedProductOnClients:
						if (poc.productId == productId):
							if poc.actionRequest not in (None, 'none'):
								checked = u'checked="checked"'
							break
					if productOnClient:
						if (productOnClient.actionRequest == 'setup'):
							checked = u'checked="checked"'
						if (productOnClient.installationStatus == "installed"):
							stateclass = "swondemand-product-state-installed"
							state = u"%s (%s: %s-%s)" % ( _('installed'), _('version'), productOnClient.productVersion, productOnClient.packageVersion )
						else:
							state = _('not installed')
					
					html.append(u'<tr><td colspan="2" class="swondemand-product-name">%s (%s-%s)</td></tr>' \
							% (product.name, productOnDepot.productVersion, productOnDepot.packageVersion))
					description = product.description or u''
					html.append(u'<tr><td class="swondemand-product-attribute-name">%s:</td>' % _(u'description'))
					html.append(u'    <td class="swondemand-product-attribute-value">%s</td></tr>' \
								% description.replace(u'\n', u'<br />') )
					
					if self._showDetails:
						html.append(u'<tr><td class="swondemand-product-attribute-name">%s:</td>' % _(u'state'))
						html.append(u'    <td class="swondemand-product-attribute-value %s">%s</td></tr>' \
								% (stateclass, state) )
						
						advice = product.advice or u''
						html.append(u'<tr><td class="swondemand-product-attribute-name">%s:</td>' % _(u'advice'))
						html.append(u'    <td class="swondemand-product-attribute-value">%s</td></tr>' \
								% advice.replace(u'\n', u'<br />') )
					
					html.append(u'<tr><td colspan="2" class="swondemand-product-checkbox">')
					html.append(u'       <input type="checkbox" name="product" value="%s" %s />%s</td></tr>' \
							% ( productId, checked, _('install') ) )
					html.append(u'</table></div>')
				html.append(u'<div class="swondemand-button-box">')
				html.append(u'<button class="swondemand-action-button" type="submit" name="action" value="next">&gt; %s</button>' % _(u'next'))
				html.append(u'</div>')
				html = mainpage.replace('%result%', u'\n'.join(html))
			else:
				raise Exception(u"No products found")
		except Exception, e:
			html = mainpage.replace('%result%', u'<div class="swondemand-summary-message-box">%s</div>' % e)
		
		self.disconnectConfigService()
		result.stream = stream.IByteStream(html.encode('utf-8'))
		return result

class ResourceSoftwareOnDemand(ResourceOpsi):
	WorkerClass = WorkerSoftwareOnDemand
