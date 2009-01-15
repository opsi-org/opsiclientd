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

__version__ = '0.4'

# Imports
import threading, time, sys, os, getopt
import struct, win32api, win32con, win32ui, win32service, commctrl, timer
from ctypes import *
try:
	# Try to use advanced gui
	import winxpgui as win32gui
except:
	import win32gui

# OPSI imports
from OPSI.Backend.File import File
from OPSI.Util import NotificationClient, SubjectsObserver
from OPSI.Logger import *

# Create logger instance
logger = Logger()

# Globals
logFile = 'status_window.log'
transparentColor = (0,0,0)
host = '127.0.0.1'
port = 4442
skin = 'skin.ini'

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


class OpsiDialogWindow(SubjectsObserver):
	def __init__(self):
		win32gui.InitCommonControls()
		self.hinst = win32api.GetModuleHandle(None)
		self.taskbarNotifyEventId = win32con.WM_USER + 20
		self.hidden = False
		self.alpha = 255
		
		try:
			self.hicon = win32gui.LoadIcon(self.hinst, 1)    ## python.exe and pythonw.exe
		except win32gui.error:
			self.hicon = win32gui.LoadIcon(self.hinst, 135)  ## pythonwin's icon
		
		self.wndClassName = "opsi status"
		
		self.loadSkin()
		
		self._notificationClient = NotificationClient(host, port, self)
		
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
		wc.hIcon = self.hicon
		try:
			classAtom = win32gui.RegisterClass(wc)
		except win32gui.error, err_info:
			if err_info[0]!=winerror.ERROR_CLASS_ALREADY_EXISTS:
				raise
		return self.wndClassName
	
	def loadSkin(self):
		def toRGB(value):
			color = value.split(',')
			return win32api.RGB(int(color[0]), int(color[1]), int(color[2]))
		
		def toStyle(value, type=None):
			logger.debug("toStyle() value: %s, type: %s" % (value, type))
			if   ( str(value).lower() == 'left' ):
				if (type == 'button'):
					return win32con.BS_LEFT
				return win32con.ES_LEFT
			elif ( str(value).lower() == 'right' ):
				if (type == 'button'):
					return win32con.BS_RIGHT
				return win32con.ES_RIGHT
			elif ( str(value).lower() in ('center', 'middle') ):
				if (type == 'button'):
					return win32con.BS_CENTER
				return win32con.ES_CENTER
			return 0
			
		def toBool(value):
			if str(value).lower() in ('0', 'false', 'off', 'no', 'nein', ''):
				return False
			return True
		
		
		ini = File().readIniFile(skin)
		
		self.skin = {
			'form': {
				'type':      'form',
				'width':     200,
				'height':    200,
				'top':       0,
				'left':      0,
				'font':      win32gui.LOGFONT(),
				'fontColor': win32api.RGB(255, 255, 255),
				'color':     win32api.RGB(255, 255, 255),
				'text':      'Opsi',
				'style':     0,
				'stayOnTop': False,
				'fadeIn':    False,
				'icon':      None,
				'systray':   False
			}
		}
		
		for section in ini.sections():
			sec = section.strip().lower()
			item = sec
			
			if (item != 'form'):
				(type, id) = ('', '')
				if   item.startswith('label'):
					(type, id) = ('label', item[5:])
				elif item.startswith('image'):
					(type, id) = ('image', item[5:])
				elif item.startswith('button'):
					(type, id) = ('button', item[6:])
				else:
					logger.error("Unkown type '%s' in ini" % item)
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
					'text':      '',
				}
			
			for (key, value) in ini.items(section):
				key = key.lower()
				if    (key == 'color'):         self.skin[item]['color'] = toRGB(value)
				elif  (key == 'transparent'):   self.skin[item]['transparent'] = toBool(value)
				elif  (key == 'frame') and toBool(value): self.skin[item]['style'] |= win32con.WS_CAPTION #|= win32con.WS_POPUP
				elif  (key == 'closeable') and toBool(value): self.skin[item]['style'] |= win32con.WS_SYSMENU
				elif  (key == 'resizable') and toBool(value): self.skin[item]['style'] |= win32con.WS_THICKFRAME
				elif  (key == 'minimizable') and toBool(value): self.skin[item]['style'] |= win32con.WS_MINIMIZEBOX
				elif  (key == 'systray'):       self.skin[item]['systray'] = toBool(value)
				elif  (key == 'left'):          self.skin[item]['left'] = int(value)
				elif  (key == 'top'):           self.skin[item]['top'] = int(value)
				elif  (key == 'width'):         self.skin[item]['width'] = int(value)
				elif  (key == 'height'):        self.skin[item]['height'] = int(value)
				elif  (key == 'fontname'):      self.skin[item]['font'].lfFaceName = value.strip()
				elif  (key == 'fontsize'):      self.skin[item]['font'].lfHeight = int(value)
				elif  (key == 'fontweight'):    self.skin[item]['font'].lfWeight = int(value)
				elif  (key == 'fontitalic'):    self.skin[item]['font'].lfItalic = toBool(value)
				elif  (key == 'fontunderline'): self.skin[item]['font'].lfUnderline = toBool(value)
				elif  (key == 'fontbold') and toBool(value): self.skin[item]['font'].lfWeight = 700
				elif  (key == 'fontcolor'):     self.skin[item]['fontColor'] = toRGB(value)
				elif  (key == 'text'):          self.skin[item]['text'] = value.strip()
				elif  (key == 'alignment'):     self.skin[item]['alignment'] = toStyle(value, self.skin[item]['type'])
				elif  (key == 'file'):          self.skin[item]['file'] = value.strip()
				elif  (key == 'icon'):          self.skin[item]['icon'] = value
				elif  (key == 'active'):        self.skin[item]['active'] = toBool(value)
				elif  (key == 'stayontop'):     self.skin[item]['stayOnTop'] = toBool(value)
				elif  (key == 'fadein'):        self.skin[item]['fadeIn'] = toBool(value)
				elif  (key == 'subjectid'):     self.skin[item]['subjectId'] = value.strip()
				elif  (key == 'choiceindex'):   self.skin[item]['choiceIndex'] = int(value)
				elif  (section.lower() == 'form') and (key == 'hidden') and toBool(value):
					self.hidden = True
		
		desktop = win32gui.GetDesktopWindow()
		(l, t, r, b) = win32gui.GetWindowRect(desktop)
		(centreX, centreY) = win32gui.ClientToScreen( desktop, ((r-l)/2, (b-t)/2) )
		
		if (self.skin['form']['left'] < 0):
			self.skin['form']['left'] = centreX*2 - (-1*self.skin['form']['left']) - self.skin['form']['width']
		if (self.skin['form']['left'] == 0):
			self.skin['form']['left'] = centreX - int(self.skin['form']['width']/2)
		if (self.skin['form']['left'] < 0):
			self.skin['form']['left'] = 0
		
		if (self.skin['form']['top'] < 0):
			self.skin['form']['top'] = centreY*2 - (-1*self.skin['form']['top']) - self.skin['form']['height']
		if (self.skin['form']['top'] == 0):
			self.skin['form']['top'] = centreY - int(self.skin['form']['height']/2)
		if (self.skin['form']['top'] < 0):
			self.skin['form']['top'] = 0
		
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
		
		# Window frame and title
		style = win32con.DS_SETFONT | win32con.WS_POPUP # win32con.WS_VISIBLE | win32con.WS_EX_TRANSPARENT
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
				dlg.append( ['Static', values.get('text', ''),
					dlgId,
					( int(values['left']/2), int(values['top']/2), int(values['width']/2), int(values['height']/2) ),
					style ] )
				self.skin[item]['id'] = item[5:]
			
			elif item.startswith('button'):
				# win32con.BS_DEFPUSHBUTTON
				style |= win32con.BS_MULTILINE | win32con.BS_PUSHBUTTON | win32con.MF_GRAYED #| win32con.BS_OWNERDRAW
				dlg.append( ['Button', values.get('text', ''),
					dlgId,
					( int(values['left']/2), int(values['top']/2), int(values['width']/2), int(values['height']/2) ),
					style ] )
			
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
			self.taskbarNotifyEventId:	self.onTaskbarNotify,
			#win32con.WM_DRAWITEM:         self.onDrawItem,
			#win32con.WM_PAINT:            self.onPaint,
			#win32con.WM_ERASEBKGND:       self.onEraseBkgnd,
			#win32con.WM_SIZE: 		self.onSize,
			#win32con.WM_NOTIFY: 		self.onNotify,
		}
		self._registerWndClass()
		
		template = self._getDialogTemplate()
		
		win32gui.CreateDialogIndirect(self.hinst, template, 0, message_map)
		
		if self.skin['form']['systray']:
			self.createTrayIcon()
		
		self.setButtonFonts()
		
		if self.skin['form']['fadeIn']:
			self.alpha = 0
			self.setWindowAlpha(self.alpha)
			timer.set_timer(50, self.fadein)

		if not self.hidden:
			if (sys.getwindowsversion()[0] == 6):
				desktop = win32service.OpenInputDesktop(0, True, win32con.MAXIMUM_ALLOWED)
				desktopName = win32service.GetUserObjectInformation(desktop, win32service.UOI_NAME)
				if (desktopName.lower() == "winlogon"):
					# On NT6 we need this for window to show up on winlogon desktop
					win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWMINIMIZED)
					win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWMAXIMIZED)
			
			insertAfter = win32con.HWND_TOP
			if self.skin['form'].get('stayOnTop'):
				insertAfter = win32con.HWND_TOPMOST
			win32gui.SetWindowPos(	self.hwnd,
						insertAfter,
						self.skin['form']['left'],
						self.skin['form']['top'],
						self.skin['form']['width'],
						self.skin['form']['height'],
						win32con.SWP_SHOWWINDOW )
		
		threading.Timer(0.01, self._notificationClient.start).start()
		
	def fadein(self, id, time):
		self.setWindowAlpha(self.alpha)
		self.alpha += 25
		if (self.alpha > 255):
			timer.kill_timer(id)
	
	def createTrayIcon(self):
		try:
			flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
			notifyInfo = (self.hwnd, 0, flags, self.taskbarNotifyEventId, self.hicon, 'opsi status')
			win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, notifyInfo)
		except Exception, e:
			logger.error("Failed to create tray icon: %s" % e)
	
	def removeTrayIcon(self):
		try:
			flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
			notifyInfo = (self.hwnd, 0, flags, self.taskbarNotifyEventId, self.hicon, 'opsi status')
			win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, notifyInfo)
		except Exception, e:
			logger.error("Failed to remove tray icon: %s" % e)
	
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
			if (values.get('type') != 'button'):
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
		logger.debug2("onEraseBkgnd")
		return 0
	
	def onDrawItem(self, hwnd, msg, wparam, lparam):
		logger.debug2("onDrawItem")
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
			if not values.get('dlgId'):
				continue
			if (win32gui.GetDlgItem(self.hwnd, values['dlgId']) == lparam):
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
		for (item, values) in self.skin.items():
			if (values['type'] == 'image') and values.get('bitmap'):
				bmCtrl = win32gui.GetDlgItem(self.hwnd, values['dlgId'])
				win32gui.SendMessage(bmCtrl, win32con.STM_SETIMAGE, win32con.IMAGE_BITMAP, values['bitmap'])
			if (values['type'] == 'button') and not values.get('active'):
				win32gui.EnableWindow(win32gui.GetDlgItem(self.hwnd, values['dlgId']), False)
	
	def onClose(self, hwnd, msg, wparam, lparam):
		try:
			self.removeTrayIcon()
		except:
			pass
		win32gui.DestroyWindow(hwnd)
	
	def onDestroy(self, hwnd, msg, wparam, lparam):
		logger.notice("Exiting...")
		self._notificationClient.stop()
		win32gui.PostQuitMessage(0) # Terminate the app.
	
	def onCommand(self, hwnd, msg, wparam, lparam):
		dlgId = win32api.LOWORD(wparam)
		logger.debug2("onCommand dlgId: %s" % dlgId)
		for (item, values) in self.skin.items():
			if not values.get('dlgId') or (dlgId != values['dlgId']):
				continue
			
			if (values.get('type') == 'button'):
				if (values['id'] == 'exit'):
					if self._notificationClient:
						self._notificationClient.stop()
					win32gui.PostQuitMessage(0)
				
				subjectId = values.get('subjectId')
				choiceIndex = values.get('choiceIndex')
				logger.info("Button subjectId: %s, choiceIndex: %s" % (subjectId, choiceIndex))
				if (subjectId and (choiceIndex >= 0)):
					self._notificationClient.setSelectedIndex(subjectId, choiceIndex)
					self._notificationClient.selectChoice(subjectId)
			
			elif (values.get('type') == 'label'):
				cwnd = win32ui.CreateWindowFromHandle(self.hwnd)
				cwnd.SetDlgItemText(dlgId, values.get('text', ''))
				self.refreshDialogItem(dlgId)
			break
		
	def setWindowAlpha(self, alpha):
		# Set WS_EX_LAYERED
		style = win32gui.GetWindowLong(self.hwnd, win32con.GWL_EXSTYLE)
		win32gui.SetWindowLong(self.hwnd, win32con.GWL_EXSTYLE, style | win32con.WS_EX_LAYERED)
		
		win32gui.SetLayeredWindowAttributes(self.hwnd, 0, alpha, win32con.LWA_ALPHA);
		
		return
		#screenDC = win32gui.GetDC(win32gui.GetDesktopWindow())
		hdc = win32gui.CreateCompatibleDC(None)
		
		blend = BLENDFUNCTION(win32con.AC_SRC_OVER, 0, alpha, 0)
		size = SIZE(400,400)
		pointSrc = POINT(200,0)
		windll.user32.UpdateLayeredWindow(self.hwnd, None, None, byref(size), hdc, byref(pointSrc), 0, byref(blend), win32con.ULW_ALPHA);

		return
		
		screenDC = win32gui.GetDC(win32gui.GetDesktopWindow())
		cScreenDC = win32gui.CreateCompatibleDC(screenDC)
		
		win32gui.SelectObject(cScreenDC, self.skin['imagebg']['bitmap'])
		point1 = POINT(200,0)
		size1 = SIZE(400,400)
		point2 = POINT(0,0)
		blend = BLENDFUNCTION(0, 0, alpha, 1)
		ret = windll.user32.UpdateLayeredWindow(
						self.hwnd,
						screenDC,
						byref(point1),
						byref(size1),
						cScreenDC,
						byref(point2),
						win32api.RGB(255,0,0),
						byref(blend),
						win32con.ULW_ALPHA)
		return ret
	
	def setStatusMessage(self, message):
		for (item, values) in self.skin.items():
			if values.get('dlgId') and (values.get('id') == 'status') and values.get('subjectId'):
				self.messageChanged(values.get('subjectId'), message)
				break
		
	def messageChanged(self, subject, message):
		subjectId = subject.get('id')
		for (item, values) in self.skin.items():
			if values.get('dlgId') and (values.get('subjectId') == subjectId):
				logger.info("message changed, subjectId: %s, dlgId: %s" % (subjectId, values['dlgId']))
				if (self.skin[item].get('text') != message):
					self.skin[item]['text'] = message
					win32gui.SendMessage(self.hwnd, win32con.WM_COMMAND, values['dlgId'], None)
				break
		
	def selectedIndexChanged(self, subject, selectedIndex):
		pass
	
	def choicesChanged(self, subject, choices):
		pass
	
	def subjectsChanged(self, subjects):
		logger.info("subjectsChanged(%s)" % subjects)
		choices = {}
		for subject in subjects:
			if (subject['class'] == 'MessageSubject'):
				self.messageChanged(subject, subject['message'])
			if (subject['class'] == 'ChoiceSubject'):
				subjectId = subject.get('id')
				choices[subjectId] = subject.get('choices', [])
		
		for (item, values) in self.skin.items():
			if (values['type'] != 'button') or not values.get('dlgId') or not values.get('subjectId'):
				continue
			if values.get('subjectId') in choices.keys():
				choiceIndex = values.get('choiceIndex', -1)
				if (choiceIndex >= 0):
					dlg = win32gui.GetDlgItem(self.hwnd, values['dlgId'])
					if (choiceIndex < len(choices[subjectId])):
						win32gui.SetWindowText(dlg, choices[subjectId][choiceIndex])
						win32gui.EnableWindow(dlg, True)
					else:
						win32gui.SetWindowText(dlg, "")
						win32gui.EnableWindow(dlg, False)
			else:
				win32gui.EnableWindow(win32gui.GetDlgItem(self.hwnd, values.get('dlgId')), False)
		logger.debug("subjectsChanged() ended")

