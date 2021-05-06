# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

from OPSI.Backend.Backend import ExtendedConfigDataBackend
from OPSI.Backend.JSONRPC import JSONRPCBackend
from OPSI.Exceptions import BackendConfigurationError
import pytest

@pytest.fixture(scope="module")
def clientCacheBackendClass():
	cacheBackendModule = pytest.importorskip("ocdlibnonfree.CacheBackend")
	return cacheBackendModule.ClientCacheBackend

def testBackendRequiresConfiguration(clientCacheBackendClass):
	with pytest.raises(BackendConfigurationError):
		clientCacheBackendClass()

@pytest.mark.skipif(True, reason="Create propert automated test")
def testBackend(clientCacheBackendClass):  # TODO: create a test
	sqlModule = pytest.importorskip("OPSI.Backend.SQLite")
	workBackend = sqlModule.SQLiteBackend(database=':memory:')
	serviceBackend = JSONRPCBackend(
		address='https://bonifax.uib.local:4447/rpc',
		username='cachetest.uib.local',
		password='12c1e40a6d3038d3eb2b4d489e978973'
	)

	cb = clientCacheBackendClass(
		workBackend=workBackend,
		masterBackend=serviceBackend,
		depotId='bonifax.uib.local',
		clientId='cachetest.uib.local'
	)

	# workBackend._sql.execute('PRAGMA synchronous=OFF')
	cb._replicateMasterToWorkBackend()
	be = ExtendedConfigDataBackend(cb)
	# cb.host_insertObject( OpsiClient(id = 'cachetest.uib.local', description = 'description') )
	# print cb.host_getObjects()
	# print workBackend._sql.getSet('select * from HOST')
	# for productPropertyState in cb.productPropertyState_getObjects(objectId = 'cachetest.uib.local'):
	#   print productPropertyState.toHash()
	# for productOnClient in cb.productOnClient_getObjects(clientId = 'cachetest.uib.local'):
	#   print productOnClient.toHash()
	print(be.licenseOnClient_getOrCreateObject(clientId='cachetest.uib.local', productId='license-test-oem'))
