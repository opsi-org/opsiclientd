# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
webserver.rpc
"""

import inspect
import re
from dataclasses import asdict, dataclass
from inspect import getfullargspec, signature
from textwrap import dedent
from typing import Any, Callable


def no_export(func: Callable) -> Callable:
	setattr(func, "no_export", True)
	return func


@dataclass(slots=True)
class MethodInterface:
	name: str
	params: list[str]
	args: list[str]
	varargs: str | None
	keywords: str | None
	defaults: tuple[Any, ...] | None
	deprecated: bool
	drop_version: str | None
	alternative_method: str | None
	doc: str | None
	annotations: dict[str, str]

	def as_dict(self) -> dict[str, Any]:
		return asdict(self)


COMPLEX_TYPE_RE = re.compile(r"\S+\.\S+")


def get_method_interface(
	func: Callable, deprecated: bool = False, drop_version: str | None = None, alternative_method: str | None = None
) -> MethodInterface:
	spec = getfullargspec(func)
	sig = signature(func)
	args = spec.args
	defaults = spec.defaults
	params = [arg for arg in args if arg != "self"]
	annotations = {}
	for param in params:
		str_param = str(sig.parameters[param])
		if ": " in str_param:
			annotation = str_param.split(": ", 1)[1].split(" = ", 1)[0]
			annotation = COMPLEX_TYPE_RE.sub("Any", annotation)
			annotations[param] = annotation

	if defaults is not None:
		offset = len(params) - len(defaults)
		for i in range(len(defaults)):
			index = offset + i
			params[index] = f"*{params[index]}"

	for index, element in enumerate((spec.varargs, spec.varkw), start=1):
		if element:
			stars = "*" * index
			params.extend([f"{stars}{arg}" for arg in (element if isinstance(element, list) else [element])])

	doc = func.__doc__
	if doc:
		doc = dedent(doc).lstrip() or None

	if drop_version:
		deprecated = True

	return MethodInterface(
		name=func.__name__,
		params=params,
		args=args,
		varargs=spec.varargs,
		keywords=spec.varkw,
		defaults=defaults,
		deprecated=deprecated,
		drop_version=drop_version,
		alternative_method=alternative_method,
		doc=doc,
		annotations=annotations,
	)


class Interface:
	def __init__(self) -> None:
		self._interface: dict[str, MethodInterface] = {}
		self._interface_list: list[dict[str, Any]]
		self._create_interface()

	def _create_interface(self) -> None:
		for _, function in inspect.getmembers(self, inspect.ismethod):
			method_name = function.__name__
			if getattr(function, "no_export", False):
				continue
			if method_name.startswith("_"):
				# protected / private
				continue
			if method_name == "get_product_action_groups":
				# Not using no_export because BackendExtender would not add this method
				continue

			self._interface[method_name] = get_method_interface(function)

		self._interface_list = [self._interface[name].as_dict() for name in sorted(list(self._interface.keys()))]

	@no_export
	def get_interface(self) -> dict[str, MethodInterface]:
		return self._interface

	@no_export
	def get_method_interface(self, method: str) -> MethodInterface | None:
		return self._interface.get(method)
