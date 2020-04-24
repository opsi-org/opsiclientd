# -*- coding: utf-8 -*-

import os

from ocdlib.SystemCheck import RUNNING_ON_WINDOWS


def test_system_determining():
        assert RUNNING_ON_WINDOWS == bool(os.name == 'nt')
