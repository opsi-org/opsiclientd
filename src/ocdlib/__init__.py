#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = =
   =   Dummy                           =
   = = = = = = = = = = = = = = = = = = =
   
   This module is part of the desktop management solution opsi
   (open pc server integration) http://www.opsi.org
   
   Copyright (C) 2010 uib GmbH
   
   http://www.uib.de/
   
   All rights reserved.
   
   This program is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License version 2 as
   published by the Free Software Foundation.
   
   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.
   
   You should have received a copy of the GNU General Public License
   along with this program; if not, write to the Free Software
   Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
   
   @copyright:	uib GmbH <info@uib.de>
   @author: Erol Ueluekmen <e.ueluekmen@uib.de>
   @license: GNU General Public License version 2
"""

# OPSI imports
from OPSI.Logger import *
from OPSI.Types import *
from OPSI import System

# Get logger instance
logger = Logger()



def selectDepotserver(config, configService, event, productIds=[], cifsOnly=True, masterOnly=False):
	productIds = forceProductIdList(productIds)
	
	logger.notice(u"Selecting depot for products %s" % productIds)
	
	if event and event.eventConfig.useCachedProducts:
		cacheDepotDir = os.path.join(config.get('cache_service', 'storage_dir'), 'depot').replace('\\', '/').replace('//', '/')
		logger.notice(u"Using depot cache: %s" % cacheDepotDir)
		config.setTemporaryDepotDrive(cacheDepotDir.split(':')[0] + u':')
		config.set('depot_server', 'url', 'smb://localhost/noshare/' + ('/'.join(cacheDepotDir.split('/')[1:])))
		return
	
	if not configService:
		raise Exception(u"Not connected to config service")
	
	if configService.isLegacyOpsi():
		return
	
	selectedDepot = None
	
	configService.backend_setOptions({"addConfigStateDefaults": True})
	
	depotIds = []
	dynamicDepot = False
	depotProtocol = 'cifs'
	for configState in configService.configState_getObjects(
				configId = ['clientconfig.depot.dynamic', 'clientconfig.depot.protocol', 'opsiclientd.depot_server.depot_id', 'opsiclientd.depot_server.url'],
				objectId = config.get('global', 'host_id')):
		if not configState.values or not configState.values[0]:
			continue
		if   (configState.configId == 'opsiclientd.depot_server.url') and configState.values:
			try:
				depotUrl = forceUrl(configState.values[0])
				config.set('depot_server', 'depot_id', u'')
				config.set('depot_server', 'url', depotUrl)
				logger.notice(u"Depot url was set to '%s' from configState %s" % (depotUrl, configState))
				return
			except Exception, e:
				logger.error(u"Failed to set depot url from values %s in configState %s: %s" % (configState.values, configState, e))
		elif (configState.configId == 'opsiclientd.depot_server.depot_id') and configState.values:
			try:
				depotId = forceHostId(configState.values[0])
				depotIds.append(depotId)
				logger.notice(u"Depot was set to '%s' from configState %s" % (depotId, configState))
			except Exception, e:
				logger.error(u"Failed to set depot id from values %s in configState %s: %s" % (configState.values, configState, e))
		elif not masterOnly and (configState.configId == 'clientconfig.depot.dynamic') and configState.values:
			dynamicDepot = forceBool(configState.values[0])
		elif (configState.configId == 'clientconfig.depot.protocol') and configState.values and configState.values[0] and (configState.values[0] == 'webdav'):
			depotProtocol = 'webdav'
	
	if dynamicDepot:
		if not depotIds:
			logger.info(u"Dynamic depot selection enabled")
		else:
			logger.info(u"Dynamic depot selection enabled, but depot is already selected")
	else:
		logger.info(u"Dynamic depot selection disabled")
	
	if not depotIds:
		clientToDepotservers = configService.configState_getClientToDepotserver(
				clientIds  = [ config.get('global', 'host_id') ],
				masterOnly = (not dynamicDepot),
				productIds = productIds)
		if not clientToDepotservers:
			raise Exception(u"Failed to get depot config from service")
		
		depotIds = [ clientToDepotservers[0]['depotId'] ]
		if dynamicDepot:
			depotIds.extend(clientToDepotservers[0].get('alternativeDepotIds', []))
		
	masterDepot = None
	alternativeDepots = []
	for depot in configService.host_getObjects(type = 'OpsiDepotserver', id = depotIds):
		if (depot.id == depotIds[0]):
			masterDepot = depot
		else:
			alternativeDepots.append(depot)
	if not masterDepot:
		raise Exception(u"Failed to get info for master depot '%s'" % depotIds[0])
	
	logger.info(u"Master depot for products %s is %s" % (productIds, masterDepot.id))
	selectedDepot = masterDepot
	if dynamicDepot:
		if alternativeDepots:
			logger.info(u"Got alternative depots for products: %s" % productIds)
			for i in range(len(alternativeDepots)):
				logger.info(u"%d. alternative depot is %s" % ((i+1), alternativeDepots[i].id))
			
			try:
					
				defaultInterface = None
				networkInterfaces = System.getNetworkInterfaces()
				if not networkInterfaces:
					raise Exception(u"No network interfaces found")
				for networkInterface in networkInterfaces:
					logger.info(u"Found network interface: %s" % networkInterface)
				defaultInterface = networkInterfaces[0]
				for networkInterface in networkInterfaces:
					if (networkInterface.ipAddressList.ipAddress == '0.0.0.0'):
						continue
					if networkInterface.gatewayList.ipAddress:
						defaultInterface = networkInterface
						break
				clientConfig = {
					"clientId":       config.get('global', 'host_id'),
					"opsiHostKey":    config.get('global', 'opsi_host_key'),
					"ipAddress":      forceUnicode(defaultInterface.ipAddressList.ipAddress),
					"netmask":        forceUnicode(defaultInterface.ipAddressList.ipMask),
					"defaultGateway": forceUnicode(defaultInterface.gatewayList.ipAddress)
				}
				
				logger.info(u"Passing client configuration to depot selection algorithm: %s" % clientConfig)
				
				depotSelectionAlgorithm = configService.getDepotSelectionAlgorithm()
				logger.debug2(u"depotSelectionAlgorithm:\n%s" % depotSelectionAlgorithm)
				exec(depotSelectionAlgorithm)
				selectedDepot = selectDepot(clientConfig = clientConfig, masterDepot = masterDepot, alternativeDepots = alternativeDepots)
				if not selectedDepot:
					selectedDepot = masterDepot
			except Exception, e:
				logger.logException(e)
				logger.error(u"Failed to select depot: %s" % e)
		else:
			logger.info(u"No alternative depot for products: %s" % productIds)
	logger.notice(u"Selected depot is: %s" % selectedDepot)
	config.set('depot_server', 'depot_id', selectedDepot.id)
	if (depotProtocol == 'webdav') and not cifsOnly:
		config.set('depot_server', 'url', selectedDepot.depotWebdavUrl)
	else:
		config.set('depot_server', 'url', selectedDepot.depotRemoteUrl)