def usage():
	print "\nUsage: %s [-h <host>] [-p <port>] [-s <skin>]" % os.path.basename(sys.argv[0])
	print "Options:"
	print "  -h, --host      Notification server host (default: %s)" % host
	print "  -p, --port      Notification server port (default: %s)" % port
	print "  -s, --skin      Skin to use (default: %s)" % skin

if (__name__ == "__main__"):
	# If you write to stdout when running from pythonw.exe program will die !!!
	logger.setConsoleLevel(LOG_NONE)
	exception = None
	
	try:
		os.chdir(os.path.dirname(sys.argv[0]))
		
		if os.path.exists(logFile):
			logger.notice("Deleting old log file: %s" % logFile)
			os.unlink(logFile)
		logger.notice("Opening log file: %s" % logFile)
		logger.setLogFile(logFile)
		logger.setFileLevel(LOG_DEBUG)
		
		logger.notice("Commandline: %s" % ' '.join(sys.argv))
		
		# Process command line arguments
		try:
			(opts, args) = getopt.getopt(sys.argv[1:], "h:p:s:", [ "host=", "port=", "skin=" ])
		except getopt.GetoptError:
			usage()
			sys.exit(1)
		
		for (opt, arg) in opts:
			logger.info("Processing option %s:%s" % (opt, arg))
			if   opt in ("-a", "--host"):
				host = arg
			elif opt in ("-p", "--port"):
				port = int(arg)
			elif opt in ("-s", "--skin"):
				skin = arg
		
		logger.notice("Host: %s, port: %s, skin: %s" % (host, port, skin))
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
		print >> sys.stderr, "ERROR:", str(exception)
		sys.exit(1)
	sys.exit(0)
	


