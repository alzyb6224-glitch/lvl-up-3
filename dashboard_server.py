# -*- coding: utf-8 -*-
"""
FreeFire Level Up Bot - Professional Web Dashboard & Real-Time EXP Tracker
Embedded Async Web Server (aiohttp)
Optimized for ultra-smooth operation, zero memory leaks, and dynamic multi-account control.
"""

import asyncio
import json
import os
import time
from typing import Dict, List, Any, Optional
from aiohttp import web

TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "index.html")

EXP_TABLE: Dict[int, int] = {
    1: 0, 2: 48, 3: 202, 4: 544, 5: 1012, 6: 1844, 7: 2792, 8: 3800,
    9: 4870, 10: 6004, 11: 7192, 12: 8448, 13: 9760, 14: 11140, 15: 12566,
    16: 14060, 17: 15610, 18: 17224, 19: 18902, 20: 20632, 21: 22424, 22: 24278,
    23: 26192, 24: 28166, 25: 30200, 26: 32294, 27: 34448, 28: 37804, 29: 41274,
    30: 44870, 31: 48582, 32: 53394, 33: 58566, 34: 64096, 35: 69994, 36: 76460,
    37: 83506, 38: 91128, 39: 99322, 40: 108092, 41: 120144, 42: 133266, 43: 147472,
    44: 162760, 45: 179126, 46: 196572, 47: 215368, 48: 235516, 49: 257010, 50: 279860,
    51: 304056, 52: 348318, 53: 394982, 54: 444044, 55: 495508, 56: 549364, 57: 633756,
    58: 721744, 59: 813336, 60: 908522, 61: 1041438, 62: 1180352, 63: 1325266,
    64: 1476184, 65: 1634300, 66: 1840946, 67: 2056594, 68: 2281242, 69: 2514880,
    70: 2757530, 71: 3059506, 72: 3372284, 73: 3699456, 74: 4041030, 75: 4397002,
    76: 4829104, 77: 5282204, 78: 5756304, 79: 6251408, 80: 6776502, 81: 7381324,
    82: 8043154, 83: 8752982, 84: 9510808, 85: 10316338, 86: 11277190, 87: 12291748,
    88: 13360304, 89: 14482858, 90: 15659418, 91: 17026708, 92: 18453950, 93: 19941280,
    94: 21488570, 95: 23095858, 96: 24763138, 97: 26490428, 98: 28378704, 99: 30124996,
    100: 32032884
}

def calculate_level_progress(level: int, current_exp: int) -> Dict[str, Any]:
    level = max(1, level)
    next_level = min(100, level + 1)
    base_exp = EXP_TABLE.get(level, 0)
    target_exp = EXP_TABLE.get(next_level, base_exp + 50000)
    
    needed_for_level = max(1, target_exp - base_exp)
    earned_in_level = max(0, current_exp - base_exp)
    remaining_exp = max(0, target_exp - current_exp)
    progress_pct = min(100.0, max(0.0, (earned_in_level / needed_for_level) * 100.0))

    return {
        "next_level": next_level,
        "base_exp": base_exp,
        "target_exp": target_exp,
        "needed_for_level": needed_for_level,
        "earned_in_level": earned_in_level,
        "remaining_exp": remaining_exp,
        "progress_pct": round(progress_pct, 1)
    }

