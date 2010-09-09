# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = =
   =   ocdlib.Localization             =
   = = = = = = = = = = = = = = = = = = =
   
   opsiclientd is part of the desktop management solution opsi
   (open pc server integration) http://www.opsi.org
   
   Copyright (C) 2010 uib GmbH
   
   http://www.uib.de/
   
   All rights reserved.
   
   This program is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License version 2 as
   published by the Free Software Foundation.
   
   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.
   
   You should have received a copy of the GNU General Public License
   along with this program; if not, write to the Free Software
   Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
   
   @copyright:	uib GmbH <info@uib.de>
   @author: Jan Schneider <j.schneider@uib.de>
   @license: GNU General Public License version 2
"""

# Imports
import gettext, locale

# OPSI imports
from OPSI.Logger import *

# Get logger instance
logger = Logger()

translation = None
try:
	language = locale.getdefaultlocale()[0].split('_')[0]
except Exception, e:
	language = 'en'

def getLanguage():
	return language

def _(string):
	if not translation:
		return string
	return translation.ugettext(string)
	
def setLocaleDir(localeDir):
	global translation
	logger.notice(u"Setting locale dir to '%s'" % localeDir)
	try:
		logger.notice(u"Loading translation for language '%s'" % language)
		translation = gettext.translation('opsiclientd', localeDir, [language])
	except Exception, e:
		logger.error(u"Locale not found: %s" % e)

