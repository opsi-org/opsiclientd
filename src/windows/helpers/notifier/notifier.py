# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = = = =
   =               notifier                =
   = = = = = = = = = = = = = = = = = = = = =
   
   notifier is part of the desktop management solution opsi
   (open pc server integration) http://www.opsi.org
   
   Copyright (C) 2008 uib GmbH
   
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

__version__ = '4.0'

# Imports
import threading, time, sys, os, getopt, locale
import struct, win32api, win32con, win32ui, win32service, commctrl, timer
from ctypes import *
try:
	# Try to use advanced gui
	import winxpgui as win32gui
except:
	import win32gui

# OPSI imports
from OPSI.Types import *
from OPSI.Util.File import IniFile
from OPSI.Util.Message import NotificationClient, SubjectsObserver
from OPSI.Logger import *

encoding = locale.getpreferredencoding()
argv = [ unicode(arg, encoding) for arg in sys.argv ]

try:
	language = locale.getdefaultlocale()[0].split('_')[0]
except Exception, e:
	language = 'en'

# Create logger instance
logger = Logger()

# Globals
global logFile
global host
global port
global skin
global notificationClientId

logFile = u''
host = u'127.0.0.1'
port = 0
skin = 'skin.ini'
notificationClientId = None

BYTE = c_ubyte
LONG = c_long

class POINT(Structure):
    _fields_ = [('x', LONG),
                ('y', LONG)]

class SIZE(Structure):
    _fields_ = [('cx', LONG),
                ('cy', LONG)]

class BLENDFUNCTION(Structure):
    _fields_ = [('BlendOp', BYTE),
                ('BlendFlags', BYTE),
                ('SourceConstantAlpha', BYTE),
                ('AlphaFormat', BYTE)]

class AREA(Structure):
    _fields_ = [("left", LONG),
                ("top", LONG),
                ("right", LONG),
                ("bottom", LONG)]