# Global bot state shared between Main.py and Web Dashboard
class BotState:
    def __init__(self):
        self.accounts: Dict[str, Dict[str, Any]] = {}
        self.logs: List[Dict[str, Any]] = []
        self.max_logs = 200
        self.total_matches = 0
        self.total_matches_started = 0      # 🔥 NEW
        self.total_gained_exp = 0
        self.start_time = time.time()
        self.account_workers: Dict[str, asyncio.Task] = {}
        self.account_token_map: Dict[str, str] = {}  # uid -> token or token_prefix -> uid
        self.auth_to_game_id: Dict[str, str] = {}   # guest login uid -> in-game account id
        self.game_to_auth_id: Dict[str, str] = {}   # in-game account id -> guest login uid
        self.paused_accounts: set = set()
        self.refresh_callbacks: Dict[str, Any] = {}
        self.account_credentials: Dict[str, Dict[str, Any]] = {}
        self.active_writers: Dict[str, set] = {}

    def register_writer(self, uid: str, writer):
        uid_str = str(uid)
        if uid_str not in self.active_writers:
            self.active_writers[uid_str] = set()
        self.active_writers[uid_str].add(writer)

    def unregister_writer(self, uid: str, writer):
        uid_str = str(uid)
        if uid_str in self.active_writers:
            self.active_writers[uid_str].discard(writer)
            if not self.active_writers[uid_str]:
                self.active_writers.pop(uid_str, None)

    def close_writers_for_account(self, uid: str):
        uid_str = str(uid)
        candidates = {uid_str}
        if uid_str in self.auth_to_game_id:
            candidates.add(str(self.auth_to_game_id[uid_str]))
        if uid_str in self.game_to_auth_id:
            candidates.add(str(self.game_to_auth_id[uid_str]))
        if uid_str in self.account_token_map:
            mapped = self.account_token_map[uid_str]
            candidates.add(str(mapped))
            candidates.add(str(mapped)[:16])

        for c in list(candidates):
            writers = list(self.active_writers.get(c, []))
            for w in writers:
                try:
                    if hasattr(w, "close"):
                        if hasattr(w, "is_closing"):
                            if not w.is_closing():
                                w.close()
                        else:
                            w.close()
                except Exception:
                    pass
            self.active_writers.pop(c, None)

    def log(self, message: str, level: str = "info", uid: Optional[str] = None):
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "level": level,
            "message": message,
            "uid": str(uid) if uid else None
        }
        self.logs.append(entry)
        if len(self.logs) > self.max_logs:
            self.logs.pop(0)

    def register_account(self, uid: str, nickname: str, region: str, level: int, exp: int,
                         likes: int = 0, token: Optional[str] = None, auth_uid: Optional[str] = None,
                         owner: Optional[str] = None):
        uid_str = str(uid)
        auth_uid_str = str(auth_uid) if auth_uid else self.game_to_auth_id.get(uid_str, "")
        if auth_uid_str:
            self.auth_to_game_id[auth_uid_str] = uid_str
            self.game_to_auth_id[uid_str] = auth_uid_str
            self.account_token_map[auth_uid_str] = uid_str
            self.account_token_map[uid_str] = auth_uid_str
        if token:
            self.account_token_map[uid_str] = token
            self.account_token_map[token[:16]] = uid_str
            if auth_uid_str:
                self.account_token_map[auth_uid_str] = token

        # Resolve owner from accounts.json if not provided
        if not owner:
            try:
                if os.path.exists("accounts.json"):
                    with open("accounts.json", "r", encoding="utf-8") as f:
                        accs = json.load(f)
                    for a in accs:
                        if str(a.get("uid", "")) == uid_str or (token and a.get("token") == token):
                            owner = a.get("owner", "")
                            break
            except Exception:
                pass
        owner = owner or ""

        prog = calculate_level_progress(level or 1, exp)

        lvl_val = level or 1
        acc_mode = "BR" if lvl_val < 3 else "LONE_WOLF"
        acc_mode_label = "Battle Royale (Lvl < 3)" if lvl_val < 3 else "Lone Wolf (Lvl 3+)"

        if uid_str not in self.accounts:
            self.accounts[uid_str] = {
                "uid": uid_str,
                "auth_uid": auth_uid_str or "",
                "nickname": nickname or f"Player_{uid_str[:6]}",
                "region": region or "BD",
                "level": lvl_val,
                "next_level": prog["next_level"],
                "mode": acc_mode,
                "mode_label": acc_mode_label,
                "initial_exp": exp,
                "current_exp": exp,
                "gained_exp": 0,
                "remaining_exp": prog["remaining_exp"],
                "target_exp": prog["target_exp"],
                "needed_for_level": prog["needed_for_level"],
                "earned_in_level": prog["earned_in_level"],
                "progress_pct": prog["progress_pct"],
                "likes": likes or 0,
                "status": "PAUSED" if self.is_paused(uid_str) else "ONLINE",
                "matches_played": 0,
                "active_matches": 0,
                "last_match_time": None,
                "token": token or "",
                "start_time": time.time(),
                "is_paused": self.is_paused(uid_str),
                "paused_at": time.time() if self.is_paused(uid_str) else None,
                "total_pause_duration": 0.0,
                "last_updated": time.strftime("%H:%M:%S"),
                "owner": owner
            }
        else:
            acc = self.accounts[uid_str]
            if auth_uid_str:
                acc["auth_uid"] = auth_uid_str
            if nickname:
                acc["nickname"] = nickname
            if region:
                acc["region"] = region
            if level:
                acc["level"] = level
            if token:
                acc["token"] = token
            if owner:
                acc["owner"] = owner
            acc["current_exp"] = exp
            acc["gained_exp"] = max(0, exp - acc["initial_exp"])
            acc["next_level"] = prog["next_level"]
            acc["remaining_exp"] = prog["remaining_exp"]
            acc["target_exp"] = prog["target_exp"]
            acc["needed_for_level"] = prog["needed_for_level"]
            acc["earned_in_level"] = prog["earned_in_level"]
            acc["progress_pct"] = prog["progress_pct"]
            acc["likes"] = likes
            if not acc.get("is_paused"):
                acc["status"] = "ONLINE"
            acc["last_updated"] = time.strftime("%H:%M:%S")
        self.recalc_totals()

    def get_account_uptime(self, uid_str: str) -> int:
        acc = self.accounts.get(uid_str)
        if not acc:
            mapped = self.game_to_auth_id.get(uid_str) or self.auth_to_game_id.get(uid_str)
            if mapped and mapped in self.accounts:
                acc = self.accounts[mapped]
        if not acc:
            return 0
        start_t = acc.get("start_time", time.time())
        total_pause = acc.get("total_pause_duration", 0.0)
        if acc.get("is_paused") and acc.get("paused_at"):
            return max(0, int(acc["paused_at"] - start_t - total_pause))
        return max(0, int(time.time() - start_t - total_pause))

    def is_paused(self, uid: str) -> bool:
        uid_str = str(uid)
        if uid_str in self.paused_accounts:
            return True
        game_id = self.auth_to_game_id.get(uid_str)
        if game_id and game_id in self.paused_accounts:
            return True
        auth_uid = self.game_to_auth_id.get(uid_str)
        if auth_uid and auth_uid in self.paused_accounts:
            return True
        acc = self.accounts.get(uid_str) or (self.accounts.get(game_id) if game_id else None)
        if acc and acc.get("is_paused"):
            return True
        return False

    def toggle_pause(self, uid: str) -> bool:
        uid_str = str(uid)
        candidates = {uid_str}
        if uid_str in self.auth_to_game_id:
            candidates.add(self.auth_to_game_id[uid_str])
        if uid_str in self.game_to_auth_id:
            candidates.add(self.game_to_auth_id[uid_str])

        target_acc = None
        target_key = uid_str
        for c in candidates:
            if c in self.accounts:
                target_acc = self.accounts[c]
                target_key = c
                break

        is_now_paused = not self.is_paused(uid_str)
        if is_now_paused:
            for c in candidates:
                self.paused_accounts.add(c)
                self.close_writers_for_account(c)
            if target_acc:
                target_acc["is_paused"] = True
                target_acc["paused_at"] = time.time()
                target_acc["status"] = "PAUSED"
            nick = target_acc.get("nickname", target_key) if target_acc else target_key
            self.log(f"⏸ UID {target_key} ({nick}) matchmaking PAUSED (TCP socket disconnected).", "warning", target_key)
            if "on_pause_toggle" in self.refresh_callbacks:
                try:
                    asyncio.create_task(self.refresh_callbacks["on_pause_toggle"](target_key, True))
                except Exception:
                    pass
        else:
            for c in candidates:
                self.paused_accounts.discard(c)
            if target_acc:
                target_acc["is_paused"] = False
                if target_acc.get("paused_at"):
                    pause_dur = time.time() - target_acc["paused_at"]
                    target_acc["total_pause_duration"] = target_acc.get("total_pause_duration", 0.0) + pause_dur
                    target_acc["paused_at"] = None
                target_acc["status"] = "ONLINE"
            nick = target_acc.get("nickname", target_key) if target_acc else target_key
            self.log(f"▶ UID {target_key} ({nick}) matchmaking RESUMED.", "success", target_key)
            if "on_pause_toggle" in self.refresh_callbacks:
                try:
                    asyncio.create_task(self.refresh_callbacks["on_pause_toggle"](target_key, False))
                except Exception:
                    pass

        return is_now_paused

    def toggle_pause_all(self) -> bool:
        any_active = any(not self.is_paused(k) for k in self.accounts.keys())
        for k in list(self.accounts.keys()):
            current_paused = self.is_paused(k)
            if any_active and not current_paused:
                self.toggle_pause(k)
            elif not any_active and current_paused:
                self.toggle_pause(k)
        return any_active

    def update_exp(self, uid: str, current_exp: int, level: Optional[int] = None):
        uid_str = str(uid)
        if uid_str in self.accounts:
            acc = self.accounts[uid_str]
            old_exp = acc["current_exp"]
            old_level = acc.get("level", 1)
            acc["current_exp"] = current_exp
            if level is not None and level > 0:
                acc["level"] = level
            acc["gained_exp"] = max(0, current_exp - acc["initial_exp"])
            
            current_lvl = acc["level"]
            acc["mode"] = "BR" if current_lvl < 3 else "LONE_WOLF"
            acc["mode_label"] = "Battle Royale (Lvl < 3)" if current_lvl < 3 else "Lone Wolf (Lvl 3+)"

            prog = calculate_level_progress(acc["level"], current_exp)
            acc["next_level"] = prog["next_level"]
            acc["remaining_exp"] = prog["remaining_exp"]
            acc["target_exp"] = prog["target_exp"]
            acc["needed_for_level"] = prog["needed_for_level"]
            acc["earned_in_level"] = prog["earned_in_level"]
            acc["progress_pct"] = prog["progress_pct"]
            acc["last_updated"] = time.strftime("%H:%M:%S")

            # Check for Level 2 -> 3 Mode Transition
            if old_level < 3 and current_lvl >= 3:
                self.log(
                    f"🎉 LEVEL UP! UID {uid_str} ({acc['nickname']}) reached Level {current_lvl}! Switching from Battle Royale to Lone Wolf mode!",
                    "success",
                    uid_str
                )

            diff = current_exp - old_exp
            if diff > 0:
                self.log(
                    f"★ UID {uid_str} ({acc['nickname']}) gained +{diff:,} EXP | Level {acc['level']} [{acc['mode']}] ({prog['progress_pct']}% - {prog['remaining_exp']:,} EXP to Lvl {prog['next_level']})",
                    "success",
                    uid_str
                )
            self.recalc_totals()

    def get_account_level(self, uid: str) -> int:
        uid_str = str(uid)
        acc = self.accounts.get(uid_str)
        if not acc:
            mapped = self.game_to_auth_id.get(uid_str) or self.auth_to_game_id.get(uid_str)
            if mapped and mapped in self.accounts:
                acc = self.accounts[mapped]
        if acc:
            return int(acc.get("level", 1) or 1)
        return 1

    def get_account_mode(self, uid: str) -> str:
        lvl = self.get_account_level(uid)
        return "BR" if lvl < 3 else "LONE_WOLF"

    def update_status(self, uid: str, status: str, active_matches: Optional[int] = None):
        uid_str = str(uid)
        if uid_str in self.accounts:
            self.accounts[uid_str]["status"] = status
            if active_matches is not None:
                self.accounts[uid_str]["active_matches"] = active_matches
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")


    def increment_match_started(self):
        """Track total matches STARTED (not completed)"""
        self.total_matches_started += 1

    def increment_match(self, uid: str):
        uid_str = str(uid)
        self.total_matches += 1
        if uid_str in self.accounts:
            self.accounts[uid_str]["matches_played"] += 1
            self.accounts[uid_str]["last_match_time"] = time.strftime("%H:%M:%S")
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")
            self.log(f"⚔ Match #{self.accounts[uid_str]['matches_played']} finished for {self.accounts[uid_str]['nickname']} ({uid_str})", "info", uid_str)

    def recalc_totals(self):
        self.total_gained_exp = sum(acc.get("gained_exp", 0) for acc in self.accounts.values())


