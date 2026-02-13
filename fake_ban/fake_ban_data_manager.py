from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Dict, Any, Optional

DATA_DIR = "data"
DATA_FILE = os.path.join(DATA_DIR, "fake_bans.json")


class FakeBanDataManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FakeBanDataManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # 数据结构: { guild_id: { user_id: { until, operator_id, reason } } }
        self._data: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._lock = asyncio.Lock()
        self._dirty = False
        self._save_task = None
        os.makedirs(DATA_DIR, exist_ok=True)
        self.load_data()

    # ==================== 数据加载与保存 ====================
    def load_data(self):
        try:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._data = {}

    async def _save_data(self):
        async with self._lock:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=4, ensure_ascii=False)
            self._dirty = False

    # ==================== 公共接口 ====================
    async def schedule_save(self):
        self._dirty = True
        if self._save_task and not self._save_task.done():
            self._save_task.cancel()
        self._save_task = asyncio.create_task(self._delayed_save())

    async def _delayed_save(self):
        try:
            await asyncio.sleep(2.0)
            if self._dirty:
                await self._save_data()
        except asyncio.CancelledError:
            pass

    async def get_ban(self, guild_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        now_ts = int(time.time())
        removed = False
        ban = None
        async with self._lock:
            guild_data = self._data.get(str(guild_id), {})
            ban = guild_data.get(str(user_id))
            if not ban:
                return None
            until_ts = int(ban.get("until", 0))
            if until_ts <= now_ts:
                del guild_data[str(user_id)]
                if not guild_data:
                    self._data.pop(str(guild_id), None)
                removed = True
                ban = None
        if removed:
            await self.schedule_save()
        return ban

    async def set_ban(self, guild_id: int, user_id: int, until_ts: int, operator_id: int, reason: str) -> Dict[str, Any]:
        ban_data = {
            "until": int(until_ts),
            "operator_id": int(operator_id),
            "reason": reason,
            "created_at": int(time.time())
        }
        async with self._lock:
            guild_key = str(guild_id)
            if guild_key not in self._data:
                self._data[guild_key] = {}
            self._data[guild_key][str(user_id)] = ban_data
        await self.schedule_save()
        return ban_data

    async def clear_ban(self, guild_id: int, user_id: int) -> bool:
        removed = False
        async with self._lock:
            guild_data = self._data.get(str(guild_id))
            if not guild_data:
                return False
            if str(user_id) in guild_data:
                del guild_data[str(user_id)]
                removed = True
            if not guild_data:
                self._data.pop(str(guild_id), None)
        if removed:
            await self.schedule_save()
        return removed
