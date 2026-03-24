# --- debug header ---
import sys, platform, site, os
print("[DEBUG] exe:", sys.executable)
print("[DEBUG] py:", platform.python_version(), platform.architecture())
print("[DEBUG] site:", site.getsitepackages()+[site.getusersitepackages()])
print("[DEBUG] PATH first 3:", os.environ.get("PATH","").split(os.pathsep)[:3])
try:
    import win32api
    print("[DEBUG] win32api:", win32api.__file__)
except Exception as e:
    print("[DEBUG] win32api import error:", repr(e))
    raise
# --- end debug header ---



# -*- coding: utf-8 -*-
import time
import ctypes
import random
import win32api, win32gui, win32con
import win32clipboard as wcb
from pywinauto import clipboard
import uiautomation as auto  # pip install uiautomation

# ================= 사용자 설정 =================
CHATROOM_NAME = "차희상"
MESSAGE_TEXT  = "아직 테스트 중 입니다."
DEBUG = True
VERIFY_TAIL_LINES = 30        # 전송 검증: 대화 하단 몇 줄 검사
OPEN_SCAN_LIMIT = 500         # 리스트에서 ↓ 최대 이동 횟수
PAGEDOWN_EVERY = 30           # 몇 번마다 PageDown(VK_NEXT) 해줄지
BRING_TO_FRONT = True         # 디버깅 중엔 전경/복원 강제
STRICT_CHATROOM_MATCH = True  # 못 찾으면 최상단 진입 대신 예외 발생
# =================================================

# ---- Win32 유틸 ----
PBYTE256 = ctypes.c_ubyte * 256
_user32 = ctypes.WinDLL("user32")
GetKeyboardState = _user32.GetKeyboardState
SetKeyboardState = _user32.SetKeyboardState
AttachThreadInput = _user32.AttachThreadInput
GetWindowThreadProcessId = _user32.GetWindowThreadProcessId

SW_RESTORE = 9

# ---- SendInput 구조체 정의 ----
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))
    ]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_ushort),
        ("wParamH", ctypes.c_ushort)
    ]

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))
    ]

class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT)
    ]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("union", INPUT_UNION)
    ]

# SendInput 상수
INPUT_KEYBOARD = 1
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002

def _log(*a):
    if DEBUG:
        print(*a)

def _send_unicode_char(char):
    """
    SendInput API를 사용하여 실제 키보드 타이핑처럼 유니코드 문자를 전송
    한글, 영문, 특수문자 모두 지원
    """
    # KeyDown
    inp_down = INPUT()
    inp_down.type = INPUT_KEYBOARD
    inp_down.union.ki = KEYBDINPUT()
    inp_down.union.ki.wVk = 0
    inp_down.union.ki.wScan = ord(char)
    inp_down.union.ki.dwFlags = KEYEVENTF_UNICODE
    inp_down.union.ki.time = 0
    inp_down.union.ki.dwExtraInfo = None

    # KeyUp
    inp_up = INPUT()
    inp_up.type = INPUT_KEYBOARD
    inp_up.union.ki = KEYBDINPUT()
    inp_up.union.ki.wVk = 0
    inp_up.union.ki.wScan = ord(char)
    inp_up.union.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
    inp_up.union.ki.time = 0
    inp_up.union.ki.dwExtraInfo = None

    # SendInput 호출
    _user32.SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(INPUT))
    time.sleep(0.005)  # KeyDown과 KeyUp 사이 짧은 지연
    _user32.SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(INPUT))

