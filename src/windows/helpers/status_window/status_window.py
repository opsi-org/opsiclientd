# -*- coding: utf-8 -*-
import struct
import win32api
import win32con
import win32ui
import commctrl
import threading, time, sys, os
from ctypes import *

from OPSI.Backend.File import File
from OPSI.Util import NotificationClient, NotificationObserver
from OPSI.Logger import *

logger = Logger()

try:
	# Try to use advanced gui
	import winxpgui as win32gui
except:
	import win32gui

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

transparentColor = (0,0,0)

		
class OpsiDialogWindow(NotificationObserver):
	def __init__(self):
		win32gui.InitCommonControls()
		self.hinst = win32gui.dllhandle
		self.wndClassName = "OpsiDialog"
		self._skinFile = 'skin.ini'
		
		self.loadSkin()
		
		self._notificationClient = NotificationClient('127.0.0.1', 4449, self)
		
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
		
		## py.ico went away in python 2.5, load from executable instead
		this_app=win32api.GetModuleHandle(None)
		try:
			wc.hIcon=win32gui.LoadIcon(this_app, 1)    ## python.exe and pythonw.exe
		except win32gui.error:
			wc.hIcon=win32gui.LoadIcon(this_app, 135)  ## pythonwin's icon
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
			print "value: %s, type: %s" % (value, type)
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
		
		ini = File().readIniFile(self._skinFile)
		
		self.skin = {
			'form': {
				'type':      'form',
				'width':     200,
				'height':    200,
				'font':      win32gui.LOGFONT(),
				'fontColor': win32api.RGB(255, 255, 255),
				'color':     win32api.RGB(255, 255, 255),
				'text':      'Opsi',
				'style':     0,
				'stayOnTop': False,
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
					print "Unkown type '%s' in ini" % item
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
				elif  (key == 'active'):        self.skin[item]['active'] = toBool(value)
				elif  (key == 'stayontop'):     self.skin[item]['stayOnTop'] = toBool(value)
				elif  (key == 'subjectid'):     self.skin[item]['subjectId'] = value.strip()
				elif  (key == 'choiceindex'):   self.skin[item]['choiceIndex'] = int(value)
			
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
		style = win32con.WS_VISIBLE | win32con.DS_SETFONT |  win32con.WS_POPUP #| win32con.WS_EX_TRANSPARENT
		if self.skin['form']['style']:
			style |= self.skin['form']['style']
		dlg = [ [ self.skin['form']['text'],
			  (0, 0, self.skin['form']['width'], self.skin['form']['height']),
			  style, None,
			  (self.skin['form']['font'].lfHeight, self.skin['form']['font'].lfFaceName),
			  None, self.wndClassName ], ]
		
		# Create fonts
		for item in self.skin.keys():
			if self.skin[item].get('font'):
				self.skin[item]['font'] = win32gui.CreateFontIndirect(self.skin[item]['font'])
			
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
			print values['file']
			self.skin[item]['bitmap'] = win32gui.LoadImage(
				self.hinst, values['file'], win32con.IMAGE_BITMAP,
				0, 0, win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE )
			
			style |= win32con.SS_BITMAP
			dlg.append( [130, values.get('text', ''),
				dlgId,
				(values['left'], values['top'], values['width'], values['height']),
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
					(values['left'], values['top'], values['width'], values['height']),
					style ] )
				self.skin[item]['id'] = item[5:]
			
			elif item.startswith('button'):
				# win32con.BS_DEFPUSHBUTTON
				style |= win32con.BS_MULTILINE | win32con.BS_PUSHBUTTON | win32con.MF_GRAYED #| win32con.BS_OWNERDRAW
				dlg.append( ['Button', values.get('text', ''),
					dlgId,
					(values['left'], values['top'], values['width'], values['height']),
					style ] )
			
			else:
				continue
			
			self.skin[item]['dlgId'] = dlgId
			dlgId += 1
		
		return dlg
		
	def CreateWindow(self):
		message_map = {
			#win32con.WM_SIZE: self.OnSize,
			win32con.WM_COMMAND:           self.onCommand,
			#win32con.WM_NOTIFY: self.OnNotify,
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
			#win32con.WM_DRAWITEM:          self.onDrawItem,
			#win32con.WM_PAINT:             self.onPaint,
			#win32con.WM_ERASEBKGND:        self.onEraseBkgnd,
		}
		self._registerWndClass()
		
		template = self._getDialogTemplate()
		win32gui.CreateDialogIndirect(self.hinst, template, 0, message_map)
		
		self.setButtonFonts()
		
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
		print "onEraseBkgnd"
		return 0
	
	def onDrawItem(self, hwnd, msg, wparam, lparam):
		print "onDrawItem"
		#win32gui.CreateCompatibleDC()
		return 0
	
	def onCtlColor(self, hwnd, msg, wparam, lparam):
		#win32gui.SelectObject(wparam, self._globalFont)
		#return windll.gdi32.GetStockObject(win32con.HOLLOW_BRUSH)
		logger.debug("onCtlColor")
		color = self.skin['form']['color']
		fontColor = self.skin['form']['fontColor']
		transparent = self.skin['form'].get('transparent', False)
		font = self.skin['form'].get('font', None)
		
		for (item, values) in self.skin.items():
			if not values.get('dlgId'):
				continue
			if (win32gui.GetDlgItem(self.hwnd, values['dlgId']) == lparam):
				logger.debug("Item found")
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
		# Centre the dialog
		desktop = win32gui.GetDesktopWindow()
		l,t,r,b = win32gui.GetWindowRect(self.hwnd)
		dt_l, dt_t, dt_r, dt_b = win32gui.GetWindowRect(desktop)
		centre_x, centre_y = win32gui.ClientToScreen( desktop, ( (dt_r-dt_l)/2, (dt_b-dt_t)/2) )
		#win32gui.MoveWindow(self.hwnd, centre_x-(r/2), centre_y-(b/2), r-l, b-t, 0)
		insertAfter = win32con.HWND_TOP
		if self.skin['form'].get('stayOnTop'):
			insertAfter = win32con.HWND_TOPMOST
		win32gui.SetWindowPos(hwnd, insertAfter, centre_x-(r/2), centre_y-(b/2), r-l, b-t, 0)
		
		for (item, values) in self.skin.items():
			if (values['type'] == 'image') and values.get('bitmap'):
				bmCtrl = win32gui.GetDlgItem(self.hwnd, values['dlgId'])
				win32gui.SendMessage(bmCtrl, win32con.STM_SETIMAGE, win32con.IMAGE_BITMAP, values['bitmap'])
			if (values['type'] == 'button') and not values.get('active'):
				win32gui.EnableWindow(win32gui.GetDlgItem(self.hwnd, values['dlgId']), False)
		
		
		
		# We need this for window to show up on winlogon desktop
		time.sleep(1)
		win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWMINIMIZED)
		time.sleep(1)
		win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWMAXIMIZED)
		win32gui.SetWindowPos(hwnd, insertAfter, centre_x-(r/2), centre_y-(b/2), r-l, b-t, win32con.SWP_SHOWWINDOW)
		
		#win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWMAXIMIZED)
		#win32gui.SetActiveWindow(self.hwnd)
		#win32gui.BringWindowToTop(self.hwnd)
		#win32gui.SetForegroundWindow(self.hwnd)
		
		#self.setWindowAlpha(200)
		
		self._timer = threading.Timer(1, self._notificationClient.start)
		self._timer.start()
		
		
	def onClose(self, hwnd, msg, wparam, lparam):
		win32gui.DestroyWindow(hwnd)
	
	def onDestroy(self, hwnd, msg, wparam, lparam):
		self._notificationClient.stop()
		win32gui.PostQuitMessage(0) # Terminate the app.
	
	def onCommand(self, hwnd, msg, wparam, lparam):
		dlgId = win32api.LOWORD(wparam)
		logger.debug("onCommand dlgId: %s" % dlgId)
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
					print self._notificationClient.setSelectedIndex(subjectId, choiceIndex)
					print self._notificationClient.selectChoice(subjectId)
			
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
		logger.info("subjects changed: %s" % subjects)
		choices = {}
		for subject in subjects:
			if (subject['type'] == 'MessageSubject'):
				self.messageChanged(subject, subject['message'])
			if (subject['type'] == 'ChoiceSubject'):
				subjectId = subject.get('id')
				choices[subjectId] = subject.get('choices', [])
		
		for (item, values) in self.skin.items():
			if (values['type'] != 'button') or not values.get('dlgId') or not values.get('subjectId'):
				continue
			if values.get('subjectId') in choices.keys():
				choiceIndex = values.get('choiceIndex', -1)
				if (choiceIndex >= 0) and (choiceIndex < len(choices[subjectId])):
					dlg = win32gui.GetDlgItem(self.hwnd, values['dlgId'])
					win32gui.SetWindowText(dlg, choices[subjectId][choiceIndex])
					
				win32gui.EnableWindow(win32gui.GetDlgItem(self.hwnd, values.get('dlgId')), True)
			else:
				win32gui.EnableWindow(win32gui.GetDlgItem(self.hwnd, values.get('dlgId')), False)

if (__name__ == "__main__"):
	logger.setConsoleLevel(LOG_DEBUG)
	exception = None
	
	try:
		os.chdir(os.path.dirname(sys.argv[0]))
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
	




