#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = = = =
   =   opsi client daemon (opsiclientd)    =
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

__version__ = '3.99.2'

# Imports
import os, sys, thread, threading, time, urllib, base64, socket, re, shutil, filecmp, codecs, inspect
import copy as pycopy
from OpenSSL import SSL
from hashlib import md5

if (os.name == 'posix'):
	from signal import *
	import getopt
	# We need a faked win32serviceutil class
	class win32serviceutil:
		ServiceFramework = object

if (os.name == 'nt'):
	import win32serviceutil, win32service, win32con, win32api, win32event, win32pipe, win32file, pywintypes
	import win32com.server.policy
	import win32com.client
	from ctypes import *

wmi = None
pythoncom = None

# Twisted imports
from twisted.internet import defer, threads, reactor
from OPSI.web2 import resource, stream, server, http, responsecode, static, http_headers
from OPSI.web2.channel.http import HTTPFactory
from twisted.python.failure import Failure
from twisted.conch.ssh import keys

# OPSI imports
from OPSI.Logger import *
from OPSI import System
from OPSI.Util import *
from OPSI.Util.Message import *
from OPSI.Util.Repository import *
from OPSI.Util.File import IniFile
from OPSI.Util.File.Opsi import PackageContentFile
from OPSI.Backend.JSONRPC import JSONRPCBackend
from OPSI.Backend.File import FileBackend
#from OPSI.Backend.Offline import OfflineBackend
from OPSI.Backend.BackendManager import BackendManager

# Create logger instance
logger = Logger()
logger.setLogFormat(u'[%l] [%D]   %M     (%F|%N)')

# Possible event types
EVENT_CONFIG_TYPE_PRODUCT_SYNC_COMPLETED = u'product sync completed'
EVENT_CONFIG_TYPE_DAEMON_STARTUP = u'daemon startup'
EVENT_CONFIG_TYPE_DAEMON_SHUTDOWN = u'daemon shutdown'
EVENT_CONFIG_TYPE_GUI_STARTUP = u'gui startup'
EVENT_CONFIG_TYPE_PANIC = u'panic'
EVENT_CONFIG_TYPE_PROCESS_ACTION_REQUESTS = u'process action requests'
EVENT_CONFIG_TYPE_TIMER = u'timer'
EVENT_CONFIG_TYPE_USER_LOGIN = u'user login'
EVENT_CONFIG_TYPE_SYSTEM_SHUTDOWN = u'system shutdown'
EVENT_CONFIG_TYPE_CUSTOM = u'custom'

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

# Message translation
def _(msg):
	return msg

importWmiAndPythoncomLock = threading.Lock()
def importWmiAndPythoncom(importWmi = True, importPythoncom = True):
	global wmi
	global pythoncom
	if not ((wmi or not importWmi) and (pythoncom or not importPythoncom)):
		logger.info(u"Need to import wmi / pythoncom")
		importWmiAndPythoncomLock.acquire()
		while not ((wmi or not importWmi) and (pythoncom or not importPythoncom)):
			try:
				if not wmi and importWmi:
					logger.debug(u"Importing wmi")
					import wmi
				if not pythoncom and importPythoncom:
					logger.debug(u"Importing pythoncom")
					import pythoncom
			except Exception, e:
				logger.warning(u"Failed to import: %s, retrying in 2 seconds" % forceUnicode(e))
				time.sleep(2)
		importWmiAndPythoncomLock.release()

'''
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
=                                             EXEPTIONS                                               =
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
=                                                                                                     =
=                                         Exception classes.                                          =
=                                                                                                     =
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
'''
class OpsiclientdError(Exception):
	ExceptionShortDescription = u"Opsiclientd error"
	
	def __init__(self, message = u''):
		self._message = forceUnicode(message)
	
	def __unicode__(self):
		if self._message:
			return u"%s: %s" % (self.ExceptionShortDescription, self._message)
		else:
			return u"%s" % self.ExceptionShortDescription
		
	def __repr__(self):
		return unicode(self).encode("utf-8")
	
	__str__ = __repr__

class CanceledByUserError(OpsiclientdError):
	""" Exception raised if user cancels operation. """
	ExceptionShortDescription = "Canceled by user error"

class OpsiclientdAuthenticationError(Exception):
	ExceptionShortDescription = u"Opsiclientd authentication error"

class OpsiclientdBadRpcError(Exception):
	ExceptionShortDescription = u"Opsiclientd bad rpc error"

class OpsiclientdRpcError(Exception):
	ExceptionShortDescription = u"Opsiclientd rpc error"





'''
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
=                                               EVENTS                                                =
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
=                                                                                                     =
=                          Classes needed for creating and handling events.                           =
=                                                                                                     =
=  The main event class is "Event", the derived classes are:                                          =
=     DaemonStartupEvent:         This event is triggered on opsiclientd statup                       =
=     DaemonShutdownEvent:        This event is triggered on opsiclientd shutdown                     =
=     ProcessActionRequestEvent:  If this event is triggered action request are processed             =
=     TimerEvent:                 This event is triggered every x seconds                             =
=                                                                                                     =
=  The class "EventListener" is an base class for classes which should handle events                  =
=                                                                                                     =
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
'''

# from Sens.h
SENSGUID_PUBLISHER = "{5fee1bd6-5b9b-11d1-8dd2-00aa004abd5e}"
SENSGUID_EVENTCLASS_LOGON = "{d5978630-5b9f-11d1-8dd2-00aa004abd5e}"

# from EventSys.h
PROGID_EventSystem = "EventSystem.EventSystem"
PROGID_EventSubscription = "EventSystem.EventSubscription"

IID_ISensLogon = "{d597bab3-5b9f-11d1-8dd2-00aa004abd5e}"


class SensLogon(win32com.server.policy.DesignatedWrapPolicy):
	_com_interfaces_=[IID_ISensLogon]
	_public_methods_=[
		'Logon',
		'Logoff',
		'StartShell',
		'DisplayLock',
		'DisplayUnlock',
		'StartScreenSaver',
		'StopScreenSaver'
	]
	
	def __init__(self, callback):
		self._wrap_(self)
		self._callback = callback
		
	def Logon(self, *args):
		logger.notice(u'Logon : %s' % [args])
		self._callback('Logon', *args)
		
	def Logoff(self, *args):
		logger.notice(u'Logoff : %s' % [args])
		self._callback('Logoff', *args)
	
	def StartShell(self, *args):
		logger.notice(u'StartShell : %s' % [args])
		self._callback('StartShell', *args)
	
	def DisplayLock(self, *args):
		logger.notice(u'DisplayLock : %s' % [args])
		self._callback('DisplayLock', *args)
	
	def DisplayUnlock(self, *args):
		logger.notice(u'DisplayUnlock : %s' % [args])
		self._callback('DisplayUnlock', *args)
	
	def StartScreenSaver(self, *args):
		logger.notice(u'StartScreenSaver : %s' % [args])
		self._callback('StartScreenSaver', *args)
	
	def StopScreenSaver(self, *args):
		logger.notice(u'StopScreenSaver : %s' % [args])
		self._callback('StopScreenSaver', *args)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                         EVENT CONFIG                                              -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
def EventConfigFactory(type, name, **kwargs):
	if   (type == EVENT_CONFIG_TYPE_PANIC):
		return PanicEventConfig(name, **kwargs)
	elif (type == EVENT_CONFIG_TYPE_DAEMON_STARTUP):
		return DaemonStartupEventConfig(name, **kwargs)
	elif (type == EVENT_CONFIG_TYPE_DAEMON_SHUTDOWN):
		return DaemonShutdownEventConfig(name, **kwargs)
	elif (type == EVENT_CONFIG_TYPE_GUI_STARTUP):
		return GUIStartupEventConfig(name, **kwargs)
	elif (type == EVENT_CONFIG_TYPE_TIMER):
		return TimerEventConfig(name, **kwargs)
	elif (type == EVENT_CONFIG_TYPE_PRODUCT_SYNC_COMPLETED):
		return ProductSyncCompletedEventConfig(name, **kwargs)
	elif (type == EVENT_CONFIG_TYPE_PROCESS_ACTION_REQUESTS):
		return ProcessActionRequestsEventConfig(name, **kwargs)
	elif (type == EVENT_CONFIG_TYPE_USER_LOGIN):
		return UserLoginEventConfig(name, **kwargs)
	elif (type == EVENT_CONFIG_TYPE_SYSTEM_SHUTDOWN):
		return SystemShutdownEventConfig(name, **kwargs)
	elif (type == EVENT_CONFIG_TYPE_CUSTOM):
		return CustomEventConfig(name, **kwargs)
	else:
		raise TypeError("Unknown event config type '%s'" % type)
	
class EventConfig(object):
	def __init__(self, name, **kwargs):
		
		if not name:
			raise TypeError("Name not given")
		self._name = unicode(name)
		
		logger.setLogFormat(u'[%l] [%D] [event config ' + self._name + ']   %M  (%F|%N)', object=self)
		
		self.message                    =  unicode ( kwargs.get('message',                    ''        ) )
		self.maxRepetitions             =      int ( kwargs.get('maxRepetitions',             -1        ) )
		# wait <activationDelay> seconds before event gets active
		self.activationDelay            =      int ( kwargs.get('activationDelay',            0         ) )
		# wait <notificationDelay> seconds before event is fired
		self.notificationDelay          =      int ( kwargs.get('notificationDelay',          0         ) )
		self.warningTime                =      int ( kwargs.get('warningTime',                0         ) )
		self.userCancelable             =     bool ( kwargs.get('userCancelable',             False     ) )
		self.blockLogin                 =     bool ( kwargs.get('blockLogin',                 False     ) )
		self.logoffCurrentUser          =     bool ( kwargs.get('logoffCurrentUser',          False     ) )
		self.lockWorkstation            =     bool ( kwargs.get('lockWorkstation',            False     ) )
		self.processShutdownRequests    =     bool ( kwargs.get('processShutdownRequests',    True      ) )
		self.getConfigFromService       =     bool ( kwargs.get('getConfigFromService',       True      ) )
		self.updateConfigFile           =     bool ( kwargs.get('updateConfigFile',           True      ) )
		self.writeLogToService          =     bool ( kwargs.get('writeLogToService',          True      ) )
		self.updateActionProcessor      =     bool ( kwargs.get('updateActionProcessor',      True      ) )
		self.actionType                 =  unicode ( kwargs.get('actionType',                 ''        ) )
		self.eventNotifierCommand       =  unicode ( kwargs.get('eventNotifierCommand',       ''        ) )
		self.eventNotifierDesktop       =  unicode ( kwargs.get('eventNotifierDesktop',       'current' ) )
		self.actionNotifierCommand      =  unicode ( kwargs.get('actionNotifierCommand',      ''        ) )
		self.actionNotifierDesktop      =  unicode ( kwargs.get('actionNotifierDesktop',      'current' ) )
		self.actionProcessorCommand     =  unicode ( kwargs.get('actionProcessorCommand',     ''        ) )
		self.actionProcessorDesktop     =  unicode ( kwargs.get('actionProcessorDesktop',     'current' ) )
		self.actionProcessorTimeout     =      int ( kwargs.get('actionProcessorTimeout',     3*3600    ) )
		self.preActionProcessorCommand  =  unicode ( kwargs.get('preActionProcessorCommand',  ''        ) )
		self.postActionProcessorCommand =  unicode ( kwargs.get('postActionProcessorCommand', ''        ) )
		self.serviceOptions             =     dict ( kwargs.get('serviceOptions',             {}        ) )
		self.cacheProducts              =     bool ( kwargs.get('cacheProducts',              False     ) )
		self.cacheMaxBandwidth          =      int ( kwargs.get('cacheMaxBandwidth',          0         ) )
		self.requiresCachedProducts     =     bool ( kwargs.get('requiresCachedProducts',     False     ) )
		self.syncConfig                 =     bool ( kwargs.get('syncConfig',                 False     ) )
		self.useCachedConfig            =     bool ( kwargs.get('useCachedConfig',            False     ) )
		
		if not self.eventNotifierDesktop in ('winlogon', 'default', 'current'):
			logger.error(u"Bad value '%s' for eventNotifierDesktop" % self.eventNotifierDesktop)
			self.eventNotifierDesktop = 'current'
		if not self.actionNotifierDesktop in ('winlogon', 'default', 'current'):
			logger.error(u"Bad value '%s' for actionNotifierDesktop" % self.actionNotifierDesktop)
			self.actionNotifierDesktop = 'current'
		if not self.actionProcessorDesktop in ('winlogon', 'default', 'current'):
			logger.error(u"Bad value '%s' for actionProcessorDesktop" % self.actionProcessorDesktop)
			self.actionProcessorDesktop = 'current'
		
	def __str__(self):
		return "<event config: %s>" % self._name
	
	def getName(self):
		return self._name
	
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                         PANIC EVENT CONFIG                                        -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class PanicEventConfig(EventConfig):
	def __init__(self, name, **kwargs):
		EventConfig.__init__(self, name, **kwargs)
		self.maxRepetitions         = -1
		self.message                = 'Panic event'
		self.activationDelay        = 0
		self.notificationDelay      = 0
		self.warningTime            = 0
		self.userCancelable         = False
		self.blockLogin             = False
		self.logoffCurrentUser      = False
		self.lockWorkstation        = False
		self.getConfigFromService   = False
		self.updateConfigFile       = False
		self.writeLogToService      = False
		self.updateActionProcessor  = False
		self.eventNotifierCommand   = None
		self.actionNotifierCommand  = None
		self.actionProcessorDesktop = 'winlogon'
		self.serviceOptions         = {}

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                     DAEMON STARTUP EVENT CONFIG                                   -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class DaemonStartupEventConfig(EventConfig):
	def __init__(self, name, **kwargs):
		EventConfig.__init__(self, name, **kwargs)
		self.maxRepetitions = 0

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                    DAEMON SHUTDOWN EVENT CONFIG                                   -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class DaemonShutdownEventConfig(EventConfig):
	def __init__(self, name, **kwargs):
		EventConfig.__init__(self, name, **kwargs)
		self.maxRepetitions = 0

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                          WMI EVENT CONFIG                                         -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class WMIEventConfig(EventConfig):
	def __init__(self, name, **kwargs):
		EventConfig.__init__(self, name, **kwargs)
		self.wql = unicode( kwargs.get('wql', '') )

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                      GUI STARTUP EVENT CONFIG                                     -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class GUIStartupEventConfig(WMIEventConfig):
	def __init__(self, name, **kwargs):
		WMIEventConfig.__init__(self, name, **kwargs)
		self.maxRepetitions = 0
		self.processName = None
	
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                         TIMER EVENT CONFIG                                        -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class TimerEventConfig(EventConfig):
	def __init__(self, name, **kwargs):
		EventConfig.__init__(self, name, **kwargs)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                PRODUCT SYNC COMPLETED EVENT CONFIG                                -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ProductSyncCompletedEventConfig(EventConfig):
	def __init__(self, name, **kwargs):
		EventConfig.__init__(self, name, **kwargs)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                               PROCESS ACTION REQUESTS EVENT CONFIG                                -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ProcessActionRequestsEventConfig(EventConfig):
	def __init__(self, name, **kwargs):
		EventConfig.__init__(self, name, **kwargs)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                       USER LOGIN EVENT CONFIG                                     -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class UserLoginEventConfig(WMIEventConfig):
	def __init__(self, name, **kwargs):
		WMIEventConfig.__init__(self, name, **kwargs)
		self.blockLogin        = False
		self.logoffCurrentUser = False
		self.lockWorkstation   = False

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                    SYSTEM SHUTDOWN EVENT CONFIG                                   -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class SystemShutdownEventConfig(WMIEventConfig):
	def __init__(self, name, **kwargs):
		WMIEventConfig.__init__(self, name, **kwargs)
		self.maxRepetitions = 0

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                        CUSTOM EVENT CONFIG                                        -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class CustomEventConfig(WMIEventConfig):
	def __init__(self, name, **kwargs):
		WMIEventConfig.__init__(self, name, **kwargs)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                          EVENT GENERATOR                                          -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
def EventGeneratorFactory(eventConfig):
	if   isinstance(eventConfig, PanicEventConfig):
		return PanicEventGenerator(eventConfig)
	elif isinstance(eventConfig, DaemonStartupEventConfig):
		return DaemonStartupEventGenerator(eventConfig)
	elif isinstance(eventConfig, DaemonShutdownEventConfig):
		return DaemonShutdownEventGenerator(eventConfig)
	elif isinstance(eventConfig, GUIStartupEventConfig):
		return GUIStartupEventGenerator(eventConfig)
	elif isinstance(eventConfig, TimerEventConfig):
		return TimerEventGenerator(eventConfig)
	elif isinstance(eventConfig, ProductSyncCompletedEventConfig):
		return ProductSyncCompletedEventGenerator(eventConfig)
	elif isinstance(eventConfig, ProcessActionRequestsEventConfig):
		return ProcessActionRequestsEventGenerator(eventConfig)
	elif isinstance(eventConfig, UserLoginEventConfig):
		return UserLoginEventGenerator(eventConfig)
	elif isinstance(eventConfig, SystemShutdownEventConfig):
		return SystemShutdownEventGenerator(eventConfig)
	elif isinstance(eventConfig, CustomEventConfig):
		return CustomEventGenerator(eventConfig)
	else:
		raise TypeError(u"Unhandled event config '%s'" % eventConfig)