def _type_text_realistically(hwnd, text, min_delay=0.05, max_delay=0.15):
    """
    실제 사람이 타이핑하는 것처럼 각 문자를 개별적으로 입력
    - hwnd: 입력 대상 윈도우 핸들
    - text: 입력할 텍스트
    - min_delay: 문자 간 최소 지연 시간 (초)
    - max_delay: 문자 간 최대 지연 시간 (초)
    """
    try:
        # 입력창에 포커스 설정
        ctrl = auto.ControlFromHandle(hwnd)
        try:
            ctrl.SetFocus()
            time.sleep(0.1)
        except:
            pass

        # 윈도우를 전경으로 가져오기
        try:
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.05)
        except:
            pass

        # 입력창 클릭 (포커스 확실하게)
        _click(hwnd, 12, 12)
        time.sleep(0.05)

        _log(f"[realistic-typing] 시작: '{text}' (총 {len(text)}자)")

        # 각 문자를 개별적으로 타이핑
        for i, char in enumerate(text):
            _send_unicode_char(char)

            # 랜덤한 지연 시간 (실제 타이핑처럼)
            delay = random.uniform(min_delay, max_delay)
            time.sleep(delay)

            if DEBUG and (i + 1) % 10 == 0:
                _log(f"[realistic-typing] {i + 1}/{len(text)} 문자 입력 완료")

        _log(f"[realistic-typing] 완료")
        return True

    except Exception as e:
        _log(f"[realistic-typing] 실패: {e}")
        return False

def PostKeyEx(hwnd, key, shift_keys=[], specialkey=False):
    if not win32gui.IsWindow(hwnd):
        return False
    ThreadId = GetWindowThreadProcessId(hwnd, None)
    win32gui.SendMessage(hwnd, win32con.WM_ACTIVATE, win32con.WA_ACTIVE, 0)
    AttachThreadInput(win32api.GetCurrentThreadId(), ThreadId, True)

    key_state = PBYTE256(); cur_state = PBYTE256()
    GetKeyboardState(ctypes.byref(cur_state))
    for mod in shift_keys:
        if mod == win32con.VK_MENU: specialkey = True
        key_state[mod] |= 0x80
    SetKeyboardState(ctypes.byref(key_state))

    lparam = win32api.MAKELONG(0, win32api.MapVirtualKey(key, 0))
    msg_down = win32con.WM_KEYDOWN if not specialkey else win32con.WM_SYSKEYDOWN
    msg_up   = win32con.WM_KEYUP   if not specialkey else win32con.WM_SYSKEYUP
    win32api.PostMessage(hwnd, msg_down, key, lparam)
    win32api.PostMessage(hwnd, msg_up,   key, lparam | 0xC0000000)
    time.sleep(0.01)

    SetKeyboardState(ctypes.byref(cur_state))
    AttachThreadInput(win32api.GetCurrentThreadId(), ThreadId, False)
    return True

def _enum_children(hwnd):
    kids=[]
    def _cb(h,_): kids.append(h)
    win32gui.EnumChildWindows(hwnd,_cb,None)
    return kids

def _find_child_by_class_recursive(hwnd_parent, class_name):
    h = win32gui.FindWindowEx(hwnd_parent, None, class_name, None)
    if h: return h
    for c in _enum_children(hwnd_parent):
        h = _find_child_by_class_recursive(c, class_name)
        if h: return h
    return 0

def _set_clipboard_text(text):
    wcb.OpenClipboard()
    try:
        wcb.EmptyClipboard()
        wcb.SetClipboardData(win32con.CF_UNICODETEXT, text)
    finally:
        wcb.CloseClipboard()

def _click(hwnd, x=12, y=12):
    lp = win32api.MAKELONG(x, y)
    win32api.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lp)
    win32api.PostMessage(hwnd, win32con.WM_LBUTTONUP,   0,                   lp)
    time.sleep(0.03)

def _ensure_kakao_front(hwnd):
    if not BRING_TO_FRONT:
        return
    try:
        win32gui.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.05)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.05)
    except:
        pass

def _get_text(hwnd, maxlen=4096):
    try:
        buf = ctypes.create_unicode_buffer(maxlen)
        win32api.SendMessage(hwnd, win32con.WM_GETTEXT, maxlen, buf)
        return buf.value
    except:
        return ""

