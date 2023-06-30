# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
Localisation ofopsiclientd.
"""

import gettext
import locale
from pathlib import Path

from opsicommon.logging import logger

try:
	language = (
		locale.getlocale("LC_ALL")[0]
		or locale.getlocale("LC_CTYPE")[0]
		or locale.getlocale("LANG")[0]
		or locale.getlocale("LANGUAGE")[0]
	).split("_")[0]
except Exception as err:  # pylint: disable=broad-except
	logger.debug("Failed to find default language: %s", err)
	language = "en"  # pylint: disable=invalid-name

path: Path | None = None  # pylint: disable=invalid-name
try:
	logger.debug("Loading translation for language '%s'", language)
	path = Path(__file__).parent.resolve()
	if (path / "site-packages").exists():
		path = path / "site-packages"
	if (path / "opsiclientd_data").exists():  # only windows
		path = path / "opsiclientd_data"
	path = path / "locale"
	translation = gettext.translation('opsiclientd', path, [language])
	_ = translation.gettext
except Exception as err:  # pylint: disable=broad-except
	logger.debug("Failed to load locale for %s from %s: %s", language, path, err)

	def _(string):
		""" Fallback function """
		return string


def getLanguage() -> str:
	return language
