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
import platform
from pathlib import Path
from typing import Any, Iterable

from opsicommon.logging import get_logger
from opsicommon.logging.constants import TRACE

DOMAIN = "opsiclientd"
logger = get_logger()
locale_path: Path | None = None
translation: gettext.GNUTranslations | None = None
translation_func = None


def _(message: str) -> str:
	logger.trace("Translating %r with %s", message, translation_func)
	if not translation_func:
		return message
	translated_message = translation_func(message)
	logger.trace("Translated %r to %r", message, translated_message)
	return translated_message


def load_translation(languages: Iterable[str] | None = None) -> None:
	global translation
	global translation_func
	global locale_path
	try:
		from opsiclientd.Config import Config

		check_paths = [
			Path(__file__).parent.parent.resolve() / "opsiclientd_data" / "locale",
			Path(Config.getBaseDirectory()) / "opsiclientd" / "locale",
		]
		existing_paths = [p for p in check_paths if p.exists()]
		if not existing_paths:
			raise RuntimeError("Failed to find locale path, checked: %s", check_paths)

		locale_path = existing_paths[0]

		logger.debug("Loading translations from '%s' (languages=%r)", locale_path, languages)

		gettext.bindtextdomain(domain=DOMAIN, localedir=locale_path)
		gettext.textdomain(domain=DOMAIN)
		try:
			translation = gettext.translation(domain=DOMAIN, localedir=locale_path, languages=languages)
		except FileNotFoundError:
			if not platform.system().lower() == "windows":
				raise
			import ctypes

			windll = ctypes.windll.kernel32  # type: ignore
			windll.GetUserDefaultUILanguage()
			lang = locale.windows_locale[windll.GetUserDefaultUILanguage()]
			languages = gettext._expand_lang(lang)  # type: ignore
			logger.debug(
				"Failed to load translations without specified language, trying languages %r from GetUserDefaultUILanguage", languages
			)
			translation = gettext.translation(domain=DOMAIN, localedir=locale_path, languages=languages)

		translation_func = translation.gettext
		logger.debug("Using translation: %r", translation.info())
		if logger.isEnabledFor(TRACE):
			logger.trace("Translation catalog:\n%s", "\n".join(f"'{k}' => '{v}'" for k, v in translation._catalog.items() if k))  # type: ignore

	except Exception as err:
		logger.debug("Failed to load translation from '%s': %s", locale_path, err)


def get_language() -> str:
	if translation:
		return translation.info().get("language", "en")
	return "en"


def get_locale_path() -> Path | None:
	return locale_path


def get_translation() -> gettext.NullTranslations | None:
	return translation


def get_translation_info() -> dict[str, Any]:
	locale_path = get_locale_path()
	data: dict[str, Any] = {
		"language": get_language(),
		"locale_path": str(locale_path) if locale_path else None,
		"translation_info": {},
	}
	if translation:
		data["translation_info"] = translation.info()
		data["translation_info"]["catalog"] = dict(translation._catalog)  # type: ignore[attr-defined]
	return data