bot_state = BotState()



# ==================== MULTI-USER AUTH & SESSION SYSTEM ====================
import hashlib
import secrets
from functools import wraps

# Hardcoded developer credentials — no circular import with Main
ADMIN_USERNAME = "sk7skinzdevlvlup"
ADMIN_PASSWORD = "sk7skinzlvl"
USERS_FILE = "users.json"

_auth_cache = {}

def _get_main_funcs():
    """Lazy import from Main after both modules are fully loaded."""
    if _auth_cache.get("loaded"):
        return _auth_cache
    try:
        import Main as _main
        _auth_cache["authenticate_user"] = getattr(_main, "authenticate_user", None)
        _auth_cache["register_user"] = getattr(_main, "register_user", None)
        _auth_cache["list_all_users"] = getattr(_main, "list_all_users", None)
        _auth_cache["delete_user"] = getattr(_main, "delete_user", None)
        _auth_cache["loaded"] = True
    except Exception:
        _auth_cache["loaded"] = True
    return _auth_cache

def authenticate_user(user_or_email: str, password: str):
    """Auth with hardcoded admin + users.json. Safe from circular imports."""
    key = (user_or_email or "").strip().lower()
    pwd = password or ""

    # Developer account always works
    if key == ADMIN_USERNAME.lower() and pwd == ADMIN_PASSWORD:
        return {
            "name": "Developer",
            "username": ADMIN_USERNAME,
            "email": "",
            "password": ADMIN_PASSWORD,
            "created": 0,
            "max_slots": 999999,
            "max_days": 999999,
            "expires_at": None,
            "is_admin": True,
            "active": True
        }

    # Prefer Main function if available
    funcs = _get_main_funcs()
    main_auth = funcs.get("authenticate_user")
    if main_auth and callable(main_auth):
        try:
            result = main_auth(user_or_email, password)
            if result:
                return result
        except Exception:
            pass

    # Direct users.json fallback
    if not os.path.exists(USERS_FILE):
        return None
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            users = json.load(f)
        if not isinstance(users, list):
            return None
        for u in users:
            if (u.get("username") == key or u.get("email") == key) and u.get("password") == pwd:
                if not u.get("active", True):
                    return None
                expires = u.get("expires_at")
                if expires and time.time() > float(expires):
                    return None
                u.setdefault("max_slots", 5)
                u.setdefault("max_days", 30)
                u.setdefault("is_admin", False)
                return u
    except Exception:
        pass
    return None

