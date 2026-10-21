"""Local visual like assistant. All input is gated by the selected foreground window."""
import ctypes as C
from ctypes import wintypes as W
import os, sys, json, time, queue, threading, datetime, traceback
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
import cv2
import numpy as np
from PIL import Image, ImageGrab, ImageTk

u = C.windll.user32
try: C.windll.shcore.SetProcessDpiAwareness(2)
except Exception: pass
u.GetForegroundWindow.restype = W.HWND
u.GetAncestor.argtypes = [W.HWND, W.UINT]; u.GetAncestor.restype = W.HWND
u.WindowFromPoint.argtypes = [W.POINT]; u.WindowFromPoint.restype = W.HWND
u.IsWindow.argtypes = [W.HWND]
u.IsIconic.argtypes = [W.HWND]
u.GetWindowRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
u.SetForegroundWindow.argtypes = [W.HWND]
u.ShowWindow.argtypes = [W.HWND, C.c_int]
u.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
u.GetWindowTextLengthW.argtypes = [W.HWND]
u.IsWindowVisible.argtypes = [W.HWND]
u.MonitorFromWindow.argtypes=[W.HWND,W.DWORD];u.MonitorFromWindow.restype=W.HANDLE
class MONITORINFO(C.Structure):
    _fields_=[('cbSize',W.DWORD),('rcMonitor',W.RECT),('rcWork',W.RECT),('dwFlags',W.DWORD)]
u.GetMonitorInfoW.argtypes=[W.HANDLE,C.POINTER(MONITORINFO)]
u.SetWindowPos.argtypes=[W.HWND,W.HWND,C.c_int,C.c_int,C.c_int,C.c_int,W.UINT]
get_style=u.GetWindowLongPtrW if C.sizeof(C.c_void_p)==8 else u.GetWindowLongW
set_style=u.SetWindowLongPtrW if C.sizeof(C.c_void_p)==8 else u.SetWindowLongW
get_style.argtypes=[W.HWND,C.c_int];get_style.restype=C.c_ssize_t
set_style.argtypes=[W.HWND,C.c_int,C.c_ssize_t];set_style.restype=C.c_ssize_t
PTR = C.c_size_t
class MI(C.Structure):
    _fields_ = [('dx', W.LONG), ('dy', W.LONG), ('mouseData', W.DWORD), ('dwFlags', W.DWORD), ('time', W.DWORD), ('dwExtraInfo', PTR)]
class KI(C.Structure):
    _fields_ = [('wVk', W.WORD), ('wScan', W.WORD), ('dwFlags', W.DWORD), ('time', W.DWORD), ('dwExtraInfo', PTR)]
class IU(C.Union):
    _fields_ = [('mi', MI), ('ki', KI)]
class INPUT(C.Structure):
    _anonymous_ = ('v',)
    _fields_ = [('type', W.DWORD), ('v', IU)]
u.SendInput.argtypes = [W.UINT, C.POINTER(INPUT), C.c_int]
u.SendInput.restype = W.UINT
DATA = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'XiaozhanLikeAssistant'
DATA.mkdir(parents=True, exist_ok=True)

def window_title(h):
    b = C.create_unicode_buffer(u.GetWindowTextLengthW(h) + 1)
    u.GetWindowTextW(h, b, len(b)); return b.value

def windows():
    found = []
    @C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    def cb(h, _):
        title = window_title(h)
        if u.IsWindowVisible(h) and title and '识图点赞助手' not in title:
            found.append((int(h), title))
        return True
    u.EnumWindows(cb, 0)
    return sorted(found, key=lambda x: ('异人之下' not in x[1], x[1]))

def rect(h):
    r = W.RECT()
    if not u.IsWindow(h) or not u.GetWindowRect(h, C.byref(r)):
        raise RuntimeError('目标窗口已关闭，请重新选择。')
    if u.IsIconic(h): raise RuntimeError('目标窗口已最小化。')
    return r.left, r.top, r.right, r.bottom

