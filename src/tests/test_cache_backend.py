# -*- coding: utf-8 -*-

from OPSI.Exceptions import BackendConfigurationError

import pytest

cacheBackendModule = pytest.importorskip("ocdlibnonfree.CacheBackend")
ClientCacheBackend = cacheBackendModule.ClientCacheBackend



def testBackendRequiresConfiguration():
    with pytest.raises(BackendConfigurationError):
        ClientCacheBackend()
