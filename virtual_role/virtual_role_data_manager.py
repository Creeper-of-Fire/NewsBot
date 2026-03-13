# virtual_role_data_manager.py
from collections import defaultdict
from typing import List, Dict

from utility.base_data_manager import AsyncUserGuildDataManager


class VirtualRoleDataManager(AsyncUserGuildDataManager[List[str]]):
    """
    用户虚拟身份组数据管理器。
    数据结构：Dict[str, Dict[str, List[str]]] -> { guild_id: { user_id: [role_keys] } }
    """
    DATA_FILENAME = "user_virtual_roles"
    USER_MODEL = list

    def load_data(self):
        super().load_data()
        # 反向映射: 初始化索引容器（放在这里可以确保即使 load_data 被多次调用，索引也会同步更新）
        self._guild_role_users: Dict[str, Dict[str, List[int]]] = defaultdict(lambda: defaultdict(list))
        self._rebuild_reverse_map()

    def _rebuild_reverse_map(self):
        self._guild_role_users.clear()
        for guild_id_str, user_roles_map in self.data.items():
            for user_id_str, roles in user_roles_map.items():
                user_id = int(user_id_str)
                for role_key in roles:
                    self._guild_role_users[guild_id_str][role_key].append(user_id)

    # --- 所有公共方法都增加了 guild_id 参数 ---

    async def get_user_roles(self, user_id: int, guild_id: int) -> List[str]:
        """获取用户在该服务器拥有的所有虚拟身份组 Key"""
        return self.get_user_data(guild_id, user_id) or []

    async def get_users_in_role(self, role_key: str, guild_id: int) -> List[int]:
        """获取拥有特定虚拟身份组的所有用户 ID"""
        return self._guild_role_users.get(str(guild_id), {}).get(role_key, [])

    async def add_role_to_user(self, user_id: int, role_key: str, guild_id: int):
        """为用户添加一个虚拟身份组"""
        # ensure_user_data 会自动处理 guild 和 user 层级的字典初始化
        roles = self.ensure_user_data(guild_id, user_id)

        if role_key not in roles:
            roles.append(role_key)
            # 同步更新索引
            self._guild_role_users[str(guild_id)][role_key].append(user_id)
            await self.save_data()

    async def rename_role_key(self, guild_id: int, old_key: str, new_key: str):
        """当一个虚拟身份组的key被重命名时，更新所有相关用户的记录。"""
        guild_id_str = str(guild_id)

        # 检查是否有这个服务器的数据
        if guild_id_str not in self.data:
            return

        user_roles_map = self.data[guild_id_str]
        updated = False

        # 遍历该服务器的所有用户
        for user_id_str, roles in user_roles_map.items():
            if old_key in roles:
                roles.remove(old_key)
                if new_key not in roles:
                    roles.append(new_key)
                updated = True

        # 如果发生了更新，重建反向映射并保存
        if updated:
            self._rebuild_reverse_map()
            await self.save_data()

    async def remove_role_from_user(self, user_id: int, role_key: str, guild_id: int):
        roles = self.get_user_data(guild_id, user_id)

        if not roles or role_key not in roles:
            return

        roles.remove(role_key)

        # 更新索引
        guild_id_str = str(guild_id)
        if user_id in self._guild_role_users[guild_id_str].get(role_key, []):
            self._guild_role_users[guild_id_str][role_key].remove(user_id)

        # 如果用户没角色了，清理掉该用户节点（基类方法会自动清理空的服务器节点）
        if not roles:
            self.remove_user_data(guild_id, user_id)

        await self.save_data()
