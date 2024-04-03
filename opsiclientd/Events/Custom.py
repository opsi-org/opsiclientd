# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

"""
Custom event.

This module selects the appropriate custom implementation based on the
OS it is running on.
"""

from opsiclientd.SystemCheck import RUNNING_ON_WINDOWS

if RUNNING_ON_WINDOWS:
	from opsiclientd.Events.Windows.Custom import (  # type: ignore[assignment]
		CustomEvent,
		CustomEventConfig,
		CustomEventGenerator,
	)
else:
	from opsiclientd.Events.Posix.Custom import (  # type: ignore[assignment]
		CustomEvent,
		CustomEventConfig,
		CustomEventGenerator,
	)

__all__ = ["CustomEvent", "CustomEventConfig", "CustomEventGenerator"]
