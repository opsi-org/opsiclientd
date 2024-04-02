# -*- coding: utf-8 -*-

# This file is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2023-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from opsiclientd.Opsiclientd import Opsiclientd

_opsiclientd: Opsiclientd | None = None


def get_opsiclientd() -> Opsiclientd:
	assert _opsiclientd
	return _opsiclientd


def set_opsiclientd(opsiclientd: Opsiclientd) -> None:
	global _opsiclientd
	_opsiclientd = opsiclientd


INTERFACE_PAGE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
	<meta http-equiv="Content-Type" content="text/xhtml; charset=utf-8" />
	<title>%(title)s</title>
	<link rel="stylesheet" type="text/css" href="/static/opsiclientd.css">

	<script type="text/javascript">
	let jsonrpcRequest;
	let methods = JSON.parse('%(methods)s');

	function syntaxHighlight(json) {
		if (typeof json != 'string') {
			json = JSON.stringify(json, undefined, 2);
		}
		json = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
		return json.replace(
			/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
			function (match) {
				var cls = 'json_number';
				if (/^"/.test(match)) {
					if (/:$/.test(match)) {
						cls = 'json_key';
					} else {
						cls = 'json_string';
					}
				} else if (/true|false/.test(match)) {
					cls = 'json_boolean';
				} else if (/null/.test(match)) {
					cls = 'json_null';
				}
				return '<span class="' + cls + '">' + match + '</span>';
			}
		);
	}

	function onSelectMethod() {
		const selectedMethod = document.getElementById('method_select').value;
		const tbody = document.getElementById('tbody');
		const trJson = document.getElementById('tr_json');
		const elements = document.getElementsByClassName("param");
		while (elements.length > 0){
			tbody.removeChild(elements[0]);
		}
		methods[selectedMethod].forEach(param => {
			const tr = document.createElement("tr");
			tr.classList.add("param");
			tr.innerHTML = `<td>${param}:</td><td><input type="text" name="${param}" onchange="createRequest()" style="width: 400px"></input></td>`;
			tbody.appendChild(tr);
			tbody.insertBefore(tr, trJson);
		})
		createRequest();
	}

	function createRequest() {
		jsonrpcRequest = {
			id: 1,
			method: document.getElementById('method_select').value,
			params: [],
			jsonrpc: '2.0'
		};

		document.getElementById("jsonrpc-request-error").innerHTML = "";
		let inputs = document.getElementsByTagName('input');
		for (i = 0; i < inputs.length; i++) {
			let name = null;
			let value = null;
			try {
				name = inputs[i].name.trim();
				value = inputs[i].value.trim();
				if (value) {
					jsonrpcRequest.params.push(JSON.parse(value));
				} else if (!name.startsWith("*")) {
					jsonrpcRequest.params.push(null);
				}
			} catch (e) {
				console.warn(`${name}: ${e}`);
				document.getElementById("jsonrpc-request-error").innerHTML = `${name}: ${e}`;
			}
		}
		let jsonStr = JSON.stringify(jsonrpcRequest, undefined, 2);
		document.getElementById('jsonrpc-request').innerHTML = syntaxHighlight(jsonStr);
	}

	function onLoad() {
		const methodSelect = document.getElementById('method_select');
		for (const [method, params] of Object.entries(methods)) {
			const option = document.createElement("option");
			option.value = method;
			option.innerText = method;
			methodSelect.appendChild(option);
		};
		onSelectMethod();
	}

	function executeJsonrpc() {
		const submitButton = document.getElementById('submit');
		submitButton.disabled = true;
		document.getElementById('jsonrpc-response').innerHTML = "";
		let xhr = new XMLHttpRequest();
		xhr.open('POST', '%(jsonrpc_path)s', true);
		xhr.setRequestHeader('Content-Type', 'application/json');
		xhr.onreadystatechange = function() {
			if (xhr.readyState == 4 && xhr.status == 200) {
				submitButton.disabled = false;
				let jsonStr = JSON.stringify(JSON.parse(xhr.responseText), undefined, 2);
				document.getElementById('jsonrpc-response').innerHTML = syntaxHighlight(jsonStr);
			}
		}
		xhr.send(JSON.stringify(jsonrpcRequest));
		return false;
	}
	</script>
</head>
<body onload="onLoad();">
	<p id="title">
		%(title)s
	</p>
	<form onsubmit="return executeJsonrpc();">
		<table class="box">
			<tbody id="tbody">
				<tr id="tr_method">
					<td style="width: 150px;">Method:</td>
					<td style="width: 440px;">
						<select id="method_select" onchange="onSelectMethod()" name="method" style="width: 400px">
						</select>
					</td>
				</tr>
				<tr id="tr_json">
					<td colspan="2">
						<div id="jsonrpc-request-error" style="width: 480px;">
						</div>
						<div class="json_label">
							jsonrpc request:
						</div>
						<pre id="jsonrpc-request" class="json" style="width: 480px;">
						</pre>
					</td>
				</tr>
				<tr id="tr_submit">
					<td align="center" colspan="2">
						<button id="submit" class="button" type="submit">Execute</button>
					</td>
				</tr>
			</tbody>
		</table>
	</form>
	<div class="json_label" style="padding-left: 30px">json-rpc response</div>
	<pre class="json" id="jsonrpc-response"></pre>
</body>
</html>
"""
