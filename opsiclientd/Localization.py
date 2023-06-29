# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
Localisation ofopsiclientd.
"""

import os
import gettext
import locale

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

sp = None  # pylint: disable=invalid-name
try:
	logger.debug("Loading translation for language '%s'", language)
	sp = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
	if os.path.exists(os.path.join(sp, "site-packages")):
		sp = os.path.join(sp, "site-packages")
	sp = os.path.join(sp, 'opsiclientd_data', 'locale')
	translation = gettext.translation('opsiclientd', sp, [language])
	_ = translation.gettext
except Exception as err:  # pylint: disable=broad-except
	logger.debug("Failed to load locale for %s from %s: %s", language, sp, err)

	def _(string):
		""" Fallback function """
		return string


def getLanguage():
	return language