class OpsiDialogWindow(SubjectsObserver):
	def __init__(self):
		win32gui.InitCommonControls()
		self.hinst = win32api.GetModuleHandle(None)
		self.taskbarNotifyEventId = win32con.WM_USER + 20
		self.hidden = False
		self.alpha = 255
		self.dpi = 96

		try:
			self.dpi = win32ui.GetDeviceCaps(win32gui.GetDC(win32gui.GetDesktopWindow()), win32con.LOGPIXELSY)
		except Exception, e:
			logger.error(u"Failed to get dpi: %s" % e)
		logger.notice(u"Screen dpi %d" % self.dpi)
		
		try:
			self.hicon = win32gui.CreateIconFromResource(win32api.LoadResource(None, win32con.RT_ICON, 1), True)
		except Exception, e:
			logger.error(u"Failed to load icon: %s" % e)
			self.hicon = None
		
		self.wndClassName = "opsi notifier"
		
		self.loadSkin()
		
		self._notificationClient = None
		if port:
			self._notificationClient = NotificationClient(host, port, self, notificationClientId)
			self._notificationClient.addEndConnectionRequestedCallback(self.close)
		
	def close(self):
		logger.notice(u"OpsiDialogWindow.close()")
		win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)
		
	def _registerWndClass(self):
		message_map = {}
		wc = win32gui.WNDCLASS()
		wc.SetDialogProc() # Make it a dialog class.
		wc.hInstance = self.hinst
		wc.lpszClassName = self.wndClassName
		wc.style = win32con.CS_VREDRAW | win32con.CS_HREDRAW
		wc.hCursor = win32gui.LoadCursor( 0, win32con.IDC_ARROW )
		wc.hbrBackground = win32con.COLOR_WINDOW + 1
		wc.lpfnWndProc = message_map # could also specify a wndproc.
		# C code: wc.cbWndExtra = DLGWINDOWEXTRA + sizeof(HBRUSH) + (sizeof(COLORREF));
		wc.cbWndExtra = win32con.DLGWINDOWEXTRA + struct.calcsize("Pi")
		icon_flags = win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE
		if self.hicon:
			wc.hIcon = self.hicon
		try:
			classAtom = win32gui.RegisterClass(wc)
		except win32gui.error, err_info:
			if err_info[0]!=winerror.ERROR_CLASS_ALREADY_EXISTS:
				raise
		return self.wndClassName
	
	def loadSkin(self):
		skinDir = os.path.dirname(skin)
		
		def toPath(value):
			if skinDir:
				return os.path.join(skinDir, value)
			return value
		
		def toRGB(value):
			color = value.split(',')
			return win32api.RGB(int(color[0]), int(color[1]), int(color[2]))
		
		def toStyle(value, type=None):
			logger.debug(u"toStyle() value: %s, type: %s" % (value, type))
			if   ( str(value).lower() == u'left' ):
				if (type == u'button'):
					return win32con.BS_LEFT
				return win32con.ES_LEFT
			elif ( str(value).lower() == u'right' ):
				if (type == u'button'):
					return win32con.BS_RIGHT
				return win32con.ES_RIGHT
			elif ( str(value).lower() in (u'center', u'middle') ):
				if (type == u'button'):
					return win32con.BS_CENTER
				return win32con.ES_CENTER
			return 0
		
		ini = IniFile(skin).parse()
		
		self.skin = {
			'form': {
				'type':             u'form',
				'width':            200,
				'height':           200,
				'top':              0,
				'left':             0,
				'font':             win32gui.LOGFONT(),
				'fontColor':        win32api.RGB(255, 255, 255),
				'color':            win32api.RGB(255, 255, 255),
				'text':             u'',
				'style':            0,
				'stayOnTop':        False,
				'fadeIn':           False,
				'fadeOut':          False,
				'slideIn':          False,
				'slideOut':         False,
				'animationTime':    1000,
				'animationSteps':   25,
				'transparentColor': None,
				'icon':             None,
				'systray':          False
			}
		}
		
		for section in ini.sections():
			sec = section.strip().lower()
			item = sec
			
			if (item != u'form'):
				(type, id) = (u'', u'')
				if   item.startswith(u'label'):
					(type, id) = (u'label', item[5:])
				elif item.startswith(u'image'):
					(type, id) = (u'image', item[5:])
				elif item.startswith('button'):
					(type, id) = (u'button', item[6:])
				elif item.startswith(u'progressbar'):
					(type, id) = (u'progressbar', item[11:])
				else:
					logger.error(u"Unkown type '%s' in ini" % item)
					continue
				
				self.skin[item] = {
					'type':      type,
					'id':        id,
					'top':       0,
					'left':      0,
					'width':     200,
					'height':    10,
					'font':      win32gui.LOGFONT(),
					'fontColor': win32api.RGB(255, 255, 255),
					'color':     win32api.RGB(255, 255, 255),
					'text':      u'',
				}

			for (key, value) in ini.items(section):
				key = key.lower()
				if    (key == 'color'):            self.skin[item]['color'] = toRGB(value)
				elif  (key == 'transparent'):      self.skin[item]['transparent'] = forceBool(value)
				elif  (key == 'frame') and forceBool(value): self.skin[item]['style'] |= win32con.WS_CAPTION #|= win32con.WS_POPUP
				elif  (key == 'closeable') and forceBool(value): self.skin[item]['style'] |= win32con.WS_SYSMENU
				elif  (key == 'resizable') and forceBool(value): self.skin[item]['style'] |= win32con.WS_THICKFRAME
				elif  (key == 'minimizable') and forceBool(value): self.skin[item]['style'] |= win32con.WS_MINIMIZEBOX
				elif  (key == 'systray'):          self.skin[item]['systray'] = forceBool(value)
				elif  (key == 'left'):             self.skin[item]['left'] = forceInt(value)
				elif  (key == 'top'):              self.skin[item]['top'] = forceInt(value)
				elif  (key == 'width'):            self.skin[item]['width'] = forceInt(value)
				elif  (key == 'height'):           self.skin[item]['height'] = forceInt(value)
				elif  (key == 'fontname'):         self.skin[item]['font'].lfFaceName = value.strip()
				elif  (key == 'fontsize'):         self.skin[item]['font'].lfHeight = forceInt(value)
				elif  (key == 'fontweight'):       self.skin[item]['font'].lfWeight = forceInt(value)
				elif  (key == 'fontitalic'):       self.skin[item]['font'].lfItalic = forceBool(value)
				elif  (key == 'fontunderline'):    self.skin[item]['font'].lfUnderline = forceBool(value)
				elif  (key == 'fontbold') and forceBool(value): self.skin[item]['font'].lfWeight = 700
				elif  (key == 'fontcolor'):        self.skin[item]['fontColor'] = toRGB(value)
				elif  (key == 'alignment'):        self.skin[item]['alignment'] = toStyle(value, self.skin[item]['type'])
				elif  (key == 'file'):             self.skin[item]['file'] = toPath(value.strip())
				elif  (key == 'icon'):             self.skin[item]['icon'] = toPath(value)
				elif  (key == 'active'):           self.skin[item]['active'] = forceBool(value)
				elif  (key == 'stayontop'):        self.skin[item]['stayOnTop'] = forceBool(value)
				elif  (key == 'fadein'):           self.skin[item]['fadeIn'] = forceBool(value)
				elif  (key == 'fadeout'):          self.skin[item]['fadeOut'] = forceBool(value)
				elif  (key == 'slidein'):          self.skin[item]['slideIn'] = value.strip().lower()
				elif  (key == 'slideout'):         self.skin[item]['slideOut'] = value.strip().lower()
				elif  (key == 'animationsteps'):   self.skin[item]['animationSteps'] = forceInt(value)
				elif  (key == 'animationtime'):    self.skin[item]['animationTime'] = forceInt(value)
				elif  (key == 'transparentcolor'): self.skin[item]['transparentColor'] = toRGB(value)
				elif  (key == 'subjectid'):        self.skin[item]['subjectId'] = value.strip()
				elif  (key == 'subjecttype'):      self.skin[item]['subjectType'] = value.strip()
				elif  (key == 'choiceindex'):      self.skin[item]['choiceIndex'] = forceInt(value)
				elif  (section.lower() == 'form') and (key == 'hidden') and forceBool(value):
					self.hidden = True
				elif  key.startswith('text'):
					tLanguage = None
					try:
						tLanguage = key.split('[')[1].split(']')[0].strip().lower()
					except:
						pass
					if tLanguage:
						if (tLanguage == language):
							self.skin[item]['text'] =  value.strip()
					elif not self.skin[item]['text']:
						self.skin[item]['text'] = value.strip()
		
		if self.skin['form']['transparentColor']:
			self.skin['form']['fadeIn'] = False
			self.skin['form']['fadeOut'] = False
		
		if self.skin['form']['slideIn'] and not self.skin['form']['slideIn'] in ('left', 'right', 'up', 'down'):
			self.skin['form']['slideIn'] = False
		if self.skin['form']['slideOut'] and not self.skin['form']['slideOut'] in ('left', 'right', 'up', 'down'):
			self.skin['form']['slideOut'] = False
		if (self.skin['form']['animationSteps'] > 200):
			self.skin['form']['animationSteps'] = 200
		elif (self.skin['form']['animationSteps'] < 1):
			self.skin['form']['animationSteps'] = 1
		if (self.skin['form']['animationTime'] < 100):
			self.skin['form']['animationTime'] = 100
		
		desktop = win32gui.GetDesktopWindow()
		(l, t, r, b) = win32gui.GetWindowRect(desktop)
		(DesktopCentreX, DesktopCentreY) = win32gui.ClientToScreen( desktop, ((r-l)/2, (b-t)/2) )
		
		area = AREA(0, 0, 0, 0)
		windll.user32.SystemParametersInfoW(win32con.SPI_GETWORKAREA, 0, pointer(area), 0)
		(l, t, r, b) = (area.left, area.top, area.right, area.bottom)
		(AvailableCentreX, AvailableCentreY) = win32gui.ClientToScreen( desktop, ((r-l)/2, (b-t)/2) )
		
		if (self.skin['form']['left'] < 0):
			self.skin['form']['left'] = AvailableCentreX*2 - (-1*self.skin['form']['left']) - self.skin['form']['width'] + 1
		elif (self.skin['form']['left'] == 0):
			self.skin['form']['left'] = AvailableCentreX - int(self.skin['form']['width']/2)
		else:
			self.skin['form']['left'] -= 1
		if (self.skin['form']['left'] < 0):
			self.skin['form']['left'] = 0
		
		if (self.skin['form']['top'] < 0):
			self.skin['form']['top'] = AvailableCentreY*2 - (-1*self.skin['form']['top']) - self.skin['form']['height'] + 1
		elif (self.skin['form']['top'] == 0):
			self.skin['form']['top'] = AvailableCentreY - int(self.skin['form']['height']/2) + 1
		else:
			self.skin['form']['top'] -= 1
		if (self.skin['form']['top'] < 0):
			self.skin['form']['top'] = 0
		
		# Needed for animations
		self.endLeft = self.startLeft = self.currentLeft = self.skin['form']['left']
		self.endTop  = self.startTop  = self.currentTop  = self.skin['form']['top']
		
	def _getDialogTemplate(self):
		# dlg item [ type, caption, id, (x,y,cx,cy), style, ex style
		#
		# Built-in classes include:
		# @flagh Control Type|String Class Name
		# @flag Check Box|Button
		# @flag Combo Box|ComboBox
		# @flag Command Button|Button
		# @flag Header|SysHeader32
		# @flag Label|Static
		# @flag List Box|ListBox<nl>SysListView32
		# @flag Option Button|Button
		# @flag Tab|SysTabControl32
		# @flag Text Box|Edit<nl>RICHEDIT
		# @flag Tool Bar|ToolbarWindow32
		# @flag Tool Tips|tooltips_class32<nl>tooltips_class
		# @flag Tree View|SysTreeView32
		# The built-in windows controls are:
		# @flagh Integer Value|Window Type
		# @flag 0x0080|Button
		# @flag 0x0081|Edit
		# @flag 0x0082|Static
		# @flag 0x0083|List box
		# @flag 0x0084|Scroll bar
		# @flag 0x0085|Combo box
		
		# win32con.WS_MINIMIZEBOX | win32con.WS_THICKFRAME
		#style = win32con.WS_POPUP | win32con.WS_VISIBLE |  win32con.WS_CAPTION | win32con.WS_SYSMENU |  win32con.DS_SETFONT
		#style = win32con.WS_POPUP | win32con.WS_VISIBLE |  win32con.WS_CAPTION | win32con.WS_SYSMENU | win32con.WS_MINIMIZEBOX | win32con.WS_THICKFRAME | win32con.DS_SETFONT
		#style = win32con.WS_POPUP | win32con.WS_VISIBLE | win32con.DS_SETFONT | win32con.WS_CAPTION | win32con.WS_SYSMENU | win32con.WS_MINIMIZEBOX | win32con.WS_THICKFRAME
		#style = win32con.WS_POPUP | win32con.WS_VISIBLE | win32con.DS_SETFONT

		dpiCorrection = float(96)/float(self.dpi)
		
		# Window frame and title
		style = win32con.DS_SETFONT | win32con.WS_POPUP #| win32con.WS_EX_TOOLWINDOW # win32con.WS_VISIBLE | win32con.WS_EX_TRANSPARENT#
		if self.skin['form']['style']:
			style |= self.skin['form']['style']
		dlg = [ [ self.skin['form']['text'],
			  (0, 0, int(self.skin['form']['width']/2), int(self.skin['form']['height']/2)),
			  style, None,
			  (self.skin['form']['font'].lfHeight, self.skin['form']['font'].lfFaceName),
			  None, self.wndClassName ], ]
		
		# Create fonts
		for item in self.skin.keys():
			if self.skin[item].get('font'):
				self.skin[item]['font'] = win32gui.CreateFontIndirect(self.skin[item]['font'])
		
		if self.skin['form'].get('icon'):
			self.hicon = win32gui.LoadImage(
				self.hinst, self.skin['form']['icon'], win32con.IMAGE_ICON,
				0, 0, win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE )
			try:
				win32api.SendMessage(self.hwnd, win32con.WM_SETICON, 0, self.hicon)
			except Exception, e:
				logger.error(u"Failed to set window icon: %s" % e)
		dlgId = 100
		# Images first
		for (item, values) in self.skin.items():
			if (values['type'] != 'image'):
				continue
			
			style = win32con.WS_VISIBLE | win32con.WS_CHILD
			if values.has_key('alignment'):
				style |= values['alignment']
			
			if not values.get('file'):
				continue
			
			self.skin[item]['bitmap'] = win32gui.LoadImage(
				self.hinst, values['file'], win32con.IMAGE_BITMAP,
				0, 0, win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE )
			
			style |= win32con.SS_BITMAP
			dlg.append( [130, values.get('text', ''),
				dlgId,
				( int(values['left']/2), int(values['top']/2), int(values['width']/2), int(values['height']/2) ),
				style ])
			self.skin[item]['dlgId'] = dlgId
			dlgId += 1
		
		for (item, values) in self.skin.items():
			if values['type'] in ('form', 'image'):
				continue
			
			style = win32con.WS_VISIBLE | win32con.WS_CHILD
			if values.has_key('alignment'):
				style |= values['alignment']
			
			if item.startswith('label'):
				(l, t, r, b) = ( int(values['left']/2), int(values['top']/2), int(values['width']/2), int(values['height']/2) )
				l = int(float(l)*dpiCorrection)
				t = int(float(t)*dpiCorrection)
				r = int(float(r)*dpiCorrection)
				b = int(float(b)*dpiCorrection)
				dlg.append( ['Static', values.get('text', ''), dlgId, (l, t, r, b), style ] )
				self.skin[item]['id'] = item[5:]
			
			elif item.startswith('button'):
				# win32con.BS_DEFPUSHBUTTON
				(l, t, r, b) = ( int(values['left']/2), int(values['top']/2), int(values['width']/2), int(values['height']/2) )
				l = int(float(l)*dpiCorrection)
				t = int(float(t)*dpiCorrection)
				r = int(float(r)*dpiCorrection)
				b = int(float(b)*dpiCorrection)
				style |= win32con.BS_MULTILINE | win32con.BS_PUSHBUTTON | win32con.MF_GRAYED #| win32con.BS_OWNERDRAW
				dlg.append( ['Button', values.get('text', ''), dlgId, (l, t, r, b), style ] )
			
			elif item.startswith('progressbar'):
				self.skin[item]['ctrlId'] = dlgId
				dlgId += 1
				continue
			
			else:
				continue
			
			self.skin[item]['dlgId'] = dlgId
			dlgId += 1
		
		return dlg
		
	def CreateWindow(self):
		message_map = {
			win32con.WM_COMMAND:           self.onCommand,
			win32con.WM_INITDIALOG:        self.onInitDialog,
			win32con.WM_CLOSE:             self.onClose,
			win32con.WM_DESTROY:           self.onDestroy,
			win32con.WM_CTLCOLORMSGBOX:    self.onCtlColor,
			win32con.WM_CTLCOLOREDIT:      self.onCtlColor,
			win32con.WM_CTLCOLORLISTBOX:   self.onCtlColor,
			win32con.WM_CTLCOLORBTN:       self.onCtlColor,
			win32con.WM_CTLCOLORDLG:       self.onCtlColor,
			win32con.WM_CTLCOLORSCROLLBAR: self.onCtlColor,
			win32con.WM_CTLCOLORSTATIC:    self.onCtlColor,
			self.taskbarNotifyEventId:     self.onTaskbarNotify,
			#win32con.WM_DRAWITEM:         self.onDrawItem,
			#win32con.WM_PAINT:            self.onPaint,
			#win32con.WM_ERASEBKGND:       self.onEraseBkgnd,
			#win32con.WM_SIZE: 	       self.onSize,
			#win32con.WM_NOTIFY: 	       self.onNotify,
		}
		self._registerWndClass()
		
		template = self._getDialogTemplate()
		
		win32gui.CreateDialogIndirect(self.hinst, template, 0, message_map)
		
		if self.skin['form']['systray']:
			self.createTrayIcon()
		
		self.setButtonFonts()

		animate = False
		if self.skin['form']['fadeIn']:
			animate = True
			self.alpha = 0
			self.setWindowAlpha(self.alpha)
		
		if self.skin['form']['slideIn']:
			animate = True
			#area = AREA(0, 0, 0, 0)
			#windll.user32.SystemParametersInfoW(win32con.SPI_GETWORKAREA, 0, pointer(area), 0)
			#(l, t, r, b) = (area.left, area.top, area.right, area.bottom)
			desktop = win32gui.GetDesktopWindow()
			(l, t, r, b) = win32gui.GetWindowRect(desktop)
			if   (self.skin['form']['slideIn'] == 'right'):
				self.startLeft = self.currentLeft = l - self.skin['form']['width']
			elif (self.skin['form']['slideIn'] == 'left'):
				self.startLeft = self.currentLeft = r
			elif (self.skin['form']['slideIn'] == 'up'):
				self.startTop = self.currentTop = b
			elif (self.skin['form']['slideIn'] == 'down'):
				self.startTop = self.currentTop = t - self.skin['form']['height']
		
		if animate:
			timer.set_timer(int(self.skin['form']['animationTime']/self.skin['form']['animationSteps']), self.animateIn)
		
		if self.skin['form']['transparentColor']:
			self.setWindowAlpha(0, self.skin['form']['transparentColor'])

		if not self.hidden:
			if (sys.getwindowsversion()[0] == 6):
				desktop = win32service.OpenInputDesktop(0, True, win32con.MAXIMUM_ALLOWED)
				desktopName = win32service.GetUserObjectInformation(desktop, win32service.UOI_NAME)
				if (desktopName.lower() == u"winlogon"):
					# On NT6 we need this for window to show up on winlogon desktop
					win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWMINIMIZED)
					win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWMAXIMIZED)
			
			insertAfter = win32con.HWND_TOP
			if self.skin['form'].get('stayOnTop'):
				insertAfter = win32con.HWND_TOPMOST
			win32gui.SetWindowPos(	self.hwnd,
						insertAfter,
						self.currentLeft,
						self.currentTop,
						self.skin['form']['width'],
						self.skin['form']['height'],
						win32con.SWP_SHOWWINDOW )
			
		if self._notificationClient:
			threading.Timer(0.01, self._notificationClient.start).start()

	def animateIn(self, id, time):
		if self.skin['form']['fadeIn']:
			self.setWindowAlpha(self.alpha)
			self.alpha += int(255/self.skin['form']['animationSteps'])
			if (self.alpha > 255):
				self.alpha = 255
		
		if self.skin['form']['slideIn']:
			insertAfter = win32con.HWND_TOP
			if self.skin['form'].get('stayOnTop'):
				insertAfter = win32con.HWND_TOPMOST
			win32gui.SetWindowPos(self.hwnd, insertAfter, self.currentLeft, self.currentTop, 0, 0, win32con.SWP_NOACTIVATE | win32con.SWP_NOSIZE)
			if   (self.skin['form']['slideIn'] == 'left'):
				self.currentLeft -= int((self.startLeft - self.skin['form']['left'])/self.skin['form']['animationSteps'])
				if (self.currentLeft < self.skin['form']['left']):
					self.currentLeft = self.skin['form']['left']
			elif (self.skin['form']['slideIn'] == 'right'):
				self.currentLeft += int((self.skin['form']['left'] - self.startLeft)/self.skin['form']['animationSteps'])
				if (self.currentLeft > self.skin['form']['left']):
					self.currentLeft = self.skin['form']['left']
			elif (self.skin['form']['slideIn'] == 'down'):
				self.currentTop += int((self.skin['form']['top'] - self.startTop)/self.skin['form']['animationSteps'])
				if (self.currentTop > self.skin['form']['top']):
					self.currentTop = self.skin['form']['top']
			elif (self.skin['form']['slideIn'] == 'up'):
				self.currentTop -= int((self.startTop - self.skin['form']['top'])/self.skin['form']['animationSteps'])
				if (self.currentTop < self.skin['form']['top']):
					self.currentTop = self.skin['form']['top']
			
		if (not self.skin['form']['fadeIn'] or (self.alpha == 255)) and \
		   (not self.skin['form']['slideIn'] \
		    or (self.skin['form']['slideIn'] in ('left', 'right') and (self.currentLeft == self.skin['form']['left']) \
		    or (self.skin['form']['slideIn'] in ('up',    'down') and (self.currentTop  == self.skin['form']['top'])))):
			if self.skin['form']['fadeIn']:
				self.setWindowAlpha(self.alpha)
			if self.skin['form']['slideIn']:
				insertAfter = win32con.HWND_TOP
				if self.skin['form'].get('stayOnTop'):
					insertAfter = win32con.HWND_TOPMOST
				win32gui.SetWindowPos(self.hwnd, insertAfter, self.currentLeft, self.currentTop, 0, 0, win32con.SWP_NOACTIVATE | win32con.SWP_NOSIZE)
			timer.kill_timer(id)

	def animateOut(self):
		if self.skin['form']['fadeOut']:
			self.setWindowAlpha(self.alpha)
			self.alpha -= int(255/self.skin['form']['animationSteps'])
			if (self.alpha < 0):
				self.alpha = 0
		
		if self.skin['form']['slideOut']:
			insertAfter = win32con.HWND_TOP
			if self.skin['form'].get('stayOnTop'):
				insertAfter = win32con.HWND_TOPMOST
			win32gui.SetWindowPos(self.hwnd, insertAfter, self.currentLeft, self.currentTop, 0, 0, win32con.SWP_NOACTIVATE | win32con.SWP_NOSIZE)
			if   (self.skin['form']['slideOut'] == 'left'):
				self.currentLeft -= int((self.skin['form']['left'] - self.endLeft)/self.skin['form']['animationSteps'])
				if (self.currentLeft < self.endLeft):
					self.currentLeft = self.endLeft
			elif (self.skin['form']['slideOut'] == 'right'):
				self.currentLeft += int((self.endLeft - self.skin['form']['left'])/self.skin['form']['animationSteps'])
				if (self.currentLeft > self.endLeft):
					self.currentLeft = self.endLeft
			elif (self.skin['form']['slideOut'] == 'down'):
				self.currentTop += int((self.endTop - self.skin['form']['top'])/self.skin['form']['animationSteps'])
				if (self.currentTop > self.endTop):
					self.currentTop = self.endTop
			elif (self.skin['form']['slideOut'] == 'up'):
				self.currentTop -= int((self.skin['form']['top'] - self.endTop)/self.skin['form']['animationSteps'])
				if (self.currentTop < self.endTop):
					self.currentTop = self.endTop
		
		if (self.skin['form']['fadeOut'] and (self.alpha > 0)) or \
		   (self.skin['form']['slideOut'] \
		    and ((self.skin['form']['slideOut'] in ('left', 'right') and (self.currentLeft != self.endLeft) \
		      or (self.skin['form']['slideOut'] in ('up',    'down') and (self.currentTop  != self.endTop))))):
			if self.skin['form']['fadeOut']:
				self.setWindowAlpha(self.alpha)
			if self.skin['form']['slideOut']:
				insertAfter = win32con.HWND_TOP
				if self.skin['form'].get('stayOnTop'):
					insertAfter = win32con.HWND_TOPMOST
				win32gui.SetWindowPos(self.hwnd, insertAfter, self.currentLeft, self.currentTop, 0, 0, win32con.SWP_NOACTIVATE | win32con.SWP_NOSIZE)
			time.sleep(float(self.skin['form']['animationTime']/self.skin['form']['animationSteps'])/1000)
			self.animateOut()
	
	def fadeout(self):
		self.setWindowAlpha(self.alpha)
		self.alpha -= 25
		if (self.alpha >= 0):
			time.sleep(0.05)
			self.fadeout()
	
	def createTrayIcon(self):
		try:
			flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
			notifyInfo = (self.hwnd, 0, flags, self.taskbarNotifyEventId, self.hicon, u'opsi notifier')
			win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, notifyInfo)
		except Exception, e:
			logger.error(u"Failed to create tray icon: %s" % e)
	
	def removeTrayIcon(self):
		try:
			win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (self.hwnd, 0))
		except Exception, e:
			logger.error(u"Failed to remove tray icon: %s" % e)
	
	def onTaskbarNotify(self, hwnd, msg, wparam, lparam):
		if (lparam == win32con.WM_LBUTTONDBLCLK):
			if self.hidden:
				# Centre the dialog
				insertAfter = win32con.HWND_TOP
				if self.skin['form'].get('stayOnTop'):
					insertAfter = win32con.HWND_TOPMOST
				win32gui.SetWindowPos(self.hwnd, insertAfter, self.skin['form']['left'], self.skin['form']['top'], self.skin['form']['width'], self.skin['form']['height'], 0)
				win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
				self.hidden = False
			else:
				win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)
				self.hidden = True
		elif (lparam == win32con.WM_RBUTTONUP):
			pos = win32api.GetCursorPos()
			# cmd = self.cMenu.TrackPopupMenu( pos, # win32con.TPM_LEFTALIGN # |win32.TPM_LEFTBUTTON # |win32con.TPM_NONOTIFY # |win32con.TPM_RETURNCMD, None )
		return 1

	def setButtonFonts(self):
		for (item, values) in self.skin.items():
			if (values.get('type') != u'button'):
				continue
			if values.get('font'):
				bmCtrl = win32gui.GetDlgItem(self.hwnd, values['dlgId'])
				win32gui.SendMessage(bmCtrl, win32con.WM_SETFONT, values['font'], True)
			
	def refreshDialogItem(self, dlgId):
		(w_left, w_top, w_right, w_bottom) = win32gui.GetWindowRect(self.hwnd)
		(i_left, i_top, i_right, i_bottom) = win32gui.GetWindowRect(win32gui.GetDlgItem(self.hwnd, dlgId))
		(left, top, right, bottom) = (i_left-w_left, i_top-w_top, i_right-w_left, i_bottom-w_top)
		#win32gui.RedrawWindow(self.hwnd, (left, top, right, bottom), None, win32con.RDW_INVALIDATE | win32con.RDW_ALLCHILDREN)
		#win32gui.InvalidateRect(self.hwnd, (left, top, right, bottom), 0)
		win32gui.RedrawWindow(self.hwnd, (left,top,right,bottom), None, win32con.RDW_INVALIDATE)
		#win32gui.EnableWindow(win32gui.GetDlgItem(self.hwnd, dlgId), True)
		#win32gui.InvalidateRect(self.hwnd, (w_left, w_top, w_right, w_bottom), 0)
		#win32gui.InvalidateRect(self.hwnd, None, True)
		#win32gui.RedrawWindow(self.hwnd, None, 0, win32con.RDW_INVALIDATE | win32con.RDW_ALLCHILDREN)
		#win32gui.SendMessage(self.hwnd, win32con.WM_PAINT, None, None)
		
	def onEraseBkgnd(self, hwnd, msg, wparam, lparam):
		logger.debug2(u"onEraseBkgnd")
		return 0
	
	def onDrawItem(self, hwnd, msg, wparam, lparam):
		logger.debug2(u"onDrawItem")
		return 0
	
	def onCtlColor(self, hwnd, msg, wparam, lparam):
		#win32gui.SelectObject(wparam, self._globalFont)
		#return windll.gdi32.GetStockObject(win32con.HOLLOW_BRUSH)
		logger.debug2("onCtlColor")
		color = self.skin['form']['color']
		fontColor = self.skin['form']['fontColor']
		transparent = self.skin['form'].get('transparent', False)
		font = self.skin['form'].get('font', None)
		
		for (item, values) in self.skin.items():
			handle = None
			if values.get('dlgId'):
				handle = win32gui.GetDlgItem(self.hwnd, values['dlgId'])
			elif values.get('ctrlId'):
				handle = values['ctrl']
			else:
				continue
			if (handle == lparam):
				logger.debug2("Item found")
				color = values.get('color', color)
				fontColor = values.get('fontColor', fontColor)
				transparent = values.get('transparent', transparent)
				font = values.get('font', font)
				break
			
		if font:
			win32gui.SelectObject(wparam, font)
		
		#wparam.TextOut(9, 3, "Button", 6)
		win32gui.SetBkMode(wparam, win32con.TRANSPARENT)
		win32gui.SetTextColor(wparam, fontColor)
		
		if transparent:
			return windll.gdi32.GetStockObject(win32con.HOLLOW_BRUSH)
		else:
			return windll.gdi32.CreateSolidBrush(color)
	
	def onInitDialog(self, hwnd, msg, wparam, lparam):
		self.hwnd = hwnd
		if self.hicon:
			try:
				win32api.SendMessage(self.hwnd, win32con.WM_SETICON, 0, self.hicon)
			except Exception, e:
				logger.error(u"Failed to set window icon: %s" % e)
		for (item, values) in self.skin.items():
			if (values['type'] == u'image') and values.get('bitmap'):
				bmCtrl = win32gui.GetDlgItem(self.hwnd, values['dlgId'])
				win32gui.SendMessage(bmCtrl, win32con.STM_SETIMAGE, win32con.IMAGE_BITMAP, values['bitmap'])
			if (values['type'] == u'button') and not values.get('active'):
				win32gui.EnableWindow(win32gui.GetDlgItem(self.hwnd, values['dlgId']), False)
			if (values['type'] == u'progressbar'):
				values['ctrl'] = win32ui.CreateProgressCtrl()
				values['ctrl'].CreateWindow(
					win32con.WS_CHILD | win32con.WS_VISIBLE,
					( int(values['left']), int(values['top']), int(values['left']+values['width']), int(values['top']+values['height']) ),
					win32ui.CreateWindowFromHandle(self.hwnd), values['ctrlId'])
	
	def onClose(self, hwnd, msg, wparam, lparam):
		try:
			self.removeTrayIcon()
			
			animate = False
			if self.skin['form']['fadeOut']:
				animate = True
				self.alpha = 255
			
			if self.skin['form']['slideOut']:
				animate = True
				desktop = win32gui.GetDesktopWindow()
				(l, t, r, b) = win32gui.GetWindowRect(desktop)
				if   (self.skin['form']['slideOut'] == 'right'):
					self.endLeft = r
				elif (self.skin['form']['slideOut'] == 'left'):
					self.endLeft = l - self.skin['form']['width']
				elif (self.skin['form']['slideOut'] == 'up'):
					self.endTop = t - self.skin['form']['height']
				elif (self.skin['form']['slideOut'] == 'down'):
					self.endTop = b
			
			if animate:
				self.animateOut()
			
		except:
			pass
		win32gui.DestroyWindow(hwnd)
	
	def onDestroy(self, hwnd, msg, wparam, lparam):
		logger.notice("Exiting...")
		if self._notificationClient:
			try:
				logger.info(u"Stopping notification client")
				self._notificationClient.stop()
			except:
				pass
		win32gui.PostQuitMessage(0) # Terminate the app.
	
	def onCommand(self, hwnd, msg, wparam, lparam):
		dlgId = win32api.LOWORD(wparam)
		logger.debug2(u"onCommand dlgId: %s" % dlgId)
		for (item, values) in self.skin.items():
			if not values.get('dlgId') or (dlgId != values['dlgId']):
				continue
			
			if (values.get('type') == u'button'):
				if (values['id'] == u'exit'):
					self.close()
				
				subjectId = values.get('subjectId')
				choiceIndex = values.get('choiceIndex')
				logger.info(u"Button subjectId: %s, choiceIndex: %s" % (subjectId, choiceIndex))
				if (subjectId and (choiceIndex >= 0)):
					if self._notificationClient:
						self._notificationClient.setSelectedIndexes(subjectId, [ choiceIndex ])
						self._notificationClient.selectChoice(subjectId)
			
			elif (values.get('type') == u'label'):
				cwnd = win32ui.CreateWindowFromHandle(self.hwnd)
				text = values.get('text', u'')
				text = text.replace('\\r', '').replace('\r', '').replace('\\n', '\n').replace('\n', '\r\n')
				cwnd.SetDlgItemText(dlgId, text)
				self.refreshDialogItem(dlgId)
			break
		
	def setWindowAlpha(self, alpha, colorKey=None):
		# 32-bit X8 R8 G8 B8
		# 32-bit A8 R8 G8 B8
		# Set WS_EX_LAYERED
		style = win32gui.GetWindowLong(self.hwnd, win32con.GWL_EXSTYLE)
		win32gui.SetWindowLong(self.hwnd, win32con.GWL_EXSTYLE, style | win32con.WS_EX_LAYERED)

		if colorKey:
			win32gui.SetLayeredWindowAttributes(self.hwnd, colorKey, alpha, win32con.LWA_COLORKEY);
		else:
			win32gui.SetLayeredWindowAttributes(self.hwnd, 0, alpha, win32con.LWA_ALPHA);
		if self.skin['form'].get('stayOnTop'):
			win32gui.SetFocus(self.hwnd)
			win32gui.SetWindowPos(self.hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, win32con.SWP_NOACTIVATE | win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)

		
		
		#screenDC = win32gui.GetDC(win32gui.GetDesktopWindow())
		#hdc = win32gui.CreateCompatibleDC(None)
		#
		#blend = BLENDFUNCTION(win32con.AC_SRC_OVER, 0, alpha, 0)
		#size = SIZE(400,400)
		#pointSrc = POINT(200,0)
		#windll.user32.UpdateLayeredWindow(self.hwnd, None, None, byref(size), hdc, byref(pointSrc), 0, byref(blend), win32con.ULW_ALPHA);

		#return
		
		#screenDC = win32gui.GetDC(win32gui.GetDesktopWindow())
		#cScreenDC = win32gui.CreateCompatibleDC(screenDC)
		#
		#win32gui.SelectObject(cScreenDC, self.skin['imagebg']['bitmap'])
		#point1 = POINT(0,0)
		#size1 = SIZE(200,200)
		#point2 = POINT(0,0)
		#blend = BLENDFUNCTION(0, 0, alpha, 1)
		#ret = windll.user32.UpdateLayeredWindow(
		#				self.hwnd,
		#				screenDC,
		#				byref(point1),
		#				byref(size1),
		#				cScreenDC,
		#				byref(point2),
		#				win32api.RGB(255,0,255),
		#				byref(blend),
		#				win32con.ULW_ALPHA)
		#return ret
	
	def setStatusMessage(self, message):
		for (item, values) in self.skin.items():
			if values.get('dlgId') and (values.get('id') == u'status') and values.get('subjectId'):
				self.messageChanged(values.get('subjectId'), message)
				break
		
	def messageChanged(self, subject, message):
		subjectId = subject.get('id')
		subjectType = subject.get('type')
		for (item, values) in self.skin.items():
			dlgId = values.get('dlgId')
			if not dlgId:
				continue
			if (values.get('subjectId') == subjectId) or (values.get('subjectType') == subjectType):
				logger.info(u"message changed, subjectId: %s, dlgId: %s" % (subjectId, dlgId))
				if (self.skin[item].get('text') != message):
					self.skin[item]['text'] = message
					win32gui.SendMessage(self.hwnd, win32con.WM_COMMAND, dlgId, None)
				break
		
	def selectedIndexesChanged(self, subject, selectedIndexes):
		pass
	
	def choicesChanged(self, subject, choices):
		pass
	
	def progressChanged(self, subject, state, percent, timeSpend, timeLeft, speed):
		subjectId = subject.get('id')
		subjectType = subject.get('type')
		for (item, values) in self.skin.items():
			if (values.get('type') != u'progressbar'):
				continue
			ctrlId = values.get('ctrlId')
			if not ctrlId:
				continue
			if (values.get('subjectId') == subjectId) or (not values.get('subjectId') and (values.get('subjectType') == subjectType)):
				logger.info(u"progress changed, subjectId: %s, ctrlId: %s, percent: %s" % (subjectId, ctrlId, percent))
				values['ctrl'].SetRange(0, 100)
				values['ctrl'].SetPos(int(percent))
	
	def subjectsChanged(self, subjects):
		logger.info(u"subjectsChanged(%s)" % subjects)
		choices = {}
		for subject in subjects:
			if (subject['class'] == 'MessageSubject'):
				self.messageChanged(subject, subject['message'])
			if (subject['class'] == 'ChoiceSubject'):
				subjectId = subject.get('id')
				choices[subjectId] = subject.get('choices', [])
			#if (subject['class'] == 'ProgressSubject'):
			#	subjectId = subject.get('id')
			#	subjectType = subject.get('type')
			#	for (item, values) in self.skin.items():
			#		if (values['type'] != 'progressbar') or not values.get('ctrlId'):
			#			continue
			#		if (values.get('subjectId') == subjectId) or (not values.get('subjectId') and (values.get('subjectType') == subjectType)):
			#			values['ctrl'].SetRange(0, subject['end'])
		
		for (item, values) in self.skin.items():
			if (values['type'] != 'button') or not values.get('dlgId') or not values.get('subjectId'):
				continue
			subjectId = values['subjectId']
			dlgId = values['dlgId']
			if subjectId in choices.keys() and (values.get('choiceIndex', -1) >= 0):
				choiceIndex = values['choiceIndex']
				logger.info(u"Found choice subject '%s' mapped to dlgId %s, choiceIndex %d (choices: %s)" \
						% (subjectId, dlgId, choiceIndex, choices[subjectId]))
				dlg = win32gui.GetDlgItem(self.hwnd, dlgId)
				if (choiceIndex < len(choices[subjectId])):
					win32gui.SetWindowText(dlg, choices[subjectId][choiceIndex])
					win32gui.EnableWindow(dlg, True)
				else:
					win32gui.SetWindowText(dlg, "")
					win32gui.EnableWindow(dlg, False)
			else:
				win32gui.EnableWindow(win32gui.GetDlgItem(self.hwnd, dlgId), False)
		logger.debug(u"subjectsChanged() ended")