def register_user(name: str, username: str, email: str, password: str,
                  max_slots: int = 5, max_days: int = 30, is_admin: bool = False):
    funcs = _get_main_funcs()
    main_reg = funcs.get("register_user")
    if main_reg and callable(main_reg):
        try:
            return main_reg(name, username, email, password,
                            max_slots=max_slots, max_days=max_days, is_admin=is_admin)
        except Exception:
            pass

    username = (username or "").strip().lower()
    if not username or not password:
        return False, "Username and password are required"
    if len(password) < 4:
        return False, "Password must be at least 4 characters"
    if username == ADMIN_USERNAME.lower():
        return False, "This username is reserved for the developer"

    users = []
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                users = json.load(f)
            if not isinstance(users, list):
                users = []
        except Exception:
            users = []

    if any(u.get("username") == username for u in users):
        return False, "Username already taken"

    created = time.time()
    expires_at = None if is_admin or max_days <= 0 else (created + max_days * 86400)
    users.append({
        "name": (name or username).strip(),
        "username": username,
        "email": (email or "").strip().lower(),
        "password": password,
        "created": created,
        "max_slots": 999999 if is_admin else max(1, int(max_slots)),
        "max_days": 999999 if is_admin else max(1, int(max_days)),
        "expires_at": expires_at,
        "is_admin": bool(is_admin),
        "active": True
    })
    try:
        tmp = USERS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2, ensure_ascii=False)
        os.replace(tmp, USERS_FILE)
    except Exception as e:
        return False, str(e)
    return True, "Account created successfully"

def list_all_users():
    funcs = _get_main_funcs()
    main_list = funcs.get("list_all_users")
    if main_list and callable(main_list):
        try:
            return main_list()
        except Exception:
            pass
    users = []
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                for u in data:
                    users.append({
                        "name": u.get("name", ""),
                        "username": u.get("username", ""),
                        "email": u.get("email", ""),
                        "created": u.get("created", 0),
                        "max_slots": u.get("max_slots", 5),
                        "max_days": u.get("max_days", 30),
                        "expires_at": u.get("expires_at"),
                        "is_admin": u.get("is_admin", False),
                        "active": u.get("active", True)
                    })
        except Exception:
            pass
    return users

def delete_user(username: str) -> bool:
    funcs = _get_main_funcs()
    main_del = funcs.get("delete_user")
    if main_del and callable(main_del):
        try:
            return main_del(username)
        except Exception:
            pass
    username = (username or "").strip().lower()
    if not os.path.exists(USERS_FILE):
        return False
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            users = json.load(f)
        if not isinstance(users, list):
            return False
        new_users = [u for u in users if u.get("username") != username]
        if len(new_users) == len(users):
            return False
        tmp = USERS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(new_users, f, indent=2, ensure_ascii=False)
        os.replace(tmp, USERS_FILE)
        return True
    except Exception:
        return False

