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

logger = Logger()
config = Config()

mainpage = u'''
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
	<title>opsi Software On Demand</title>
	<style>
	body          { font-family: verdana, arial; font-size: 12px; }
	#title        { padding: 10px; color: #6276a0; font-size: 20px; letter-spacing: 5px; }
	input, select { background-color: #fafafa; border: 1px #abb1ef solid; font-family: verdana, arial;}
	.title        { color: #555555; font-size: 20px; font-weight: bolder; letter-spacing: 5px; }
	button       { color: #9e445a; background-color: #fafafa; border: 1px solid;  }
	table  { margin-top: 20px; margin-left: 20px; border-collapse:collapse;text-align: center; width: 700px; border: solid #555555 1px; background-color: #D5D9F9;}
	thead           { background-color: #6495ed;}
	.checkbox:hover  { color:#007700; }
	tfoot           { margin-top: 50px; }
	th              { padding: 5px; padding-left: 10px; }
	td              { padding: 5px;}
	.productname    { width: 100px; padding-top:20px; padding-left:20px; text-align:left; font-weight: bolder; font-size: 120%; }
	.product	{ padding-left:10px; vertical-align:top; text-align:left; font-style: italic; }
	.key            { padding-left:10px; vertical-align:top; text-align:right; font-style: italic; }
	.value          { text-align:left; }
	.buttonarea	{ padding: 5px; }
	.checkbox       { border-bottom: solid #555555 1px; text-align:left; padding-bottom:20px; padding-left:20px; }
	</style>

</head>
<body>
	<span id="title">
		<img src="/opsi_logo.png" />
		<span sytle="padding: 1px; top: 5px;">opsi software on demand</span>
	</span>
	<form method="post">
		%result%
	</form>
	
</body>
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
		modules = None
		if self._configService.isOpsi35():
			modules = self._configService.backend_info()['modules']
		else:
			modules = self._configService.getOpsiInformation_hash()['modules']
		
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
					configId = ["software-on-demand.product-group-ids", "software-on-demand.show-details"],
					objectId = config.get('global', 'host_id')):
			
			logger.debug("Config found: '%s'" % configState.toHash())
			
			if (configState.getConfigId() == "software-on-demand.product-group-ids"):
				onDemandGroupIds = forceUnicodeList(configState.getValues())
				if onDemandGroupIds:
					for objectToGroup in self._configService.objectToGroup_getObjects(groupType = "ProductGroup", groupId = onDemandGroupIds):
						logger.debug(u"On demand product found: '%s'" % objectToGroup.objectId)
						if not objectToGroup.objectId in self._swOnDemandProductIds:
							self._swOnDemandProductIds.append(objectToGroup.objectId)
			
			elif (configState.getConfigId() == "software-on-demand.show-details"):
				self._showDetails = forceBool(configState.getValues()[0])
	
	def _processProducts(self):
		productOnClients = self._configService.productOnClient_getObjects(clientId = config.get('global', 'host_id'))
		modifiedProductOnClients = []
		
		for productId in forceProductIdList(self.query.get('product', [])):
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
			if (productOnClients[index].getActionRequest() == 'setup'):
				productOnClients[index].setActionRequest('none')
			else:
				productOnClients[index].setActionRequest('setup')
			modifiedProductOnClients.append(productOnClients[index])
		
		productOnClientsWithDependencies = []
		if modifiedProductOnClients:
			logger.info(u"ProductOnClients modified, adding dependencies")
			productOnClientsWithDependencies = self._configService.productOnClient_addDependencies(productOnClients)
		
		return (modifiedProductOnClients, productOnClients, productOnClientsWithDependencies)
	
	def _processAction(self, modifiedProductOnClients, productOnClients, productOnClientsWithDependencies):
		productIds = []
		tableSelectedRows = []
		tableDependencyRows = []
		tableOtherRows = []
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
					row = u'<tr><td></td><td class="product">%s (%s)</td><td class="value"></td></tr>' \
						% (productOnClient.productId, productOnClient.actionRequest)
					if (t == 'selected'):
						tableSelectedRows.append(row)
						tableSelectedRows.append(u'<input type="hidden" name="product" value="%s" />' % productOnClient.productId)
					elif (t == 'other'):
						tableOtherRows.append(row)
					elif (t == 'depend'):
						tableDependencyRows.append(row)
		
		table = [u'<table>']
		if tableSelectedRows:
			table.append(u'<tr><td colspan="3" class="productname">%s</td></tr>' % _(u'selected products'))
			table.extend(tableSelectedRows)
		if self._showDetails:
			if tableDependencyRows:
				table.append(u'<tr><td colspan="3" class="productname">%s</td></tr>' % _(u'product dependencies'))
				table.extend(tableDependencyRows)
			if tableOtherRows:
				table.append(u'<tr><td colspan="3" class="productname">%s</td></tr>' % _(u'other products'))
				table.extend(tableOtherRows)
		
		logger.notice(u"Action '%s' was sent" % self.query.get('action'))
		buttons = []
		if (self.query.get('action') == "next"):
			if getEventGenerators(generatorClass = SwOnDemandEventGenerator):
				buttons.append(u'<button type="submit" id="submit" name="action" value="ondemand">%s</button>' % _(u"process now"))
			buttons.append(u'<button type="submit" id="submit" name="action" value="onrestart">%s</button>' % _(u"process on next boot"))
		
		elif (self.query.get('action') == "ondemand"):
			table.append(u'<tr><td colspan="3" class="productname" style="color:#007700">%s</td></tr>' % _(u'Starting to process actions now.'))
		
		elif (self.query.get('action') == "onrestart"):
			table.append(u'<tr><td colspan="3" class="productname" style="color:#007700">%s</td></tr>' % _(u'Actions will be processed on next boot.'))
		
		else:
			table.append(u'<tr><td colspan="3" class="productname">%s</td></tr>' % (_(u'Nothing selected')))
		
		buttons.append(u'<button type="submit" id="submit" name="action" value="back">%s</button>' % _(u"back"))
		table.append(u'<tr><td align="center" colspan="3" class="buttonarea">')
		table.extend(buttons)
		table.append(u'</td></tr>')
		table.append(u'</table>')
		
		html = mainpage.replace('%result%', forceUnicode(u'\n'.join(table)))
		
		if self.query.get('action') in ('ondemand', 'onrestart'):
			if modifiedProductOnClients:
				logger.info(u"Updating productOnClients")
				self._configService.productOnClient_updateObjects(productOnClientsWithDependencies)
			if (self.query.get('action') == 'ondemand'):
				for eventGenerator in getEventGenerators(generatorClass = SwOnDemandEventGenerator):
					eventGenerator.fireEvent()
		
		return html
	
	def _generateResponse(self, result):
		if not isinstance(result, http.Response):
			result = http.Response()
		
		self.connectConfigService()
		self._getSwOnDemandConfig()
		
		productOnClients = []
		modifiedProductOnClients = []
		productOnClientsWithDependencies = []
		html = u''
		
		if self.query.get('product'):
			(modifiedProductOnClients, productOnClients, productOnClientsWithDependencies) = self._processProducts()
		
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
			
			table = [u'<table><tbody>']
			for productId in self._swOnDemandProductIds:
				productOnClient = None
				for poc in productOnClients:
					if (poc.productId == productId):
						productOnClient = poc
						break
				
				product = None
				for p in products:
					if (p.id == productId):
						product = p
						break
				if not product:
					logger.error(u"Product '%s' not found" % productId)
				
				productOnDepot = None
				for pod in productOnDepots:
					if (pod.productId == productId):
						productOnDepot = pod
						break
				if not productOnDepot:
					logger.error(u"Product '%s' not found on depot '%s'" % (productId, config.get('depot_server', 'depot_id')))
				
				state = _('not installed')
				statecolor = u"color:#770000"
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
						statecolor = "color:#007700"
						state = u"%s (%s: %s-%s)" % ( _('installed'), _('version'), productOnClient.productVersion, productOnClient.packageVersion )
					else:
						state = _('not installed')
				
				table.append(u'<tr><td colspan="3" class="productname">%s (%s-%s)</td></tr>' \
						% (product.name, productOnDepot.productVersion, productOnDepot.packageVersion))
				description = product.description or u''
				table.append(u'<tr><td></td><td class="key">%s</td><td class="value">%s</td>' \
						% ( _(u'description'), description.replace(u'\n', u'<br />') ) )
				
				if self._showDetails:
					table.append(u'<tr><td></td><td class="key">%s</td><td class="value" style="%s">%s</td>' \
							% ( _('state'), statecolor, state ) )
					advice = product.advice or u''
					table.append(u'<tr><td></td><td class="key">%s</td><td class="value">%s</td>' \
							% ( _('advice'), advice.replace(u'\n', u'<br />') ) )
				table.append(u'<tr><td colspan="3" class="checkbox"><input type="checkbox" name="product" value="%s" %s>%s</td></td>' \
						% ( productId, checked, _('install') ) )
			table.append(u'<tr><td align="center" colspan="3"><input name="action" value="%s" id="submit" class="button" type="submit" /></td><tr>' % _(u'next'))
			table.append(u'</tbody></table>')
			html = mainpage.replace('%result%', u'\n'.join(table))
			
		self.disconnectConfigService()
		result.stream = stream.IByteStream(html.encode('utf-8'))
		return result

class ResourceSoftwareOnDemand(ResourceOpsi):
	WorkerClass = WorkerSoftwareOnDemand