def usage():
	print u"\nUsage: %s [-h <host>] [-p <port>] [-s <skin>]" % os.path.basename(argv[0])
	print u"Options:"
	print u"  -h, --host      Notification server host (default: %s)" % host
	print u"  -p, --port      Notification server port (default: %s)" % port
	print u"  -i, --id        Notification client id (default: %s)" % notificationClientId
	print u"  -s, --skin      Skin to use (default: %s)" % skin

if (__name__ == "__main__"):
	# If you write to stdout when running from pythonw.exe program will die !!!
	logger.setConsoleLevel(LOG_NONE)
	exception = None
	
	try:
		try:
			os.chdir(os.path.dirname(argv[0]))
		except:
			pass
		
		logger.notice(u"Commandline: %s" % ' '.join(argv))
		
		# Process command line arguments
		try:
			(opts, args) = getopt.getopt(argv[1:], "h:p:s:i:l:", [ "host=", "port=", "skin=", "id=", "log-file=" ])
		except getopt.GetoptError:
			usage()
			sys.exit(1)
		
		for (opt, arg) in opts:
			logger.info(u"Processing option %s:%s" % (opt, arg))
			if   opt in ("-a", "--host"):
				host = forceUnicode(arg)
			elif opt in ("-p", "--port"):
				port = forceInt(arg)
			elif opt in ("-s", "--skin"):
				skin = forceFilename(arg)
			elif opt in ("-i", "--id"):
				notificationClientId = forceUnicode(arg)
			elif opt in ("-l", "--log-file"):
				logFile = forceFilename(arg)
				if os.path.exists(logFile):
					logger.notice(u"Deleting old log file: %s" % logFile)
					os.unlink(logFile)
				logger.notice(u"Opening log file: %s" % logFile)
				logger.setLogFile(logFile)
				logger.setFileLevel(LOG_DEBUG)
		
		logger.notice(u"Host: %s, port: %s, skin: %s, logfile: %s" % (host, port, skin, logFile))
		w = OpsiDialogWindow()
		w.CreateWindow()
		# PumpMessages runs until PostQuitMessage() is called by someone.
		win32gui.PumpMessages()
	except SystemExit, e:
		pass
		
	except Exception, e:
		exception = e
	
	if exception:
		logger.logException(exception)
		tb = sys.exc_info()[2]
		while (tb != None):
			f = tb.tb_frame
			c = f.f_code
			print >> sys.stderr, u"     line %s in '%s' in file '%s'" % (tb.tb_lineno, c.co_name, c.co_filename)
			tb = tb.tb_next
		print >> sys.stderr, u"ERROR: %s" % exception
		sys.exit(1)
	sys.exit(0)
	


