# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2026 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0-only

import sys
from unittest.mock import MagicMock, patch

from opsiclientd.actionprocessorstarter import main


def starter_arguments(depot_url: str) -> list[str]:
	return [
		"action_processor_starter.exe",
		"client.test.invalid",
		"host-key",
		"4441",
		"opsiclientd.log",
		"6",
		depot_url,
		"P:",
		"DOMAIN\\pcpatch",
		"password",
		"1",
		"default",
		"opsi-script.exe",
		"3600",
	]


def test_smb_mount_uses_network_impersonation() -> None:
	impersonation = MagicMock()
	service_client = MagicMock()

	with (
		patch.object(sys, "argv", starter_arguments("smb://depot.test.invalid/opsi_depot")),
		patch("opsiclientd.actionprocessorstarter.logging_config"),
		patch("opsiclientd.actionprocessorstarter.ServiceClient", return_value=service_client),
		patch("opsiclientd.actionprocessorstarter.System.Impersonate", return_value=impersonation, create=True) as impersonate,
		patch("opsiclientd.actionprocessorstarter.mount_network_share") as mount_network_share,
		patch("opsiclientd.actionprocessorstarter.unmount_network_share") as unmount_network_share,
		patch("opsiclientd.actionprocessorstarter.run_command") as run_command,
	):
		main()

	impersonate.assert_called_once_with(username="DOMAIN\\pcpatch", password="password", desktop="default")
	impersonation.start.assert_called_once_with(logonType="NEW_CREDENTIALS")
	mount_network_share.assert_called_once()
	impersonation.runCommand.assert_called_once_with("opsi-script.exe", timeoutSeconds=3600)
	run_command.assert_not_called()
	unmount_network_share.assert_called_once_with("P:")
	impersonation.end.assert_called_once_with()
	service_client.stop.assert_called_once_with()


def test_webdav_mount_does_not_impersonate() -> None:
	with (
		patch.object(sys, "argv", starter_arguments("https://depot.test.invalid:4447/opsi_depot")),
		patch("opsiclientd.actionprocessorstarter.logging_config"),
		patch("opsiclientd.actionprocessorstarter.ServiceClient"),
		patch("opsiclientd.actionprocessorstarter.System.Impersonate", create=True) as impersonate,
		patch("opsiclientd.actionprocessorstarter.mount_network_share"),
		patch("opsiclientd.actionprocessorstarter.unmount_network_share"),
		patch("opsiclientd.actionprocessorstarter.run_command") as run_command,
	):
		main()

	impersonate.assert_not_called()
	run_command.assert_called_once_with("opsi-script.exe", timeout=3600)


def test_failed_smb_mount_ends_impersonation() -> None:
	impersonation = MagicMock()

	with (
		patch.object(sys, "argv", starter_arguments("smb://depot.test.invalid/opsi_depot")),
		patch("opsiclientd.actionprocessorstarter.logging_config"),
		patch("opsiclientd.actionprocessorstarter.ServiceClient"),
		patch("opsiclientd.actionprocessorstarter.System.Impersonate", return_value=impersonation, create=True),
		patch("opsiclientd.actionprocessorstarter.mount_network_share", side_effect=RuntimeError("mount failed")),
		patch("opsiclientd.actionprocessorstarter.unmount_network_share") as unmount_network_share,
	):
		main()

	unmount_network_share.assert_not_called()
	impersonation.end.assert_called_once_with()
