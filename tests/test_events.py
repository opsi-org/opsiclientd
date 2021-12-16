# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
test_events
"""

from opsiclientd.Events.Utilities.Configs import getEventConfigs

from .utils import default_config  # pylint: disable=unused-import


def testGettingEventConfiguration():
	"""
	Testing if event configuration can be read from an config file.
	No check if the data is correct.
	"""
	configs = getEventConfigs()
	assert configs, 'no event configurations read'