def _send_enter_variants(hwnd, via_root=None):
    """다양한 Enter 조합을 순차 시도. 성공여부(Boolean) 반환."""
    # 1) UIA: Ctrl+Enter, Enter
    try:
        ctrl = auto.ControlFromHandle(hwnd)
        try:
            ctrl.SetFocus(); time.sleep(0.03)
        except: pass
        for keys in ['{ENTER}', '{Ctrl}{Enter}', '{Enter}']:
            try:
                auto.SendKeys(keys, waitTime=0.01)
                _log(f"[send-try] UIA SendKeys: {keys}")
                return True
            except Exception as e:
                _log(f"[send-try] UIA SendKeys 실패: {keys} err={e}")
    except Exception as e:
        _log("[send-try] UIA ControlFromHandle 실패:", e)

    # 2) Low-level: PostKeyEx (Ctrl+Enter → Enter)
    for mods in ([win32con.VK_CONTROL], []):
        try:
            PostKeyEx(hwnd, win32con.VK_RETURN, mods)
            _log(f"[send-try] PostKeyEx VK_RETURN mods={mods}")
            return True
        except Exception as e:
            _log(f"[send-try] PostKeyEx 실패 mods={mods} err={e}")

    # 3) 최후: 루트창에 Enter 시도
    if via_root and win32gui.IsWindow(via_root):
        for mods in ([win32con.VK_CONTROL], []):
            try:
                PostKeyEx(via_root, win32con.VK_RETURN, mods)
                _log(f"[send-try] root VK_RETURN mods={mods}")
                return True
            except Exception as e:
                _log(f"[send-try] root VK_RETURN 실패 mods={mods} err={e}")
    return False

# ------------- (A) 채팅방 열기 -------------
def open_chatroom(name):
    kakao = win32gui.FindWindow(None, "카카오톡")
    if not kakao: raise Exception("카카오톡 창 없음")
    _ensure_kakao_front(kakao)

    child = win32gui.FindWindowEx(kakao, None, "EVA_ChildWindow", None) or \
            _find_child_by_class_recursive(kakao, "EVA_ChildWindow")
    if not child: raise Exception("EVA_ChildWindow 없음")

    # 좌/우 패널
    wnd1 = win32gui.FindWindowEx(child, None, "EVA_Window", None)
    wnd2 = win32gui.FindWindowEx(child, wnd1, "EVA_Window", None)
    if not wnd2:
        # 백업: child 하위 EVA_Window 2개 모아 두 번째
        cands=[]
        def _cb(h,_):
            if win32gui.GetClassName(h)=="EVA_Window": cands.append(h)
        win32gui.EnumChildWindows(child,_cb,None)
        if len(cands)>=2: wnd2=cands[1]
    if not wnd2: raise Exception("채팅목록 패널 탐색 실패")

    # 검색어 넣기
    search_edit = win32gui.FindWindowEx(wnd2, None, "Edit", None) or \
                  _find_child_by_class_recursive(wnd2,"Edit")
    if not search_edit: raise Exception("검색 입력창(Edit) 없음")
    win32api.SendMessage(search_edit, win32con.WM_SETTEXT, 0, name)
    time.sleep(0.25)

    # 리스트 찾기 (SearchListCtrl 우선)
    def _lists(parent):
        out=[]
        for h in _enum_children(parent):
            if win32gui.GetClassName(h)=="EVA_VH_ListControl_Dblclk":
                out.append((win32gui.GetWindowText(h) or "", h))
        return out
    list_hwnd = 0
    list_title = ""
    for t,h in _lists(wnd2)+_lists(child):
        if "SearchListCtrl" in t:
            list_hwnd=h
            list_title=t
            break
    if not list_hwnd:
        for t,h in _lists(wnd2)+_lists(child):
            if "ChatRoomListCtrl" in t:
                list_hwnd=h
                list_title=t
                break
    if not list_hwnd:
        lst=_lists(child)
        if lst:
            list_title, list_hwnd = lst[0]
    if not list_hwnd: raise Exception("채팅 리스트 컨트롤 없음")

    # 리스트에 포커스 강제: UIA SetFocus + 실제 클릭
    list_ctrl = auto.ControlFromHandle(list_hwnd)
    try:
        list_ctrl.SetFocus()
        time.sleep(0.05)
    except: pass
    _click(list_hwnd, 14, 14)
    time.sleep(0.05)

    # HOME → 포커스 기반 스캔
    PostKeyEx(list_hwnd, win32con.VK_HOME, [])
    time.sleep(0.05)

    target = name.strip()
    found = False
    for i in range(OPEN_SCAN_LIMIT):
        foc = auto.GetFocusedControl()
        foc_name = (getattr(foc, "Name", "") or "").strip() if foc else ""

        if DEBUG and i % 10 == 0:
            _log(f"[scan] focus='{foc_name}'")

        if foc_name and (foc_name == target or target in foc_name):
            PostKeyEx(list_hwnd, win32con.VK_RETURN, [])
            time.sleep(0.6)
            found = True
            break

        # 아래로 이동
        PostKeyEx(list_hwnd, win32con.VK_DOWN, [])
        time.sleep(0.02)

        # 주기적으로 PageDown (VK_NEXT)
        if (i+1) % PAGEDOWN_EVERY == 0:
            PostKeyEx(list_hwnd, win32con.VK_NEXT, [])
            time.sleep(0.06)

        # 포커스가 다른 앱(예: 명령 프롬프트)으로 튀면 다시 전경/포커스 강제
        if foc_name == "" or foc_name == "명령 프롬프트":
            _ensure_kakao_front(kakao)
            try:
                list_ctrl.SetFocus()
                time.sleep(0.03)
            except:
                pass
            _click(list_hwnd, 14, 14)
            time.sleep(0.03)

    if not found:
        message = f"[open_chatroom] 대상 '{target}' 을(를) 찾지 못했습니다."
        # 검색 결과 전용 리스트라면 포커스 이름을 못 읽더라도 첫 검색 결과는
        # 안전하게 여는 편이 실제 사용성에 더 가깝다.
        if "SearchListCtrl" in list_title:
            _log(message, "검색 결과 첫 항목으로 진입합니다.")
            PostKeyEx(list_hwnd, win32con.VK_HOME, [])
            time.sleep(0.05)
            PostKeyEx(list_hwnd, win32con.VK_RETURN, [])
            time.sleep(0.6)
            return
        if STRICT_CHATROOM_MATCH:
            _log(message, "검색 결과 리스트가 아니므로 진입을 중단합니다.")
            raise Exception(message)
        _log(message, "최상단 입장 시도")
        PostKeyEx(list_hwnd, win32con.VK_HOME, [])
        time.sleep(0.05)
        PostKeyEx(list_hwnd, win32con.VK_RETURN, [])
        time.sleep(0.6)