# In-memory sessions: token -> {username, is_admin, created, expires}
SESSIONS: Dict[str, Dict[str, Any]] = {}
SESSION_TTL = 86400 * 7  # 7 days

def _create_session(user: Dict) -> str:
    token = secrets.token_hex(32)
    SESSIONS[token] = {
        "username": user["username"],
        "is_admin": bool(user.get("is_admin", False)),
        "name": user.get("name", user["username"]),
        "max_slots": user.get("max_slots", 5),
        "max_days": user.get("max_days", 30),
        "expires_at": user.get("expires_at"),
        "created": time.time()
    }
    return token

def _get_session(request: web.Request) -> Optional[Dict]:
    token = request.cookies.get("ff_session") or request.headers.get("X-Session-Token")
    if not token or token not in SESSIONS:
        return None
    sess = SESSIONS[token]
    if time.time() - sess["created"] > SESSION_TTL:
        SESSIONS.pop(token, None)
        return None
    return sess

def _require_auth(handler):
    async def wrapper(request: web.Request):
        sess = _get_session(request)
        if not sess:
            return web.json_response({"status": "error", "error": "Unauthorized", "code": 401}, status=401)
        request["session"] = sess
        return await handler(request)
    return wrapper

def _require_admin(handler):
    async def wrapper(request: web.Request):
        sess = _get_session(request)
        if not sess:
            return web.json_response({"status": "error", "error": "Unauthorized", "code": 401}, status=401)
        if not sess.get("is_admin"):
            return web.json_response({"status": "error", "error": "Admin only", "code": 403}, status=403)
        request["session"] = sess
        return await handler(request)
    return wrapper

