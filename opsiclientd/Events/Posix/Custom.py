# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2026 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0-only

"""
Posix-specific custom event.

This does not use WMI.
"""

from opsi.logging import logger

__all__ = ["CustomEvent", "CustomEventConfig", "CustomEventGenerator"]

try:
	from opsiclientd.nonfree.Events.Config import CustomEventConfig
	from opsiclientd.nonfree.Events.Generator import CustomEvent, CustomEventGenerator
except ImportError:
	logger.critical("Unable to import from opsiclientd.nonfree, is this the full version?")
	raise