class EventGenerator(threading.Thread):
	def __init__(self, eventConfig):
		threading.Thread.__init__(self)
		self._eventConfig = eventConfig
		self._eventListeners = []
		self._eventsOccured = 0
		self._threadId = None
		self._stopped = False
		self._event = None
		self._lastEventOccurence = None
		logger.setLogFormat(u'[%l] [%D] [event generator ' + self._eventConfig.getName() + ']   %M  (%F|%N)', object=self)
		
	def addEventListener(self, eventListener):
		if not isinstance(eventListener, EventListener):
			raise TypeError(u"Failed to add event listener, got class %s, need class EventListener" % eventListener.__class__)
		
		for l in self._eventListeners:
			if (l == eventListener):
				return
		
		self._eventListeners.append(eventListener)
	
	def createEvent(self, eventInfo={}):
		return Event(eventConfig = self._eventConfig, eventInfo = eventInfo)
		
	def initialize(self):
		pass
	
	def getNextEvent(self):
		self._event = threading.Event()
		self._event.wait()
	
	def cleanup(self):
		pass
	
	def fireEvent(self, event=None):
		if self._stopped:
			return
		
		if not event:
			event = self.createEvent()
		
		self._lastEventOccurence = time.time()
		
		logger.info(u"Firing event '%s'" % event)
		logger.info(u"Event info:")
		for (key, value) in event.eventInfo.items():
			logger.info(u"     %s: %s" % (key, value))
		
		class FireEventThread(threading.Thread):
			def __init__(self, eventListener, event):
				threading.Thread.__init__(self)
				self._eventListener = eventListener
				self._event = event
				logger.setLogFormat(u'[%l] [%D] [event generator ' + self._event.eventConfig.getName() + ']   %M  (%F|%N)', object=self)
				
			def run(self):
				if (self._event.eventConfig.notificationDelay > 0):
					logger.debug(u"Waiting %d seconds before notifying listener '%s' of event '%s'" \
						% (self._event.eventConfig.notificationDelay, self._eventListener, self._event))
					time.sleep(self._event.eventConfig.notificationDelay)
				try:
					logger.info(u"Calling processEvent on listener %s" % self._eventListener)
					self._eventListener.processEvent(self._event)
				except Exception, e:
					logger.logException(e)
		
		logger.info(u"Starting FireEventThread for listeners: %s" % self._eventListeners)
		for l in self._eventListeners:
			# Create a new thread for each event listener
			FireEventThread(l, event).start()
		
	def run(self):
		self._threadId = thread.get_ident()
		try:
			logger.info(u"Initializing event generator '%s'" % self)
			self.initialize()
			
			if (self._eventConfig.activationDelay > 0):
				logger.debug(u"Waiting %d seconds before activation of event generator '%s'" % \
					(self._eventConfig.activationDelay, self))
				time.sleep(self.activationDelay)
			
			logger.info(u"Activating event generator '%s'" % self)
			while not self._stopped and ( (self._eventConfig.maxRepetitions < 0) or (self._eventsOccured <= self._eventConfig.maxRepetitions) ):
				logger.info(u"Getting next event...")
				event = self.getNextEvent()
				if event:
					self._eventsOccured += 1
					self.fireEvent(event)
			logger.info(u"Event generator '%s' now deactivated after %d event occurrences" % (self, self._eventsOccured))
			
		except Exception, e:
			logger.error(u"Failure in event generator '%s': %s" % (self, forceUnicode(e)))
			logger.logException(e)
		
		try:
			self.cleanup()
		except Exception, e:
			logger.error(u"Failed to clean up: %s" % forceUnicode(e))
		
		logger.info(u"Event generator '%s' exiting " % self)
	
	def stop(self):
		self._stopped = True
		if self._event:
			self._event.set()
		
class PanicEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)
	
	def createEvent(self, eventInfo={}):
		return PanicEvent(eventConfig = self._eventConfig, eventInfo = eventInfo)
	
class DaemonStartupEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)
	
	def createEvent(self, eventInfo={}):
		return DaemonStartupEvent(eventConfig = self._eventConfig, eventInfo = eventInfo)
	
class DaemonShutdownEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)
	
	def createEvent(self, eventInfo={}):
		return DaemonShutdownEvent(eventConfig = self._eventConfig, eventInfo = eventInfo)
	
class WMIEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)
		self._wql = self._eventConfig.wql
		self._watcher = None
		
	def initialize(self):
		if not (os.name == 'nt'):
			return
		
		importWmiAndPythoncom()
		pythoncom.CoInitialize()
		if self._wql:
			while not self._watcher:
				try:
					logger.debug(u"Creating wmi object")
					c = wmi.WMI(privileges = ["Security"])
					logger.info(u"Watching for wql: %s" % self._wql)
					self._watcher = c.watch_for(raw_wql = self._wql, wmi_class = '')
				except Exception, e:
					try:
						logger.warning(u"Failed to create wmi watcher: %s" % forceUnicode(e))
					except Exception:
						logger.warning(u"Failed to create wmi watcher, failed to log exception")
					time.sleep(1)
		logger.debug(u"Initialized")
		
	def getNextEvent(self):
		if not self._watcher:
			logger.error(u"Nothing to watch for")
			self._event = threading.Event()
			self._event.wait()
			return None
		
		wqlResult = None
		while not self._stopped:
			try:
				wqlResult = self._watcher(timeout_ms=500)
				break
			except wmi.x_wmi_timed_out:
				continue
		
		if wqlResult:
			eventInfo = {}
			for p in wqlResult.properties:
				value = getattr(wqlResult, p)
				if type(value) is tuple:
					eventInfo[p] = []
					for v in value:
						eventInfo[p].append(v)
				else:
					eventInfo[p] = value
			return self.createEvent(eventInfo)
		
	def cleanup(self):
		if self._lastEventOccurence and (time.time() - self._lastEventOccurence < 10):
			# Waiting some seconds before exit to avoid Win32 releasing exceptions
			waitTime = int(10 - (time.time() - self._lastEventOccurence))
			logger.info(u"Event generator '%s' cleaning up in %d seconds" % (self, waitTime))
			time.sleep(waitTime)
			
		importWmiAndPythoncom()
		pythoncom.CoUninitialize()
	
class GUIStartupEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)
		if   (os.name == 'nt') and (sys.getwindowsversion()[0] == 5):
			self.guiProcessName = u'winlogon.exe'
		elif (os.name == 'nt') and (sys.getwindowsversion()[0] == 6):
			self.guiProcessName = u'LogonUI.exe'
		else:
			raise Exception(u"OS unsupported")
	
	def createEvent(self, eventInfo={}):
		return GUIStartupEvent(eventConfig = self._eventConfig, eventInfo = eventInfo)
	
	def getNextEvent(self):
		while not self._stopped:
			logger.debug(u"Checking if process '%s' running" % self.guiProcessName)
			if System.getPid(self.guiProcessName):
				logger.debug(u"Process '%s' is running" % self.guiProcessName)
				return self.createEvent()
			time.sleep(3)

class TimerEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)
	
	def createEvent(self, eventInfo={}):
		return TimerEvent(eventConfig = self._eventConfig, eventInfo = eventInfo)
	
class ProductSyncCompletedEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)
	
	def createEvent(self, eventInfo={}):
		return ProductSyncCompletedEvent(eventConfig = self._eventConfig, eventInfo = eventInfo)
	
class ProcessActionRequestsEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)
	
	def createEvent(self, eventInfo={}):
		return ProcessActionRequestsEvent(eventConfig = self._eventConfig, eventInfo = eventInfo)

class SensLogonEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)
		
	def initialize(self):
		EventGenerator.initialize(self)
		if not (os.name == 'nt'):
			return
		
		logger.notice(u'Registring ISensLogon')
		
		importWmiAndPythoncom(importWmi = False, importPythoncom = True)
		pythoncom.CoInitialize()
		
		sl = SensLogon(self.callback)
		subscription_interface = pythoncom.WrapObject(sl)
		
		event_system = win32com.client.Dispatch(PROGID_EventSystem)
		
		event_subscription = win32com.client.Dispatch(PROGID_EventSubscription)
		event_subscription.EventClassID = SENSGUID_EVENTCLASS_LOGON
		event_subscription.PublisherID = SENSGUID_PUBLISHER
		event_subscription.SubscriptionName = 'opsiclientd subscription'
		event_subscription.SubscriberInterface = subscription_interface
		
		event_system.Store(PROGID_EventSubscription, event_subscription)
	
	def getNextEvent(self):
		pythoncom.PumpMessages()
		logger.info(u"Event generator '%s' now deactivated after %d event occurrences" % (self, self._eventsOccured))
		self.cleanup()
		
	def callback(self, eventType, *args):
		logger.debug(u"SensLogonEventGenerator event callback: eventType '%s', args: %s" % (eventType, args))
	
	def stop(self):
		EventGenerator.stop(self)
		# Post WM_QUIT
		win32api.PostThreadMessage(self._threadId, 18, 0, 0)
		
	def cleanup(self):
		if self._lastEventOccurence and (time.time() - self._lastEventOccurence < 10):
			# Waiting some seconds before exit to avoid Win32 releasing exceptions
			waitTime = int(10 - (time.time() - self._lastEventOccurence))
			logger.info(u"Event generator '%s' cleaning up in %d seconds" % (self, waitTime))
			time.sleep(waitTime)
		
		importWmiAndPythoncom(importWmi = False, importPythoncom = True)
		pythoncom.CoUninitialize()
		
class UserLoginEventGenerator(SensLogonEventGenerator):
	def __init__(self, eventConfig):
		SensLogonEventGenerator.__init__(self, eventConfig)
	
	def callback(self, eventType, *args):
		logger.debug(u"UserLoginEventGenerator event callback: eventType '%s', args: %s" % (eventType, args))
		#if (eventType == 'Logon'):
		if (eventType == 'StartShell'):
			logger.notice(u"User login detected: %s" % args[0])
			self._eventsOccured += 1
			self.fireEvent(self.createEvent(eventInfo = {'User': args[0]}))
			if (self._eventConfig.maxRepetitions > 0) and (self._eventsOccured > self._eventConfig.maxRepetitions):
				self.stop()
	
	def createEvent(self, eventInfo={}):
		return UserLoginEvent(eventConfig = self._eventConfig, eventInfo = eventInfo)

class SystemShutdownEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)

class CustomEventGenerator(EventGenerator):
	def __init__(self, eventConfig):
		EventGenerator.__init__(self, eventConfig)
	
	def createEvent(self, eventInfo={}):
		return CustomEvent(eventConfig = self._eventConfig, eventInfo = eventInfo)
	
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                            EVENT                                                  -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class Event(object):
	def __init__(self, eventConfig, eventInfo={}):
		self.eventConfig = eventConfig
		self.eventInfo = eventInfo
		logger.setLogFormat(u'[%l] [%D] [event ' + self.eventConfig.getName() + ']   %M  (%F|%N)', object=self)
		
	def getActionProcessorCommand(self):
		actionProcessorCommand = self.eventConfig.actionProcessorCommand
		for (key, value) in self.eventInfo.items():
			actionProcessorCommand = actionProcessorCommand.replace(u'%' + u'event.' + unicode(key.lower()) + u'%', unicode(value))
		return actionProcessorCommand

class PanicEvent(Event):
	def __init__(self, eventConfig, eventInfo={}):
		Event.__init__(self, eventConfig, eventInfo)

class DaemonStartupEvent(Event):
	def __init__(self, eventConfig, eventInfo={}):
		Event.__init__(self, eventConfig, eventInfo)

class DaemonShutdownEvent(Event):
	def __init__(self, eventConfig, eventInfo={}):
		Event.__init__(self, eventConfig, eventInfo)

class GUIStartupEvent(Event):
	def __init__(self, eventConfig, eventInfo={}):
		Event.__init__(self, eventConfig, eventInfo)

class TimerEvent(Event):
	def __init__(self, eventConfig, eventInfo={}):
		Event.__init__(self, eventConfig, eventInfo)

class ProductSyncCompletedEvent(Event):
	def __init__(self, eventConfig, eventInfo={}):
		Event.__init__(self, eventConfig, eventInfo)

class ProcessActionRequestsEvent(Event):
	def __init__(self, eventConfig, eventInfo={}):
		Event.__init__(self, eventConfig, eventInfo)

class UserLoginEvent(Event):
	def __init__(self, eventConfig, eventInfo={}):
		Event.__init__(self, eventConfig, eventInfo)

class SystemShutdownEvent(Event):
	def __init__(self, eventConfig, eventInfo={}):
		Event.__init__(self, eventConfig, eventInfo)

class CustomEvent(Event):
	def __init__(self, eventConfig, eventInfo={}):
		Event.__init__(self, eventConfig, eventInfo)


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                          EVENT LISTENER                                           -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class EventListener(object):
	def __init__(self):
		logger.debug(u"EventListener initiated")
	
	def processEvent(event):
		logger.warning(u"%s: processEvent() not implemented" % self)
	




# = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
# =                                       CLASS JSON RPC                                              =
# = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
class JsonRpc(object):
	def __init__(self, opsiclientdRpcInterface, rpc):
		self.opsiclientdRpcInterface = opsiclientdRpcInterface
		logger.setLogFormat(u'[%l] [%D] [json rpc]   %M     (%F|%N)', object=self)
		self.started   = None
		self.ended     = None
		self.type      = rpc.get('type')
		self.tid       = rpc.get('tid', rpc.get('id'))
		self.action    = rpc.get('action')
		self.method    = rpc.get('method')
		self.params    = rpc.get('params', rpc.get('data'))
		if not self.params:
			self.params = []
		self.result    = None
		self.exception = None
		self.traceback = None
		if not self.tid:
			raise Exception(u"No transaction id ((t)id) found in rpc")
		if not self.method:
			raise Exception(u"No method found in rpc")
	
	def isStarted(self):
		return bool(self.started)
	
	def hasEnded(self):
		return bool(self.ended)
	
	def getMethodName(self):
		if self.action:
			return u'%s_%s' % (self.action, self.method)
		return self.method
	
	def getDuration(self):
		if not self.started or not self.ended:
			return None
		return round(self.ended - self.started, 3)
		
	def execute(self):
		# Execute rpc
		params = []
		for param in self.params:
			params.append(param)
		
		pString = unicode(params)[1:-1]
		if (len(pString) > 200):
			pString = pString[:200] + u'...'
		
		logger.notice(u"-----> Executing: %s(%s)" % (self.getMethodName(), pString))
		
		self.started = time.time()
		try:
			found = False
			keywords = {}
			for m in self.opsiclientdRpcInterface.getInterface():
				if (self.getMethodName() == m['name']):
					if m['keywords']:
						l = 0
						if m['args']:
							l += len(m['args'])
						if m['varargs']:
							l += len(m['varargs'])
						if (len(params) >= l):
							for (key, value) in params.pop(-1).items():
								keywords[str(key)] = value
					found = True
					break
			if not found:
				raise OpsiclientdRpcError(u"Method '%s' is not valid" % self.getMethodName())
			
			opsiclientdRpcInterface = self.opsiclientdRpcInterface
			if keywords:
				self.result = eval( "opsiclientdRpcInterface.%s(*params, **keywords)" % self.getMethodName() )
			else:
				self.result = eval( "opsiclientdRpcInterface.%s(*params)" % self.getMethodName() )
			
			logger.info(u'Got result')
			logger.debug2(u"Result is: %s" % self.result)
		
		except Exception, e:
			logger.logException(e)
			logger.error(u'Execution error: %s' % forceUnicode(e))
			self.exception = e
			self.traceback = []
			tb = sys.exc_info()[2]
			while (tb != None):
				f = tb.tb_frame
				c = f.f_code
				self.traceback.append(u"     line %s in '%s' in file '%s'" % (tb.tb_lineno, c.co_name, c.co_filename))
				tb = tb.tb_next
		self.ended = time.time()
		
	def getResponse(self):
		response = {}
		if (self.type == 'rpc'):
			response['tid']    = self.tid
			response['action'] = self.action
			response['method'] = self.method
			if self.exception:
				response['type']    = 'exception'
				response['message'] = { 'class': self.exception.__class__.__name__, 'message': unicode(self.exception) }
				response['where']   = self.traceback
			else:
				response['type']   = 'rpc'
				response['result'] = self.result
		else:
			response['id'] = self.tid
			if self.exception:
				response['error']  = { 'class': self.exception.__class__.__name__, 'message': unicode(self.exception) }
				response['result'] = None
			else:
				response['error']  = None
				response['result'] = self.result
		return response
	