# --------------- (B) 입력창 찾기 (Win32) ---------------
def _collect_all_class_recursive(hwnd_parent, class_name, out):
    h = win32gui.FindWindowEx(hwnd_parent, None, class_name, None)
    while h:
        out.append(h)
        h = win32gui.FindWindowEx(hwnd_parent, h, class_name, None)
    for c in _enum_children(hwnd_parent):
        _collect_all_class_recursive(c, class_name, out)

def _get_rect(hwnd):
    try:
        return win32gui.GetWindowRect(hwnd)  # (l,t,r,b)
    except:
        return (0,0,0,0)

def _get_list_bottom(root_hwnd):
    lst = _find_child_by_class_recursive(root_hwnd, "EVA_VH_ListControl_Dblclk")
    if not lst:
        return None
    l,t,r,b = _get_rect(lst)
    return b

def _probe_edit_can_setget(hwnd):
    """WM_SETTEXT/GETTEXT가 먹는지 테스트 (입력창 판별 보조)"""
    token = "__PROBE_TOKEN__"
    try:
        win32api.SendMessage(hwnd, win32con.WM_SETTEXT, 0, token)
        time.sleep(0.03)
        buf = ctypes.create_unicode_buffer(1024)
        win32api.SendMessage(hwnd, win32con.WM_GETTEXT, 1024, buf)
        ok = (buf.value == token)
        # 지우기
        win32api.SendMessage(hwnd, win32con.WM_SETTEXT, 0, "")
        time.sleep(0.02)
        return ok
    except:
        return False

