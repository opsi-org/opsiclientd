# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2026 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0-only

from contextlib import ExitStack
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

import opsiclientd.EventProcessing as event_processing
from opsiclientd.EventProcessing import EventProcessingThread


def event_processing_thread() -> EventProcessingThread:
	thread = EventProcessingThread.__new__(EventProcessingThread)
	thread._depotShareMounted = False
	thread._depotShareImpersonation = None
	thread.setStatusMessage = MagicMock()
	return thread


def patch_windows_smb_mount(
	stack: ExitStack, impersonation: MagicMock, mount_side_effect: Exception | None = None
) -> tuple[MagicMock, MagicMock, MagicMock]:
	stack.enter_context(patch.object(event_processing, "RUNNING_ON_WINDOWS", True))
	stack.enter_context(patch.object(event_processing, "RUNNING_ON_LINUX", False))
	stack.enter_context(patch.object(event_processing, "RUNNING_ON_DARWIN", False))
	stack.enter_context(patch.object(EventProcessingThread, "service_client", new_callable=PropertyMock, return_value=MagicMock()))
	stack.enter_context(patch.object(event_processing.config, "get", return_value="smb://depot.test.invalid/opsi_depot"))
	stack.enter_context(patch.object(event_processing.config, "getDepotserverCredentials", return_value=("DOMAIN\\pcpatch", "password")))
	stack.enter_context(patch.object(event_processing.config, "getDepotDrive", return_value="P:"))
	stack.enter_context(patch.object(event_processing.System, "setRegistryValue", create=True))
	impersonate = stack.enter_context(patch.object(event_processing.System, "Impersonate", return_value=impersonation, create=True))
	mount_network_share = stack.enter_context(patch.object(event_processing, "mount_network_share", side_effect=mount_side_effect))
	unmount_network_share = stack.enter_context(patch.object(event_processing, "unmount_network_share"))
	return impersonate, mount_network_share, unmount_network_share


def test_windows_smb_mount_retains_impersonation_until_unmount() -> None:
	thread = event_processing_thread()
	impersonation = MagicMock()

	with ExitStack() as stack:
		impersonate, mount_network_share, unmount_network_share = patch_windows_smb_mount(stack, impersonation)
		thread.mountDepotShare()

		impersonate.assert_called_once_with(username="DOMAIN\\pcpatch", password="password")
		impersonation.start.assert_called_once_with(logonType="NEW_CREDENTIALS")
		mount_network_share.assert_called_once()
		assert thread._depotShareMounted is True
		assert thread._depotShareImpersonation is impersonation
		impersonation.end.assert_not_called()

		thread.umountDepotShare()

		unmount_network_share.assert_called_once_with("P:")
		impersonation.end.assert_called_once_with()
		assert thread._depotShareMounted is False
		assert thread._depotShareImpersonation is None


def test_failed_windows_smb_mount_ends_impersonation() -> None:
	thread = event_processing_thread()
	impersonation = MagicMock()

	with ExitStack() as stack, pytest.raises(RuntimeError, match="mount failed"):
		patch_windows_smb_mount(stack, impersonation, mount_side_effect=RuntimeError("mount failed"))
		thread.mountDepotShare()

	impersonation.end.assert_called_once_with()
	assert thread._depotShareMounted is False
	assert thread._depotShareImpersonation is None


def test_failed_unmount_still_ends_impersonation() -> None:
	thread = event_processing_thread()
	impersonation = MagicMock()
	thread._depotShareMounted = True
	thread._depotShareImpersonation = impersonation

	with (
		patch.object(event_processing.config, "getDepotDrive", return_value="P:"),
		patch.object(event_processing, "unmount_network_share", side_effect=RuntimeError("unmount failed")),
	):
		thread.umountDepotShare()

	impersonation.end.assert_called_once_with()
	assert thread._depotShareMounted is False
	assert thread._depotShareImpersonation is None