'''
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
=                                            CONTROL PIPES                                            =
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
=                                                                                                     =
=             These classes are used to create named pipes for remote procedure calls                 =
=                                                                                                     =
=  The class "ControlPipe" is the base class for a named pipe which handles remote procedure calls    =
=     PosixControlPipe implements a control pipe for posix operating systems                          =
=     NTControlPipe implements a control pipe for windows operating systems                           =
=  The class "ControlPipeFactory" selects the right implementation for the running os                 =
=                                                                                                     =
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
'''

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                        CONTROL PIPE                                               -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ControlPipe(threading.Thread):
	def __init__(self, opsiclientdRpcInterface):
		logger.setLogFormat(u'[%l] [%D] [control pipe]   %M     (%F|%N)', object=self)
		threading.Thread.__init__(self)
		self._opsiclientdRpcInterface = opsiclientdRpcInterface
		self._pipe = None
		self._pipeName = ""
		self._bufferSize = 4096
		self._running = False
		self._stopped = False
		
	def stop(self):
		self._stopped = True
	
	def closePipe(self):
		return
	
	def isRunning(self):
		return self._running
	
	def executeRpc(self, rpc):
		try:
			rpc = fromJson(rpc)
			rpc = JsonRpc(self._opsiclientdRpcInterface, rpc)
			rpc.execute()
			return toJson(rpc.getResponse())
		except Exception, e:
			logger.logException(e)
		
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                     POSIX CONTROL PIPE                                            -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class PosixControlPipe(ControlPipe):
	def __init__(self, opsiclientdRpcInterface):
		ControlPipe.__init__(self, opsiclientdRpcInterface)
		self._pipeName = "/var/run/opsiclientd/fifo"
	
	def createPipe(self):
		logger.debug2(u"Creating pipe %s" % self._pipeName)
		if not os.path.exists( os.path.dirname(self._pipeName) ):
			os.mkdir( os.path.dirname(self._pipeName) )
		if os.path.exists(self._pipeName):
			os.unlink(self._pipeName)
		os.mkfifo(self._pipeName)
		logger.debug2(u"Pipe %s created" % self._pipeName)
	
	def closePipe(self):
		if self._pipe:
			try:
				os.close(self._pipe)
			except Exception, e:
				pass
	
	def run(self):
		self._running = True
		try:
			self.createPipe()
			while self._running:
				try:
					logger.debug2(u"Opening named pipe %s" % self._pipeName)
					self._pipe = os.open(self._pipeName, os.O_RDONLY)
					logger.debug2(u"Reading from pipe %s" % self._pipeName)
					rpc = os.read(self._pipe, self._bufferSize)
					os.close(self._pipe)
					if not rpc:
						logger.error(u"No rpc from pipe")
						continue
					logger.debug2(u"Received rpc from pipe '%s'" % rpc)
					result = self.executeRpc(rpc)
					logger.debug2(u"Opening named pipe %s" % self._pipeName)
					timeout = 3
					ta = 0.0
					while (ta < timeout):
						try:
							self._pipe = os.open(self._pipeName, os.O_WRONLY | os.O_NONBLOCK)
							break
						except Exception, e:
							if not hasattr(e, 'errno') or (e.errno != 6):
								raise
							time.sleep(0.01)
							ta += 0.01
					if (ta >= timeout):
						logger.error(u"Failed to write to pipe (timed out after %d seconds)" % timeout)
						continue
					logger.debug2(u"Writing to pipe")
					written = os.write(self._pipe, result)
					logger.debug2(u"Number of bytes written: %d" % written)
					if (len(result) != written):
						logger.error("Failed to write all bytes to pipe (%d/%d)" % (written, len(result)))
				
				except Exception, e:
					logger.error(u"Pipe IO error: %s" % forceUnicode(e))
				try:
					os.close(self._pipe)
				except:
					pass
		except Exception, e:
			logger.logException(e)
		logger.notice(u"ControlPipe exiting")
		if os.path.exists(self._pipeName):
			os.unlink(self._pipeName)
		self._running = False

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                     NT CONTROL PIPE CONNECTION                                    -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class NTControlPipeConnection(threading.Thread):
	def __init__(self, ntControlPipe, pipe, bufferSize):
		logger.setLogFormat(u'[%l] [%D] [control pipe]   %M     (%F|%N)', object=self)
		threading.Thread.__init__(self)
		self._ntControlPipe = ntControlPipe
		self._pipe = pipe
		self._bufferSize = bufferSize
		logger.debug(u"NTControlPipeConnection initiated")
	
	def closePipe(self):
		if self._pipe:
			try:
				windll.kernel32.CloseHandle(self._pipe)
			except:
				pass
	
	def run(self):
		self._running = True
		try:
			chBuf = create_string_buffer(self._bufferSize)
			cbRead = c_ulong(0)
			while self._running:
				logger.debug2(u"Reading fom pipe")
				fReadSuccess = windll.kernel32.ReadFile(self._pipe, chBuf, self._bufferSize, byref(cbRead), None)
				if ((fReadSuccess == 1) or (cbRead.value != 0)):
					logger.debug(u"Received rpc from pipe '%s'" % chBuf.value)
					result =  "%s\0" % self._ntControlPipe.executeRpc(chBuf.value)
					cbWritten = c_ulong(0)
					logger.debug2(u"Writing to pipe")
					fWriteSuccess = windll.kernel32.WriteFile(
									self._pipe,
									c_char_p(result),
									len(result),
									byref(cbWritten),
									None )
					logger.debug2(u"Number of bytes written: %d" % cbWritten.value)
					if not fWriteSuccess:
						logger.error(u"Could not reply to the client's request from the pipe")
						break
					if (len(result) != cbWritten.value):
						logger.error(u"Failed to write all bytes to pipe (%d/%d)" % (cbWritten.value, len(result)))
						break
					break
				else:
					logger.error(u"Failed to read from pipe")
					break
			
			windll.kernel32.FlushFileBuffers(self._pipe)
			windll.kernel32.DisconnectNamedPipe(self._pipe)
			windll.kernel32.CloseHandle(self._pipe)
		except Exception, e:
			logger.error(u"NTControlPipeConnection error: %s" % forceUnicode(e))
		logger.debug(u"NTControlPipeConnection exiting")
		self._running = False

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                          NT CONTROL PIPE                                          -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class NTControlPipe(ControlPipe):
	
	def __init__(self, opsiclientdRpcInterface):
		threading.Thread.__init__(self)
		ControlPipe.__init__(self, opsiclientdRpcInterface)
		self._pipeName = "\\\\.\\pipe\\opsiclientd"
	
	def createPipe(self):
		logger.info(u"Creating pipe %s" % self._pipeName)
		PIPE_ACCESS_DUPLEX = 0x3
		PIPE_TYPE_MESSAGE = 0x4
		PIPE_READMODE_MESSAGE = 0x2
		PIPE_WAIT = 0
		PIPE_UNLIMITED_INSTANCES = 255
		NMPWAIT_USE_DEFAULT_WAIT = 0
		INVALID_HANDLE_VALUE = -1
		self._pipe = windll.kernel32.CreateNamedPipeA(
					self._pipeName,
					PIPE_ACCESS_DUPLEX,
					PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT,
					PIPE_UNLIMITED_INSTANCES,
					self._bufferSize,
					self._bufferSize,
					NMPWAIT_USE_DEFAULT_WAIT,
					None )
		if (self._pipe == INVALID_HANDLE_VALUE):
			raise Exception(u"Failed to create named pipe")
		logger.debug(u"Pipe %s created" % self._pipeName)
	
	#def createPipe(self):
	#	logger.info(u"Creating pipe %s" % self._pipeName)
	#	self._pipe = win32pipe.CreateNamedPipe(
	#			self._pipeName,
	#			win32pipe.PIPE_ACCESS_DUPLEX | win32file.FILE_FLAG_OVERLAPPED,
	#			win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
	#			win32pipe.PIPE_UNLIMITED_INSTANCES,
	#			self._bufferSize,
	#			self._bufferSize,
	#			5000,
	#			None)
	#	logger.debug(u"Pipe %s created" % self._pipeName)
	
	def run(self):
		ERROR_PIPE_CONNECTED = 535
		self._running = True
		try:
			while self._running:
				self.createPipe()
				logger.debug(u"Connecting to named pipe %s" % self._pipeName)
				# This call is blocking until a client connects
				fConnected = windll.kernel32.ConnectNamedPipe(self._pipe, None)
				if ((fConnected == 0) and (windll.kernel32.GetLastError() == ERROR_PIPE_CONNECTED)):
					fConnected = 1
				if (fConnected == 1):
					logger.debug(u"Connected to named pipe %s" % self._pipeName)
					logger.debug(u"Creating NTControlPipeConnection")
					cpc = NTControlPipeConnection(self, self._pipe, self._bufferSize)
					cpc.start()
					logger.debug(u"NTControlPipeConnection thread started")
				else:
					logger.error(u"Failed to connect to pipe")
					windll.kernel32.CloseHandle(self._pipe)
		except Exception, e:
			logger.logException(e)
		logger.notice(u"ControlPipe exiting")
		self._running = False

	#def run(self):
	#	self._running = True
	#	try:
	#		while not self._stopped:
	#			self.createPipe()
	#			connected = False
	#			while not self._stopped:
	#				logger.debug2(u"Connecting to named pipe %s" % self._pipeName)
	#				overlapped = pywintypes.OVERLAPPED()
	#				#overlapped.hEvent = win32event.CreateEvent(None, 1, 0, None)
	#				overlapped.hEvent = win32event.CreateEvent(None, 0, 0, None)
	#				fConnected = win32pipe.ConnectNamedPipe(self._pipe, overlapped)
	#				waitResult = win32event.WaitForSingleObject(overlapped.hEvent, 3000)
	#				logger.debug2(u"Wait for pipe connection result: %s" % waitResult)
	#				if (waitResult == win32event.WAIT_OBJECT_0):
	#					connected = True
	#					logger.debug(u"Connected to named pipe '%s'" % self._pipeName)
	#					break
	#				elif (waitResult == win32event.WAIT_TIMEOUT):
	#					continue
	#				else:
	#					raise Exception(u"Failed to connect to pipe '%s': %s" (self._pipeName, waitResult))
	#			if connected:
	#				try:
	#					logger.debug2(u"Reading fom pipe")
	#					(errCode, readString) = win32file.ReadFile(self._pipe, self._bufferSize, None)
	#					if (errCode != 0):
	#						raise Exception(u"Failed to read from pipe: %s" % errCode)
	#					readString = readString.split('\0')[0].strip()
	#					logger.debug(u"Received rpc from pipe '%s'" % readString)
	#					result = self.executeRpc(readString)
	#					logger.debug(u"Writing rpc result '%s' to pipe" % result)
	#					(errCode, nBytesWritten) = win32file.WriteFile(self._pipe, result + '\0', None)
	#					win32file.FlushFileBuffers(self._pipe)
	#					logger.debug2(u"Number of bytes written: %d" % nBytesWritten)
	#					if (errCode != 0):
	#						raise Exception(u"Failed to write to pipe: %s" % errCode)
	#				except Exception, e:
	#					logger.error(u"Failed to cummunicate through pipe: %s" % forceUnicode(e))
	#				win32pipe.DisconnectNamedPipe(self._pipe)
	#			win32api.CloseHandle(self._pipe)
	#			self._pipe = None
	#	except Exception, e:
	#		logger.logException(e)
	#	logger.notice(u"ControlPipe exiting")
	#	if self._pipe:
	#		try:
	#			win32api.CloseHandle(self._pipe)
	#		except:
	#			pass
	#	self._running = False
	
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                     CONTROL PIPE FACTORY                                          -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
def ControlPipeFactory(opsiclientdRpcInterface):
	if (os.name == 'posix'):
		return PosixControlPipe(opsiclientdRpcInterface)
	if (os.name == 'nt'):
		return NTControlPipe(opsiclientdRpcInterface)
	else:
		raise NotImplemented(u"Unsupported operating system %s" % os.name)







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
		logger.setLogFormat(u'[%l] [%D] [control server]   %M     (%F|%N)', object=self)
	
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
					raise Exception(u"Bad Authorization header from '%s'" % self.request.remoteAddr.host)
			
			logger.notice(u"Authorization request from %s@%s" % (user, self.request.remoteAddr.host))
			if not user:
				user = socket.getfqdn()
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
		logger.setLogFormat(u'[%l] [%D] [control server]   %M     (%F|%N)', object=self)
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
		logger.setLogFormat(u'[%l] [%D] [control server]   %M     (%F|%N)', object=self)
		ControlServerResourceJsonRpc.__init__(self, opsiclientdRpcInterface)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                        CACHED CONFIG SERVICE                                      -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

class CacheService(threading.Thread):
	def __init__(self, opsiclientd):
		threading.Thread.__init__(self)
		logger.setLogFormat(u'[%l] [%D] [cache service]   %M     (%F|%N)', object=self)
		self._opsiclientd = opsiclientd
		self._storageDir = self._opsiclientd.getConfigValue('cache_service', 'storage_dir')
		self._tempDir = os.path.join(self._storageDir, 'tmp')
		self._productCacheDir = os.path.join(self._storageDir, 'depot')
		self._productCacheMaxSize = forceInt(self._opsiclientd.getConfigValue('cache_service', 'product_cache_max_size'))
		
		self._stopped = False
		self._running = False
		
		self._state = {
			'product':  {},
			'config':   {}
		}
		
		self._configService = None
		self._productIds = []
		
		self._cacheProductsRequested = False
		self._cacheProductsRunning = False
		self._cacheProductsEnded = threading.Event()
		
		self._currentProductSyncProgressObserver = None
		self._overallProductSyncProgressObserver = None
		self._initialized = False
	
	def initialize(self):
		if self._initialized:
			return
		#self.readStateFile()
		self._initialized = True
		if not os.path.exists(self._storageDir):
			logger.notice(u"Creating cache service storage dir '%s'" % self._storageDir)
			os.mkdir(self._storageDir)
		if not os.path.exists(self._tempDir):
			logger.notice(u"Creating cache service temp dir '%s'" % self._tempDir)
			os.mkdir(self._tempDir)
		if not os.path.exists(self._productCacheDir):
			logger.notice(u"Creating cache service product cache dir '%s'" % self._productCacheDir)
			os.mkdir(self._productCacheDir)
	
	def setCurrentProductSyncProgressObserver(self, currentProductSyncProgressObserver):
		self._currentProductSyncProgressObserver = currentProductSyncProgressObserver
	
	def setOverallProductSyncProgressObserver(self, overallProductSyncProgressObserver):
		self._overallProductSyncProgressObserver = overallProductSyncProgressObserver
	
	def getProductCacheDir(self):
		return self._productCacheDir
		
	def getProductSyncCompleted(self):
		self.initialize()
		if not self._state['product']:
			logger.info(u"No products cached")
			return False
		productSyncCompleted = True
		for (productId, state) in self._state['product'].items():
			if state.get('sync_completed'):
				logger.debug(u"Product '%s': sync completed" % productId)
			else:
				productSyncCompleted = False
				logger.debug(u"Product '%s': sync not completed" % productId)
		return productSyncCompleted
		
	def cacheProducts(self, configService, productIds, waitForEnding=False):
		if self._cacheProductsRunning:
			logger.info(u"Already caching products")
		else:
			self.initialize()
			self._configService = configService
			self._productIds = productIds
			self._cacheProductsRequested = True
			self._cacheProductsEnded.clear()
			for productId in self._productIds:
				if not self._state['product'].has_key(productId):
					self._state['product'][productId] = {'sync_started': '', 'sync_completed': '', 'sync_failure': '' }
		if waitForEnding:
			self._cacheProductsEnded.wait()
			for productId in self._state['product'].keys():
				if self._state['product'][productId]['sync_failure']:
					raise Exception(u"Failed to cache product '%s': %s" % (productId, self._state['product'][productId]['sync_failure']))
	
	def freeProductCacheSpace(self, neededSpace = 0, neededProducts = []):
		try:
			# neededSpace in byte
			neededSpace    = forceInt(neededSpace)
			neededProducts = forceProductIdList(neededProducts)
			
			maxFreeableSize = 0
			productDirSizes = {}
			for product in os.listdir(self._productCacheDir):
				if not product in neededProducts:
					productDirSizes[product] = System.getDirectorySize(os.path.join(self._productCacheDir, product))
					maxFreeableSize += productDirSizes[product]
			if (maxFreeableSize < neededSpace):
				raise Exception(u"Needed space: %0.3f MB, maximum freeable space: %0.3f MB" \
							% ( (float(neededSpace)/(1024*1024)), (float(maxFreeableSize)/(1024*1024)) ) )
			freedSpace = 0
			while (freedSpace < neededSpace):
				deleteProduct = None
				eldestTime = None
				for (product, size) in productDirSizes.items():
					packageContentFile = os.path.join(self._productCacheDir, product, u'%s.files' % product)
					if not os.path.exists(packageContentFile):
						logger.info(u"Package content file '%s' not found, deleting product cache to free disk space")
						deleteProduct = product
						break
					mtime = os.path.getmtime(packageContentFile)
					if not eldestTime:
						eldestTime = mtime
						deleteProduct = product
						continue
					if (mtime < eldestTime):
						eldestTime = mtime
						deleteProduct = product
				if not deleteProduct:
					raise Exception(u"Internal error")
				deleteDir = os.path.join(self._productCacheDir, deleteProduct)
				logger.notice(u"Deleting product cache directory '%s'" % deleteDir)
				if not os.path.exists(deleteDir):
					raise Exception(u"Directory '%s' not found" % deleteDir)
				shutil.rmtree(deleteDir)
				freedSpace += productDirSizes[deleteProduct]
			logger.notice(u"%0.3f MB of product cache freed" % (float(freedSpace)/(1024*1024)))
		except Exception, e:
			raise Exception(u"Failed to free enough disk space for product cache: %s" % forceUnicode(e))
		
	def stop(self):
		self._stopped = True
		
	def run(self):
		self._running = True
		while not self._stopped:
			try:
				if self._cacheProductsRequested:
					self._cacheProductsRequested = False
					self._cacheProductsRunning = True
					
					try:
						logger.notice(u"Caching products: %s" % ', '.join(self._productIds))
						self.initialize()
						
						if not self._configService:
							raise Exception(u"Not connected to config service")
						
						modules = None
						if self._configService.isOpsi35():
							modules = self._configService.backend_info()['modules']
						else:
							modules = self._configService.getOpsiInformation_hash()['modules']
						
						if not modules.get('vpn'):
							raise Exception(u"Cannot sync products: VPN module currently disabled")
						
						if not modules.get('customer'):
							raise Exception(u"Cannot sync products: No customer in modules file")
							
						if not modules.get('valid'):
							raise Exception(u"Cannot sync products: modules file invalid")
						
						if (modules.get('expires', '') != 'never') and (time.mktime(time.strptime(modules.get('expires', '2000-01-01'), "%Y-%m-%d")) - time.time() <= 0):
							raise Exception(u"Cannot sync products: modules file expired")
						
						logger.info(u"Verifying modules file signature")
						publicKey = keys.Key.fromString(data = base64.decodestring('AAAAB3NzaC1yc2EAAAADAQABAAABAQCAD/I79Jd0eKwwfuVwh5B2z+S8aV0C5suItJa18RrYip+d4P0ogzqoCfOoVWtDojY96FDYv+2d73LsoOckHCnuh55GA0mtuVMWdXNZIE8Avt/RzbEoYGo/H0weuga7I8PuQNC/nyS8w3W8TH4pt+ZCjZZoX8S+IizWCYwfqYoYTMLgB0i+6TCAfJj3mNgCrDZkQ24+rOFS4a8RrjamEz/b81noWl9IntllK1hySkR+LbulfTGALHgHkDUlk0OSu+zBPw/hcDSOMiDQvvHfmR4quGyLPbQ2FOVm1TzE0bQPR+Bhx4V8Eo2kNYstG2eJELrz7J1TJI0rCjpB+FQjYPsP')).keyObject
						data = u''
						mks = modules.keys()
						mks.sort()
						for module in mks:
							if module in ('valid', 'signature'):
								continue
							val = modules[module]
							if (val == False): val = 'no'
							if (val == True):  val = 'yes'
							data += u'%s = %s\r\n' % (module.lower().strip(), val)
						if not bool(publicKey.verify(md5(data).digest(), [ long(modules['signature']) ])):
							raise Exception(u"Cannot sync products: modules file invalid")
						logger.notice(u"Modules file signature verified (customer: %s)" % modules.get('customer'))
						
						logger.info(u"Synchronizing %d product(s):" % len(self._productIds))
						for productId in self._productIds:
							logger.info("   %s" % productId)
						
						overallProgressSubject = ProgressSubject(id = 'sync_products_overall', type = 'product_sync', end = len(self._productIds))
						overallProgressSubject.setMessage( _(u'Synchronizing products') )
						if self._overallProductSyncProgressObserver:
							overallProgressSubject.attachObserver(self._overallProductSyncProgressObserver)
						
						productCacheDirSize = 0
						if (self._productCacheMaxSize > 0):
							productCacheDirSize = System.getDirectorySize(self._productCacheDir)
						diskFreeSpace = System.getDiskSpaceUsage(self._productCacheDir)['available']
						
						errorsOccured = []
						for productId in self._productIds:
							logger.notice(u"Syncing files of product '%s'" % productId)
							self._state['product'][productId]['sync_started']   = time.time()
							self._state['product'][productId]['sync_completed'] = ''
							self._state['product'][productId]['sync_failure']   = ''
							
							# TODO: choose depot / url
							# self._opsiclientd.getConfigValue('depot_server', 'url')
							depotUrl = u'webdavs://%s:4447/opsi-depot' % self._opsiclientd.getConfigValue('depot_server', 'depot_id')
							repository = getRepository(
									url          = depotUrl,
									username     = self._opsiclientd.getConfigValue('global', 'host_id'),
									password     = self._opsiclientd.getConfigValue('global', 'opsi_host_key')
							)
							
							#self.writeStateFile()
							try:
								logger.info(u"Downloading package content file of product '%s' from depot '%s'" % (productId, depotUrl))
								tempPackageContentFile = os.path.join(self._tempDir, u'%s.files' % productId)
								repository.download(source = u'%s/%s.files' % (productId, productId), destination = tempPackageContentFile)
								
								packageContentFile = os.path.join(self._productCacheDir, productId, u'%s.files' % productId)
								if os.path.exists(packageContentFile) and (md5sum(tempPackageContentFile) == md5sum(packageContentFile)):
									logger.info(u"Package content file unchanged, assuming that product is up to date")
									self._state['product'][productId]['sync_completed'] = time.time()
									overallProgressSubject.addToState(1)
									continue
								
								packageInfo = PackageContentFile(tempPackageContentFile).parse()
								productSize = 0
								fileCount = 0
								for value in packageInfo.values():
									if value.has_key('size'):
										fileCount += 1
										productSize += int(value['size'])
								
								logger.info(u"Product '%s' contains %d files with a total size of %0.3f MB" \
									% ( productId, fileCount, (float(productSize)/(1024*1024)) ) )
								
								if (self._productCacheMaxSize > 0) and (productCacheDirSize + productSize > self._productCacheMaxSize):
									logger.info(u"Product cache dir sizelimit of %0.3f MB exceeded. Current size: %0.3f MB, space needed for product '%s': %0.3f MB" \
											% ( (float(self._productCacheMaxSize)/(1024*1024)), (float(productCacheDirSize)/(1024*1024)), \
											    productId, (float(productSize)/(1024*1024)) ) )
									self.freeProductCacheSpace(neededSpace = productSize, neededProducts = self._productIds)
									productCacheDirSize = System.getDirectorySize(self._productCacheDir)
								
								if (diskFreeSpace < productSize + 500*1024*1024):
									raise Exception(u"Only %0.3f MB free space available on disk, refusing to cache product files" \
												% (float(diskFreeSpace)/(1024*1024)))
								
								productSynchronizer = DepotToLocalDirectorySychronizer(
									sourceDepot          = repository,
									destinationDirectory = self._productCacheDir,
									productIds           = [ productId ],
									maxBandwidth         = 0,
									dynamicBandwidth     = False
								)
								productSynchronizer.synchronize(productProgressObserver = self._currentProductSyncProgressObserver)
								self._state['product'][productId]['sync_completed'] = time.time()
								logger.notice(u"Product '%s' synced" % productId)
								productCacheDirSize += productSize
								diskFreeSpace -= productSize
							except Exception, e:
								logger.error("Failed to sync product '%s': %s" % (productId, forceUnicode(e)))
								errorsOccured.append( u'%s: %s' % (productId, forceUnicode(e)) )
								self._state['product'][productId]['sync_failure'] = forceUnicode(e)
							#self.writeStateFile()
							overallProgressSubject.addToState(1)
						
						if self._overallProductSyncProgressObserver:
							overallProgressSubject.detachObserver(self._overallProductSyncProgressObserver)
						
						#for productId in self._productIds:
						#	if self._state['product'][productId]['sync_failed']:
						#		raise Exception(self._state['product'][productId]['sync_failed'])
						
						if errorsOccured:
							logger.error(u"Errors occured while caching products %s: %s" % (', '.join(self._productIds), ', '.join(errorsOccured)))
						else:
							logger.notice(u"All products cached: %s" % ', '.join(self._productIds))
						for eventGenerator in self.getEventGenerators(generatorClass = ProductSyncCompletedEventGenerator):
							eventGenerator.fireEvent()
						
					except Exception, e:
						logger.logException(e)
						logger.error(u"Failed to cache products: %s" % forceUnicode(e))
					
					#self.writeStateFile()
					self._cacheProductsRunning = False
					self._cacheProductsEnded.set()
			
			except Exception, e:
				logger.logException(e)
			time.sleep(3)
			
		self._running = False
		
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                              CACHED CONFIG SERVICE RESOURCE JSON RPC                              -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class CacheServiceResourceJsonRpc(resource.Resource):
	def __init__(self, opsiclientd):
		logger.setLogFormat(u'[%l] [%D] [cached cfg server]   %M     (%F|%N)', object=self)
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
# -                               CACHED CONFIG SERVICE JSON RPC WORKER                               -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class CacheServiceJsonRpcWorker(Worker):
	def __init__(self, request, opsiclientd, resource):
		Worker.__init__(self, request, opsiclientd, resource)
		logger.setLogFormat(u'[%l] [%D] [cached cfg server]   %M     (%F|%N)', object=self)
	
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
# -                                           CONTROL SERVER                                          -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ControlServer(threading.Thread):
	def __init__(self, opsiclientd, httpsPort, sslServerKeyFile, sslServerCertFile, staticDir=None):
		logger.setLogFormat(u'[%l] [%D] [control server]   %M     (%F|%N)', object=self)
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









