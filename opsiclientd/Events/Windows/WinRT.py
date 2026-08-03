# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2026 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0-only

"""
Windows Runtime API event monitoring
"""

from __future__ import annotations

from typing import Any, Protocol

from opsi.logging import get_logger, log_context

from opsiclientd.SystemCheck import RUNNING_ON_WINDOWS

logger = get_logger()
_winrt_imports: dict[str, Any] = {}


class HandlerMethods:
	def __init__(self, setup_method: str, cleanup_method: str) -> None:
		self.setup_method = setup_method
		self.cleanup_method = cleanup_method


HANDLER_METHODS = {
	"network_status": HandlerMethods("_setup_network_status_handler", "_cleanup_network_status_handler"),
	# Add more handlers here as needed
}


def _get_winrt_module(module_path: str) -> Any:
	if module_path not in _winrt_imports:
		try:
			if module_path == "winrt.windows.networking.connectivity":
				from winrt.windows.networking.connectivity import (  # ty: ignore
					NetworkConnectivityLevel,
					NetworkCostType,
					NetworkInformation,
				)

				_winrt_imports[module_path] = {
					"NetworkInformation": NetworkInformation,
					"NetworkConnectivityLevel": NetworkConnectivityLevel,
					"NetworkCostType": NetworkCostType,
				}
			# Add other WinRT modules here as needed
			else:
				raise ImportError(f"Unknown WinRT module: {module_path}")
		except Exception as err:
			logger.error("Failed to import WinRT module '%s': %s.", module_path, err)
			_winrt_imports[module_path] = None
	return _winrt_imports[module_path]


class WinRTMonitor:
	"""
	Base class for WinRT event monitors.
	"""

	def __init__(self, handler: str) -> None:
		self._event_token: Any = None
		self._handler: str = handler
		if RUNNING_ON_WINDOWS:
			self._setup_handler()
		else:
			logger.info(f"{self.__class__.__name__} is only available on Windows. Skipping initialization.")

	def stop(self) -> None:
		self._cleanup_handler()

	def _setup_handler(self) -> None:
		if self._handler in HANDLER_METHODS:
			setup_method_name = HANDLER_METHODS[self._handler].setup_method
			setup_method = getattr(self, setup_method_name, None)
			if setup_method:
				setup_method()

	def _cleanup_handler(self) -> None:
		if self._handler in HANDLER_METHODS:
			cleanup_method_name = HANDLER_METHODS[self._handler].cleanup_method
			cleanup_method = getattr(self, cleanup_method_name, None)
			if cleanup_method:
				cleanup_method()


class OnStatusChange(Protocol):
	def __call__(self, connected: bool, metered: bool) -> None: ...


class WinRTNetworkStatusMonitor(WinRTMonitor):
	"""
	Monitor  Windows network connectivity and cost changes using WinRT APIs.
	"""

	def __init__(self, on_status_change: OnStatusChange) -> None:
		self._on_status_change: OnStatusChange = on_status_change
		super().__init__(handler="network_status")

	def _setup_network_status_handler(self) -> None:
		winrt_module = _get_winrt_module("winrt.windows.networking.connectivity")
		if not winrt_module:
			logger.error("WinRT network module not available.")
			return

		NetworkInformation = winrt_module["NetworkInformation"]
		NetworkCostType = winrt_module["NetworkCostType"]
		NetworkConnectivityLevel = winrt_module["NetworkConnectivityLevel"]

		def _on_network_status_change(_: Any) -> None:
			with log_context({"instance": "winrt network handler"}):
				try:
					profile = NetworkInformation.get_internet_connection_profile()
					if not profile:
						logger.debug("No internet connection profile available, assuming connected and not metered.")
						self._on_status_change(connected=True, metered=False)
						return
					cost = profile.get_connection_cost()
					connectivity = profile.get_network_connectivity_level()
					connected = connectivity != NetworkConnectivityLevel.NONE
					is_metered = (
						cost.network_cost_type != NetworkCostType.UNRESTRICTED
						or cost.over_data_limit
						or cost.approaching_data_limit
						or cost.roaming
					)
					self._on_status_change(connected=connected, metered=is_metered)
				except Exception as e:
					logger.exception("Error in WinRT handler: %s, assuming connected and not metered", e)
					self._on_status_change(connected=True, metered=False)

		_on_network_status_change(None)
		self._event_token = NetworkInformation.add_network_status_changed(_on_network_status_change)

	def _cleanup_network_status_handler(self) -> None:
		if self._event_token is not None:
			winrt_module = _get_winrt_module("winrt.windows.networking.connectivity")
			if winrt_module:
				NetworkInformation = winrt_module["NetworkInformation"]
				NetworkInformation.remove_network_status_changed(self._event_token)
			self._event_token = None
