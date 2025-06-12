# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2025 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0-only

import contextlib
import io

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from opsicommon.logging import get_logger

from opsiclientd.Config import Config
from opsiclientd.webserver.application import get_opsiclientd

PYTHON_PAGE = """<!DOCTYPE html>
<html>
<head>
	<title>opsiclientd - Python executor</title>
	<link rel="stylesheet" href="/static/opsiclientd.css" />
	<style>
		#python-code-editor {
			box-sizing: border-box;
			width: 100%;
			height: 50vh;
			font-family: monospace;
			border: 1px solid #ccc;
			padding: 10px;
			font-size: 12px;
			resize: vertical;
		}
		#python-output {
			box-sizing: border-box;
			width: 100%;
			height: 20vh;
			font-family: monospace;
			border: 1px solid #ccc;
			padding: 10px;
			font-size: 12px;
			resize: vertical;
		}
	</style>
	<script>
		function executePythonCode() {
			const codeEditor = document.getElementById('python-code-editor');
			const outputArea = document.getElementById('python-output');
			const code = codeEditor.value;

			outputArea.value = 'Executing...\\n';

			fetch('/python_executor/execute', {
				method: 'POST',
				headers: {
					'Content-Type': 'text/plain',
				},
				body: code,
			})
			.then(response => response.text())
			.then(data => {
				outputArea.value = data;
			})
			.catch(error => {
				console.error('Error executing Python code:', error);
				outputArea.value = 'Error: ' + error.toString();
			});
		}
	</script>
</head>
<body>
	<div id="python-executor-container" style="padding: 10px">
		<h3>Python code:</h3>
		<div>
			<textarea id="python-code-editor"></textarea>
		</div>
		<div style="margin-top: 10px; margin-bottom: 20px;">
			<button id="execute-python-button" class="button" onclick="executePythonCode();">Execute</button>
		</div>
		<h3>Output:</h3>
		<div>
			<textarea id="python-output"></textarea>
		</div>
	</div>
</body>
</html>
"""

logger = get_logger()
config = Config()
python_executor_router = APIRouter()


@python_executor_router.get("/")
def index_page() -> HTMLResponse:
	return HTMLResponse(PYTHON_PAGE)


@python_executor_router.post("/execute")
async def execute_python(request: Request) -> PlainTextResponse:
	code = (await request.body()).decode("utf-8")
	stdout = io.StringIO()
	stderr = io.StringIO()

	try:
		with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
			exec(code, {"logger": logger, "opsiclientd": get_opsiclientd()})
	except Exception as err:
		return PlainTextResponse(f"Error: {err}")

	return PlainTextResponse(stdout.getvalue() + stderr.getvalue())


def setup(app: FastAPI) -> None:
	app.include_router(python_executor_router, prefix="/python_executor")