'''
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
=                                             OPSICLIENTD                                             =
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
=                                                                                                     =
=              These classes are used to create the main opsiclientd service / daemon                 =
=                                                                                                     =
=                                                                                                     =
= = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
'''
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                     SERVICE CONNECTION THREAD                                     -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class ServiceConnectionThread(KillableThread):
	def __init__(self, configServiceUrl, username, password, statusObject):
		logger.setLogFormat(u'[%l] [%D] [service connection]   %M     (%F|%N)', object=self)
		KillableThread.__init__(self)
		self._configServiceUrl = configServiceUrl
		self._username = username
		self._password = password
		self._statusSubject = statusObject
		self.configService = None
		self.running = False
		self.connected = False
		self.cancelled = False
		if not self._configServiceUrl:
			raise Exception(u"No config service url given")
	
	def setStatusMessage(self, message):
		self._statusSubject.setMessage(message)
	
	def getUsername(self):
		return self._username
	
	def run(self):
		try:
			logger.debug(u"ServiceConnectionThread started...")
			self.running = True
			self.connected = False
			self.cancelled = False
			
			tryNum = 0
			while not self.cancelled and not self.connected:
				try:
					tryNum += 1
					logger.notice(u"Connecting to config server '%s' #%d" % (self._configServiceUrl, tryNum))
					self.setStatusMessage( _(u"Connecting to config server '%s' #%d") % (self._configServiceUrl, tryNum))
					if (len(self._username.split('.')) < 3):
						logger.notice(u"Domain missing in username %s, fetching domain from service" % self._username)
						configService = JSONRPCBackend(address = self._configServiceUrl, username = u'', password = u'')
						domain = configService.getDomain()
						self._username += '.' + domain
						logger.notice(u"Got domain '%s' from service, username expanded to '%s'" % (domain, self._username))
					self.configService = JSONRPCBackend(address = self._configServiceUrl, username = self._username, password = self._password)
					self.configService.authenticated()
					self.connected = True
					self.setStatusMessage(u"Connected to config server '%s'" % self._configServiceUrl)
					logger.notice(u"Connected to config server '%s'" % self._configServiceUrl)
				except Exception, e:
					self.setStatusMessage("Failed to connect to config server '%s': %s" % (self._configServiceUrl, forceUnicode(e)))
					logger.error(u"Failed to connect to config server '%s': %s" % (self._configServiceUrl, forceUnicode(e)))
					fqdn = System.getFQDN().lower()
					if (self._username != fqdn) and (fqdn.count('.') >= 2):
						logger.notice(u"Connect failed with username '%s', got fqdn '%s' from os, trying fqdn" \
								% (self._username, fqdn))
						self._username = fqdn
					time.sleep(1)
					time.sleep(1)
					time.sleep(1)
			
		except Exception, e:
			logger.logException(e)
		self.running = False
	
	def stopConnectionCallback(self, choiceSubject):
		logger.notice(u"Connection cancelled by user")
		self.stop()
	
	def stop(self):
		logger.debug(u"Stopping thread")
		self.cancelled = True
		self.running = False
		for i in range(10):
			if not self.isAlive():
				break
			self.terminate()
			time.sleep(0.5)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                      EVENT PROCESSING THREAD                                      -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class EventProcessingThread(KillableThread):
	def __init__(self, opsiclientd, event):
		logger.setLogFormat(u'[%l] [%D] [event processing ' + event.eventConfig.getName() + ']   %M     (%F|%N)', object=self)
		KillableThread.__init__(self)
		
		self.opsiclientd = opsiclientd
		self.event = event
		
		self.running = False
		self.eventCancelled = False
		self.waiting = False
		self.waitCancelled = False
		
		self._sessionId = None
		
		self._configService = None
		self._configServiceException = None
		
		self._notificationServer = None
		
		self._notifierApplicationPid = {}
		self._depotShareMounted = False
		
		self._statusSubject = MessageSubject('status')
		self._eventSubject = MessageSubject('event')
		self._serviceUrlSubject = MessageSubject('configServiceUrl')
		self._clientIdSubject = MessageSubject('clientId')
		self._actionProcessorInfoSubject = MessageSubject('actionProcessorInfo')
		self._opsiclientdInfoSubject = MessageSubject('opsiclientdInfo')
		self._detailSubjectProxy = MessageSubjectProxy('detail')
		self._currentProgressSubjectProxy = ProgressSubjectProxy('currentProgress')
		self._overallProgressSubjectProxy = ProgressSubjectProxy('overallProgress')
		
		self._statusSubject.setMessage( _("Processing event %s") % self.event.eventConfig.getName() )
		self._serviceUrlSubject.setMessage(self.opsiclientd.getConfigValue('config_service', 'url'))
		self._clientIdSubject.setMessage(self.opsiclientd.getConfigValue('global', 'host_id'))
		self._opsiclientdInfoSubject.setMessage("opsiclientd %s" % __version__)
		self._actionProcessorInfoSubject.setMessage("")
		
		
		#self.isLoginEvent = isinstance(self.event, UserLoginEvent)
		self.isLoginEvent = bool(self.event.eventConfig.actionType == 'login')
		if self.isLoginEvent:
			logger.info(u"Event is user login event")
		
		self.getSessionId()
		
		self._notificationServerPort = int(self.opsiclientd.getConfigValue('notification_server', 'start_port')) + int(self.getSessionId())
		
	def setSessionId(self, sessionId):
		self._sessionId = int(sessionId)
		logger.info(u"Session id set to %s" % self._sessionId)
		
	def getSessionId(self):
		logger.debug(u"getSessionId()")
		if self._sessionId is None:
			sessionId = None
			if self.isLoginEvent:
				logger.info(u"Using session id of user '%s'" % self.event.eventInfo["User"])
				#timeout = 30
				#while True:
				#	if (win32serviceutil.QueryServiceStatus("TermService")[1] == 4):
				#		break
				#	logger.debug(u"TermService not running, waiting...")
				#	if (timeout <= 0):
				#		raise Exception(u"Timed out while waiting for TermService")
				#	timeout -= 1
				userSessionsIds = System.getUserSessionIds(self.event.eventInfo["User"])
				if userSessionsIds:
					sessionId = userSessionsIds[0]
			if not sessionId:
				logger.info(u"Using active console session id")
				sessionId = System.getActiveConsoleSessionId()
			self.setSessionId(sessionId)
		return self._sessionId
		
	def setStatusMessage(self, message):
		self._statusSubject.setMessage(message)
		
	def startNotificationServer(self):
		logger.notice(u"Starting notification server on port %s" % self._notificationServerPort)
		try:
			self._notificationServer = NotificationServer(
							address  = self.opsiclientd.getConfigValue('notification_server', 'interface'),
							port     = self._notificationServerPort,
							subjects = [
								self._statusSubject,
								self._eventSubject,
								self._serviceUrlSubject,
								self._clientIdSubject,
								self._actionProcessorInfoSubject,
								self._opsiclientdInfoSubject,
								self._detailSubjectProxy,
								self._currentProgressSubjectProxy,
								self._overallProgressSubjectProxy ] )
			#logger.setLogFormat('[%l] [%D] [notification server]   %M     (%F|%N)', object=self._notificationServer)
			#logger.setLogFormat('[%l] [%D] [notification server]   %M     (%F|%N)', object=self._notificationServer.getObserver())
			self._notificationServer.start()
			logger.notice(u"Notification server started")
		except Exception, e:
			logger.error(u"Failed to start notification server: %s" % forceUnicode(e))
			raise
		
	def connectConfigServer(self):
		if self._configService:
			# Already connected
			return
		
		if self._configServiceException:
			# Exception will be cleared on disconnect
			raise Exception(u"Connect failed, will not retry")
		
		try:
			choiceSubject = ChoiceSubject(id = 'choice')
			choiceSubject.setChoices([ 'Stop connection' ])
			
			logger.debug(u"Creating ServiceConnectionThread")
			serviceConnectionThread = ServiceConnectionThread(
						configServiceUrl    = self.opsiclientd.getConfigValue('config_service', 'url'),
						username            = self.opsiclientd.getConfigValue('global', 'host_id'),
						password            = self.opsiclientd.getConfigValue('global', 'opsi_host_key'),
						statusObject        = self._statusSubject )
			
			choiceSubject.setCallbacks( [ serviceConnectionThread.stopConnectionCallback ] )
			
			cancellableAfter = forceInt(self.opsiclientd.getConfigValue('config_service', 'user_cancellable_after'))
			logger.info(u"User is allowed to cancel connection after %d seconds" % cancellableAfter)
			if (cancellableAfter < 1):
				self._notificationServer.addSubject(choiceSubject)
			
			timeout = forceInt(self.opsiclientd.getConfigValue('config_service', 'connection_timeout'))
			logger.info(u"Starting ServiceConnectionThread, timeout is %d seconds" % timeout)
			serviceConnectionThread.start()
			time.sleep(1)
			logger.debug(u"ServiceConnectionThread started")
			
			while serviceConnectionThread.running and (timeout > 0):
				logger.debug(u"Waiting for ServiceConnectionThread (timeout: %d, alive: %s, cancellable in: %d) " \
					% (timeout, serviceConnectionThread.isAlive(), cancellableAfter))
				self._detailSubjectProxy.setMessage( _(u'Timeout: %ds') % timeout )
				cancellableAfter -= 1
				if (cancellableAfter == 0):
					self._notificationServer.addSubject(choiceSubject)
				time.sleep(1)
				timeout -= 1
			
			self._detailSubjectProxy.setMessage('')
			self._notificationServer.removeSubject(choiceSubject)
			
			if serviceConnectionThread.cancelled:
				logger.error(u"ServiceConnectionThread canceled by user")
				raise CanceledByUserError(u"Failed to connect to config service '%s': cancelled by user" % \
							self.opsiclientd.getConfigValue('config_service', 'url') )
			elif serviceConnectionThread.running:
				logger.error(u"ServiceConnectionThread timed out after %d seconds" % self.opsiclientd.getConfigValue('config_service', 'connection_timeout'))
				serviceConnectionThread.stop()
				raise Exception(u"Failed to connect to config service '%s': timed out after %d seconds" % \
							(self.opsiclientd.getConfigValue('config_service', 'url'), self.opsiclientd.getConfigValue('config_service', 'connection_timeout')) )
				
			if not serviceConnectionThread.connected:
				raise Exception(u"Failed to connect to config service '%s': reason unknown" % self.opsiclientd.getConfigValue('config_service', 'url'))
			
			if (serviceConnectionThread.getUsername() != self.opsiclientd.getConfigValue('global', 'host_id')):
				self.opsiclientd.setConfigValue('global', 'host_id', serviceConnectionThread.getUsername().lower())
				logger.info(u"Updated host_id to '%s'" % self.opsiclientd.getConfigValue('global', 'host_id'))
			self._configService = serviceConnectionThread.configService
			self.opsiclientd.setConfigValue('config_service', 'server_id', self._configService.getServerId(self.opsiclientd.getConfigValue('global', 'host_id')))
			logger.info(u"Updated config_service.host_id to '%s'" % self.opsiclientd.getConfigValue('config_service', 'server_id'))
			
			if self.event.eventConfig.updateConfigFile:
				self.setStatusMessage( _(u"Updating config file") )
				self.opsiclientd.updateConfigFile()
			
		except Exception, e:
			self.disconnectConfigServer()
			self._configServiceException = e
			raise
		
	def disconnectConfigServer(self):
		if self._configService:
			try:
				self._configService.exit()
			except Exception, e:
				logger.error(u"Failed to disconnect config service: %s" % forceUnicode(e))
		self._configService = None
		self._configServiceException = None
	
	def getConfigFromService(self):
		''' Get settings from service '''
		logger.notice(u"Getting config from service")
		try:
			self.setStatusMessage(_(u"Getting config from service"))
			
			self.connectConfigServer()
			
			for (key, value) in self._configService.getNetworkConfig_hash(self.opsiclientd.getConfigValue('global', 'host_id')).items():
				if (key.lower() == 'depotid'):
					depotId = value
					self.opsiclientd.setConfigValue('depot_server', 'depot_id', depotId)
					self.opsiclientd.setConfigValue('depot_server', 'url', self._configService.getDepot_hash(depotId)['depotRemoteUrl'])
				elif (key.lower() == 'depotdrive'):
					self.opsiclientd.setConfigValue('depot_server', 'drive', value)
				else:
					logger.info(u"Unhandled network config key '%s'" % key)
				
			logger.notice(u"Got network config from service")
			
			for (key, value) in self._configService.getGeneralConfig_hash(self.opsiclientd.getConfigValue('global', 'host_id')).items():
				try:
					parts = key.lower().split('.')
					if (len(parts) < 3) or (parts[0] != 'opsiclientd'):
						continue
					
					self.opsiclientd.setConfigValue(section = parts[1], option = parts[2], value = value)
					
				except Exception, e:
					logger.error(u"Failed to process general config key '%s:%s': %s" % (key, value, forceUnicode(e)))
			
			logger.notice(u"Got config from service")
			
			self.setStatusMessage(_(u"Got config from service"))
			logger.debug(u"Config is now:\n %s" % objectToBeautifiedText(self.opsiclientd.getConfig()))
		#except CanceledByUserError, e:
		#	logger.error("Failed to get config from service: %s" % forceUnicode(e))
		#	raise
		#except Exception, e:
		#	logger.error("Failed to get config from service: %s" % forceUnicode(e))
		#	logger.logException(e)
		except Exception, e:
			logger.error(u"Failed to get config from service: %s" % forceUnicode(e))
			raise
		
	def writeLogToService(self):
		logger.notice(u"Writing log to service")
		try:
			if not self._configService:
				raise Exception(u"Not connected to config service")
			self.setStatusMessage( _(u"Writing log to service") )
			f = codecs.open(self.opsiclientd.getConfigValue('global', 'log_file'), 'r', 'utf-8', 'replace')
			data = f.read()
			data += u"-------------------- submitted part of log file ends here, see the rest of log file on client --------------------\n"
			f.close()
			# Do not log jsonrpc request
			logger.setFileLevel(LOG_WARNING)
			self._configService.writeLog('clientconnect', data.replace(u'\ufffd', u'?'), self.opsiclientd.getConfigValue('global', 'host_id'))
			#self._configService.writeLog('clientconnect', data.replace(u'\ufffd', u'?').encode('utf-8'), self.opsiclientd.getConfigValue('global', 'host_id'))
		finally:
			logger.setFileLevel(self.opsiclientd.getConfigValue('global', 'log_level'))
		
	def runCommandInSession(self, command, desktop=None, waitForProcessEnding=False, timeoutSeconds=0):
		
		sessionId = self.getSessionId()
		
		if not desktop or desktop.lower() not in (u'winlogon', u'default'):
			if self.isLoginEvent:
				desktop = u'default'
			else:
				logger.debug(u"Getting current active desktop name")
				desktop = self.opsiclientd.getCurrentActiveDesktopName(sessionId)
				logger.debug(u"Got current active desktop name: %s" % desktop)
				
		if not desktop or desktop.lower() not in (u'winlogon', u'default'):
			desktop = u'winlogon'
		
		processId = None
		while True:
			try:
				logger.info("Running command %s in session '%s' on desktop '%s'" % (command, sessionId, desktop))
				processId = System.runCommandInSession(
						command              = command,
						sessionId            = sessionId,
						desktop              = desktop,
						waitForProcessEnding = waitForProcessEnding,
						timeoutSeconds       = timeoutSeconds)[2]
				break
			except Exception, e:
				logger.error(e)
				if (e[0] == 233) and (sys.getwindowsversion()[0] == 5) and (sessionId != 0):
					# No process is on the other end
					# Problem with pipe \\\\.\\Pipe\\TerminalServer\\SystemExecSrvr\\<sessionid>
					# After logging off from a session other than 0 csrss.exe does not create this pipe or CreateRemoteProcessW is not able to read the pipe.
					logger.info(u"Retrying to run command on winlogon desktop of session 0")
					sessionId = 0
					desktop = 'winlogon'
				else:
					raise
		
		self.setSessionId(sessionId)
		return processId
	
	def startNotifierApplication(self, notifierType, command, desktop=None):
		logger.notice(u"Starting notifier application type '%s' in session '%s'" % (notifierType, self.getSessionId()))
		self._notifierApplicationPid[notifierType] = self.runCommandInSession(command = command.replace('%port%', unicode(self._notificationServerPort)), waitForProcessEnding = False)
		time.sleep(3)
		
	def stopNotifierApplication(self, notifierType):
		if not self._notifierApplicationPid.get(notifierType):
			logger.info(u"Failed to stop notifier application type '%s': not started" % notifierType)
			return
		
		logger.notice(u"Stopping notifier application (pid %s)" % self._notifierApplicationPid[notifierType])
		try:
			try:
				# Does not work in all cases
				self.closeProcessWindows(self._notifierApplicationPid[notifierType])
			except:
				pass
			time.sleep(2)
			System.terminateProcess(processId = self._notifierApplicationPid[notifierType])
		except Exception, e:
			logger.warning(u"Failed to stop notifier application: %s" % forceUnicode(e))
	
	def closeProcessWindows(self, processId):
		command = None
		try:
			command = '%s "exit(); System.closeProcessWindows(processId = %s)"' \
					% (self.opsiclientd.getConfigValue('opsiclientd_rpc', 'command'), processId)
		except Exception, e:
			raise Exception(u"opsiclientd_rpc command not defined: %s" % forceUnicode(e))
		
		self.runCommandInSession(command = cmd, waitForProcessEnding = False)
		
	def setActionProcessorInfo(self):
		try:
			actionProcessorFilename = self.opsiclientd.getConfigValue('action_processor', 'filename')
			actionProcessorLocalDir = self.opsiclientd.getConfigValue('action_processor', 'local_dir')
			actionProcessorLocalFile = os.path.join(actionProcessorLocalDir, actionProcessorFilename)
			actionProcessorLocalFile = actionProcessorLocalFile
			info = System.getFileVersionInfo(actionProcessorLocalFile)
			version = info.get('FileVersion', u'')
			name = info.get('ProductName', u'')
			logger.info(u"Action processor name '%s', version '%s'" % (name, version))
			self._actionProcessorInfoSubject.setMessage("%s %s" % (name.encode('utf-8'), version.encode('utf-8')))
		except Exception, e:
			logger.error(u"Failed to set action processor info: %s" % forceUnicode(e))
	
	def getDepotserverCredentials(self):
		self.connectConfigServer()
		depotServerUsername = self.opsiclientd.getConfigValue('depot_server', 'username')
		encryptedDepotServerPassword = self._configService.getPcpatchPassword(self.opsiclientd.getConfigValue('global', 'host_id'))
		depotServerPassword = blowfishDecrypt(self.opsiclientd.getConfigValue('global', 'opsi_host_key'), encryptedDepotServerPassword)
		logger.addConfidentialString(depotServerPassword)
		return (depotServerUsername, depotServerPassword)
		
	def mountDepotShare(self, impersonation):
		if self._depotShareMounted:
			logger.debug(u"Depot share already mounted")
			return
		
		logger.notice(u"Mounting depot share %s" %  self.opsiclientd.getConfigValue('depot_server', 'url'))
		self.setStatusMessage(_(u"Mounting depot share %s") % self.opsiclientd.getConfigValue('depot_server', 'url'))
		
		if impersonation:
			System.mount(self.opsiclientd.getConfigValue('depot_server', 'url'), self.opsiclientd.getConfigValue('depot_server', 'drive'))
		else:
			(depotServerUsername, depotServerPassword) = self.getDepotserverCredentials()
			System.mount(self.opsiclientd.getConfigValue('depot_server', 'url'), self.opsiclientd.getConfigValue('depot_server', 'drive'), username = depotServerUsername, password = depotServerPassword)
		self._depotShareMounted = True
		
	def umountDepotShare(self):
		if not self._depotShareMounted:
			logger.debug(u"Depot share not mounted")
			return
		try:
			logger.notice(u"Unmounting depot share")
			System.umount(self.opsiclientd.getConfigValue('depot_server', 'drive'))
			self._depotShareMounted = False
		except Exception, e:
			logger.warning(e)
		
	def updateActionProcessor(self):
		logger.notice(u"Updating action processor")
		self.setStatusMessage(_(u"Updating action processor"))
		
		impersonation = None
		try:
			# This logon type allows the caller to clone its current token and specify new credentials for outbound connections.
			# The new logon session has the same local identifier but uses different credentials for other network connections.
			(depotServerUsername, depotServerPassword) = self.getDepotserverCredentials()
			impersonation = System.Impersonate(username = depotServerUsername, password = depotServerPassword)
			impersonation.start(logonType = 'NEW_CREDENTIALS')
			
			self.mountDepotShare(impersonation)
			
			actionProcessorFilename = self.opsiclientd.getConfigValue('action_processor', 'filename')
			actionProcessorLocalDir = self.opsiclientd.getConfigValue('action_processor', 'local_dir')
			actionProcessorLocalTmpDir = actionProcessorLocalDir + '.tmp'
			actionProcessorLocalFile = os.path.join(actionProcessorLocalDir, actionProcessorFilename)
			actionProcessorLocalTmpFile = os.path.join(actionProcessorLocalTmpDir, actionProcessorFilename)
			
			actionProcessorRemoteDir = os.path.join(
							self.opsiclientd.getConfigValue('depot_server', 'drive'),
							self.opsiclientd.getConfigValue('action_processor', 'remote_dir'))
			actionProcessorRemoteFile = os.path.join(actionProcessorRemoteDir, actionProcessorFilename)
			
			if not os.path.exists(actionProcessorLocalFile):
				logger.notice(u"Action processor needs update because file '%s' not found" % actionProcessorLocalFile)
			elif ( abs(os.stat(actionProcessorLocalFile).st_mtime - os.stat(actionProcessorRemoteFile).st_mtime) > 10 ):
				logger.notice(u"Action processor needs update because modification time difference is more than 10 seconds")
			elif not filecmp.cmp(actionProcessorLocalFile, actionProcessorRemoteFile):
				logger.notice(u"Action processor needs update because file changed")
			else:
				logger.notice("Local action processor exists and seems to be up to date")
				return actionProcessorLocalFile
			
			# Update files
			logger.notice(u"Start copying the action processor files")
			if os.path.exists(actionProcessorLocalTmpDir):
				logger.info(u"Deleting dir '%s'" % actionProcessorLocalTmpDir)
				shutil.rmtree(actionProcessorLocalTmpDir)
			logger.info(u"Copying from '%s' to '%s'" % (actionProcessorRemoteDir, actionProcessorLocalTmpDir))
			shutil.copytree(actionProcessorRemoteDir, actionProcessorLocalTmpDir)
			
			if not os.path.exists(actionProcessorLocalTmpFile):
				raise Exception(u"File '%s' does not exist after copy" % actionProcessorLocalTmpFile)
			
			if os.path.exists(actionProcessorLocalDir):
				logger.info(u"Deleting dir '%s'" % actionProcessorLocalDir)
				shutil.rmtree(actionProcessorLocalDir)
			
			logger.info(u"Moving dir '%s' to '%s'" % (actionProcessorLocalTmpDir, actionProcessorLocalDir))
			shutil.move(actionProcessorLocalTmpDir, actionProcessorLocalDir)
			
			logger.notice(u'Local action processor successfully updated')
			
			self._configService.setProductInstallationStatus(
							'opsi-winst',
							self.opsiclientd.getConfigValue('global', 'host_id'),
							'installed')
			
			self.setActionProcessorInfo()
			
			self.umountDepotShare()
			
		except Exception, e:
			logger.error(u"Failed to update action processor: %s" % forceUnicode(e))
		
		if impersonation:
			try:
				impersonation.end()
			except Exception, e:
				logger.warning(e)
	
	def processUserLoginActions(self):
		self.setStatusMessage(_(u"Processing login actions"))
		
		impersonation = None
		try:
			# This logon type allows the caller to clone its current token and specify new credentials for outbound connections.
			# The new logon session has the same local identifier but uses different credentials for other network connections.
			(depotServerUsername, depotServerPassword) = self.getDepotserverCredentials()
			impersonation = System.Impersonate(username = depotServerUsername, password = depotServerPassword)
			impersonation.start(logonType = 'NEW_CREDENTIALS')
			
			self.mountDepotShare(impersonation)
			
			userScripts = []
			productDir = os.path.join(self.opsiclientd.getConfigValue('depot_server', 'drive'), 'install')
			for entry in os.listdir(productDir):
				if not os.path.isdir( os.path.join(productDir, entry) ):
					continue
				userScript = os.path.join(productDir, entry, 'userscript.ins')
				if not os.path.isfile(userScript):
					continue
				logger.info(u"User script found: %s" % userScript)
				userScripts.append(userScript)
			
			self.umountDepotShare()
			
			if userScripts:
				logger.notice(u"User scripts found, executing")
				additionalParams = ''
				for userScript in userScripts:
					additionalParams += ' "%s"' % userScript
				self.runActions(additionalParams)
			else:
				logger.notice(u"No user script found, nothing to do")
			
		except Exception, e:
			logger.logException(e)
			logger.error(u"Failed to process login actions: %s" % forceUnicode(e))
			self.setStatusMessage( _(u"Failed to process login actions: %s") % forceUnicode(e) )
		
		if impersonation:
			try:
				impersonation.end()
			except Exception, e:
				logger.warning(e)
		
	def processProductActionRequests(self):
		self.setStatusMessage(_(u"Getting action requests from config service"))
		
		try:
			bootmode = ''
			try:
				bootmode = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\general", "bootmode")
			except Exception, e:
				logger.warning(u"Failed to get bootmode from registry: %s" % forceUnicode(e))
			
			self.connectConfigServer()
			productStates = []
			if (self._configService.getLocalBootProductStates_hash.func_code.co_argcount == 2):
				if self.event.eventConfig.serviceOptions:
					logger.warning(u"Service cannot handle service options in method getLocalBootProductStates_hash")
				productStates = self._configService.getLocalBootProductStates_hash(self.opsiclientd.getConfigValue('global', 'host_id'))
				productStates = productStates.get(self.opsiclientd.getConfigValue('global', 'host_id'), [])
			else:
				productStates = self._configService.getLocalBootProductStates_hash(
							self.opsiclientd.getConfigValue('global', 'host_id'),
							self.event.eventConfig.serviceOptions )
				productStates = productStates.get(self.opsiclientd.getConfigValue('global', 'host_id'), [])
			
			logger.notice(u"Got product action requests from configservice")
			productIds = []
			for productState in productStates:
				if (productState['actionRequest'] not in ('none', 'undefined')):
					productIds.append(productState['productId'])
					logger.notice("   [%2s] product %-20s %s" % (len(productIds), productState['productId'] + ':', productState['actionRequest']))
			
			if (len(productIds) == 0) and (bootmode == 'BKSTD'):
				logger.notice(u"No product action requests set")
				self.setStatusMessage( _(u"No product action requests set") )
			
			else:
				logger.notice(u"Start processing action requests")
				
				#if not self.event.eventConfig.useCachedConfig and self.event.eventConfig.syncConfig:
				#	logger.notice(u"Syncing config (products: %s)" % productIds)
				#	self._cacheService.init()
				#	self.setStatusMessage( _(u"Syncing config") )
				#	self._cacheService.setCurrentConfigProgressObserver(self._currentProgressSubjectProxy)
				#	self._cacheService.setOverallConfigProgressObserver(self._overallProgressSubjectProxy)
				#	self._cacheService.syncConfig(productIds = productIds, waitForEnding = True)
				#	self.setStatusMessage( _(u"Config synced") )
				#	self._currentProgressSubjectProxy.setState(0)
				#	self._overallProgressSubjectProxy.setState(0)
				
				if self.event.eventConfig.cacheProducts:
					logger.notice(u"Caching products: %s" % productIds)
					self.setStatusMessage( _(u"Caching products") )
					self.opsiclientd._cacheService.setCurrentProductSyncProgressObserver(self._currentProgressSubjectProxy)
					self.opsiclientd._cacheService.setOverallProductSyncProgressObserver(self._overallProgressSubjectProxy)
					self._currentProgressSubjectProxy.attachObserver(self._detailSubjectProxy)
					try:
						self.opsiclientd._cacheService.cacheProducts(
							self._configService,
							productIds,
							waitForEnding = self.event.eventConfig.requiresCachedProducts)
						self.setStatusMessage( _(u"Products cached") )
					finally:
						self._detailSubjectProxy.setMessage(u"")
						self._currentProgressSubjectProxy.detachObserver(self._detailSubjectProxy)
						self._currentProgressSubjectProxy.reset()
						self._overallProgressSubjectProxy.reset()
				
				savedDepotUrl = None
				savedDepotDrive = None
				if self.event.eventConfig.requiresCachedProducts:
					# Event needs cached products => initialize cache service
					if self.opsiclientd._cacheService.getProductSyncCompleted():
						logger.notice(u"Event '%s' requires cached products and product sync is done" % self.event.eventConfig.getName())
						savedDepotUrl = self.opsiclientd.getConfigValue('depot_server', 'url')
						savedDepotDrive = self.opsiclientd.getConfigValue('depot_server', 'drive')
						cacheDepotDir = self.opsiclientd._cacheService.getProductCacheDir().replace('\\', '/').replace('//', '/')
						cacheDepotDrive = cacheDepotDir.split('/')[0]
						cacheDepotUrl = 'smb://localhost/noshare/' + ('/'.join(cacheDepotDir.split('/')[1:]))
						self.opsiclientd.setConfigValue('depot_server', 'url', cacheDepotUrl)
						self.opsiclientd.setConfigValue('depot_server', 'drive', cacheDepotDrive)
					else:
						raise Exception(u"Event '%s' requires cached products but product sync is not done, exiting" % self.event.eventConfig.getName())
				
				try:
					self.runActions()
				finally:
					if savedDepotUrl:
						self.opsiclientd.setConfigValue('depot_server', 'url', savedDepotUrl)
					if savedDepotDrive:
						self.opsiclientd.setConfigValue('depot_server', 'drive', savedDepotDrive)
				
		except Exception, e:
			logger.logException(e)
			logger.error(u"Failed to process product action requests: %s" % forceUnicode(e))
			self.setStatusMessage( _(u"Failed to process product action requests: %s") % forceUnicode(e) )
		
		time.sleep(3)
	
	def runActions(self, additionalParams=''):
		if not additionalParams:
			additionalParams = ''
		if not self.event.getActionProcessorCommand():
			raise Exception(u"No action processor command defined")
		
		# Before Running Action Processor check for Trusted Installer
		if (os.name == 'nt') and (sys.getwindowsversion()[0] == 6):
			logger.debug(u"Try to read TrustedInstaller service-configuration")
			try:
				# Trusted Installer "Start" Key in Registry: 2 = automatic Start: Registry: 3 = manuell Start; Default: 3
				automaticStartup = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SYSTEM\\CurrentControlSet\\services\\TrustedInstaller", "Start", reflection = False)
				if (automaticStartup == 2):
					logger.notice(u"Automatic startup for service Trusted Installer is set, waiting until upgrade process is finished")
					self.setStatusMessage( _(u"Waiting for trusted installer") )
					while True:
						time.sleep(3)
						logger.debug(u"Checking if automatic startup for service Trusted Installer is set")
						automaticStartup = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SYSTEM\\CurrentControlSet\\services\\TrustedInstaller", "Start")
						if not (automaticStartup == 2):
							break
			except Exception, e:
				logger.error(u"Failed to read TrustedInstaller service-configuration: %s" % e)
		
		self.setStatusMessage( _(u"Starting actions") )
		
		# Setting some registry values before starting action
		# Mainly for action processor winst
		System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "depoturl",   self.opsiclientd.getConfigValue('depot_server', 'url'))
		System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "depotdrive", self.opsiclientd.getConfigValue('depot_server', 'drive'))
		System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "configurl",   "<deprecated>")
		System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "configdrive", "<deprecated>")
		System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "utilsurl",    "<deprecated>")
		System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "utilsdrive",  "<deprecated>")
		
		# action processor desktop can be one of current / winlogon / default
		desktop = self.event.eventConfig.actionProcessorDesktop
		
		# Choose desktop for action processor
		if not desktop or desktop.lower() not in ('winlogon', 'default'):
			if self.isLoginEvent:
				desktop = 'default'
			else:
				desktop = self.opsiclientd.getCurrentActiveDesktopName(self.getSessionId())
		
		if not desktop or desktop.lower() not in ('winlogon', 'default'):
			# Default desktop is winlogon
			desktop = 'winlogon'
		
		
		depotServerUsername = self.opsiclientd.getConfigValue('depot_server', 'username')
		encryptedDepotServerPassword = self._configService.getPcpatchPassword(self.opsiclientd.getConfigValue('global', 'host_id'))
		depotServerPassword = blowfishDecrypt(self.opsiclientd.getConfigValue('global', 'opsi_host_key'), encryptedDepotServerPassword)
		logger.addConfidentialString(depotServerPassword)
		
		# Update action processor
		if self.opsiclientd.getConfigValue('depot_server', 'url').split('/')[2] not in ('127.0.0.1', 'localhost') and self.event.eventConfig.updateActionProcessor:
			self.updateActionProcessor()
		
		# Run action processor
		actionProcessorCommand = self.opsiclientd.fillPlaceholders(self.event.getActionProcessorCommand())
		actionProcessorCommand += additionalParams
		actionProcessorCommand = actionProcessorCommand.replace('"', '\\"')
		command = u'%system.program_files_dir%\\opsi.org\\preloginloader\\action_processor_starter.exe ' \
			+ u'"%global.host_id%" "%global.opsi_host_key%" "%control_server.port%" ' \
			+ u'"%global.log_file%" "%global.log_level%" ' \
			+ u'"%depot_server.url%" "%depot_server.drive%" ' \
			+ u'"' + depotServerUsername + u'" "' + depotServerPassword + '" ' \
			+ u'"' + unicode(self.getSessionId()) + u'" "' + desktop + '" ' \
			+ u'"' + actionProcessorCommand + u'" ' + unicode(self.event.eventConfig.actionProcessorTimeout) + ' ' \
			+ u'"' + self.opsiclientd._actionProcessorUserName + u'" "' + self.opsiclientd._actionProcessorUserPassword + u'"'
		command = self.opsiclientd.fillPlaceholders(command)
		
		if self.event.eventConfig.preActionProcessorCommand:
			impersonation = None
			try:
				if self.opsiclientd._actionProcessorUserName:
					impersonation = System.Impersonate(username = self.opsiclientd._actionProcessorUserName, password = self.opsiclientd._actionProcessorUserPassword)
					impersonation.start(logonType = 'INTERACTIVE', newDesktop = True)
					
				logger.notice(u"Starting pre action processor command '%s' in session '%s' on desktop '%s'" \
					% (self.event.eventConfig.preActionProcessorCommand, self.getSessionId(), desktop))
				if impersonation:
					impersonation.runCommand(command = self.event.eventConfig.preActionProcessorCommand, desktop = desktop, waitForProcessEnding = False)
				else:
					self.runCommandInSession(command = self.event.eventConfig.preActionProcessorCommand, desktop = desktop, waitForProcessEnding = False)
				time.sleep(10)
			finally:
				if impersonation:
					impersonation.end()
				
		logger.notice(u"Starting action processor in session '%s' on desktop '%s'" % (self.getSessionId(), desktop))
		self.runCommandInSession(command = command, desktop = desktop, waitForProcessEnding = True)
		
		if self.event.eventConfig.postActionProcessorCommand:
			impersonation = None
			try:
				if self.opsiclientd._actionProcessorUserName:
					impersonation = System.Impersonate(username = self.opsiclientd._actionProcessorUserName, password = self.opsiclientd._actionProcessorUserPassword)
					impersonation.start(logonType = 'INTERACTIVE', newDesktop = True)
					
				logger.notice(u"Starting post action processor command '%s' in session '%s' on desktop '%s'" \
					% (self.event.eventConfig.postActionProcessorCommand, self.getSessionId(), desktop))
				if impersonation:
					impersonation.runCommand(command = self.event.eventConfig.postActionProcessorCommand, desktop = desktop, waitForProcessEnding = False)
				else:
					self.runCommandInSession(command = self.event.eventConfig.postActionProcessorCommand, desktop = desktop, waitForProcessEnding = False)
				time.sleep(10)
			finally:
				if impersonation:
					impersonation.end()
		
		self.setStatusMessage( _(u"Actions completed") )
		
	def setEnvironment(self):
		try:
			logger.debug(u"Current environment:")
			for (k, v) in os.environ.items():
				logger.debug(u"   %s=%s" % (k,v))
			logger.debug(u"Updating environment")
			hostname = os.environ['COMPUTERNAME']
			(homeDrive, homeDir) = os.environ['USERPROFILE'].split('\\')[0:2]
			# TODO: Anwendungsdaten
			os.environ['APPDATA']     = '%s\\%s\\%s\\Anwendungsdaten' % (homeDrive, homeDir, username)
			os.environ['HOMEDRIVE']   = homeDrive
			os.environ['HOMEPATH']    = '\\%s\\%s' % (homeDir, username)
			os.environ['LOGONSERVER'] = '\\\\%s' % hostname
			os.environ['SESSIONNAME'] = 'Console'
			os.environ['USERDOMAIN']  = '%s' % hostname
			os.environ['USERNAME']    = username
			os.environ['USERPROFILE'] = '%s\\%s\\%s' % (homeDrive, homeDir, username)
			logger.debug(u"Updated environment:")
			for (k, v) in os.environ.items():
				logger.debug(u"   %s=%s" % (k,v))
		except Exception, e:
			logger.error(u"Failed to set environment: %s" % forceUnicode(e))
	
	def run(self):
		try:
			logger.notice(u"============= EventProcessingThread for occurcence of event '%s' started =============" % self.event)
			self.running = True
			self.eventCancelled = False
			self.waiting = False
			self.waitCancelled = False
			
			# Store current config service url and depot url
			configServiceUrl = self.opsiclientd.getConfigValue('config_service', 'url')
			depotServerUrl = self.opsiclientd.getConfigValue('depot_server', 'url')
			depotDrive = self.opsiclientd.getConfigValue('depot_server', 'drive')
			try:
				self.startNotificationServer()
				self.setActionProcessorInfo()
				
				if self.event.eventConfig.useCachedConfig:
					# Event needs cached config => initialize cache service
					if self.opsiclientd._cacheService.getConfigSyncCompleted():
						logger.notice(u"Event '%s' requires cached config and config sync is done" % self.event)
						self.opsiclientd._cacheService.workWithLocalConfig()
						cacheConfigServiceUrl = 'https://127.0.0.1:%s/rpc' % self.opsiclientd.getConfigValue('control_server', 'port')
						logger.notice(u"Setting config service url to cache service url '%s'" % cacheConfigServiceUrl)
						self.opsiclientd.setConfigValue('config_service', 'url', cacheConfigServiceUrl)
					else:
						logger.notice(u"Event '%s' requires cached config but config sync is not done, exiting" % self.event)
						self.running = False
						return
				
				self._eventSubject.setMessage(self.event.eventConfig.message)
				if self.event.eventConfig.warningTime:
					choiceSubject = ChoiceSubject(id = 'choice')
					if self.event.eventConfig.userCancelable:
						choiceSubject.setChoices([ 'Abort', 'Start now' ])
						choiceSubject.setCallbacks( [ self.abortEventCallback, self.startEventCallback ] )
					else:
						choiceSubject.setChoices([ 'Start now' ])
						choiceSubject.setCallbacks( [ self.startEventCallback ] )
					self._notificationServer.addSubject(choiceSubject)
					try:
						if self.event.eventConfig.eventNotifierCommand:
							self.startNotifierApplication(
									notifierType = 'event',
									command      = self.event.eventConfig.eventNotifierCommand,
									desktop      = self.event.eventConfig.eventNotifierDesktop )
							
						timeout = int(self.event.eventConfig.warningTime)
						while(timeout > 0) and not self.eventCancelled and not self.waitCancelled:
							self.waiting = True
							logger.info(u"Notifying user of event %s" % self.event)
							self.setStatusMessage(u"Event %s: processing will start in %d seconds" % (self.event.eventConfig.getName(), timeout))
							timeout -= 1
							time.sleep(1)
						
						if self.eventCancelled:
							raise CanceledByUserError(u"Cancelled by user")
					finally:
						self.waiting = False
						self.stopNotifierApplication(notifierType = 'event')
						self._notificationServer.removeSubject(choiceSubject)
				
				self.setStatusMessage(_(u"Processing event %s") % self.event.eventConfig.getName())
				
				if self.event.eventConfig.blockLogin:
					self.opsiclientd.setBlockLogin(True)
				else:
					self.opsiclientd.setBlockLogin(False)
				if self.event.eventConfig.logoffCurrentUser:
					System.logoffCurrentUser()
					time.sleep(15)
				elif self.event.eventConfig.lockWorkstation:
					System.lockWorkstation()
					time.sleep(15)
				
				if self.event.eventConfig.actionNotifierCommand:
					self.startNotifierApplication(
						notifierType = 'action',
						command      = self.event.eventConfig.actionNotifierCommand,
						desktop      = self.event.eventConfig.actionNotifierDesktop )
				
				if not self.event.eventConfig.useCachedConfig:
					if self.event.eventConfig.getConfigFromService:
						self.getConfigFromService()
					if self.event.eventConfig.updateConfigFile:
						self.opsiclientd.updateConfigFile()
				
				if (self.event.eventConfig.actionType == 'login'):
					self.processUserLoginActions()
				else:
					self.processProductActionRequests()
			
			finally:
				self._eventSubject.setMessage(u"")
				
				if self.event.eventConfig.writeLogToService:
					try:
						self.writeLogToService()
					except Exception, e:
						logger.logException(e)
				
				try:
					# Disconnect has to be called, even if connect failed!
					self.disconnectConfigServer()
				except Exception, e:
					logger.logException(e)
				
				if self.event.eventConfig.processShutdownRequests:
					try:
						self.opsiclientd.processShutdownRequests()
					except Exception, e:
						logger.logException(e)
				
				if self.opsiclientd._shutdownRequested:
					self.setStatusMessage(_("Shutting down machine"))
				elif self.opsiclientd._rebootRequested:
					self.setStatusMessage(_("Rebooting machine"))
				else:
					self.setStatusMessage(_("Unblocking login"))
				
				try:
					self.stopNotifierApplication(notifierType = 'action')
				except Exception, e:
					logger.logException(e)
				
				#if (not self.opsiclientd._rebootRequested and not self.opsiclientd._shutdownRequested) \
				#    or (sys.getwindowsversion()[0] < 6):
				#	# Windows NT < 6 can't shutdown while opsigina.dll is blocking login!
				#	# On other systems we keep blocking
				#	self.opsiclientd.setBlockLogin(False)
				if not self.opsiclientd._rebootRequested and not self.opsiclientd._shutdownRequested:
					self.opsiclientd.setBlockLogin(False)
				
				self.setStatusMessage(u"")
				
				if self.event.eventConfig.useCachedConfig:
					# Set config service url back to previous url
					logger.notice(u"Setting config service url back to '%s'" % configServiceUrl)
					self.opsiclientd.setConfigValue('config_service', 'url', configServiceUrl)
					logger.notice("Setting depot server url back to '%s'" % depotServerUrl)
					self.opsiclientd.setConfigValue('depot_server', 'url', depotServerUrl)
					logger.notice(u"Setting depot drive back to '%s'" % depotDrive)
					self.opsiclientd.setConfigValue('depot_server', 'drive', depotDrive)
				
				# Stop notification server thread
				if self._notificationServer:
					try:
						logger.info(u"Stopping notification server")
						self._notificationServer.stop(stopReactor = False)
					except Exception, e:
						logger.logException(e)
		except Exception, e:
			logger.error(u"Failed to process event %s: %s" % (self.event, forceUnicode(e)))
			logger.logException(e)
			self.opsiclientd.setBlockLogin(False)
		
		self.running = False
		logger.notice(u"============= EventProcessingThread for event '%s' ended =============" % self.event)
		
	def abortEventCallback(self, choiceSubject):
		logger.notice(u"Event aborted by user")
		self.eventCancelled = True
	
	def startEventCallback(self, choiceSubject):
		logger.notice(u"Waiting cancelled by user")
		self.waitCancelled = True
	
	
	#def stop(self):
	#	time.sleep(5)
	#	if self.running and self.isAlive():
	#		logger.debug(u"Terminating thread")
	#		self.terminate()