def _find_input_edit_win32(root_hwnd):
    """
    카카오톡 입력창 찾기(우선순위: RichEdit 계열 → 일반 Edit)
    - 너무 작은/0사이즈 컨트롤 제외
    - 대화 리스트 하단 근처에 위치한 컨트롤 우선
    - WM_SETTEXT/GETTEXT probe로 2차 필터링
    """
    priority_classes = [
        "RICHEDIT50W", "RichEdit50W",
        "RICHEDIT20W", "RichEdit20W",
        "EVA_ChatEdit", "EVA_RichEdit",
        "Edit",
    ]

    def _gather(class_name):
        items=[]
        _collect_all_class_recursive(root_hwnd, class_name, items)
        # 가시성 우선
        return [h for h in items if win32gui.IsWindowVisible(h)]

    chat_bottom = _get_list_bottom(root_hwnd)
    rl, rt, rr, rb = _get_rect(root_hwnd)

    best = []  # (prio, dist, -w, hwnd, rect)

    for prio, cls in enumerate(priority_classes):
        handles = _gather(cls)
        for h in handles:
            l,t,r,b = _get_rect(h)
            w,hgt = (r-l),(b-t)
            # 0사이즈/너무 작은 컨트롤 제외
            if w <= 0 or hgt <= 0:
                continue
            if w < 160 or hgt < 16:
                continue
            # 대화 리스트 하단 근처에 있어야 함(허용 오차 20px)
            if chat_bottom is not None and t < chat_bottom - 20:
                continue
            dist = 999999 if chat_bottom is None else abs(t - chat_bottom)
            best.append((prio, dist, -w, h, (l,t,r,b), cls))

    # 후순위: 아무 것도 못 찾았으면 모든 후보(클래스 무관) 중 가장 아래쪽/큰 것
    if not best:
        fallbacks=[]
        all_classes = set(priority_classes)
        for cls in list(all_classes):
            for h in _gather(cls):
                l,t,r,b = _get_rect(h)
                w,hgt = (r-l),(b-t)
                if w <= 0 or hgt <= 0:
                    continue
                fallbacks.append((99, 10**9 - b, -w, h, (l,t,r,b), cls))
        best = fallbacks

    best.sort(key=lambda x: (x[0], x[1], x[2]))

    # 상위 몇 개만 probe
    for prio, dist, negw, h, rect, cls in best[:8]:
        _log(f"[edit-cand] cls={cls} hwnd={h} rect={rect}")
        if _probe_edit_can_setget(h):
            _log(f"[edit-probe] OK hwnd={h} cls={cls}")
            return h

    # probe 다 실패하면 1순위 반환(로그 남김)
    if best:
        _log("[edit-pick-fallback]", best[0])
        return best[0][3]
    return None

# ------------- (C) 메시지 수신/검증 -------------
def get_chat_text(chatroom):
    root = _get_chat_root_window(chatroom)
    if not root:
        raise Exception(f"'{chatroom}' 또는 '카카오톡' 창을 찾지 못했습니다.")
    lst = _find_child_by_class_recursive(root, "EVA_VH_ListControl_Dblclk")
    if not lst:
        raise Exception("대화 리스트 컨트롤(EVA_VH_ListControl_Dblclk) 없음")
    PostKeyEx(lst, ord('A'), [win32con.VK_CONTROL]); time.sleep(0.06)
    PostKeyEx(lst, ord('C'), [win32con.VK_CONTROL]); time.sleep(0.06)
    try:
        return clipboard.GetData()
    except Exception as e:
        raise Exception("클립보드 읽기 실패: " + str(e))

# ------------- (D) 발신 + 검증 -------------
def _get_chat_root_window(chatroom):
    return win32gui.FindWindow(None, chatroom) or win32gui.FindWindow(None, "카카오톡")

