# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2025 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0-only

"""
Windows Runtime API event handling
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from opsicommon.logging import get_logger, log_context

logger = get_logger()

from opsiclientd.EventConfiguration import EventConfig
from opsiclientd.Events.Basic import Event, EventGenerator

if TYPE_CHECKING:
	from opsiclientd.Opsiclientd import Opsiclientd

_winrt_imports: dict[str, Any] = {}


__all__ = ["WinRTEventConfig", "WinRTEventGenerator"]


class HandlerMethods:
	def __init__(self, setup_method: str, cleanup_method: str):
		self.setup_method = setup_method
		self.cleanup_method = cleanup_method


HANDLER_METHODS = {
	"network_cost": HandlerMethods("_setup_network_cost_handler", "_cleanup_network_cost_handler"),
	# Add other handlers here as needed
}


class WinRTEventConfig(EventConfig):
	def __init__(self, eventId: str, handler: str, **kwargs: Any) -> None:
		super().__init__(eventId, **kwargs)
		self.handler = handler

	def setConfig(self, conf: dict[str, Any]) -> None:
		EventConfig.setConfig(self, conf)

		if hasattr(self, "handler") and self.handler not in HANDLER_METHODS:
			logger.warning("Unknown WinRT handler '%s', supported: %s", self.handler, ", ".join(HANDLER_METHODS.keys()))


def _get_winrt_module(module_path: str) -> Any:
	if module_path not in _winrt_imports:
		try:
			if module_path == "winrt.windows.networking.connectivity":
				from winrt.windows.networking.connectivity import (  # type: ignore
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
		except ImportError as err:
			logger.error("Failed to import WinRT module '%s': %s.", module_path, err)
			_winrt_imports[module_path] = None
	return _winrt_imports[module_path]


class WinRTEventGenerator(EventGenerator):
	"""
	Uses Windows Runtime APIs via pywinrt. See:
	https://github.com/microsoft/xlang?tab=readme-ov-file#python
	"""

	_generatorConfig: WinRTEventConfig

	def __init__(self, opsiclientd: Opsiclientd, generatorConfig: WinRTEventConfig) -> None:
		EventGenerator.__init__(self, opsiclientd, generatorConfig)
		self._handler: str = self._generatorConfig.handler
		self._event_token: Any = None

	def initialize(self) -> None:
		if self._opsiclientd.is_stopping() or not self._handler:
			return

		self._setup_handler()

	def finalize(self) -> None:
		if self._handler in HANDLER_METHODS:
			cleanup_method_name = HANDLER_METHODS[self._handler].cleanup_method
			cleanup_method = getattr(self, cleanup_method_name, None)
			if cleanup_method:
				cleanup_method()

	def createEvent(self, eventInfo: dict[str, Any] | None = None) -> Event | None:
		eventConfig = self.getEventConfig()
		if not eventConfig:
			return None
		return Event(eventConfig=eventConfig, eventInfo=eventInfo)

	def _setup_handler(self) -> None:
		if self._handler in HANDLER_METHODS:
			setup_method_name = HANDLER_METHODS[self._handler].setup_method
			setup_method = getattr(self, setup_method_name, None)
			if setup_method:
				setup_method()

	def _setup_network_cost_handler(self) -> None:
		winrt_module = _get_winrt_module("winrt.windows.networking.connectivity")
		if not winrt_module:
			return

		NetworkInformation = winrt_module["NetworkInformation"]
		NetworkCostType = winrt_module["NetworkCostType"]
		NetworkConnectivityLevel = winrt_module["NetworkConnectivityLevel"]

		def network_changed_handler(_: Any) -> None:
			with log_context({"instance": "winrt network handler"}):
				try:
					profile = NetworkInformation.get_internet_connection_profile()
					if not profile:
						logger.debug("No internet connection profile available")
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

					self.createAndFireEvent(
						eventInfo={
							"is_connected": connected,
							"is_metered": is_metered,
						}
					)

				except Exception as e:
					logger.error("Error in network changed handler: %s", e)
					pass

		network_changed_handler(None)
		self._event_token = NetworkInformation.add_network_status_changed(network_changed_handler)

	def _cleanup_network_cost_handler(self) -> None:
		if self._event_token is not None:
			winrt_module = _get_winrt_module("winrt.windows.networking.connectivity")
			if winrt_module:
				NetworkInformation = winrt_module["NetworkInformation"]
				NetworkInformation.remove_network_status_changed(self._event_token)
			self._event_token = None