class OpsiclientdRpcPipeInterface(object):
	def __init__(self, opsiclientd):
		self.opsiclientd = opsiclientd
		logger.setLogFormat(u'[%l] [%D] [opsiclientd]   %M     (%F|%N)', object=self)
	
	def getInterface(self):
		methods = {}
		for member in inspect.getmembers(self, inspect.ismethod):
			methodName = member[0]
			if methodName.startswith('_'):
				# protected / private
				continue
			(args, varargs, keywords, defaults) = inspect.getargspec(member[1])
			params = []
			if args:
				for arg in forceList(args):
					if (arg != 'self'):
						params.append(arg)
			if ( defaults != None and len(defaults) > 0 ):
				offset = len(params) - len(defaults)
				for i in range(len(defaults)):
					params[offset+i] = '*' + params[offset+i]
			
			if varargs:
				for arg in forceList(varargs):
					params.append('*' + arg)
			
			if keywords:
				for arg in forceList(keywords):
					params.append('**' + arg)
			
			logger.debug2(u"Interface method name '%s' params %s" % (methodName, params))
			methods[methodName] = { 'name': methodName, 'params': params, 'args': args, 'varargs': varargs, 'keywords': keywords, 'defaults': defaults}
		
		methodList = []
		methodNames = methods.keys()
		methodNames.sort()
		for methodName in methodNames:
			methodList.append(methods[methodName])
		return methodList
	
	def getPossibleMethods_listOfHashes(self):
		return self.getInterface()
	
	def backend_getInterface(self):
		return self.getInterface()
	
	def backend_info(self):
		return {}
	
	def exit(self):
		return
	
	def backend_exit(self):
		return
	
	def getBlockLogin(self):
		logger.notice(u"rpc getBlockLogin: blockLogin is '%s'" % self.opsiclientd._blockLogin)
		return self.opsiclientd._blockLogin
	
	def isRebootRequested(self):
		return self.opsiclientd._rebootRequested
	
	def isShutdownRequested(self):
		return self.opsiclientd._shutdownRequested
	
	
