# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

"""
test_config
"""

import shutil
from pathlib import Path

import pytest

from opsiclientd.Config import (
	Config,
	NoConfigOptionFoundException,
	SectionNotFoundException,
)

from .utils import default_config  # noqa

config = Config()


def test_getting_unknown_section_fails() -> None:
	with pytest.raises(SectionNotFoundException):
		config.get("nothing", "bla")


def test_default_paths_exist_per_os() -> None:
	assert config.WINDOWS_DEFAULT_PATHS
	assert config.LINUX_DEFAULT_PATHS
	assert config.MACOS_DEFAULT_PATHS


@pytest.mark.windows
def test_config_system_defaults_windows() -> None:
	for option in ("log_dir", "state_file", "timeline_db", "server_cert_dir"):
		assert config.get("global", option).lower().startswith("c:")
	assert config.get("cache_service", "storage_dir").lower().startswith("c:")
	assert config.get("system", "program_files_dir")


@pytest.mark.linux
@pytest.mark.darwin
def test_config_system_defaults_posix() -> None:
	for option in ("log_dir", "state_file", "timeline_db", "server_cert_dir"):
		assert config.get("global", option).startswith("/")
	assert config.get("cache_service", "storage_dir").startswith("/")


def test_getting_unknown_option_fails() -> None:
	with pytest.raises(NoConfigOptionFoundException):
		config.get("global", "non_existing_option")


def test_update_config_file(tmp_path: Path, default_config: Config) -> None:  # noqa
	conf_file = config.get("global", "config_file")
	tmp_conf_file = tmp_path / "opsiclientd.conf"
	shutil.copy(conf_file, tmp_conf_file)
	content = tmp_conf_file.read_text(encoding="utf-8")
	content = content.replace("[global]\n", "[global]\nold_option_to_remove = value")
	tmp_conf_file.write_text(content, encoding="utf-8")

	mtime = tmp_conf_file.stat().st_mtime
	config.set("global", "config_file", str(tmp_conf_file))
	try:
		config.set("global", "max_log_size", 6)
		config.set("event_test", "test_find_me", True)
		config.updateConfigFile()
		# changed by another program
		assert tmp_conf_file.stat().st_mtime == mtime

		config.updateConfigFile(force=True)
		assert tmp_conf_file.stat().st_mtime != mtime
		content = tmp_conf_file.read_text(encoding="utf-8")
		assert "max_log_size = 6" in content
		assert "test_find_me = true" in content
		assert "old_option_to_remove" not in content
	finally:
		config.set("global", "config_file", conf_file)
		config.set("global", "config_file", conf_file)
