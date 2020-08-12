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
:author: Jan Schneider <j.schneider@uib.de>
:license: GNU Affero General Public License version 3
"""

import gettext
import locale

from opsicommon.logging import logger

translation = None
try:
	language = locale.getdefaultlocale()[0].split('_')[0]
except Exception as error:
	logger.debug("Unable to load localisation: %s", error)
	language = "en"


def getLanguage():
	return language


def _(string):
	if translation is None:
		return string

	return translation.gettext(string)


def setLocaleDir(localeDir):
	global translation
	logger.notice("Setting locale dir to '%s'" % localeDir)
	try:
		logger.notice("Loading translation for language '%s'" % language)
		translation = gettext.translation('opsiclientd', localeDir, [language])
	except Exception as error:
		logger.error("Failed to load locale: %s", error)
