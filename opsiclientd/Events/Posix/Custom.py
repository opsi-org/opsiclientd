# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0
"""
Posix-specific custom event.

This does not use WMI.
"""

from OPSI.Logger import Logger

__all__ = ['CustomEvent', 'CustomEventConfig', 'CustomEventGenerator']

logger = Logger()

try:
	from opsiclientd.nonfree.Events.Config import CustomEventConfig
	from opsiclientd.nonfree.Events.Generator import CustomEvent, CustomEventGenerator
except ImportError as error:
	logger.critical(
		"Unable to import from opsiclientd.nonfree."
		"Is this the full version?"
	)
	raise error
