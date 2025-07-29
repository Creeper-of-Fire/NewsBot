# virtual_role_data_manager.py
import asyncio
import json
import os
from collections import defaultdict
from typing import List

DATA_DIR = "data"
DATA_FILE = os.path.join(DATA_DIR, "user_virtual_roles.json")


class VirtualRoleDataManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(VirtualRoleDataManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # 新数据结构: { guild_id_str: { user_id_str: [roles] } }
        self._guild_data = {}
        # 反向映射: { guild_id_str: { role_key: [user_ids] } }
        self._guild_role_users = defaultdict(lambda: defaultdict(list))
        self._lock = asyncio.Lock()
        self._dirty = False
        self._save_task = None
        os.makedirs(DATA_DIR, exist_ok=True)
        self.load_data()

    def load_data(self):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                self._guild_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._guild_data = {}
        self._rebuild_reverse_map()

    def _rebuild_reverse_map(self):
        self._guild_role_users.clear()
        for guild_id_str, user_roles_map in self._guild_data.items():
            for user_id_str, roles in user_roles_map.items():
                user_id = int(user_id_str)
                for role_key in roles:
                    self._guild_role_users[guild_id_str][role_key].append(user_id)

    async def save_data(self):
        self._dirty = True
        if self._save_task:
            self._save_task.cancel()
        self._save_task = asyncio.create_task(self._delayed_save())

    async def _delayed_save(self):
        try:
            await asyncio.sleep(1.5)
            async with self._lock:
                if self._dirty:
                    with open(DATA_FILE, 'w', encoding='utf-8') as f:
                        json.dump(self._guild_data, f, indent=4, ensure_ascii=False)
                    self._dirty = False
        except asyncio.CancelledError:
            pass
        finally:
            self._save_task = None

    # --- 所有公共方法都增加了 guild_id 参数 ---

    async def get_user_roles(self, user_id: int, guild_id: int) -> List[str]:
        guild_id_str, user_id_str = str(guild_id), str(user_id)
        async with self._lock:
            return self._guild_data.get(guild_id_str, {}).get(user_id_str, [])

    async def get_users_in_role(self, role_key: str, guild_id: int) -> List[int]:
        guild_id_str = str(guild_id)
        async with self._lock:
            return self._guild_role_users.get(guild_id_str, {}).get(role_key, [])

    async def add_role_to_user(self, user_id: int, role_key: str, guild_id: int):
        guild_id_str, user_id_str = str(guild_id), str(user_id)
        async with self._lock:
            if guild_id_str not in self._guild_data:
                self._guild_data[guild_id_str] = {}
            if user_id_str not in self._guild_data[guild_id_str]:
                self._guild_data[guild_id_str][user_id_str] = []

            if role_key not in self._guild_data[guild_id_str][user_id_str]:
                self._guild_data[guild_id_str][user_id_str].append(role_key)
                self._guild_role_users[guild_id_str][role_key].append(user_id)
                await self.save_data()

    async def remove_role_from_user(self, user_id: int, role_key: str, guild_id: int):
        guild_id_str, user_id_str = str(guild_id), str(user_id)
        async with self._lock:
            if guild_id_str in self._guild_data and user_id_str in self._guild_data[guild_id_str]:
                if role_key in self._guild_data[guild_id_str][user_id_str]:
                    self._guild_data[guild_id_str][user_id_str].remove(role_key)
                    if not self._guild_data[guild_id_str][user_id_str]:
                        del self._guild_data[guild_id_str][user_id_str]
                    if not self._guild_data[guild_id_str]:
                        del self._guild_data[guild_id_str]

                    if role_key in self._guild_role_users[guild_id_str] and user_id in self._guild_role_users[guild_id_str][role_key]:
                        self._guild_role_users[guild_id_str][role_key].remove(user_id)

                    await self.save_data()
