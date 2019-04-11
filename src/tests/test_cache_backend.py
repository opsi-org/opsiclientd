# -*- coding: utf-8 -*-

from OPSI.Exceptions import BackendConfigurationError

import pytest

docutils = pytest.importorskip("ocdlibnonfree.CacheBackend")
from ocdlibnonfree.CacheBackend import ClientCacheBackend


def testBackendRequiresConfiguration(config, configFile):
    with pytest.raises(BackendConfigurationError):
        ClientCacheBackend()