def _count_user_accounts(username: str) -> int:
    """Count accounts owned by a specific user from accounts.json"""
    accounts_file = "accounts.json"
    if not os.path.exists(accounts_file):
        return 0
    try:
        with open(accounts_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return 0
        return sum(1 for a in data if str(a.get("owner", "")).lower() == username.lower())
    except Exception:
        return 0

def _load_accounts_json() -> List[Dict]:
    accounts_file = "accounts.json"
    if not os.path.exists(accounts_file):
        return []
    try:
        with open(accounts_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []

def _save_accounts_json(accounts: List[Dict]):
    accounts_file = "accounts.json"
    tmp = accounts_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(accounts, f, indent=2, ensure_ascii=False)
    os.replace(tmp, accounts_file)

# Fallback HTML
FALLBACK_INDEX_HTML = """<!DOCTYPE html>
<html>
<head><title>SK7 LevelUp Dashboard</title></head>
<body style="background:#050510;color:#fff;font-family:sans-serif;text-align:center;padding:80px;">
<h1 style="background:linear-gradient(90deg,#00f0ff,#a855f7);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">SK7 LEVEL UP</h1>
<p>Loading dashboard...</p>
</body>
</html>"""


# ==================== HTTP HANDLERS ====================

async def handle_index(request: web.Request) -> web.Response:
    content = FALLBACK_INDEX_HTML
    if os.path.exists(TEMPLATE_PATH):
        try:
            with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            pass
    return web.Response(text=content, content_type="text/html", charset="utf-8")


async def handle_login(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        username = str(data.get("username", "")).strip()
        password = str(data.get("password", "")).strip()
        if not username or not password:
            return web.json_response({"status": "error", "error": "Username and password required"})

        user = authenticate_user(username, password)
        if not user:
            return web.json_response({"status": "error", "error": "Invalid credentials or account expired"})

        token = _create_session(user)
        resp = web.json_response({
            "status": "ok",
            "user": {
                "username": user["username"],
                "name": user.get("name", user["username"]),
                "is_admin": bool(user.get("is_admin", False)),
                "max_slots": user.get("max_slots", 5),
                "max_days": user.get("max_days", 30),
                "expires_at": user.get("expires_at")
            }
        })
        resp.set_cookie("ff_session", token, max_age=SESSION_TTL, httponly=True, samesite="Lax")
        return resp
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_logout(request: web.Request) -> web.Response:
    token = request.cookies.get("ff_session")
    if token and token in SESSIONS:
        SESSIONS.pop(token, None)
    resp = web.json_response({"status": "ok"})
    resp.del_cookie("ff_session")
    return resp


async def handle_me(request: web.Request) -> web.Response:
    sess = _get_session(request)
    if not sess:
        return web.json_response({"status": "error", "error": "Not logged in", "code": 401}, status=401)

    # Refresh live data for non-admin
    used_slots = _count_user_accounts(sess["username"])
    days_left = None
    if sess.get("expires_at"):
        remaining = float(sess["expires_at"]) - time.time()
        days_left = max(0, int(remaining / 86400))

    return web.json_response({
        "status": "ok",
        "user": {
            "username": sess["username"],
            "name": sess.get("name", sess["username"]),
            "is_admin": sess.get("is_admin", False),
            "max_slots": sess.get("max_slots", 5),
            "used_slots": used_slots if not sess.get("is_admin") else used_slots,
            "max_days": sess.get("max_days", 30),
            "days_left": days_left,
            "expires_at": sess.get("expires_at")
        }
    })


@_require_auth
async def handle_get_stats(request: web.Request) -> web.Response:
    sess = request["session"]
    is_admin = sess.get("is_admin", False)
    username = sess["username"]

    accounts_data = []
    total_active_matches = 0
    total_gained = 0
    saved_accounts = _load_accounts_json()

    for uid, acc in bot_state.accounts.items():
        owner = str(acc.get("owner", "") or "")
        # Resolve ownership when the runtime game UID differs from the saved login UID/token.
        if not owner:
            credentials = bot_state.account_credentials.get(str(uid), {}) or {}
            source_uid = str(acc.get("auth_uid") or credentials.get("auth_uid") or "")
            source_token = str(credentials.get("access_token") or credentials.get("auth_token") or "")
            for saved in saved_accounts:
                saved_uid = str(saved.get("uid", ""))
                saved_token = str(saved.get("token", ""))
                if (source_uid and saved_uid == source_uid) or (source_token and saved_token == source_token) or saved_uid == str(uid):
                    owner = str(saved.get("owner", "") or "")
                    if owner:
                        acc["owner"] = owner
                    break

        # Non-admin sees only own accounts
        if not is_admin and owner.lower() != username.lower():
            continue

        prog = calculate_level_progress(acc.get("level", 1), acc.get("current_exp", 0))
        accounts_data.append({
            "uid": acc.get("uid", uid),
            "auth_uid": acc.get("auth_uid", ""),
            "nickname": acc.get("nickname", "Unknown"),
            "region": acc.get("region", "BD"),
            "level": acc.get("level", 1),
            "current_exp": acc.get("current_exp", 0),
            "initial_exp": acc.get("initial_exp", 0),
            "gained_exp": acc.get("gained_exp", 0),
            "matches_played": acc.get("matches_played", 0),
            "status": acc.get("status", "ONLINE"),
            "active_matches": acc.get("active_matches", 0),
            "is_paused": bot_state.is_paused(uid),
            "mode": acc.get("mode", "BR"),
            "mode_label": acc.get("mode_label", ""),
            "progress_pct": prog["progress_pct"],
            "remaining_exp": prog["remaining_exp"],
            "uptime": bot_state.get_account_uptime(uid),
            "owner": owner
        })
        total_active_matches += acc.get("active_matches", 0)
        total_gained += acc.get("gained_exp", 0)

    uptime_sec = int(time.time() - bot_state.start_time)
    exp_per_hour = 0
    if uptime_sec > 60:
        exp_per_hour = int(total_gained / (uptime_sec / 3600))

    result = {
        "status": "ok",
        "total_accounts": len(accounts_data),
        "total_active_matches": total_active_matches,
        "total_gained_exp": total_gained,
        "exp_per_hour": exp_per_hour,
        "accounts": accounts_data,
        "logs": bot_state.logs[-80:] if is_admin else [l for l in bot_state.logs[-40:] if not l.get("uid") or any(a["uid"] == l.get("uid") for a in accounts_data)],
        "uptime": uptime_sec,
        "is_admin": is_admin
    }

    # Admin-only global stats
    if is_admin:
        all_users = list_all_users()
        active_users = sum(1 for u in all_users if u.get("active", True))
        result.update({
            "server": {
                "total_registered_users": len(all_users),
                "active_users": active_users,
                "total_sessions_running": len(bot_state.account_workers),
                "total_matches_started": bot_state.total_matches_started,
                "total_matches_finished": bot_state.total_matches,
                "global_gained_exp": bot_state.total_gained_exp,
                "paused_count": len(bot_state.paused_accounts),
                "start_time": bot_state.start_time
            },
            "users": all_users
        })

    return web.json_response(result)


@_require_auth
async def handle_add_account(request: web.Request) -> web.Response:
    try:
        sess = request["session"]
        is_admin = sess.get("is_admin", False)
        username = sess["username"]
        data = await request.json()

        # Slot limit check for normal users
        if not is_admin:
            used = _count_user_accounts(username)
            max_slots = sess.get("max_slots", 5)
            if used >= max_slots:
                return web.json_response({
                    "status": "error",
                    "error": f"Slot limit reached ({used}/{max_slots}). Contact admin to increase."
                })

        existing = _load_accounts_json()

        if "uid" in data and "password" in data:
            uid = str(data["uid"]).strip()
            pwd = str(data["password"]).strip()
            if not uid or not pwd:
                return web.json_response({"status": "error", "error": "UID and Password are required"})

            # Cancel previous worker if already running
            if uid in bot_state.account_workers:
                try:
                    bot_state.account_workers[uid].cancel()
                except Exception:
                    pass
                bot_state.account_workers.pop(uid, None)

            existing = [acc for acc in existing if str(acc.get("uid", "")) != uid]
            existing.append({
                "uid": uid,
                "password": pwd,
                "owner": username
            })
            identifier = uid

        elif "token" in data:
            token = str(data["token"]).strip()
            if not token:
                return web.json_response({"status": "error", "error": "Token is required"})

            tok_key = token[:16]
            for k in list(bot_state.account_workers.keys()):
                if k == tok_key or k.startswith(tok_key[:10]) or tok_key.startswith(k[:10]):
                    try:
                        bot_state.account_workers[k].cancel()
                    except Exception:
                        pass
                    bot_state.account_workers.pop(k, None)

            existing = [acc for acc in existing if acc.get("token", "") != token]
            existing.append({
                "token": token,
                "owner": username
            })
            identifier = f"Token_{token[:8]}..."
        else:
            return web.json_response({"status": "error", "error": "Invalid payload"})

        _save_accounts_json(existing)

        bot_state.log(f"New account added by {username}: {identifier}", "success")

        if "on_account_added" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_account_added"](data))

        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


@_require_auth
async def handle_bulk_upload(request: web.Request) -> web.Response:
    """Upload accs.txt (UID:PASSWORD per line) and start all accounts."""
    try:
        sess = request["session"]
        is_admin = sess.get("is_admin", False)
        username = sess["username"]

        # Accept multipart file or raw text body
        content = ""
        if request.content_type and "multipart" in request.content_type:
            reader = await request.multipart()
            field = await reader.next()
            if field is None:
                return web.json_response({"status": "error", "error": "No file uploaded"})
            raw = await field.read()
            content = raw.decode("utf-8", errors="replace")
        else:
            try:
                data = await request.json()
                content = str(data.get("content", "") or data.get("text", ""))
            except Exception:
                content = (await request.text()) or ""

        if not content.strip():
            return web.json_response({"status": "error", "error": "File is empty"})

        lines = []
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                left, right = line.split(":", 1)
                left, right = left.strip(), right.strip()
                if not left or not right:
                    continue
                # TOKEN:xxxxx  or  just a long token-like line starting with TOKEN
                if left.upper() == "TOKEN":
                    lines.append({"token": right})
                else:
                    # UID:PASSWORD guest format
                    lines.append({"uid": left, "password": right})

        if not lines:
            return web.json_response({"status": "error", "error": "No valid lines. Use UID:PASSWORD or TOKEN:access_token per line"})

        # Slot limit for normal users
        if not is_admin:
            used = _count_user_accounts(username)
            max_slots = sess.get("max_slots", 5)
            remaining = max_slots - used
            if remaining <= 0:
                return web.json_response({
                    "status": "error",
                    "error": f"Slot limit reached ({used}/{max_slots})"
                })
            if len(lines) > remaining:
                lines = lines[:remaining]

        existing = _load_accounts_json()
        added = 0
        skipped = 0

        for item in lines:
            if "token" in item:
                token = item["token"]
                existing = [a for a in existing if a.get("token", "") != token]
                existing.append({"token": token, "owner": username})
                tok_key = token[:16]
                for k in list(bot_state.account_workers.keys()):
                    if k == tok_key or k.startswith(tok_key[:10]) or tok_key.startswith(k[:10]):
                        try:
                            bot_state.account_workers[k].cancel()
                        except Exception:
                            pass
                        bot_state.account_workers.pop(k, None)
                if "on_account_added" in bot_state.refresh_callbacks:
                    asyncio.create_task(bot_state.refresh_callbacks["on_account_added"]({"token": token}))
                added += 1
            else:
                uid = item["uid"]
                pwd = item["password"]
                existing = [a for a in existing if str(a.get("uid", "")) != uid]
                existing.append({"uid": uid, "password": pwd, "owner": username})
                if uid in bot_state.account_workers:
                    try:
                        bot_state.account_workers[uid].cancel()
                    except Exception:
                        pass
                    bot_state.account_workers.pop(uid, None)
                if "on_account_added" in bot_state.refresh_callbacks:
                    asyncio.create_task(bot_state.refresh_callbacks["on_account_added"]({
                        "uid": uid, "password": pwd
                    }))
                added += 1

        _save_accounts_json(existing)
        bot_state.log(f"Bulk upload by {username}: {added} accounts started from accs.txt", "success")

        return web.json_response({
            "status": "ok",
            "added": added,
            "skipped": skipped,
            "message": f"Started {added} accounts successfully"
        })
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


@_require_auth
async def handle_delete_account(request: web.Request) -> web.Response:
    try:
        sess = request["session"]
        is_admin = sess.get("is_admin", False)
        username = sess["username"]
        data = await request.json()
        req_uid = str(data.get("uid", "")).strip()
        req_auth_uid = str(data.get("auth_uid", "")).strip()
        if not req_uid and not req_auth_uid:
            return web.json_response({"status": "error", "error": "UID is required"})

        candidate_ids = set()
        if req_uid:
            candidate_ids.add(req_uid)
        if req_auth_uid:
            candidate_ids.add(req_auth_uid)

        for cid in list(candidate_ids):
            if cid in bot_state.game_to_auth_id:
                candidate_ids.add(str(bot_state.game_to_auth_id[cid]))
            if cid in bot_state.auth_to_game_id:
                candidate_ids.add(str(bot_state.auth_to_game_id[cid]))

        # Ownership check for non-admin
        if not is_admin:
            acc_info = bot_state.accounts.get(req_uid) or bot_state.accounts.get(req_auth_uid) or {}
            owner = acc_info.get("owner", "")
            # Also check accounts.json
            all_accs = _load_accounts_json()
            for a in all_accs:
                if str(a.get("uid", "")) in candidate_ids or str(a.get("token", ""))[:10] in candidate_ids:
                    owner = a.get("owner", owner)
            if owner.lower() != username.lower():
                return web.json_response({"status": "error", "error": "You can only delete your own accounts"})

        # Cancel workers & clean state (same logic as original)
        for cid in list(candidate_ids):
            if cid in bot_state.account_workers:
                try:
                    bot_state.account_workers[cid].cancel()
                except Exception:
                    pass
                bot_state.account_workers.pop(cid, None)
            bot_state.close_writers_for_account(cid)
            bot_state.accounts.pop(cid, None)
            bot_state.paused_accounts.discard(cid)

        # Remove from accounts.json
        existing = _load_accounts_json()
        new_existing = []
        for acc in existing:
            uid_str = str(acc.get("uid", ""))
            tok = str(acc.get("token", ""))
            if uid_str in candidate_ids or any(tok.startswith(c[:8]) for c in candidate_ids if c):
                continue
            new_existing.append(acc)
        _save_accounts_json(new_existing)

        bot_state.log(f"Account deleted by {username}: {req_uid or req_auth_uid}", "warning")
        bot_state.recalc_totals()
        return web.json_response({"status": "ok", "deleted": list(candidate_ids)})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


@_require_auth
async def handle_refresh_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        if "on_refresh_account" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_refresh_account"](uid))
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


@_require_auth
async def handle_restart_account(request: web.Request) -> web.Response:
    try:
        sess = request["session"]
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        # Ownership already enforced via stats filtering; restart is allowed for own accounts
        if uid in bot_state.account_workers:
            try:
                bot_state.account_workers[uid].cancel()
            except Exception:
                pass
            bot_state.account_workers.pop(uid, None)

        # Re-add via callback if we have credentials
        all_accs = _load_accounts_json()
        for acc in all_accs:
            if str(acc.get("uid", "")) == uid or (acc.get("token") and acc["token"][:10] == uid[:10]):
                if "on_account_added" in bot_state.refresh_callbacks:
                    asyncio.create_task(bot_state.refresh_callbacks["on_account_added"](acc))
                break
        bot_state.log(f"Account restarted by {sess['username']}: {uid}", "info")
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


@_require_auth
async def handle_clear_logs(request: web.Request) -> web.Response:
    bot_state.logs.clear()
    return web.json_response({"status": "ok"})


@_require_auth
async def handle_toggle_pause(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        if not uid:
            return web.json_response({"status": "error", "error": "UID is required"})
        is_paused = bot_state.toggle_pause(uid)
        return web.json_response({"status": "ok", "is_paused": is_paused})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


@_require_auth
async def handle_toggle_pause_all(request: web.Request) -> web.Response:
    try:
        sess = request["session"]
        if not sess.get("is_admin"):
            # For normal users, pause only their own accounts
            username = sess["username"]
            paused_any = False
            for uid, acc in list(bot_state.accounts.items()):
                if acc.get("owner", "").lower() == username.lower():
                    bot_state.toggle_pause(uid)
                    paused_any = True
            return web.json_response({"status": "ok", "all_paused": paused_any})
        paused_state = bot_state.toggle_pause_all()
        return web.json_response({"status": "ok", "all_paused": paused_state})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


# ==================== ADMIN ONLY ENDPOINTS ====================

@_require_admin
async def handle_admin_create_user(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        username = str(data.get("username", "")).strip().lower()
        password = str(data.get("password", "")).strip()
        name = str(data.get("name", username)).strip()
        max_slots = int(data.get("max_slots", 5))
        max_days = int(data.get("max_days", 30))

        if not username or not password:
            return web.json_response({"status": "error", "error": "Username and password required"})

        ok, msg = register_user(name=name, username=username, email="", password=password,
                                max_slots=max_slots, max_days=max_days, is_admin=False)
        if not ok:
            return web.json_response({"status": "error", "error": msg})
        bot_state.log(f"Admin created user: {username} (slots={max_slots}, days={max_days})", "success")
        return web.json_response({"status": "ok", "message": msg})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


@_require_admin
async def handle_admin_delete_user(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        username = str(data.get("username", "")).strip().lower()
        if not username or username == ADMIN_USERNAME.lower():
            return web.json_response({"status": "error", "error": "Cannot delete this user"})
        if delete_user(username):
            bot_state.log(f"Admin deleted user: {username}", "warning")
            return web.json_response({"status": "ok"})
        return web.json_response({"status": "error", "error": "User not found"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


@_require_admin
async def handle_admin_list_users(request: web.Request) -> web.Response:
    users = list_all_users()
    # Enrich with used slots
    for u in users:
        u["used_slots"] = _count_user_accounts(u["username"])
        if u.get("expires_at"):
            remaining = float(u["expires_at"]) - time.time()
            u["days_left"] = max(0, int(remaining / 86400))
        else:
            u["days_left"] = None
    return web.json_response({"status": "ok", "users": users})


async def start_web_dashboard(host: str = "0.0.0.0", port: int = 5000):
    app = web.Application()
    app.router.add_get("/", handle_index)

    # Auth
    app.router.add_post("/api/login", handle_login)
    app.router.add_post("/api/logout", handle_logout)
    app.router.add_get("/api/me", handle_me)

    # Core (auth required)
    app.router.add_get("/api/stats", handle_get_stats)
    app.router.add_post("/api/account/add", handle_add_account)
    app.router.add_post("/api/account/bulk", handle_bulk_upload)
    app.router.add_post("/api/account/delete", handle_delete_account)
    app.router.add_post("/api/account/refresh", handle_refresh_account)
    app.router.add_post("/api/account/restart", handle_restart_account)
    app.router.add_post("/api/account/pause", handle_toggle_pause)
    app.router.add_post("/api/account/pause_all", handle_toggle_pause_all)
    app.router.add_post("/api/logs/clear", handle_clear_logs)

    # Admin only
    app.router.add_post("/api/admin/create_user", handle_admin_create_user)
    app.router.add_post("/api/admin/delete_user", handle_admin_delete_user)
    app.router.add_get("/api/admin/users", handle_admin_list_users)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    return runner