def send_message_and_verify(chatroom, text):
    root = _get_chat_root_window(chatroom)
    if not root:
        raise Exception(f"'{chatroom}' 또는 '카카오톡' 창 없음")

    # 전경 강제 (UIA SendKeys 안정화)
    _ensure_kakao_front(root)

    before = get_chat_text(chatroom)  # 전송 전 스냅샷

    # Win32로 입력창 찾기
    hwndEdit = _find_input_edit_win32(root)
    if not hwndEdit:
        raise Exception("보이는 Edit 입력창 후보를 찾지 못했습니다.")

    # 🔥 우선순위 1) 실제 키보드 타이핑 시뮬레이션 (SendInput API 사용)
    sent = False
    try:
        _log("[send] 실제 타이핑 시뮬레이션 시도 중...")
        if _type_text_realistically(hwndEdit, text):
            time.sleep(0.3)  # 입력 완료 후 잠시 대기
            # 입력창 텍스트 확인
            cur_txt = _get_text(hwndEdit)
            _log(f"[send] realistic-typing 후 입력창 내용: '{cur_txt[:50]}...'")
            # Enter 전송
            if _send_enter_variants(hwndEdit, via_root=root):
                sent = True
                _log("[send] ✅ 실제 타이핑 시뮬레이션 + Enter 성공")
    except Exception as e:
        _log(f"[send] ❌ 실제 타이핑 시뮬레이션 실패: {e}")

    # 2) UIA SendKeys로 타이핑 (백업 방법)
    if not sent:
        try:
            _log("[send] UIA SendKeys 시도 중...")
            ctrl = auto.ControlFromHandle(hwndEdit)
            try:
                ctrl.SetFocus(); time.sleep(0.05)
            except: pass
            auto.SendKeys(text, waitTime=0.01)
            time.sleep(0.07)
            cur_txt = _get_text(hwndEdit)
            _log(f"[send] typed via UIA, edit_now='{cur_txt[:50]}...'")
            if _send_enter_variants(hwndEdit, via_root=root):
                sent=True
                _log("[send] UIA SendKeys + Enter 완료")
        except Exception as e:
            _log(f"[send] UIA SendKeys 실패: {e}")

    # 3) 붙여넣기 → Enter
    if not sent:
        try:
            _log("[send] WM_PASTE 시도 중...")
            _set_clipboard_text(text)
            win32api.SendMessage(hwndEdit, win32con.WM_PASTE, 0, 0)
            time.sleep(0.05)
            cur_txt = _get_text(hwndEdit)
            _log(f"[send] pasted, edit_now='{cur_txt[:50]}...'")
            if _send_enter_variants(hwndEdit, via_root=root):
                sent=True
                _log("[send] WM_PASTE + Enter 완료")
        except Exception as e:
            _log(f"[send] WM_PASTE 실패: {e}")

    # 4) WM_SETTEXT → Enter (최후 수단)
    if not sent:
        try:
            _log("[send] WM_SETTEXT 시도 중...")
            win32api.SendMessage(hwndEdit, win32con.WM_SETTEXT, 0, text)
            time.sleep(0.05)
            cur_txt = _get_text(hwndEdit)
            _log(f"[send] settext, edit_now='{cur_txt[:50]}...'")
            if _send_enter_variants(hwndEdit, via_root=root):
                sent=True
                _log("[send] WM_SETTEXT + Enter 완료")
        except Exception as e:
            _log(f"[send] WM_SETTEXT 실패: {e}")

    # 전송 후 약간 더 대기 (전송/렌더링 지연)
    time.sleep(1.2)
    after = get_chat_text(chatroom)
    tail = "\n".join(after.splitlines()[-max(VERIFY_TAIL_LINES,1):])
    ok = text.strip() and (text.strip() in tail)
    if DEBUG:
        _log(f"[verify] ok={ok}")
        if not ok:
            _log("[verify-tail]---")
            for line in tail.splitlines()[-10:]:
                _log("    ", line)
            _log("[verify-tail]--- end")
    return ok

# ------------- 실행부 -------------
if __name__=="__main__":
    try:
        open_chatroom(CHATROOM_NAME)
    except Exception as e:
        print("[!] 열기 실패:", e)
        raise

    try:
        if send_message_and_verify(CHATROOM_NAME, MESSAGE_TEXT):
            print(f"[*] 실제로 '{CHATROOM_NAME}' 방에 메시지를 보냈습니다: {MESSAGE_TEXT}")
        else:
            print("[!] 전송 실패로 판단(대화창 하단에서 텍스트 확인 불가)")
    except Exception as e:
        print("[!] 발신 예외:", e)
        raise

    print("[*] 실시간 수신 시작 (Ctrl+C로 종료)\n")
    last = get_chat_text(CHATROOM_NAME)
    while True:
        time.sleep(1.0)
        cur = get_chat_text(CHATROOM_NAME)
        if cur != last:
            delta = cur[len(last):].strip() if cur.startswith(last) else cur
            if delta:
                print("[새 메시지]", delta)
            last = cur
