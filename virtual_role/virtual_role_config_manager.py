# virtual_role/virtual_role_config_manager.py
import asyncio
import json
import os
from typing import Dict, Any, List, Optional

CONFIG_DIR = "data"
CONFIG_FILE = os.path.join(CONFIG_DIR, "virtual_roles_config.json")


class VirtualRoleConfigManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(VirtualRoleConfigManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # { guild_id_str: { role_key: {name, description, allowed_by_roles} } }
        self._config_data: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._lock = asyncio.Lock()
        self._dirty = False
        self._save_task = None
        os.makedirs(CONFIG_DIR, exist_ok=True)
        self.load_config()

    def load_config(self):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                self._config_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._config_data = {}

    async def _save_config(self):
        async with self._lock:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self._config_data, f, indent=4, ensure_ascii=False)
            self._dirty = False

    async def schedule_save(self):
        self._dirty = True
        if self._save_task and not self._save_task.done():
            self._save_task.cancel()
        self._save_task = asyncio.create_task(self._delayed_save())

    async def _delayed_save(self):
        try:
            await asyncio.sleep(2.0)
            if self._dirty:
                await self._save_config()
        except asyncio.CancelledError:
            pass

    async def get_guild_config(self, guild_id: int) -> Dict[str, Dict[str, Any]]:
        async with self._lock:
            return self._config_data.get(str(guild_id), {})

    async def get_role_config(self, guild_id: int, role_key: str) -> Optional[Dict[str, Any]]:
        guild_config = await self.get_guild_config(guild_id)
        return guild_config.get(role_key)

    async def add_role(
            self,
            guild_id: int,
            role_key: str,
            name: str,
            description: str,
            allowed_by_roles: List[int],
            forum_tag_id: Optional[int]
    ) -> bool:
        """添加一个新角色。如果key已存在，则返回False。"""
        guild_id_str = str(guild_id)
        async with self._lock:
            if guild_id_str not in self._config_data:
                self._config_data[guild_id_str] = {}

            if role_key in self._config_data[guild_id_str]:
                return False  # Key already exists

            self._config_data[guild_id_str][role_key] = {
                "name": name,
                "description": description,
                "allowed_by_roles": [str(r) for r in allowed_by_roles],
                # 如果有ID则转为字符串存储，否则存为 null
                "forum_tag_id": str(forum_tag_id) if forum_tag_id else None
            }
        await self.schedule_save()
        return True

    async def update_role(
            self,
            guild_id: int,
            old_key: str,
            new_key: str,
            name: str,
            description: str,
            allowed_by_roles: List[int],
            forum_tag_id: Optional[int]
    ) -> bool:
        """更新一个角色。如果new_key已存在（且不是old_key），则返回False。"""
        guild_id_str = str(guild_id)
        async with self._lock:
            guild_config = self._config_data.get(guild_id_str, {})
            if new_key != old_key and new_key in guild_config:
                return False  # New key conflicts with an existing one

            # 如果key变了，删除旧的
            if new_key != old_key and old_key in guild_config:
                del guild_config[old_key]

            guild_config[new_key] = {
                "name": name,
                "description": description,
                "allowed_by_roles": [str(r) for r in allowed_by_roles],
                # 如果有ID则转为字符串存储，否则存为 null
                "forum_tag_id": str(forum_tag_id) if forum_tag_id else None
            }
            self._config_data[guild_id_str] = guild_config
        await self.schedule_save()
        return True

    async def delete_role(self, guild_id: int, role_key: str) -> bool:
        """删除一个角色配置。"""
        guild_id_str = str(guild_id)
        async with self._lock:
            if guild_id_str in self._config_data and role_key in self._config_data[guild_id_str]:
                del self._config_data[guild_id_str][role_key]
                if not self._config_data[guild_id_str]:
                    del self._config_data[guild_id_str]
                await self.schedule_save()
                return True
        return False