def capture(h):
    if u.GetForegroundWindow() != h: raise RuntimeError('目标窗口不在前台，任务已停止。')
    r = rect(h)
    if r[2]-r[0] < 150 or r[3]-r[1] < 250: raise RuntimeError('目标窗口太小。')
    return np.array(ImageGrab.grab(bbox=r, all_screens=True).convert('RGB'))

def ensure_point(h, x, y):
    if u.GetForegroundWindow() != h: raise RuntimeError('前台窗口已改变，停止操作。')
    left, top, _, _ = rect(h)
    xx, yy = left+int(x), top+int(y)
    hit = u.WindowFromPoint(W.POINT(xx, yy))
    if u.GetAncestor(hit, 2) != h: raise RuntimeError('点击区域被其他窗口遮挡，已停止。')
    u.SetCursorPos(xx, yy)

def mouse(flags, data=0):
    event = INPUT(type=0, mi=MI(0, 0, data & 0xffffffff, flags, 0, 0))
    if u.SendInput(1, C.byref(event), C.sizeof(INPUT)) != 1:
        raise RuntimeError('系统拒绝鼠标操作，请让两个程序使用相同权限运行。')

def color_count(patch):
    hsv = cv2.cvtColor(patch, cv2.COLOR_RGB2HSV)
    return int(np.count_nonzero((hsv[:,:,1] > 85) & (hsv[:,:,2] > 95) & ((hsv[:,:,0] < 30) | (hsv[:,:,0] > 155))))

