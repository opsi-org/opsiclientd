# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org
# Copyright (C) 2010-2018 uib GmbH <info@uib.de>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
Localisation ofopsiclientd.

:copyright: uib GmbH <info@uib.de>
:license: GNU Affero General Public License version 3
"""

import os
import gettext
import locale

from opsicommon.logging import logger

try:
	language = locale.getdefaultlocale()[0].split('_')[0]
except Exception as err: # pylint: disable=broad-except
	logger.debug("Failed to find default language: %s", err)
	language = "en" # pylint: disable=invalid-name

sp = None # pylint: disable=invalid-name
try:
	logger.debug("Loading translation for language '%s'", language)
	sp = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
	if os.path.exists(os.path.join(sp, "site-packages")):
		sp = os.path.join(sp, "site-packages")
	sp = os.path.join(sp, 'opsiclientd_data', 'locale')
	translation = gettext.translation('opsiclientd', sp, [language])
	_ = translation.gettext
except Exception as err: # pylint: disable=broad-except
	logger.debug("Failed to load locale for %s from %s: %s", language, sp, err)

	def _(string):
		""" Fallback function """
		return string

def getLanguage():
	return language
