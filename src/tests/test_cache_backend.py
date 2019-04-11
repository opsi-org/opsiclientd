# -*- coding: utf-8 -*-

from OPSI.Backend.JSONRPC import JSONRPCBackend
from OPSI.Exceptions import BackendConfigurationError

import pytest

cacheBackendModule = pytest.importorskip("ocdlibnonfree.CacheBackend")
ClientCacheBackend = cacheBackendModule.ClientCacheBackend

sqlModule = pytest.importorskip("OPSI.Backend.SQLite")
SQLiteBackend = sqlModule.SQLiteBackend


def testBackendRequiresConfiguration():
    with pytest.raises(BackendConfigurationError):
        ClientCacheBackend()


@pytest.mark.skipif(True, reason="Create propert automated test")
def testBackend():  # TODO: create a test
    workBackend = SQLiteBackend(database=':memory:')

    serviceBackend = JSONRPCBackend(
        address='https://bonifax.uib.local:4447/rpc',
        username='cachetest.uib.local',
        password='12c1e40a6d3038d3eb2b4d489e978973'
    )

    cb = ClientCacheBackend(
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