def find_hearts(rgb, template, base_width, threshold=.90):
    """Return neutral-color template matches in the feed's right action column."""
    H, width = rgb.shape[:2]
    ratio = width / base_width
    x0, x1 = int(width*.68), int(width*.94)
    y0, y1 = max(75, int(width*.18)), H-max(70, int(width*.18))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    source = gray[y0:y1, x0:x1]
    hits = []
    if source.size == 0: return []
    for factor in (.94, 1., 1.06):
        t = cv2.resize(template, None, fx=ratio*factor, fy=ratio*factor, interpolation=cv2.INTER_AREA)
        th, tw = t.shape[:2]
        if min(th,tw) < 5 or th >= source.shape[0] or tw >= source.shape[1]: continue
        result = cv2.matchTemplate(source, t, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(result >= threshold)
        for yy, xx in zip(ys, xs):
            patch = rgb[y0+yy:y0+yy+th, x0+xx:x0+xx+tw]
            if color_count(patch) > max(2, tw*th*.03): continue
            hits.append((float(result[yy,xx]), x0+int(xx), y0+int(yy), tw, th))
    kept=[]
    for item in sorted(hits, reverse=True):
        _, x,y,w,h=item
        if all(abs(x+w/2-(a[1]+a[3]/2)) > max(w,a[3]) or abs(y+h/2-(a[2]+a[4]/2)) > max(h,a[4]) for a in kept): kept.append(item)
    return sorted(kept, key=lambda a:a[2])

def confirmed(before, after):
    return color_count(after)-color_count(before) >= max(5, int(before.shape[0]*before.shape[1]*.06))

def progress_position(target, work, width, height, gap=14):
    left,top,right,bottom=target;wl,wt,wr,wb=work
    candidates=[(right+gap,max(wt,min(top,wb-height))),
                (left-gap-width,max(wt,min(top,wb-height))),
                (max(wl,min(left,wr-width)),bottom+gap),
                (max(wl,min(left,wr-width)),top-gap-height)]
    for x,y in candidates:
        if wl<=x and wt<=y and x+width<=wr and y+height<=wb:
            return x,y
    raise RuntimeError('小程序周围没有足够空间显示进度窗。请把小程序移到屏幕左侧或右侧后再开始。')

class App:
    def __init__(self):
        self.root=tk.Tk(); self.root.title('识图点赞助手')
        self.root.geometry('670x860'); self.root.minsize(620,820)
        self.root.configure(bg='#f5f7f9')
        self.events=queue.Queue(); self.stop_event=threading.Event(); self.running=False
        self.template=None; self.base_width=0; self.thread=None; self.count=0
        self.items=[]; self.preview_refs=[]
        style=ttk.Style(); style.theme_use('clam')
        style.configure('.',font=('Microsoft YaHei UI',10))
        style.configure('TFrame',background='#f5f7f9'); style.configure('TLabel',background='#f5f7f9',foreground='#29343b')
        style.configure('TButton',padding=(12,9)); style.configure('Accent.TButton',background='#187d6b',foreground='white')
        style.configure('TCheckbutton',background='#f5f7f9'); style.configure('TProgressbar',background='#187d6b')
        f=ttk.Frame(self.root,padding=26); f.pack(fill='both',expand=True);self.main_frame=f
        ttk.Label(f,text='识图点赞助手',font=('Microsoft YaHei UI',24,'bold')).pack(anchor='w')
        ttk.Label(f,text='小栈版  ·  图标识别  ·  确认变色后计数',foreground='#74818a').pack(anchor='w',pady=(5,23))
        ttk.Label(f,text='1   选择小程序窗口',font=('Microsoft YaHei UI',11,'bold')).pack(anchor='w')
        row=ttk.Frame(f);row.pack(fill='x',pady=(10,18))
        self.win=ttk.Combobox(row,state='readonly');self.win.pack(side='left',fill='x',expand=True)
        self.refresh_btn=ttk.Button(row,text='刷新',command=self.refresh);self.refresh_btn.pack(side='left',padx=(10,0))
        ttk.Label(f,text='2   校准空心点赞图标',font=('Microsoft YaHei UI',11,'bold')).pack(anchor='w')
        row=ttk.Frame(f);row.pack(fill='x',pady=(10,6))
        self.cal_btn=ttk.Button(row,text='框选空心赞',command=self.calibrate);self.cal_btn.pack(side='left')
        self.preview_btn=ttk.Button(row,text='预览识别（不点击）',command=self.preview);self.preview_btn.pack(side='left',padx=10)
        self.cal_status=ttk.Label(f,text='首次使用：只框心形图标，不包含右侧数字。',foreground='#74818a');self.cal_status.pack(anchor='w',pady=(0,20))
        ttk.Label(f,text='3   设置本次目标',font=('Microsoft YaHei UI',11,'bold')).pack(anchor='w')
        row=ttk.Frame(f);row.pack(fill='x',pady=(10,10))
        self.target=tk.IntVar(value=500);self.delay=tk.DoubleVar(value=3.0)
        self.target_box=ttk.Spinbox(row,from_=1,to=10000,textvariable=self.target,width=8);self.target_box.pack(side='left')
        ttk.Label(row,text='  个新增点赞       间隔 ').pack(side='left')
        self.delay_box=ttk.Spinbox(row,from_=1.5,to=30,increment=.5,textvariable=self.delay,width=5);self.delay_box.pack(side='left')
        ttk.Label(row,text=' 秒').pack(side='left')
        self.auto=tk.BooleanVar(value=True)
        self.auto_box=ttk.Checkbutton(f,text='处理完当前页面后自动下滑',variable=self.auto);self.auto_box.pack(anchor='w')
        row=ttk.Frame(f);row.pack(fill='x',pady=(20,15))
        self.start_btn=ttk.Button(row,text='开始',style='Accent.TButton',command=self.start);self.start_btn.pack(side='left',fill='x',expand=True)
        self.stop_btn=ttk.Button(row,text='停止 · F8',command=self.stop,state='disabled');self.stop_btn.pack(side='left',fill='x',expand=True,padx=(12,0))
        self.counter=ttk.Label(f,text='0 / 500 已确认',font=('Microsoft YaHei UI',24,'bold'),foreground='#187d6b');self.counter.pack(anchor='w')
        self.status=ttk.Label(f,text='就绪 · 计数仅包含本次确认成功的新增点赞',foreground='#74818a');self.status.pack(anchor='w',pady=(5,10))
        self.progress=ttk.Progressbar(f,maximum=500);self.progress.pack(fill='x')
        self.logbox=tk.Text(f,height=7,font=('Microsoft YaHei UI',9),relief='solid',bd=1,bg='white',fg='#41505b',state='disabled',wrap='word');self.logbox.pack(fill='both',expand=True,pady=(15,12))
        ttk.Label(f,text='运行时保持小栈在前台，勿操作鼠标。F8 随时停止。\n已点赞会跳过；状态不明、遮挡或连续无新内容时自动停止。',foreground='#74818a',font=('Microsoft YaHei UI',9)).pack(anchor='w')
        self.run_frame=ttk.Frame(self.root,padding=20)
        ttk.Label(self.run_frame,text='点赞进度',font=('Microsoft YaHei UI',16,'bold')).pack(anchor='w')
        self.run_counter=ttk.Label(self.run_frame,text='0 / 500',font=('Microsoft YaHei UI',27,'bold'),foreground='#187d6b');self.run_counter.pack(anchor='w',pady=(12,8))
        self.run_progress=ttk.Progressbar(self.run_frame,maximum=500);self.run_progress.pack(fill='x')
        self.run_time=ttk.Label(self.run_frame,text='已用时 00:00',foreground='#74818a');self.run_time.pack(anchor='w',pady=(10,5))
        self.run_status=ttk.Label(self.run_frame,text='准备中',wraplength=295);self.run_status.pack(anchor='w',fill='x')
        ttk.Button(self.run_frame,text='停止 · F8',command=self.stop).pack(fill='x',side='bottom',pady=(12,0))
        self.compact=False;self.saved_style=None;self.started_at=0
        self.refresh();self.load_template();self.root.after(100,self.poll)
        self.root.protocol('WM_DELETE_WINDOW',self.close)
        self.log('请先打开小栈帖子列表，框选一个灰色空心心形，再预览识别。')

    def log(self,s):
        line=f'{datetime.datetime.now():%H:%M:%S}  {s}'
        self.logbox.configure(state='normal');self.logbox.insert('end',line+'\n');self.logbox.see('end');self.logbox.configure(state='disabled')
        try:
            with open(DATA/'运行日志.txt','a',encoding='utf-8') as out: out.write(line+'\n')
        except OSError: pass
        if self.compact:self.run_status.configure(text=s)

    def show_running(self,h,goal):
        monitor=u.MonitorFromWindow(h,2);info=MONITORINFO();info.cbSize=C.sizeof(info)
        if not u.GetMonitorInfoW(monitor,C.byref(info)):raise RuntimeError('无法读取显示器可用区域。')
        r=info.rcWork;work=(r.left,r.top,r.right,r.bottom)
        self.root.update_idletasks();self.saved_geometry=self.root.geometry()
        # Reserve the title bar and border as well as the client area.
        x,y=progress_position(rect(h),work,356,354)
        self.main_frame.pack_forget();self.run_frame.pack(fill='both',expand=True)
        self.root.minsize(340,310);self.root.resizable(False,False)
        self.root.geometry(f'340x310{x:+d}{y:+d}');self.root.attributes('-topmost',True)
        self.root.update_idletasks()
        self.run_hwnd=u.GetAncestor(self.root.winfo_id(),2)
        self.saved_style=get_style(self.run_hwnd,-20)
        set_style(self.run_hwnd,-20,self.saved_style|0x08000000) # WS_EX_NOACTIVATE
        u.SetWindowPos(self.run_hwnd,W.HWND(-1),x,y,0,0,0x0011) # NOSIZE | NOACTIVATE
        self.run_counter.configure(text=f'0 / {goal}');self.run_progress.configure(maximum=goal,value=0)
        self.run_status.configure(text='3 秒后开始 · F8 随时停止')
        self.started_at=time.monotonic();self.compact=True

    def restore_main(self):
        if not self.compact:return
        if self.saved_style is not None:set_style(self.run_hwnd,-20,self.saved_style)
        self.root.attributes('-topmost',False);self.run_frame.pack_forget()
        self.main_frame.pack(fill='both',expand=True);self.root.resizable(True,True)
        self.root.minsize(620,820);self.root.geometry(self.saved_geometry)
        self.compact=False;self.root.deiconify()

    def refresh(self):
        self.items=windows();self.win['values']=[f'{title}  [{h}]' for h,title in self.items]
        if self.items:self.win.current(0)

    def selected(self):
        i=self.win.current()
        if i<0 or i>=len(self.items):raise RuntimeError('请先选择目标窗口。')
        h,title=self.items[i]
        if not u.IsWindow(h) or window_title(h)!=title: raise RuntimeError('窗口已改变，请刷新后重新选择。')
        return h

    def front(self,h):
        u.ShowWindow(h,9);u.SetForegroundWindow(h)

    def load_template(self):
        try:
            folder=DATA if (DATA/'heart.png').exists() else Path(getattr(sys,'_MEIPASS',Path(__file__).parent))
            self.template=np.array(Image.open(folder/'heart.png').convert('L'))
            self.base_width=json.loads((folder/'calibration.json').read_text(encoding='utf-8'))['width']
            self.cal_status.configure(text='已载入上次校准；页面缩放改变后请重新校准。')
        except Exception:self.template=None

    def ready_capture(self,action):
        try:h=self.selected();self.root.iconify();self.front(h)
        except Exception as e:messagebox.showerror('无法读取窗口',str(e));return
        def later():
            try:action(capture(h))
            except Exception as e:self.root.deiconify();messagebox.showerror('读取失败',str(e))
        self.root.after(600,later)

    def calibrate(self):
        self.ready_capture(lambda rgb:self.image_dialog(rgb,True))

    def preview(self):
        if self.template is None:messagebox.showinfo('需要校准','先框选一个灰色空心点赞图标。');return
        def action(rgb):
            hits=find_hearts(rgb,self.template,self.base_width)
            shown=rgb.copy()
            for _,x,y,w,h in hits:cv2.rectangle(shown,(x-3,y-3),(x+w+3,y+h+3),(20,170,110),2)
            self.log(f'预览识别到 {len(hits)} 个空心赞（未点击）。')
            self.image_dialog(shown,False,len(hits))
        self.ready_capture(action)

    def image_dialog(self,rgb,calibration,n=0):
        dlg=tk.Toplevel(self.root);dlg.title('框选空心赞' if calibration else f'识别预览 · {n} 个');dlg.attributes('-topmost',True)
        screen_h=self.root.winfo_screenheight();scale=min(1,(screen_h-200)/rgb.shape[0],800/rgb.shape[1])
        im=Image.fromarray(rgb);im=im.resize((int(im.width*scale),int(im.height*scale)))
        photo=ImageTk.PhotoImage(im);dlg._photo=photo
        ttk.Label(dlg,text='拖动框住一个灰色心形，仅含图标，留 1–2 像素白边。' if calibration else '绿色框应只圈住未点赞心形。若位置不对，请重新校准。',padding=10).pack()
        canvas=tk.Canvas(dlg,width=im.width,height=im.height,highlightthickness=0,cursor='crosshair' if calibration else 'arrow');canvas.pack();canvas.create_image(0,0,anchor='nw',image=photo)
        selected={}
        def down(e):selected['start']=(e.x,e.y);selected['box']=canvas.create_rectangle(e.x,e.y,e.x,e.y,outline='#0aab78',width=2)
        def move(e):
            if 'start' in selected:canvas.coords(selected['box'],*selected['start'],e.x,e.y)
        def up(e):
            if 'start' not in selected:return
            x,y=selected['start'];x0,x1=sorted((int(x/scale),int(e.x/scale)));y0,y1=sorted((int(y/scale),int(e.y/scale)))
            x0=max(0,x0);y0=max(0,y0);x1=min(rgb.shape[1],x1);y1=min(rgb.shape[0],y1)
            if not(8<=x1-x0<=65 and 8<=y1-y0<=65):messagebox.showinfo('重新框选','图标框的宽高须在 8–65 像素之间。',parent=dlg);return
            patch=rgb[y0:y1,x0:x1]
            if color_count(patch)>max(2,patch.shape[0]*patch.shape[1]*.03):messagebox.showinfo('请选择空心赞','框内有明显彩色像素，请选择灰色空心心形。',parent=dlg);return
            template=cv2.cvtColor(patch,cv2.COLOR_RGB2GRAY)
            if template.std()<8:messagebox.showinfo('重新框选','框内缺少图标细节。',parent=dlg);return
            self.template=template;self.base_width=rgb.shape[1]
            Image.fromarray(template).save(DATA/'heart.png')
            (DATA/'calibration.json').write_text(json.dumps({'width':self.base_width}),encoding='utf-8')
            self.cal_status.configure(text=f'已校准 {x1-x0} × {y1-y0} 像素；建议先预览识别。')
            self.log('校准完成。');finish()
        def finish():dlg.destroy();self.root.deiconify()
        if calibration:canvas.bind('<ButtonPress-1>',down);canvas.bind('<B1-Motion>',move);canvas.bind('<ButtonRelease-1>',up)
        ttk.Button(dlg,text='关闭',command=finish).pack(pady=10);dlg.protocol('WM_DELETE_WINDOW',finish)

    def start(self):
        try:
            h=self.selected();goal=int(self.target.get());delay=float(self.delay.get())
            if not 1<=goal<=10000 or not 1.5<=delay<=30:raise ValueError('数量范围 1–10000，间隔范围 1.5–30 秒。')
            if self.template is None:raise ValueError('请先框选空心点赞图标。')
            self.show_running(h,goal)
        except Exception as e:messagebox.showerror('无法开始',str(e));return
        self.running=True;self.count=0;self.stop_event.clear();self.progress.configure(maximum=goal,value=0)
        self.counter.configure(text=f'0 / {goal} 已确认');self.status.configure(text='运行中 · F8 随时停止')
        for widget in (self.win,self.refresh_btn,self.cal_btn,self.preview_btn,self.target_box,self.delay_box,self.start_btn,self.auto_box):widget.configure(state='disabled')
        self.stop_btn.configure(state='normal');self.log(f'开始本次任务，目标 {goal} 个新增点赞；3 秒后执行。')
        self.front(h)
        self.thread=threading.Thread(target=self.worker,args=(h,goal,delay,self.auto.get(),self.template.copy(),self.base_width),daemon=True);self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.compact:self.run_status.configure(text='正在停止，请稍候…')

    def wait(self,seconds):
        if self.stop_event.wait(seconds):raise InterruptedError('已停止。')

    def capture_running(self,h):
        a=rect(h);b=rect(self.run_hwnd)
        if max(a[0],b[0])<min(a[2],b[2]) and max(a[1],b[1])<min(a[3],b[3]):
            raise RuntimeError('进度窗与小程序发生重叠，已停止。请调整窗口位置后重试。')
        return capture(h)

    def worker(self,h,goal,delay,auto,template,base):
        count=0;scrolls=0;unchanged=0;empty=0;attempts=0
        try:
            self.wait(3);initial=self.capture_running(h);size=initial.shape
            while count<goal:
                self.wait(.1);rgb=self.capture_running(h)
                if rgb.shape!=size:raise RuntimeError('窗口尺寸已改变，请重新预览后开始。')
                hits=find_hearts(rgb,template,base)
                if hits:
                    empty=0
                    _,x,y,w,hh=hits[0];before=rgb[y:y+hh,x:x+w].copy()
                    ensure_point(h,x+w//2,y+hh//2)
                    if self.stop_event.is_set():raise InterruptedError('已停止。')
                    mouse(0x0002)
                    mouse(0x0004)
                    attempts+=1;self.events.put(('log',f'已点击，正在确认变色（尝试 {attempts}）。'))
                    ok=False
                    for _ in range(6):
                        self.wait(.5);after=self.capture_running(h)
                        if after.shape!=size:raise RuntimeError('窗口尺寸改变，停止确认。')
                        if confirmed(before,after[y:y+hh,x:x+w]):ok=True;break
                    if not ok:raise RuntimeError('未确认到心形变色，已停止；该次点击不计数，请人工检查。')
                    count+=1;self.events.put(('count',(count,goal)))
                    self.events.put(('log',f'已确认新增点赞 {count} / {goal}。'))
                    if count>=goal:break
                    self.wait(delay)
                    continue
                if not auto:raise RuntimeError('当前页面没有可识别的空心赞，自动下滑未开启。')
                empty+=1
                if empty>=40:raise RuntimeError('连续 40 次下滑没有可确认的新点赞，请检查列表或重新校准。')
                H,ww=rgb.shape[:2];ensure_point(h,int(ww*.52),int(H*.56));mouse(0x0800,-360)
                self.wait(max(1.2,delay));after=self.capture_running(h);scrolls+=1
                if after.shape!=size:raise RuntimeError('窗口尺寸已改变。')
                a=rgb[int(H*.15):int(H*.85),int(ww*.1):int(ww*.9)]
                b=after[int(H*.15):int(H*.85),int(ww*.1):int(ww*.9)]
                diff=np.mean(np.abs(a.astype(float)-b.astype(float)))
                unchanged=unchanged+1 if diff<.8 else 0
                self.events.put(('log',f'已下滑 {scrolls} 次，继续识别。'))
                if unchanged>=5:raise RuntimeError('连续 5 次下滑页面没有变化，可能已到底部或加载停滞。')
            self.events.put(('log',f'任务完成：本次确认 {count} 个新增点赞。'))
        except InterruptedError:self.events.put(('log',f'用户停止；本次已确认 {count} 个。'))
        except Exception as e:self.events.put(('log',f'已停止：{e}'))
        finally:self.events.put(('done',None))

    def poll(self):
        if self.running and u.GetAsyncKeyState(0x77)&0x8000:self.stop_event.set()
        if self.compact:
            elapsed=int(time.monotonic()-self.started_at)
            self.run_time.configure(text=f'已用时 {elapsed//60:02d}:{elapsed%60:02d}')
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='log':self.log(value)
                elif kind=='count':
                    self.count,goal=value;self.counter.configure(text=f'{self.count} / {goal} 已确认');self.progress.configure(value=self.count)
                    self.run_counter.configure(text=f'{self.count} / {goal}');self.run_progress.configure(value=self.count)
                elif kind=='done':
                    self.running=False;self.status.configure(text='已结束 · 可查看下方日志');self.restore_main()
                    for widget in (self.refresh_btn,self.cal_btn,self.preview_btn,self.target_box,self.delay_box,self.start_btn,self.auto_box):widget.configure(state='normal')
                    self.win.configure(state='readonly');self.stop_btn.configure(state='disabled')
        except queue.Empty:pass
        self.root.after(80,self.poll)

    def close(self):
        self.stop_event.set()
        if self.thread and self.thread.is_alive():self.root.after(100,self.close)
        else:self.root.destroy()

if __name__=='__main__':
    try:App().root.mainloop()
    except Exception:
        (DATA/'错误日志.txt').write_text(traceback.format_exc(),encoding='utf-8')
        messagebox.showerror('启动失败',f'请查看 {DATA / "错误日志.txt"}')
