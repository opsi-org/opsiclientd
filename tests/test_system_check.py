# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0

import os
from opsiclientd.SystemCheck import RUNNING_ON_WINDOWS

def test_system_determining():
	assert RUNNING_ON_WINDOWS == bool(os.name == 'nt')
