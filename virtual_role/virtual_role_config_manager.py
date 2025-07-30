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

        # 新数据结构: { guild_id_str: { "roles": { role_key: {details} }, "order": [keys] } }
        self._config_data: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._dirty = False
        self._save_task = None
        os.makedirs(CONFIG_DIR, exist_ok=True)
        self.load_config()

    def _migrate_config_if_needed(self):
        """检查并迁移旧格式的配置文件。"""
        migrated = False
        for guild_id_str, guild_config in self._config_data.items():
            # 旧格式的 value 是一个角色字典，而不是包含 "roles" 和 "order" 的字典
            if not isinstance(guild_config, dict) or "roles" not in guild_config or "order" not in guild_config:
                new_config = {
                    "roles": guild_config,
                    "order": list(guild_config.keys())
                }
                self._config_data[guild_id_str] = new_config
                migrated = True

        if migrated:
            self._dirty = True
            # 同步保存一次以完成迁移
            try:
                with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                    json.dump(self._config_data, f, indent=4, ensure_ascii=False)
                self._dirty = False
            except Exception:
                # 如果同步保存失败，至少标记为脏数据，等待异步保存
                pass

    def load_config(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    self._config_data = json.load(f)
                self._migrate_config_if_needed()
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

    async def get_guild_roles_ordered(self, guild_id: int) -> Dict[str, Dict[str, Any]]:
        """获取一个服务器的所有角色配置，并按照存储的顺序排序。"""
        async with self._lock:
            guild_config = self._config_data.get(str(guild_id), {})
            if not guild_config:
                return {}

            roles_dict = guild_config.get("roles", {})
            order_list = guild_config.get("order", [])

            # 数据一致性检查和修复
            role_keys_in_dict = set(roles_dict.keys())
            role_keys_in_order = set(order_list)

            if role_keys_in_dict != role_keys_in_order:
                # 过滤掉顺序列表中不存在于角色字典中的key
                clean_order = [key for key in order_list if key in roles_dict]
                # 将角色字典中存在但不在顺序列表中的key添加到末尾
                for key in roles_dict:
                    if key not in clean_order:
                        clean_order.append(key)
                guild_config["order"] = clean_order
                await self.schedule_save()  # 修复了数据，安排保存

            # 构建排序后的字典
            ordered_roles = {}
            for role_key in guild_config.get("order", []):
                if role_key in roles_dict:
                    ordered_roles[role_key] = roles_dict[role_key]
            return ordered_roles

    async def get_role_config(self, guild_id: int, role_key: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            guild_config = self._config_data.get(str(guild_id), {})
            return guild_config.get("roles", {}).get(role_key)

    async def add_role(
            self, guild_id: int, role_key: str, name: str, description: str,
            allowed_by_roles: List[int], forum_tag_id: Optional[int]
    ) -> bool:
        guild_id_str = str(guild_id)
        async with self._lock:
            if guild_id_str not in self._config_data:
                self._config_data[guild_id_str] = {"roles": {}, "order": []}

            guild_roles = self._config_data[guild_id_str]["roles"]
            if role_key in guild_roles:
                return False

            guild_roles[role_key] = {
                "name": name, "description": description,
                "allowed_by_roles": [str(r) for r in allowed_by_roles],
                "forum_tag_id": str(forum_tag_id) if forum_tag_id else None
            }
            self._config_data[guild_id_str]["order"].append(role_key)
        await self.schedule_save()
        return True

    async def update_role(
            self, guild_id: int, old_key: str, new_key: str, name: str, description: str,
            allowed_by_roles: List[int], forum_tag_id: Optional[int]
    ) -> bool:
        guild_id_str = str(guild_id)
        async with self._lock:
            guild_config = self._config_data.get(guild_id_str)
            if not guild_config: return False

            guild_roles = guild_config.get("roles", {})
            if new_key != old_key and new_key in guild_roles:
                return False

            if new_key != old_key and old_key in guild_roles:
                del guild_roles[old_key]
                try:
                    index = guild_config["order"].index(old_key)
                    guild_config["order"][index] = new_key
                except ValueError:
                    guild_config["order"].append(new_key)  # 容错处理

            guild_roles[new_key] = {
                "name": name, "description": description,
                "allowed_by_roles": [str(r) for r in allowed_by_roles],
                "forum_tag_id": str(forum_tag_id) if forum_tag_id else None
            }
        await self.schedule_save()
        return True

    async def delete_role(self, guild_id: int, role_key: str) -> bool:
        guild_id_str = str(guild_id)
        async with self._lock:
            if guild_id_str in self._config_data:
                guild_config = self._config_data[guild_id_str]
                if role_key in guild_config.get("roles", {}):
                    del guild_config["roles"][role_key]
                    if role_key in guild_config.get("order", []):
                        guild_config["order"].remove(role_key)

                    if not guild_config["roles"]:
                        del self._config_data[guild_id_str]

                    await self.schedule_save()
                    return True
        return False

    async def update_role_order(self, guild_id: int, new_order: List[str]) -> bool:
        """更新一个服务器的角色顺序。"""
        guild_id_str = str(guild_id)
        async with self._lock:
            if guild_id_str not in self._config_data:
                return False

            guild_config = self._config_data[guild_id_str]
            current_keys = set(guild_config.get("roles", {}).keys())
            new_order_keys = set(new_order)

            if current_keys != new_order_keys:
                return False  # 键集合不匹配，可能是排序期间发生了增删

            guild_config["order"] = new_order
        await self.schedule_save()
        return True