class OpsiclientdRpcServerInterface(OpsiclientdRpcPipeInterface):
	def __init__(self, opsiclientd):
		OpsiclientdRpcPipeInterface.__init__(self, opsiclientd)
	
	def _authenticate(self, username, password):
		if (username == self.opsiclientd.getConfigValue('global', 'host_id')) and (password == self.opsiclientd.getConfigValue('global', 'opsi_host_key')):
			return True
		if (os.name == 'nt'):
			if (username == 'Administrator'):
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
			f = codecs.open(self.opsiclientd.getConfigValue('global', 'log_file'), 'r', 'utf-8', 'replace')
			data = f.read()
			f.close()
			return data
		return u""
	
	def runCommand(self, command, desktop=None):
		command = forceUnicode(command)
		if not command:
			raise ValueError("No command given")
		if desktop:
			desktop = forceUnicode(desktop)
		else:
			desktop = self.opsiclientd.getCurrentActiveDesktopName()
		logger.notice(u"rpc runCommand: executing command '%s' on desktop '%s'" % (command, desktop))
		System.runCommandInSession(command = command, sessionId = None, desktop = desktop, waitForProcessEnding = False)
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
		if not name in self.opsiclientd._eventGenerators.keys():
			raise ValueError(u"Event '%s' not in list of known events: %s" % (name, ', '.join(self.opsiclientd._eventGenerators.keys())))
		logger.notice(u"Firing event '%s'" % name)
		self.opsiclientd._eventGenerators[name].fireEvent()
		
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
	
	def setConfigValue(self, section, option, value):
		section = forceUnicode(section)
		option = forceUnicode(option)
		value = forceUnicode(value)
		return self.opsiclientd.setConfigValue(section, option, value)
	
	def updateConfigFile(self):
		self.opsiclientd.updateConfigFile()
		
	def showPopup(self, message):
		message = forceUnicode(message)
		self.opsiclientd.showPopup(message)
		
	
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                            OPSICLIENTD                                            -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class Opsiclientd(EventListener, threading.Thread):
	def __init__(self):
		logger.setLogFormat(u'[%l] [%D] [opsiclientd]   %M     (%F|%N)', object=self)
		logger.debug(u"Opsiclient initiating")
		
		EventListener.__init__(self)
		threading.Thread.__init__(self) 
		
		self._startupTime = time.time()
		self._running = False
		self._eventProcessingThreads = []
		self._eventProcessingThreadsLock = threading.Lock()
		self._blockLogin = True
		self._currentActiveDesktopName = {}
		self._eventGenerators = {}
		
		self._actionProcessorUserName = u''
		self._actionProcessorUserPassword = u''
		
		self._statusApplicationProcess = None
		self._blockLoginNotifierPid = None
		
		self._rebootRequested = False
		self._shutdownRequested = False
		
		self._popupNotificationServer = None
		self._popupNotifierPids = {}
		self._popupNotificationLock = threading.Lock()
		
		self._config = {
			'system': {
				'program_files_dir': u'',
			},
			'global': {
				'config_file':                    u'opsiclientd.conf',
				'log_file':                       u'opsiclientd.log',
				'log_level':                      LOG_NOTICE,
				'host_id':                        System.getFQDN().lower(),
				'opsi_host_key':                  u'',
				'wait_for_gui_timeout':           120,
				'wait_for_gui_application':       u'',
				'block_login_notifier':           u'',
			},
			'config_service': {
				'server_id':              u'',
				'url':                    u'',
				'connection_timeout':     10,
				'user_cancellable_after': 0,
			},
			'depot_server': {
				'depot_id': u'',
				'url':      u'',
				'drive':    u'',
				'username': u'pcpatch',
			},
			'cache_service': {
				'storage_dir':            u'c:\\tmp\\cache_service',
				'product_cache_max_size': 6000000000,
				'backend_manager_config': u'',
			},
			'control_server': {
				'interface':            '0.0.0.0', # TODO
				'port':                 4441,
				'ssl_server_key_file':  u'opsiclientd.pem',
				'ssl_server_cert_file': u'opsiclientd.pem',
				'static_dir':           u'static_html',
			},
			'notification_server': {
				'interface':  u'127.0.0.1',
				'start_port': 44000,
				'popup_port': 45000,
			},
			'opsiclientd_notifier': {
				'command': u'',
			},
			'action_processor': {
				'local_dir':   u'',
				'remote_dir':  u'',
				'filename':    u'',
				'command':     u'',
				'run_as_user': u'SYSTEM',
				'create_user': True,
				'delete_user': True,
			}
		}
		
	
	def setBlockLogin(self, blockLogin):
		self._blockLogin = bool(blockLogin)
		logger.notice(u"Block login now set to '%s'" % self._blockLogin)
		
		if (self._blockLogin):
			if not self._blockLoginNotifierPid and self.getConfigValue('global', 'block_login_notifier'):
				logger.info(u"Starting block login notifier app")
				sessionId = System.getActiveConsoleSessionId()
				while True:
					try:
						self._blockLoginNotifierPid = System.runCommandInSession(
								command = self.getConfigValue('global', 'block_login_notifier'),
								sessionId = sessionId,
								desktop = 'winlogon',
								waitForProcessEnding = False)[2]
						break
					except Exception, e:
						logger.error(e)
						if (e[0] == 233) and (sys.getwindowsversion()[0] == 5) and (sessionId != 0):
							# No process is on the other end
							# Problem with pipe \\\\.\\Pipe\\TerminalServer\\SystemExecSrvr\\<sessionid>
							# After logging off from a session other than 0 csrss.exe does not create this pipe or CreateRemoteProcessW is not able to read the pipe.
							logger.info(u"Retrying to run command in session 0")
							sessionId = 0
						else:
							logger.error(u"Failed to start block login notifier app: %s" % forceUnicode(e))
		elif (self._blockLoginNotifierPid):
			try:
				logger.info(u"Terminating block login notifier app (pid %s)" % self._blockLoginNotifierPid)
				System.terminateProcess(processId = self._blockLoginNotifierPid)
			except Exception, e:
				logger.warning(u"Failed to terminate block login notifier app: %s" % forceUnicode(e))
			self._blockLoginNotifierPid = None
		
	def isRunning(self):
		return self._running
	
	def getConfig(self):
		return self._config
	
	def getConfigValue(self, section, option, raw = False):
		if not section:
			section = 'global'
		section = unicode(section).strip().lower()
		option = unicode(option).strip().lower()
		if not self._config.has_key(section):
			raise ValueError(u"No such config section: %s" % section)
		if not self._config[section].has_key(option):
			raise ValueError(u"No such config option in section '%s': %s" % (section, option))
		
		value = self._config[section][option]
		if not raw and type(value) in (unicode, str) and (value.count('%') >= 2):
			value = self.fillPlaceholders(value)
		if type(value) is str:
			value = unicode(value)
		return value
		
	def setConfigValue(self, section, option, value):
		if not section:
			section = 'global'
		
		section = unicode(section).strip().lower()
		option = unicode(option).strip().lower()
		value = unicode(value.strip())
		
		logger.info(u"Setting config value %s.%s" % (section, option))
		logger.debug(u"setConfigValue(%s, %s, %s)" % (section, option, value))
		
		if option not in ('action_processor_command') and (value == ''):
			logger.warning(u"Refusing to set empty value for config value '%s' of section '%s'" % (option, section))
			return
		
		if (option == 'opsi_host_key'):
			if (len(value) != 32):
				raise ValueError("Bad opsi host key, length != 32")
			logger.addConfidentialString(value)
		
		if option in ('server_id', 'depot_id', 'host_id'):
			value = value.lower()
		
		if section in ('system'):
			return
		
		if option in ('log_level', 'wait_for_gui_timeout', 'popup_port', 'port', 'start_port'):
			value = forceInt(value)
		
		if option in ('create_user', 'delete_user'):
			value = forceBool(value)
		
		if not self._config.has_key(section):
			self._config[section] = {}
		self._config[section][option] = value
		
		if   (section == 'config_service') and (option == 'url'):
			self.setConfigServiceUrl(self._config[section][option])
		elif (section == 'config_service') and option in ('connection_timeout', 'user_cancellable_after'):
			self._config[section][option] = int(self._config[section][option])
			if (self._config[section][option] < 0):
				self._config[section][option] = 0
		elif (section == 'global') and (option == 'log_level'):
			logger.setFileLevel(self._config[section][option])
		elif (section == 'global') and (option == 'log_file'):
			logger.setLogFile(self._config[section][option])
	
	def setConfigServiceUrl(self, url):
		if not re.search('https?://[^/]+', url):
			raise ValueError("Bad config service url '%s'" % url)
		self._config['config_service']['url'] = url
		self._config['config_service']['host'] = self._config['config_service']['url'].split('/')[2]
		self._config['config_service']['port'] = '4447'
		if (self._config['config_service']['host'].find(':') != -1):
			(self._config['config_service']['host'], self._config['config_service']['port']) = self._config['config_service']['host'].split(':', 1)
		
	def readConfigFile(self):
		''' Get settings from config file '''
		logger.notice(u"Trying to read config from file: '%s'" % self.getConfigValue('global', 'config_file'))
		
		try:
			# Read Config-File
			config = IniFile(filename = self.getConfigValue('global', 'config_file'), raw = True).parse()
			
			# Read log settings early
			if config.has_section('global'):
				debug = False
				try:
					debug = bool(System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SYSTEM\\CurrentControlSet\\Services\\opsiclientd", "Debug"))
				except:
					pass
				if not debug:
					if config.has_option('global', 'log_level'):
						self.setConfigValue('global', 'log_level', config.get('global', 'log_level'))
					if config.has_option('global', 'log_file'):
						logFile = config.get('global', 'log_file')
						for i in (2, 1, 0):
							slf = None
							dlf = None
							try:
								slf = logFile + '.' + unicode(i-1)
								if (i <= 0):
									slf = logFile
								dlf = logFile + '.' + unicode(i)
								if os.path.exists(slf):
									if os.path.exists(dlf):
										os.unlink(dlf)
									os.rename(slf, dlf)
							except Exception, e:
								logger.error(u"Failed to rename %s to %s: %s" % (slf, dlf, forceUnicode(e)) )
						self.setConfigValue('global', 'log_file', logFile)
			
			# Process all sections
			for section in config.sections():
				logger.debug(u"Processing section '%s' in config file: '%s'" % (section, self.getConfigValue('global', 'config_file')))
				
				for (option, value) in config.items(section):
					option = option.lower()
					self.setConfigValue(section.lower(), option, value)
				
		except Exception, e:
			# An error occured while trying to read the config file
			logger.error(u"Failed to read config file '%s': %s" % (self.getConfigValue('global', 'config_file'), forceUnicode(e)))
			logger.logException(e)
			return
		logger.notice(u"Config read")
		logger.debug(u"Config is now:\n %s" % objectToBeautifiedText(self._config))
	
	def updateConfigFile(self):
		''' Get settings from config file '''
		logger.notice(u"Updating config file: '%s'" % self.getConfigValue('global', 'config_file'))
		
		try:
			# Read config file
			configFile = IniFile(filename = self.getConfigValue('global', 'config_file'), raw = True)
			config = configFile.parse()
			changed = False
			for (section, value) in self._config.items():
				if not type(value) is dict:
					continue
				if section in ('system'):
					continue
				if not config.has_section(section):
					config.add_section(section)
					changed = True
				for (option, value) in value.items():
					if (section == 'config_service') and option in ('host', 'port'):
						continue
					if (section == 'global') and option in ('config_file'):
						# Do not store these options
						continue
					value = unicode(value)
					if not config.has_option(section, option) or (config.get(section, option) != value):
						changed = True
						config.set(section, option, value)
			if changed:
				# Write back config file if changed
				configFile.generate(config)
				logger.notice(u"Config file '%s' written" % self.getConfigValue('global', 'config_file'))
			else:
				logger.notice(u"No need to write config file '%s', config file is up to date" % self.getConfigValue('global', 'config_file'))
			
		except Exception, e:
			# An error occured while trying to write the config file
			logger.error(u"Failed to write config file '%s': %s" % (self.getConfigValue('global', 'config_file'), forceUnicode(e)))
			logger.logException(e)
	
	def fillPlaceholders(self, string, escaped=False):
		for (section, values) in self._config.items():
			if not type(values) is dict:
				continue
			for (key, value) in values.items():
				value = unicode(value)
				if (string.find(u'"%' + unicode(section) + u'.' + unicode(key) + u'%"') != -1) and escaped:
					if (os.name == 'posix'):
						value = value.replace('"', '\\"')
					if (os.name == 'nt'):
						value = value.replace('"', '^"')
				newString = string.replace(u'%' + unicode(section) + u'.' + unicode(key) + u'%', value)
				
				if (newString != string):
					string = self.fillPlaceholders(newString, escaped)
		return unicode(string)
	
	def createEventGenerators(self):
		self._eventGenerators['panic'] = EventGeneratorFactory(
			PanicEventConfig('panic', actionProcessorCommand = self.getConfigValue('action_processor', 'command', raw=True))
		)
		
		eventConfigs = {}
		for (section, options) in self._config.items():
			section = section.lower()
			if section.startswith('event_'):
				eventConfigName = section.split('_', 1)[1]
				if not eventConfigName:
					logger.error(u"No event config name defined in section '%s'" % section)
					continue
				if eventConfigName in self._eventGenerators.keys():
					logger.error(u"Event config '%s' already defined" % eventConfigName)
					continue
				eventConfigs[eventConfigName] = {
					'active': True,
					'args':   {},
					'super':  None }
				try:
					for key in options.keys():
						if   (key.lower() == 'active'):
							eventConfigs[eventConfigName]['active'] = not options[key].lower() in ('0', 'false', 'off', 'no')
						elif (key.lower() == 'super'):
							eventConfigs[eventConfigName]['super'] = options[key]
						else:
							eventConfigs[eventConfigName]['args'][key.lower()] = options[key]
				except Exception, e:
					logger.error(u"Failed to parse event config '%s': %s" % (eventConfigName, forceUnicode(e)))
		
		def __inheritArgsFromSuperEvents(eventConfigsCopy, args, superEventConfigName):
			if not superEventConfigName in eventConfigsCopy.keys():
				logger.error(u"Super event '%s' not found" % superEventConfigName)
				return args
			superArgs = pycopy.deepcopy(eventConfigsCopy[superEventConfigName]['args'])
			if eventConfigsCopy[superEventConfigName]['super']:
				__inheritArgsFromSuperEvents(eventConfigsCopy, superArgs, eventConfigsCopy[superEventConfigName]['super'])
			superArgs.update(args)
			return superArgs
		
		eventConfigsCopy = pycopy.deepcopy(eventConfigs)
		for eventConfigName in eventConfigs.keys():
			if eventConfigs[eventConfigName]['super']:
				eventConfigs[eventConfigName]['args'] = __inheritArgsFromSuperEvents(
										eventConfigsCopy,
										eventConfigs[eventConfigName]['args'],
										eventConfigs[eventConfigName]['super'])
		
		for (eventConfigName, eventConfig) in eventConfigs.items():
			try:
				if not eventConfig['active']:
					logger.notice(u"Event config '%s' is deactivated" % eventConfigName)
					continue
				
				if not eventConfig['args'].get('type'):
					logger.error(u"Event config '%s': event type not set" % eventConfigName)
					continue
				
				#if not eventConfig['args'].get('action_processor_command'):
				#	eventConfig['args']['action_processor_command'] = self.getConfigValue('action_processor', 'command')
				
				args = {}
				for (key, value) in eventConfig['args'].items():
					if   (key == 'type'):
						continue
					elif (key == 'message'):
						args['message'] = value
					elif (key == 'max_repetitions'):
						args['maxRepetitions'] = int(value)
					elif (key == 'activation_delay'):
						args['activationDelay'] = int(value)
					elif (key == 'notification_delay'):
						args['notificationDelay'] = int(value)
					elif (key == 'warning_time'):
						args['warningTime'] = int(value)
					elif (key == 'wql'):
						args['wql'] = value
					elif (key == 'user_cancelable'):
						args['userCancelable'] = not value.lower() in ('0', 'false', 'off', 'no')
					elif (key == 'block_login'):
						args['blockLogin'] = not value.lower() in ('0', 'false', 'off', 'no')
					elif (key == 'lock_workstation'):
						args['lockWorkstation'] = value.lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'logoff_current_user'):
						args['logoffCurrentUser'] = value.lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'process_shutdown_requests'):
						args['processShutdownRequests'] = not value.lower() in ('0', 'false', 'off', 'no')
					elif (key == 'get_config_from_service'):
						args['getConfigFromService'] = not value.lower() in ('0', 'false', 'off', 'no')
					elif (key == 'update_config_file'):
						args['updateConfigFile'] = not value.lower() in ('0', 'false', 'off', 'no')
					elif (key == 'write_log_to_service'):
						args['writeLogToService'] = not value.lower() in ('0', 'false', 'off', 'no')
					elif (key == 'cache_products'):
						args['cacheProducts'] = value.lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'cache_max_bandwidth'):
						args['cacheMaxBandwidth'] = int(value)
					elif (key == 'requires_cached_products'):
						args['requiresCachedProducts'] = value.lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'sync_config'):
						args['syncConfig'] = value.lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'use_cached_config'):
						args['useCachedConfig'] = value.lower() in ('1', 'true', 'on', 'yes')
					elif (key == 'update_action_processor'):
						args['updateActionProcessor'] = not value.lower() in ('0', 'false', 'off', 'no')
					elif (key == 'action_type'):
						args['actionType'] = value.lower()
					elif (key == 'event_notifier_command'):
						args['eventNotifierCommand'] = self.fillPlaceholders(value.lower(), escaped=True)
					elif (key == 'event_notifier_desktop'):
						args['eventNotifierDesktop'] = value.lower()
					elif (key == 'action_notifier_command'):
						args['actionNotifierCommand'] = self.fillPlaceholders(value.lower(), escaped=True)
					elif (key == 'action_notifier_desktop'):
						args['actionNotifierDesktop'] = value.lower()
					elif (key == 'action_processor_command'):
						args['actionProcessorCommand'] = value.lower()
					elif (key == 'action_processor_desktop'):
						args['actionProcessorDesktop'] = value.lower()
					elif (key == 'action_processor_timeout'):
						args['actionProcessorTimeout'] = int(value)
					elif (key == 'service_options'):
						args['serviceOptions'] = eval(value)
					elif (key == 'pre_action_processor_command'):
						args['preActionProcessorCommand'] = self.fillPlaceholders(value.lower(), escaped=True)
					elif (key == 'post_action_processor_command'):
						args['postActionProcessorCommand'] = self.fillPlaceholders(value.lower(), escaped=True)
					else:
						logger.error(u"Skipping unknown option '%s' in definition of event '%s'" % (key, eventConfigName))
				
				logger.info(u"\nEvent config '" + eventConfigName + u"' args:\n" + objectToBeautifiedText(args) + u"\n")
				
				self._eventGenerators[eventConfigName] = EventGeneratorFactory(
					EventConfigFactory(eventConfig['args']['type'], eventConfigName, **args)
				)
				logger.notice(u"%s event generator '%s' created" % (eventConfig['args']['type'], eventConfigName))
				
			except Exception, e:
				logger.error(u"Failed to create event generator '%s': %s" % (eventConfigName, forceUnicode(e)))
		
		for eventGenerator in self._eventGenerators.values():
			eventGenerator.addEventListener(self)
			eventGenerator.start()
			logger.notice(u"Event generator '%s' started" % eventGenerator)
		
	def getEventGenerators(self, generatorClass=None):
		eventGenerators = []
		for eventGenerator in self._eventGenerators.values():
			if not generatorClass or isinstance(eventGenerator, generatorClass):
				eventGenerators.append(eventGenerator)
		return eventGenerators
		
	def waitForGUI(self, timeout=None):
		if not timeout:
			timeout = None
		class WaitForGUI(EventListener):
			def __init__(self, waitApp = None):
				self._waitApp = waitApp
				self._waitAppPid = None
				if self._waitApp:
					logger.info(u"Starting wait for GUI app")
					sessionId = System.getActiveConsoleSessionId()
					while True:
						try:
							self._waitAppPid = System.runCommandInSession(
									command = self._waitApp,
									sessionId = sessionId,
									desktop = 'winlogon',
									waitForProcessEnding = False)[2]
							break
						except Exception, e:
							logger.error(e)
							if (e[0] == 233) and (sys.getwindowsversion()[0] == 5) and (sessionId != 0):
								# No process is on the other end
								# Problem with pipe \\\\.\\Pipe\\TerminalServer\\SystemExecSrvr\\<sessionid>
								# After logging off from a session other than 0 csrss.exe does not create this pipe or CreateRemoteProcessW is not able to read the pipe.
								logger.info(u"Retrying to run command in session 0")
								sessionId = 0
							else:
								logger.error(u"Failed to start wait for GUI app: %s" % forceUnicode(e))
				self._guiStarted = threading.Event()
				eventGenerator = EventGeneratorFactory(GUIStartupEventConfig("wait_for_gui"))
				eventGenerator.addEventListener(self)
				eventGenerator.start()
			
			def processEvent(self, event):
				logger.info(u"GUI started")
				if self._waitAppPid:
					try:
						logger.info(u"Terminating wait for GUI app (pid %s)" % self._waitAppPid)
						System.terminateProcess(processId = self._waitAppPid)
					except Exception, e:
						logger.warning(u"Failed to terminate wait for GUI app: %s" % forceUnicode(e))
				self._guiStarted.set()
				
			def wait(self, timeout=None):
				self._guiStarted.wait(timeout)
				if not self._guiStarted.isSet():
					logger.warning(u"Timed out after %d seconds while waiting for GUI" % timeout)
				
		WaitForGUI(self.getConfigValue('global', 'wait_for_gui_application')).wait(timeout)
	
	def createActionProcessorUser(self, recreate = True):
		if not self.getConfigValue('action_processor', 'create_user'):
			return
		
		runAsUser = self.getConfigValue('action_processor', 'run_as_user')
		if (runAsUser.lower() == 'system'):
			self._actionProcessorUserName = u''
			self._actionProcessorUserPassword = u''
			return
		
		if (runAsUser.find('\\') != -1):
			logger.warning(u"Ignoring domain part of user to run action processor '%s'" % runAsUser)
			runAsUser = runAsUser.split('\\', -1)
		
		if not recreate and self._actionProcessorUserName and self._actionProcessorUserPassword and System.existsUser(username = runAsUser):
			return
		
		self._actionProcessorUserName = runAsUser
		logger.notice(u"Creating local user '%s'" % runAsUser)
		
		self._actionProcessorUserPassword = u'$!?' + unicode(randomString(16)) + u'§/%'
		logger.addConfidentialString(self._actionProcessorUserPassword)
		
		if System.existsUser(username = runAsUser):
			System.deleteUser(username = runAsUser)
		System.createUser(username = runAsUser, password = self._actionProcessorUserPassword, groups = [ System.getAdminGroupName() ])
	
	def deleteActionProcessorUser(self):
		if not self.getConfigValue('action_processor', 'delete_user'):
			return
		if not self._actionProcessorUserName:
			return
		if not System.existsUser(username = self._actionProcessorUserName):
			return
		System.deleteUser(username = self._actionProcessorUserName)
		self._actionProcessorUserName = u''
		self._actionProcessorUserPassword = u''
	
	def run(self):
		self._running = True
		self._stopped = False
		
		self.readConfigFile()
		
		try:
			logger.comment(u"Opsiclientd version: %s" % __version__)
			logger.comment(u"Commandline: %s" % ' '.join(sys.argv))
			logger.comment(u"Working directory: %s" % os.getcwd())
			logger.notice(u"Using host id '%s'" % self.getConfigValue('global', 'host_id'))
			
			self.setBlockLogin(True)
			
			logger.notice(u"Starting control pipe")
			try:
				self._controlPipe = ControlPipeFactory(OpsiclientdRpcPipeInterface(self))
				self._controlPipe.start()
				logger.notice(u"Control pipe started")
			except Exception, e:
				logger.error(u"Failed to start control pipe: %s" % forceUnicode(e))
				raise
			
			logger.notice(u"Starting control server")
			try:
				self._controlServer = ControlServer(
								opsiclientd        = self,
								httpsPort          = self.getConfigValue('control_server', 'port'),
								sslServerKeyFile   = self.getConfigValue('control_server', 'ssl_server_key_file'),
								sslServerCertFile  = self.getConfigValue('control_server', 'ssl_server_cert_file'),
								staticDir          = self.getConfigValue('control_server', 'static_dir') )
				self._controlServer.start()
				logger.notice(u"Control server started")
			except Exception, e:
				logger.error(u"Failed to start control server: %s" % forceUnicode(e))
				raise
			
			logger.notice(u"Starting cache service")
			try:
				self._cacheService = CacheService(opsiclientd = self)
				self._cacheService.start()
				logger.notice(u"Cache service started")
			except Exception, e:
				logger.error(u"Failed to start cache service: %s" % forceUnicode(e))
				raise
			
			# Create event generators
			self.createEventGenerators()
			for eventGenerator in self.getEventGenerators(generatorClass = DaemonStartupEventGenerator):
				eventGenerator.fireEvent()
			
			if self.getEventGenerators(generatorClass = GUIStartupEventGenerator):
				# Wait until gui starts up
				logger.notice(u"Waiting for gui startup (timeout: %d seconds)" % self.getConfigValue('global', 'wait_for_gui_timeout'))
				self.waitForGUI(timeout = self.getConfigValue('global', 'wait_for_gui_timeout'))
				logger.notice(u"Done waiting for GUI")
				
				# Wait some more seconds for events to fire
				time.sleep(5)
			
			if not self._eventProcessingThreads:
				logger.notice(u"No events processing, unblocking login")
				self.setBlockLogin(False)
			
			while not self._stopped:
				time.sleep(1)
			
			for eventGenerator in self.getEventGenerators(generatorClass = DaemonShutdownEventGenerator):
				eventGenerator.fireEvent()
			
			logger.notice(u"opsiclientd is going down")
			
			for eventGenerator in self.getEventGenerators():
				logger.info(u"Stopping event generator %s" % eventGenerator)
				eventGenerator.stop()
				eventGenerator.join(2)
			
			for ept in self._eventProcessingThreads:
				logger.info(u"Waiting for event processing thread %s" % ept)
				ept.join(5)
			
			logger.info(u"Stopping cache service")
			if self._cacheService:
				self._cacheService.stop()
				self._cacheService.join(2)
			
			logger.info(u"Stopping control server")
			if self._controlServer:
				self._controlServer.stop()
				self._controlServer.join(2)
			
			logger.info(u"Stopping control pipe")
			if self._controlPipe:
				self._controlPipe.stop()
				self._controlPipe.join(2)
			
			if reactor and reactor.running:
				logger.info(u"Stopping reactor")
				reactor.stop()
				while reactor.running:
					logger.debug(u"Waiting for reactor to stop")
					time.sleep(1)
			
			logger.info(u"Exiting main thread")
			
		except Exception, e:
			logger.logException(e)
			self.setBlockLogin(False)
		
		self._running = False
	
	def stop(self):
		self._stopped = True
	
	def processEvent(self, event):
		
		logger.notice(u"Processing event %s" % event)
		
		eventProcessingThread = None
		self._eventProcessingThreadsLock.acquire()
		try:
			eventProcessingThread = EventProcessingThread(self, event)
			
			# Always process panic events
			if not isinstance(event, PanicEvent):
				for ept in self._eventProcessingThreads:
					if (event.eventConfig.actionType != 'login') and (ept.event.eventConfig.actionType != 'login'):
						raise Exception(u"Already processing an other (non login) event: %s" % ept.event.eventConfig.getName())
					if (event.eventConfig.actionType == 'login') and (ept.event.eventConfig.actionType == 'login'):
						if (ept.getSessionId() == eventProcessingThread.getSessionId()):
							raise Exception(u"Already processing login event '%s' in session %s" \
										% (ept.event.eventConfig.getName(), eventProcessingThread.getSessionId()))
		
		except Exception, e:
			self._eventProcessingThreadsLock.release()
			raise
		
		self.createActionProcessorUser(recreate = False)
		
		self._eventProcessingThreads.append(eventProcessingThread)
		self._eventProcessingThreadsLock.release()
		
		try:
			eventProcessingThread.start()
			eventProcessingThread.join()
			logger.notice(u"Done processing event '%s'" % event)
		finally:
			self._eventProcessingThreadsLock.acquire()
			self._eventProcessingThreads.remove(eventProcessingThread)
			try:
				if not self._eventProcessingThreads:
					self.deleteActionProcessorUser()
			except Exception, e:
				logger.warning(e)
			self._eventProcessingThreadsLock.release()
		
	def getEventProcessingThread(self, sessionId):
		for ept in self._eventProcessingThreads:
			if (int(ept.getSessionId()) == int(sessionId)):
				return ept
		raise Exception(u"Event processing thread for session %s not found" % sessionId)
		
	def processProductActionRequests(self, event):
		logger.error(u"processProductActionRequests not implemented")
	
	def getCurrentActiveDesktopName(self, sessionId=None):
		if not (self._config.has_key('opsiclientd_rpc') and self._config['opsiclientd_rpc'].has_key('command')):
			raise Exception(u"opsiclientd_rpc command not defined")
		
		if sessionId is None:
			sessionId = System.getActiveConsoleSessionId()
		rpc = 'setCurrentActiveDesktopName("%s", System.getActiveDesktopName())' % sessionId
		cmd = '%s "%s"' % (self.getConfigValue('opsiclientd_rpc', 'command'), rpc)
		
		try:
			System.runCommandInSession(command = cmd, sessionId = sessionId, waitForProcessEnding = True, timeoutSeconds = 60)
		except Exception, e:
			logger.error(e)
		
		desktop = self._currentActiveDesktopName.get(sessionId)
		if not desktop:
			logger.warning(u"Failed to get current active desktop name for session %d, using 'default'" % sessionId)
			desktop = 'default'
			self._currentActiveDesktopName[sessionId] = desktop
		logger.debug(u"Returning current active dektop name '%s' for session %s" % (desktop, sessionId))
		return desktop
	
	
	def processShutdownRequests(self):
		pass
	
	def showPopup(self, message):
		port = self.getConfigValue('notification_server', 'popup_port')
		if not port:
			raise Exception(u'notification_server.popup_port not defined')
		
		notifierCommand = self.getConfigValue('opsiclientd_notifier', 'command').replace('%port%', forceUnicode(port))
		if not notifierCommand:
			raise Exception(u'opsiclientd_notifier.command not defined')
		notifierCommand += u" -s notifier\\popup.ini"
		
		self._popupNotificationLock.acquire()
		try:
			self.hidePopup()
			
			popupSubject = MessageSubject('message')
			choiceSubject = ChoiceSubject(id = 'choice')
			popupSubject.setMessage(message)
			
			logger.notice(u"Starting popup message notification server on port %d" % port)
			try:
				self._popupNotificationServer = NotificationServer(
								address  = "127.0.0.1",
								port     = port,
								subjects = [ popupSubject, choiceSubject ] )
				self._popupNotificationServer.start()
			except Exception, e:
				logger.error(u"Failed to start notification server: %s" % forceUnicode(e))
				raise
			
			choiceSubject.setChoices([ 'Close' ])
			choiceSubject.setCallbacks( [ self.popupCloseCallback ] )
			
			for sessionId in System.getActiveSessionIds():
				logger.info(u"Starting popup message notifier app in session %d" % sessionId)
				try:
					self._popupNotifierPids[sessionId] = System.runCommandInSession(
								command = notifierCommand,
								sessionId = sessionId,
								desktop = self.getCurrentActiveDesktopName(sessionId),
								waitForProcessEnding = False)[2]
				except Exception,e:
					logger.error(u"Failed to start popup message notifier app in session %d: %s" % (sessionId, forceUnicode(e)))
		finally:
			self._popupNotificationLock.release()
		
	def hidePopup(self):
		if self._popupNotificationServer:
			try:
				logger.info(u"Stopping popup message notification server")
				self._popupNotificationServer.stop(stopReactor = False)
			except Exception, e:
				logger.error(u"Failed to stop popup notification server: %s" % e)
		
		#for (sessionId, notifierPid) in self._popupNotifierPids.items():
		#	try:
		#		logger.info(u"Terminating popup notifier app (pid %s)" % notifierPid)
		#		System.terminateProcess(processId = notifierPid)
		#	except Exception, e:
		#		logger.warning(u"Failed to terminate popup notifier app: '%s'" % forceUnicode(e))
		self._popupNotifierPids = {}
		
	def popupCloseCallback(self, choiceSubject):
		self.hidePopup()
	
	
	
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                         OPSICLIENTD POSIX                                         -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class OpsiclientdPosix(Opsiclientd):
	def __init__(self):
		Opsiclientd.__init__(self)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                          OPSICLIENTD NT                                           -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class OpsiclientdNT(Opsiclientd):
	def __init__(self):
		Opsiclientd.__init__(self)
		self._config['system']['program_files_dir'] = System.getProgramFilesDir()
		self._config['cache_service']['storage_dir'] = '%s\\tmp\\cache_service' % System.getSystemDrive()
		self._config['cache_service']['backend_manager_config'] = self._config['system']['program_files_dir'] + '\\opsi.org\\preloginloader\\opsiclientd\\backendManager.d'
		self._config['global']['config_file'] = self._config['system']['program_files_dir'] + '\\opsi.org\\preloginloader\\opsiclientd\\opsiclientd.conf'
		
	def _shutdownMachine(self):
		self._shutdownRequested = True
		System.shutdown(3)
	
	def _rebootMachine(self):
		self._rebootRequested = True
		System.reboot(3)
	
	def processShutdownRequests(self):
		self._rebootRequested = False
		self._shutdownRequested = False
		rebootRequested = 0
		try:
			rebootRequested = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "RebootRequested")
		except Exception, e:
			logger.warning(u"Failed to get rebootRequested from registry: %s" % forceUnicode(e))
		logger.info(u"rebootRequested: %s" % rebootRequested)
		if rebootRequested:
			System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "RebootRequested", 0)
			if (rebootRequested == 2):
				# Logout
				logger.notice(u"Logout requested, nothing to do")
				pass
			else:
				# Reboot
				self._rebootRequested = True
				self._rebootMachine()
		else:
			shutdownRequested = 0
			try:
				shutdownRequested = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "ShutdownRequested")
			except Exception, e:
				logger.warning(u"Failed to get shutdownRequested from registry: %s" % forceUnicode(e))
			logger.info(u"shutdownRequested: %s" % shutdownRequested)
			if shutdownRequested:
				# Shutdown
				System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "ShutdownRequested", 0)
				self._shutdownRequested = True
				self._shutdownMachine()
	
	
	
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                          OPSICLIENTD NT5                                          -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class OpsiclientdNT5(OpsiclientdNT):
	def __init__(self):
		OpsiclientdNT.__init__(self)
		self._config['action_processor']['run_as_user'] = 'pcpatch'
		
	def _shutdownMachine(self):
		self._shutdownRequested = True
		# Running in thread to avoid failure of shutdown (device not ready)
		class _shutdownThread(threading.Thread):
			def __init__(self):
				threading.Thread.__init__(self)
			
			def run(self):
				while(True):
					try:
						System.shutdown(0)
						logger.notice(u"Shutdown initiated")
						break
					except Exception, e:
						# Device not ready?
						logger.info(u"Failed to initiate shutdown: %s" % forceUnicode(e))
						time.sleep(1)
			
		_shutdownThread().start()
		
	def _rebootMachine(self):
		self._rebootRequested = True
		# Running in thread to avoid failure of reboot (device not ready)
		class _rebootThread(threading.Thread):
			def __init__(self):
				threading.Thread.__init__(self)
			
			def run(self):
				while(True):
					try:
						System.reboot(0)
						logger.notice(u"Reboot initiated")
						break;
					except Exception, e:
						# Device not ready?
						logger.info(u"Failed to initiate reboot: %s" % forceUnicode(e))
						time.sleep(1)
		
		_rebootThread().start()
	
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                          OPSICLIENTD NT6                                          -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class OpsiclientdNT6(OpsiclientdNT):
	def __init__(self):
		OpsiclientdNT.__init__(self)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                          OPSICLIENTD NT61                                         -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class OpsiclientdNT61(OpsiclientdNT):
	def __init__(self):
		OpsiclientdNT.__init__(self)
	
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                         OPSICLIENTD INIT                                          -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
def OpsiclientdInit():
	if (os.name == 'posix'):
		return OpsiclientdPosixInit()
	
	# if sys.platform == 'win32':
	if (os.name == 'nt'):
		return OpsiclientdNTInit()
	else:
		raise NotImplementedError(u"Unsupported operating system %s" % os.name)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                       OPSICLIENTD POSIX INIT                                      -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class OpsiclientdPosixInit(object):
	def __init__(self):
		logger.debug(u"OpsiclientdPosixInit")
		argv = sys.argv[1:]
		
		# Call signalHandler on signal SIGHUP, SIGTERM, SIGINT
		signal(SIGHUP,  self.signalHandler)
		signal(SIGTERM, self.signalHandler)
		signal(SIGINT,  self.signalHandler)
		
		# Process command line arguments
		try:
			(opts, args) = getopt.getopt(argv, "vDl:")
		
		except getopt.GetoptError:
			self.usage()
			sys.exit(1)
		
		daemon = False
		logLevel = LOG_NOTICE
		for (opt, arg) in opts:
			if   (opt == "-v"):
				print u"opsiclientd version %s" % __version__
				sys.exit(0)
			if   (opt == "-D"):
				daemon = True
			if   (opt == "-l"):
				logLevel = int(arg)
		if daemon:
			logger.setConsoleLevel(LOG_NONE)
			self.daemonize()
		else:
			logger.setConsoleLevel(logLevel)
		
		# Start opsiclientd
		self._opsiclientd = OpsiclientdPosix()
		self._opsiclientd.start()
		#self._opsiclientd.join()
		while self._opsiclientd.isRunning():
			time.sleep(1)
		
	def signalHandler(self, signo, stackFrame):
		if (signo == SIGHUP):
			return
		if (signo == SIGTERM or signo == SIGINT):
			self._opsiclientd.stop()
	
	def usage(self):
		print u"\nUsage: %s [-v] [-D]" % os.path.basename(sys.argv[0])
		print u"Options:"
		print u"  -v    Show version information and exit"
		print u"  -D    Causes the server to operate as a daemon"
		print u"  -l    Set log level (default: 4)"
		print u"        0=nothing, 1=critical, 2=error, 3=warning, 4=notice, 5=info, 6=debug, 7=debug2, 9=confidential"
		print u""
	
	def daemonize(self):
		return
		# Fork to allow the shell to return and to call setsid
		try:
			pid = os.fork()
			if (pid > 0):
				# Parent exits
				sys.exit(0)
		except OSError, e:
			raise Exception(u"First fork failed: %e" % forceUnicode(e))
		
		# Do not hinder umounts
		os.chdir("/")
		# Create a new session
		os.setsid()
		
		# Fork a second time to not remain session leader
		try:
			pid = os.fork()
			if (pid > 0):
				sys.exit(0)
		except OSError, e:
			raise Exception(u"Second fork failed: %e" % forceUnicode(e))
		
		logger.setConsoleLevel(LOG_NONE)
		
		# Close standard output and standard error.
		os.close(0)
		os.close(1)
		os.close(2)
		
		# Open standard input (0)
		if (hasattr(os, "devnull")):
			os.open(os.devnull, os.O_RDWR)
		else:
			os.open("/dev/null", os.O_RDWR)
		
		# Duplicate standard input to standard output and standard error.
		os.dup2(0, 1)
		os.dup2(0, 2)
		sys.stdout = logger.getStdout()
		sys.stderr = logger.getStderr()

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                   OPSICLIENTD SERVICE FRAMEWORK                                   -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class OpsiclientdServiceFramework(win32serviceutil.ServiceFramework):
		_svc_name_ = "opsiclientd"
		_svc_display_name_ = "opsiclientd"
		_svc_description_ = "opsi client daemon"
		#_svc_deps_ = ['Eventlog', 'winmgmt']
		
		def __init__(self, args):
			"""
			Initialize service and create stop event
			"""
			sys.stdout = logger.getStdout()
			sys.stderr = logger.getStderr()
			logger.setConsoleLevel(LOG_NONE)
			
			logger.debug(u"OpsiclientdServiceFramework initiating")
			win32serviceutil.ServiceFramework.__init__(self, args)
			self._stopEvent = threading.Event()
			logger.debug(u"OpsiclientdServiceFramework initiated")
		
		def ReportServiceStatus(self, serviceStatus, waitHint = 5000, win32ExitCode = 0, svcExitCode = 0):
			# Wrapping because ReportServiceStatus sometimes lets windows report a crash of opsiclientd (python 2.6.5)
			# invalid handle ...
			try:
				win32serviceutil.ServiceFramework.ReportServiceStatus(
					self, serviceStatus, waitHint = waitHint, win32ExitCode = win32ExitCode, svcExitCode = svcExitCode)
			except Exception, e:
				logger.error(u"Failed to report service status %s: %s" % (serviceStatus, forceUnicode(e)))
			
		def SvcInterrogate(self):
			logger.debug(u"OpsiclientdServiceFramework SvcInterrogate")
			# Assume we are running, and everyone is happy.
			self.ReportServiceStatus(win32service.SERVICE_RUNNING)
		
		def SvcStop(self):
			"""
			Gets called from windows to stop service
			"""
			logger.debug(u"OpsiclientdServiceFramework SvcStop")
			# Write to event log
			self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
			# Fire stop event to stop blocking self._stopEvent.wait()
			self._stopEvent.set()
		
		def SvcShutdown(self):
			"""
			Gets called from windows on system shutdown
			"""
			logger.debug(u"OpsiclientdServiceFramework SvcShutdown")
			# Write to event log
			self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
			# Fire stop event to stop blocking self._stopEvent.wait()
			self._stopEvent.set()
		
		def SvcRun(self):
			"""
			Gets called from windows to start service
			"""
			try:
				try:
					if System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SYSTEM\\CurrentControlSet\\Services\\opsiclientd", "Debug"):
						debugLogFile = "c:\\tmp\\opsiclientd.log"
						f = open(debugLogFile, "w")
						f.write(u"--- Debug log started ---\r\n")
						f.close()
						try:
							logger.setLogFile(debugLogFile)
							logger.setFileLevel(LOG_CONFIDENTIAL)
							logger.log(1, u"Logger initialized", raiseException = True)
						except Exception, e:
							error = 'unkown error'
							try:
								error = str(e)
							except:
								pass
							f = open(debugLogFile, "a+")
							f.write("Failed to initialize logger: %s\r\n" % error)
							f.close()
				except Exception, e:
					pass
				
				startTime = time.time()
				
				logger.debug(u"OpsiclientdServiceFramework SvcDoRun")
				# Write to event log
				self.ReportServiceStatus(win32service.SERVICE_START_PENDING)
				
				# Start opsiclientd
				#workingDirectory = os.getcwd()
				#try:
				#	workingDirectory = os.path.dirname(System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SYSTEM\\CurrentControlSet\\Services\\opsiclientd\\PythonClass", ""))
				#except Exception, e:
				#	logger.error(u"Failed to get working directory from registry: %s" % forceUnicode(e))
				#os.chdir(workingDirectory)
				
				if (sys.getwindowsversion()[0] == 5):
					# NT5: XP
					opsiclientd = OpsiclientdNT5()
				
				elif (sys.getwindowsversion()[0] == 6):
					# NT6: Vista / Windows7
					if (sys.getwindowsversion()[1] >= 1):
						# Windows7
						opsiclientd = OpsiclientdNT61()
					else:
						opsiclientd = OpsiclientdNT6()
				else:
					raise Exception(u"Running windows version not supported")
				
				opsiclientd.start()
				# Write to event log
				self.ReportServiceStatus(win32service.SERVICE_RUNNING)
				
				logger.debug(u"Took %0.2f seconds to report service running status" % (time.time() - startTime))
				
				# Wait for stop event
				self._stopEvent.wait()
				
				# Shutdown opsiclientd
				opsiclientd.stop()
				opsiclientd.join(15)
				
				logger.notice(u"opsiclientd stopped")
				for thread in threading.enumerate():
					logger.notice(u"Running thread after stop: %s" % thread)
				
			except Exception, e:
				logger.critical(u"opsiclientd crash")
				logger.logException(e)
			
			# This call sometimes produces an error in eventlog (invalid handle)
			#self.ReportServiceStatus(win32service.SERVICE_STOPPED)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                        OPSICLIENTD NT INIT                                        -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class OpsiclientdNTInit(object):
	def __init__(self):
		logger.debug(u"OpsiclientdNTInit")
		win32serviceutil.HandleCommandLine(OpsiclientdServiceFramework)
		

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                               MAIN                                                -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
if (__name__ == "__main__"):
	logger.setConsoleLevel(LOG_WARNING)
	exception = None
	
	try:
		OpsiclientdInit()
		
	except SystemExit, e:
		pass
		
	except Exception, e:
		exception = e
	
	if exception:
		logger.logException(exception)
		print >> sys.stderr, u"ERROR:", unicode(exception)
		sys.exit(1)
	sys.exit(0)


