# -*- coding: utf-8 -*-

# This file is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2023-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, Response

from opsiclientd.webserver.application import get_opsiclientd
from opsiclientd.webserver.rpc.control import get_control_interface
from opsiclientd.webserver.rpc.jsonrpc import process_request

INTERFACE_PAGE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
	<meta http-equiv="Content-Type" content="text/xhtml; charset=utf-8" />
	<title>%(title)s</title>
	<style>
	a:link 	      { color: #555555; text-decoration: none; }
	a:visited     { color: #555555; text-decoration: none; }
	a:hover	      { color: #46547f; text-decoration: none; }
	a:active      { color: #555555; text-decoration: none; }
	body          { font-family: verdana, arial; font-size: 12px; }
	#title        { padding: 10px; color: #6276a0; font-size: 20px; letter-spacing: 5px; }
	input, select { background-color: #fafafa; border: 1px #abb1ef solid; width: 430px; font-family: verdana, arial; }
	.json         { color: #555555; width: 95%%; float: left; clear: both; margin: 30px; padding: 20px; background-color: #fafafa; border: 1px #abb1ef dashed; font-size: 11px; }
	.json_key     { color: #9e445a; }
	.json_label   { color: #abb1ef; margin-top: 20px; margin-bottom: 5px; font-size: 11px; }
	.title        { color: #555555; font-size: 20px; font-weight: bolder; letter-spacing: 5px; }
	.button       { color: #9e445a; background-color: #fafafa; border: none; margin-top: 20px; font-weight: bolder; }
	.box          { background-color: #fafafa; border: 1px #555555 solid; padding: 20px; margin-left: 30px; margin-top: 50px;}
	</style>
	<script type="text/javascript">
	var path = '%(path)s';
	var parameters = new Array();
	var method = '';
	var params = '';
	var id = '"id": 1';
	%(javascript)s

	function createElement(element) {
		if (typeof document.createElementNS != 'undefined') {
			return document.createElementNS('http://www.w3.org/1999/xhtml', element);
		}
		if (typeof document.createElement != 'undefined') {
			return document.createElement(element);
		}
		return false;
	}

	function selectPath(select) {
		path = select.value;
		document.getElementById('json_method').firstChild.data = '"backend_getInterface"';
		document.getElementById('json_params').firstChild.data = '[]';
		onSubmit();
	}
	function selectMethod(select) {
		method = select.value;
		tbody = document.getElementById('tbody');
		var button;
		var json;
		for (i=tbody.childNodes.length-1; i>=0; i--) {
			if (tbody.childNodes[i].id == 'tr_path') {
			}
			else if (tbody.childNodes[i].id == 'tr_method') {
			}
			else if (tbody.childNodes[i].id == 'tr_submit') {
				button = tbody.childNodes[i];
				tbody.removeChild(button);
			}
			else if (tbody.childNodes[i].id == 'tr_json') {
				json = tbody.childNodes[i];
				tbody.removeChild(json);
			}
			else {
				tbody.removeChild(tbody.childNodes[i]);
			}
		}

		for (i=0; i < parameters[select.value].length; i++) {
			tr = createElement("tr");
			td1 = createElement("td");
			text = document.createTextNode(parameters[select.value][i] + ":");
			td1.appendChild(text);
			td2 = createElement("td");
			input = createElement("input");
			input.setAttribute('onchange', 'jsonString()');
			input.setAttribute('type', 'text');
			if ((method == currentMethod) && (currentParams[i] != null)) {
				input.value = currentParams[i];
			}
			td2.appendChild(input);
			tr.appendChild(td1);
			tr.appendChild(td2);
			tbody.appendChild(tr)
		}
		tbody.appendChild(json)
		tbody.appendChild(button)

		jsonString();
	}

	function onSubmit() {
		var json = '{ "id": 1, "method": ';
		json += document.getElementById('json_method').firstChild.data;
		json += ', "params": ';
		json += document.getElementById('json_params').firstChild.data;
		json += ' }';
		window.location.href = '/' + path + '?' + json;
		return false;
	}

	function jsonString() {
		span = document.getElementById('json_method');
		for (i=span.childNodes.length-1; i>=0; i--) {
			span.removeChild(span.childNodes[i])
		}
		span.appendChild(document.createTextNode('"' + method + '"'));

		span = document.getElementById('json_params');
		for (i=span.childNodes.length-1; i>=0; i--) {
			span.removeChild(span.childNodes[i])
		}
		params = '['
		inputs = document.getElementsByTagName('input');
		for (i=0; i<inputs.length; i++) {
			if (inputs[i].id != 'submit') {
				if (inputs[i].value == '') {
					i = inputs.length;
				}
				else {
					if (i>0) {
						params += ', ';
					}
					params += inputs[i].value;
				}
			}
		}
		span.appendChild(document.createTextNode(params + ']'));
	}

	function onLoad() {
		selectMethod(document.getElementById('method_select'));
		window.history.replaceState(null, null, window.location.href.split('?')[0]);
	}
	</script>
</head>
<body onload="onLoad();">
	<p id="title">
		<img src="/static/opsi_logo.png" /><br /><br />
		<span style="padding: 1px">%(title)s</span>
	</p>
	<form method="post" onsubmit="return onSubmit()">
		<table class="box">
			<tbody id="tbody">
				<tr id="tr_path">
					<td style="width: 150px;">Path:</td>
					<td style="width: 440px;">
						<select id="path_select" onchange="selectPath(this)" name="path">
							%(select_path)s
						</select>
					</td>
				</tr>
				<tr id="tr_method">
					<td style="width: 150px;">Method:</td>
					<td style="width: 440px;">
						<select id="method_select" onchange="selectMethod(this)" name="method">
							%(select_method)s
						</select>
					</td>
				</tr>
				<tr id="tr_json">
					<td colspan="2">
						<div class="json_label">
							resulting json remote procedure call:
						</div>
						<div class="json" style="width: 480px;">
							{&nbsp;"<font class="json_key">method</font>": <span id="json_method"></span>,<br />
							&nbsp;&nbsp;&nbsp;"<font class="json_key">params</font>": <span id="json_params">[]</span>,<br />
							&nbsp;&nbsp;&nbsp;"<font class="json_key">id</font>": 1 }
						</div>
					</td>
				</tr>
				<tr id="tr_submit">
					<td align="center" colspan="2">
						<input value="Execute" id="submit" class="button" type="submit" />
					</td>
				</tr>
			</tbody>
		</table>
	</form>
	<div class="json_label" style="padding-left: 30px">json-rpc result</div>
	%(result)s
</body>
</html>
"""

interface_router = APIRouter()


@interface_router.get("/", response_class=HTMLResponse)
def index_page() -> str:
	return INTERFACE_PAGE % {
		"path": "/interface",
		"title": "opsiclientd interface page",
		"javascript": "",
		"select_path": '<option selected="selected">/</option>',
		"select_method": "",
		"result": "",
	}


jsonrpc_router = APIRouter()


@jsonrpc_router.head("")
async def jsonrpc_head() -> Response:
	return Response()


@jsonrpc_router.get("")
@jsonrpc_router.post("")
@jsonrpc_router.get("{any:path}")
@jsonrpc_router.post("{any:path}")
async def jsonrpc(request: Request, response: Response) -> Response:
	return await process_request(interface=get_control_interface(get_opsiclientd()), request=request, response=response)


def setup(app: FastAPI) -> None:
	app.include_router(interface_router, prefix="/interface")
	app.include_router(jsonrpc_router, prefix="/opsiclientd")
