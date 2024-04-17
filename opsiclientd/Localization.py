# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

"""
Localisation of opsiclientd.
"""

import gettext
import locale
from pathlib import Path

from opsicommon.logging import logger

try:
	language = (locale.getlocale()[0] or "en").split("_")[0]
except Exception as err:
	logger.debug("Failed to find default language: %s", err)
	language = "en"

path: Path | None = None
try:
	logger.debug("Loading translation for language '%s'", language)

	from opsiclientd.Config import Config

	check_paths = [Path(__file__).parent.parent.resolve() / "opsiclientd_data" / "locale", Path(Config.getBaseDirectory()) / "locale"]
	existing_paths = [p for p in check_paths if p.exists()]
	if not existing_paths:
		raise RuntimeError("Failed to find locale path, checked: %s", check_paths)

	path = existing_paths[0]
	translation = gettext.translation("opsiclientd", path, [language])
	_ = translation.gettext
except Exception as err:
	logger.debug("Failed to load locale for '%s' from '%s': %s", language, path, err)

	def _(message: str) -> str:
		"""Fallback function"""
		return message


def getLanguage() -> str:
	logger.debug("Using translation '%s' with files located at '%s'", language, path)
	return language
