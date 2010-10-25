# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = = = =
   =   ocdlib.ControlServer                =
   = = = = = = = = = = = = = = = = = = = = =
   
   opsiclientd is part of the desktop management solution opsi
   (open pc server integration) http://www.opsi.org
   
   Copyright (C) 2010 uib GmbH
   
   http://www.uib.de/
   
   All rights reserved.
   
   This program is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License version 2 as
   published by the Free Software Foundation.
   
   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.
   
   You should have received a copy of the GNU General Public License
   along with this program; if not, write to the Free Software
   Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
   
   @copyright:	uib GmbH <info@uib.de>
   @author: Jan Schneider <j.schneider@uib.de>
   @license: GNU General Public License version 2
"""

# Imports
from OpenSSL import SSL
import base64, urllib, codecs

# Twisted imports
from twisted.internet import defer, threads, reactor
from OPSI.web2 import resource, stream, server, http, responsecode, static, http_headers
from OPSI.web2.channel.http import HTTPFactory
from twisted.python.failure import Failure

# OPSI imports
from OPSI.Logger import *
from OPSI.Types import *
from OPSI.Util import *
from OPSI import System

from ocdlib.Exceptions import *
from ocdlib.ControlPipe import OpsiclientdRpcPipeInterface
from ocdlib.CacheService import CacheService
from ocdlib.JsonRpc import JsonRpc
from ocdlib.Config import Config
from ocdlib.Events import eventGenerators

logger = Logger()
config = Config()

interfacePage = u'''
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
	<title>opsi client interface</title>
	<style>
	a:link 	      { color: #555555; text-decoration: none; }
	a:visited     { color: #555555; text-decoration: none; }
	a:hover	      { color: #46547f; text-decoration: none; }
	a:active      { color: #555555; text-decoration: none; }
	body          { font-family: verdana, arial; font-size: 12px; }
	#title        { padding: 10px; color: #6276a0; font-size: 20px; letter-spacing: 5px; }
	input, select { background-color: #fafafa; border: 1px #abb1ef solid; width: 430px; font-family: verdana, arial; }
	.json         { color: #555555; width: 95%; float: left; clear: both; margin: 30px; padding: 20px; background-color: #fafafa; border: 1px #abb1ef dashed; font-size: 11px; }
	.json_key     { color: #9e445a; }
	.json_label   { color: #abb1ef; margin-top: 20px; margin-bottom: 5px; font-size: 11px; }
	.title        { color: #555555; font-size: 20px; font-weight: bolder; letter-spacing: 5px; }
	.button       { color: #9e445a; background-color: #fafafa; border: none; margin-top: 20px; font-weight: bolder; }
	.box          { background-color: #fafafa; border: 1px #555555 solid; padding: 20px; margin-left: 30px; margin-top: 50px;}
	</style>
	<script type="text/javascript">
		var parameters = new Array();
		var method = '';
		var params = '';
		var id = '"id": 1';
		%javascript%
		function selectFunction(select) {
			method = select.value;
			tbody = document.getElementById('tbody');
			var button;
			var json;
			for (i=tbody.childNodes.length-1; i>=0; i--) {
				if (tbody.childNodes[i].id == 'tr_method') {
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
				tr = document.createElement("tr");
				td1 = document.createElement("td");
				text = document.createTextNode(parameters[select.value][i] + ":");
				td1.appendChild(text);
				td2 = document.createElement("td");
				input = document.createElement("input");
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
			window.location.href = '?' + json;
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
						params += inputs[i].value.replace(/\\\/g, '\\\\\\\\');
					}
				}
			}
			span.appendChild(document.createTextNode(params + ']'));
		}
	</script>
</head>
<body onload="selectFunction(document.getElementById('select'))">
	<span id="title">
		<img src="opsi_logo.png" />
		<span sytle="padding: 1px">opsi client interface</span>
	</span>
	<form method="post" onsubmit="return onSubmit()">
		<table class="box">
			<tbody id="tbody">
				<tr id="tr_method">
					<td style="width: 150px;">Method:</td>
					<td style="width: 440px;">
						<select id="select" onchange="selectFunction(this)" name="method">
							%select_method%
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
	%result%
</body>
'''


'''
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
=                                            CONTROL SERVER                                           =
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
=                                                                                                     =
=      These classes are used to create a https service which executes remote procedure calls         =
=                                                                                                     =
=                                                                                                     =
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
'''

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                            SSL CONTEXT                                            -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class SSLContext:
	def __init__(self, sslServerKeyFile, sslServerCertFile):
		self._sslServerKeyFile = sslServerKeyFile
		self._sslServerCertFile = sslServerCertFile
		
	def getContext(self):
		''' Create an SSL context. '''
		
		# Test if server certificate and key file exist.
		if not os.path.isfile(self._sslServerKeyFile):
			raise Exception(u"Server key file '%s' does not exist!" % self._sslServerKeyFile)
			
		if not os.path.isfile(self._sslServerCertFile):
			raise Exception(u"Server certificate file '%s' does not exist!" % self._sslServerCertFile)
		
		# Create and return ssl context
		context = SSL.Context(SSL.SSLv23_METHOD)
		context.use_privatekey_file(self._sslServerKeyFile)
		context.use_certificate_file(self._sslServerCertFile)
		return context

# = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
# =                                        CLASS WORKER                                               =
# = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
class Worker:
	def __init__(self, opsiclientdRpcInterface, request, resource):
		self.opsiclientdRpcInterface = opsiclientdRpcInterface
		self.request   = request
		self.query     = u''
		self.resource  = resource
		self.session   = None
		moduleName = u' %-30s' % (u'control server')
		logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)
	
	def process(self):
		logger.info("Worker %s started processing" % self)
		deferred = defer.Deferred()
		deferred.addCallback(self._authenticate)
		deferred.addCallback(self._getQuery)
		deferred.addCallback(self._decodeQuery)
		deferred.addCallback(self._setResponse)
		deferred.addErrback(self._errback)
		deferred.callback(None)
		deferred
	
	def _errback(self, failure):
		logger.debug2("%s._errback" % self.__class__.__name__)
		
		result = self._renderError(failure)
		result.code = responsecode.INTERNAL_SERVER_ERROR
		try:
			failure.raiseException()
		except OpsiclientdAuthenticationError, e:
			logger.error(e)
			result.code = responsecode.UNAUTHORIZED
			result.headers.setHeader('www-authenticate', [('basic', { 'realm': 'OPSI Client Service' } )])
		except OpsiclientdBadRpcError, e:
			logger.error(e)
			result.code = responsecode.BAD_REQUEST
		except Exception, e:
			logger.logException(e)
		
		return result
	
	def _renderError(self, failure):
		result = http.Response()
		result.headers.setHeader('content-type', http_headers.MimeType("text", "html", {"charset": "utf-8"}))
		error = u'Unknown error'
		try:
			failure.raiseException()
		except Exception, e:
			error = {'class': e.__class__.__name__, 'message': unicode(e)}
			error = toJson({"id": None, "result": None, "error": error})
		result.stream = stream.IByteStream(error.encode('utf-8'))
		return result
	
	def _authenticate(self, result):
		''' This function tries to authenticate a user.
		    Raises an exception on authentication failure. '''
		
		try:
			(user, password) = ('', '')
			logger.debug(u"Trying to get username and password from Authorization header")
			auth = self.request.headers.getHeader('Authorization')
			if auth:
				logger.debug(u"Authorization header found (type: %s)" % auth[0])
				try:
					encoded = auth[1]
					(user, password) = base64.decodestring(encoded).split(':')
					logger.confidential(u"Client supplied username '%s' and password '%s'" % (user, password))
				except Exception:
					raise Exception(u"Bad authorization header from '%s'" % self.request.remoteAddr.host)
			
			logger.notice(u"Authorization request from %s@%s" % (user, self.request.remoteAddr.host))
			if not user:
				user = config.get('global', 'host_id')
			if not password:
				raise Exception(u"Cannot authenticate, no password given")
			
			self.opsiclientdRpcInterface._authenticate(user, password)
			
		except Exception, e:
			raise OpsiclientdAuthenticationError(u"Forbidden: %s" % forceUnicode(e))
		return result
		
	def _getQuery(self, result):
		self.query = ''
		if   (self.request.method == 'GET'):
			self.query = urllib.unquote( self.request.querystring )
		elif (self.request.method == 'POST'):
			# Returning deferred needed for chaining
			d = stream.readStream(self.request.stream, self._handlePostData)
			d.addErrback(self._errback)
			return d
		else:
			raise ValueError(u"Unhandled method %s" % request.method)
		return result
		
	def _handlePostData(self, chunk):
		#logger.debug2(u"_handlePostData %s" % chunk)
		self.query += chunk
	
	def _decodeQuery(self, result):
		self.query = unicode(self.query, 'utf-8', 'replace')
		logger.debug2(u"query: %s" % self.query)
		return result
	
	def _setResponse(self, result):
		if not isinstance(result, http.Response):
			result = http.Response()
		result.code = responsecode.OK
		result.headers.setHeader('content-type', http_headers.MimeType("text", "html", {"charset": "utf-8"}))
		result.stream = stream.IByteStream("")
		return result

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                   CONTROL SERVER JSON RPC WORKER                                  -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ControlServerJsonRpcWorker(Worker):
	def __init__(self, opsiclientdRpcInterface, request, resource):
		Worker.__init__(self, opsiclientdRpcInterface, request, resource)
		self._rpcs = []
		
	def process(self):
		logger.info("Worker %s started processing" % self)
		deferred = defer.Deferred()
		deferred.addCallback(self._authenticate)
		deferred.addCallback(self._getQuery)
		deferred.addCallback(self._decodeQuery)
		deferred.addCallback(self._getRpcs)
		deferred.addCallback(self._executeRpcs)
		deferred.addCallback(self._setResponse)
		deferred.addErrback(self._errback)
		deferred.callback(None)
		return deferred
	
	def _getRpcs(self, result):
		if not self.query:
			return result
		
		rpcs = []
		try:
			rpcs = fromJson(self.query)
			if not rpcs:
				raise Exception(u"Got no rpcs")
		
		except Exception, e:
			raise OpsiclientdBadRpcError(u"Failed to decode rpc: %s" % forceUnicode(e))
		
		for rpc in forceList(rpcs):
			self._rpcs.append(JsonRpc(self.opsiclientdRpcInterface, rpc))
		
		return result
	
	def _executeRpcs(self, result):
		deferred = None
		for rpc in self._rpcs:
			if rpc.hasEnded():
				continue
			deferred = threads.deferToThread(rpc.execute)
			deferred.addCallback(self._executeRpcs)
			deferred.addErrback(self._errback)
			break
		if deferred:
			return deferred
		return result
	
	def _setResponse(self, result):
		if not isinstance(result, http.Response):
			result = http.Response()
		result.code = responsecode.OK
		result.headers.setHeader('content-type', http_headers.MimeType("application", "json", {"charset": "utf-8"}))
		response = []
		for rpc in self._rpcs:
			response.append(rpc.getResponse())
		if (len(response) == 1):
			response = response[0]
		if not response:
			response = None
		
		result.stream = stream.IByteStream(toJson(response).encode('utf-8'))
		return result
	
		
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                       JSON INTERFACE WORKER                                       -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ControlServerJsonInterfaceWorker(ControlServerJsonRpcWorker):
	
	def __init__(self, opsiclientdRpcInterface, request, resource):
		ControlServerJsonRpcWorker.__init__(self, opsiclientdRpcInterface, request, resource)
	
	def _setResponse(self, result):
		logger.info(u"Creating opsiclientd interface page")
		
		javascript  = u"var currentParams = new Array();\n"
		javascript += u"var currentMethod = null;\n"
		currentMethod = u''
		if self._rpcs:
			currentMethod = self._rpcs[0].getMethodName()
			javascript += u"currentMethod = '%s';\n" % currentMethod
			for i in range(len(self._rpcs[0].params)):
				param = self._rpcs[0].params[i]
				javascript += u"currentParams[%d] = '%s';\n" % (i, toJson(param))
		
		selectMethod = u''
		for method in self.opsiclientdRpcInterface.getInterface():
			javascript += u"parameters['%s'] = new Array();\n" % (method['name'])
			for param in range(len(method['params'])):
				javascript += u"parameters['%s'][%s]='%s';\n" % (method['name'], param, method['params'][param])
			selected = u''
			if (method['name'] == currentMethod):
				selected = u' selected'
			selectMethod += '<option%s>%s</option>' % (selected, method['name'])
		
		resultDiv = u'<div id="result">'
		for rpc in self._rpcs:
			resultDiv += '<div class="json">'
			resultDiv += objectToHtml(rpc.getResponse())
			resultDiv += u'</div>'
		resultDiv += u'</div>'
		
		html = interfacePage
		html = html.replace('%javascript%', javascript)
		html = html.replace('%select_method%', selectMethod)
		html = html.replace('%result%', resultDiv)
		
		if not isinstance(result, http.Response):
			result = http.Response()
		result.code = responsecode.OK
		result.stream = stream.IByteStream(html.encode('utf-8'))
		return result
	
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                               CACHED CONFIG SERVICE JSON RPC WORKER                               -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class CacheServiceJsonRpcWorker(Worker):
	def __init__(self, request, opsiclientd, resource):
		Worker.__init__(self, request, opsiclientd, resource)
		moduleName = u' %-30s' % (u'cached cfg server')
		logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)
	
	def _realRpc(self):
		method = self.rpc.get('method')
		params = self.rpc.get('params')
		logger.info(u"RPC method: '%s' params: '%s'" % (method, params))
		
		try:
			# Execute method
			start = time.time()
			self.result['result'] = self._opsiclientd._cacheService.processRpc(method, params)
		except Exception, e:
			logger.logException(e)
			self.result['error'] = { 'class': e.__class__.__name__, 'message': unicode(e) }
			self.result['result'] = None
			return
		
		logger.debug(u'Got result...')
		duration = round(time.time() - start, 3)
		logger.debug(u'Took %0.3fs to process %s(%s)' % (duration, method, unicode(params)[1:-1]))



# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                    CONTROL SERVER RESOURCE ROOT                                   -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ControlServerResourceRoot(resource.Resource):
	addSlash = True
	def render(self, request):
		''' Process request. '''
		return http.Response(stream="<html><head><title>opsiclientd</title></head><body></body></html>")
	
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                 CONTROL SERVER RESOURCE JSON RPC                                  -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ControlServerResourceJsonRpc(resource.Resource):
	WorkerClass = ControlServerJsonRpcWorker
	
	def __init__(self, opsiclientdRpcInterface):
		moduleName = u' %-30s' % (u'control server')
		logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)
		resource.Resource.__init__(self)
		self._opsiclientdRpcInterface = opsiclientdRpcInterface
		
	def getChild(self, name, request):
		''' Get the child resource for the requested path. '''
		if not name:
			return self
		return resource.Resource.getChild(self, name, request)
	
	def renderHTTP(self, request):
		''' Process request. '''
		try:
			logger.debug2(u"%s.renderHTTP()" % self.__class__.__name__)
			if not self.WorkerClass:
				raise Exception(u"No worker class defined in resource %s" % self.__class__.__name__)
			worker = self.WorkerClass(self._opsiclientdRpcInterface, request, self)
			return worker.process()
		except Exception, e:
			logger.logException(e)
	
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                 CONTROL SERVER RESOURCE INTERFACE                                 -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ControlServerResourceInterface(ControlServerResourceJsonRpc):
	WorkerClass = ControlServerJsonInterfaceWorker
	
	def __init__(self, opsiclientdRpcInterface):
		moduleName = u' %-30s' % (u'control server')
		logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)
		ControlServerResourceJsonRpc.__init__(self, opsiclientdRpcInterface)


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                              CACHED CONFIG SERVICE RESOURCE JSON RPC                              -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class CacheServiceResourceJsonRpc(resource.Resource):
	def __init__(self, opsiclientd):
		moduleName = u' %-30s' % (u'cached cfg server')
		logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)
		resource.Resource.__init__(self)
		self._opsiclientd = opsiclientd
		
	def getChild(self, name, request):
		''' Get the child resource for the requested path. '''
		if not name:
			return self
		return resource.Resource.getChild(self, name, request)
	
	def http_POST(self, request):
		''' Process POST request. '''
		logger.info(u"CacheServiceResourceJsonRpc: processing POST request")
		worker = CacheServiceJsonRpcWorker(request, self._opsiclientd, method = 'POST')
		return worker.process()
		
	def http_GET(self, request):
		''' Process GET request. '''
		logger.info(u"CacheServiceResourceJsonRpc: processing GET request")
		worker = CacheServiceJsonRpcWorker(request, self._opsiclientd, method = 'GET')
		return worker.process()



# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                           CONTROL SERVER                                          -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ControlServer(threading.Thread):
	def __init__(self, opsiclientd, httpsPort, sslServerKeyFile, sslServerCertFile, staticDir=None):
		moduleName = u' %-30s' % (u'control server')
		logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)', object=self)
		threading.Thread.__init__(self)
		self._opsiclientd = opsiclientd
		self._httpsPort = httpsPort
		self._sslServerKeyFile = sslServerKeyFile
		self._sslServerCertFile = sslServerCertFile
		self._staticDir = staticDir
		self._root = None
		self._running = False
		self._server = None
		self._opsiclientdRpcInterface = OpsiclientdRpcServerInterface(self._opsiclientd)
		logger.info(u"ControlServer initiated")
		
	def run(self):
		self._running = True
		try:
			logger.info(u"creating root resource")
			self.createRoot()
			self._site = server.Site(self._root)
			self._server = reactor.listenSSL(
				self._httpsPort,
				HTTPFactory(self._site),
				SSLContext(self._sslServerKeyFile, self._sslServerCertFile) )
			logger.notice(u"Control server is accepting HTTPS requests on port %d" % self._httpsPort)
			if not reactor.running:
				reactor.run(installSignalHandlers=0)
			
		except Exception, e:
			logger.logException(e)
		logger.notice(u"Control server exiting")
		self._running = False
	
	def stop(self):
		if self._server:
			self._server.stopListening()
		self._running = False
		
	def createRoot(self):
		if self._staticDir:
			if os.path.isdir(self._staticDir):
				self._root = static.File(self._staticDir)
			else:
				logger.error(u"Cannot add static content '/': directory '%s' does not exist." % self._staticDir)
		if not self._root:
			self._root = ControlServerResourceRoot()
		self._root.putChild("opsiclientd", ControlServerResourceJsonRpc(self._opsiclientdRpcInterface))
		self._root.putChild("interface", ControlServerResourceInterface(self._opsiclientdRpcInterface))
		self._root.putChild("rpc", CacheServiceResourceJsonRpc(self._opsiclientd))






class OpsiclientdRpcServerInterface(OpsiclientdRpcPipeInterface):
	def __init__(self, opsiclientd):
		OpsiclientdRpcPipeInterface.__init__(self, opsiclientd)
	
	def _authenticate(self, username, password):
		if (username.lower() == config.get('global', 'host_id').lower()) and (password == config.get('global', 'opsi_host_key')):
			return True
		if (os.name == 'nt'):
			if (username.lower() == 'administrator'):
				import win32security
				# The LogonUser function will raise an Exception on logon failure
				win32security.LogonUser(username, 'None', password, win32security.LOGON32_LOGON_NETWORK, win32security.LOGON32_PROVIDER_DEFAULT)
				# No exception raised => user authenticated
				return True
		raise Exception(u"Invalid credentials")
	
	def setBlockLogin(self, blockLogin):
		self.opsiclientd.setBlockLogin(bool(blockLogin))
		logger.notice(u"rpc setBlockLogin: blockLogin set to '%s'" % self.opsiclientd._blockLogin)
		if self.opsiclientd._blockLogin:
			return u"Login blocker is on"
		else:
			return u"Login blocker is off"
	
	def readLog(self, logType='opsiclientd'):
		logType = forceUnicode(logType)
		if not logType in ('opsiclientd'):
			raise ValueError(u"Unknown log type '%s'" % logType)
		
		logger.notice(u"rpc readLog: reading log of type '%s'" % logType)
		
		if (logType == 'opsiclientd'):
			f = codecs.open(config.get('global', 'log_file'), 'r', 'utf-8', 'replace')
			data = f.read()
			f.close()
			return data
		return u""
	
	def runCommand(self, command, sessionId=None, desktop=None):
		command = forceUnicode(command)
		if not command:
			raise ValueError("No command given")
		if sessionId:
			sessionId = forceInt(sessionId)
		else:
			sessionId = System.getActiveSessionId()
		if desktop:
			desktop = forceUnicode(desktop)
		else:
			desktop = self.opsiclientd.getCurrentActiveDesktopName()
		logger.notice(u"rpc runCommand: executing command '%s' in session %d on desktop '%s'" % (command, sessionId, desktop))
		System.runCommandInSession(command = command, sessionId = sessionId, desktop = desktop, waitForProcessEnding = False)
		return u"command '%s' executed" % command
	
	def logoffCurrentUser(self):
		logger.notice(u"rpc logoffCurrentUser: logging of current user now")
		System.logoffCurrentUser()
	
	def lockWorkstation(self):
		logger.notice(u"rpc lockWorkstation: locking workstation now")
		System.lockWorkstation()
	
	def shutdown(self, waitSeconds=0):
		waitSeconds = forceInt(waitSeconds)
		logger.notice(u"rpc shutdown: shutting down computer in %s seconds" % waitSeconds)
		System.shutdown(wait = waitSeconds)
	
	def reboot(self, waitSeconds=0):
		waitSeconds = forceInt(waitSeconds)
		logger.notice(u"rpc reboot: rebooting computer in %s seconds" % waitSeconds)
		System.reboot(wait = waitSeconds)
		
	def uptime(self):
		uptime = int(time.time() - self.opsiclientd._startupTime)
		logger.notice(u"rpc uptime: opsiclientd is running for %d seconds" % uptime)
		return uptime
	
	def fireEvent(self, name):
		name = forceUnicode(name)
		if not name in eventGenerators.keys():
			raise ValueError(u"Event '%s' not in list of known events: %s" % (name, ', '.join(eventGenerators.keys())))
		logger.notice(u"Firing event '%s'" % name)
		eventGenerators[name].fireEvent()
		
	def setStatusMessage(self, sessionId, message):
		sessionId = forceInt(sessionId)
		message = forceUnicode(message)
		ept = self.opsiclientd.getEventProcessingThread(sessionId)
		logger.notice(u"rpc setStatusMessage: Setting status message to '%s'" % message)
		ept.setStatusMessage(message)
	
	def getCurrentActiveDesktopName(self, sessionId=None):
		desktop = self.opsiclientd.getCurrentActiveDesktopName(sessionId)
		logger.notice(u"rpc getCurrentActiveDesktopName: current active desktop name is '%s'" % desktop)
		return desktop
	
	def setCurrentActiveDesktopName(self, sessionId, desktop):
		sessionId = forceInt(sessionId)
		desktop = forceUnicode(desktop)
		self.opsiclientd._currentActiveDesktopName[sessionId] = desktop
		logger.notice(u"rpc setCurrentActiveDesktopName: current active desktop name for session %s set to '%s'" % (sessionId, desktop))
	
	def set(self, section, option, value):
		section = forceUnicode(section)
		option = forceUnicode(option)
		value = forceUnicode(value)
		return config.set(section, option, value)
	
	def updateConfigFile(self):
		config.updateConfigFile()
		
	def showPopup(self, message):
		message = forceUnicode(message)
		self.opsiclientd.showPopup(message)
		
	












