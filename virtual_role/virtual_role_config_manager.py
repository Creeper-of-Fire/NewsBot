# virtual_role/virtual_role_config_manager.py
from typing import Dict, Any, List, Optional

from pydantic import BaseModel, Field, model_validator

from utility.base_data_manager import AsyncJsonDataManager, AsyncGuildDataManager


# 单个角色的配置
class RoleConfig(BaseModel):
    name: str
    description: str
    allowed_by_roles: List[str] = Field(default_factory=list)
    forum_tag_id: Optional[str] = None


# 单个服务器的完整配置
class GuildRoleConfig(BaseModel):
    roles: Dict[str, RoleConfig] = Field(default_factory=dict)
    order: List[str] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """用于判断该服务器是否没有任何配置，方便基类自动清理空间"""
        return len(self.roles) == 0


class VirtualRoleConfigManager(AsyncGuildDataManager[GuildRoleConfig]):
    """
    虚拟身份组配置管理器。
    数据结构：Dict[str, GuildRoleConfig] -> { guild_id: { "roles": {...}, "order": [...] } }
    """
    DATA_FILENAME = "virtual_roles_config"
    GUILD_MODEL = GuildRoleConfig

    def _migrate_raw_data(self, raw_dict: Any) -> Any:
        """检查并迁移旧格式的配置文件。"""
        for guild_id_str, guild_config in raw_dict.items():
            # 旧格式的 value 是一个角色字典，而不是包含 "roles" 和 "order" 的字典
            if not isinstance(guild_config, dict) or "roles" not in guild_config or "order" not in guild_config:
                raw_dict[guild_id_str] = {
                    "roles": guild_config,
                    "order": list(guild_config.keys())
                }

        return raw_dict

    async def get_guild_roles_ordered(self, guild_id: int) -> Dict[str, RoleConfig]:
        """获取一个服务器的所有角色配置，并按照存储的顺序排序。"""
        guild_config = self.get_guild(guild_id)
        if not guild_config:
            return {}

        roles_dict = guild_config.roles
        order_list = guild_config.order

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
            guild_config.order = clean_order
            await self.save_data()  # 修复了数据，安排保存

        # 构建排序后的字典
        ordered_roles = {}
        for role_key in guild_config.order:
            if role_key in roles_dict:
                ordered_roles[role_key] = roles_dict[role_key]
        return ordered_roles

    async def get_role_config(self, guild_id: int, role_key: str) -> Optional[RoleConfig]:
        """获取特定身份的配置"""
        guild_config = self.get_guild(guild_id)
        if not guild_config:
            return None
        return guild_config.roles.get(role_key)

    async def add_role(
            self, guild_id: int, role_key: str, name: str, description: str,
            allowed_by_roles: List[int], forum_tag_id: Optional[int]
    ) -> bool:
        """添加一个新的虚拟身份配置"""
        # ensure_guild 会自动初始化 Dict[str, GuildRoleConfig]
        guild_config = self.ensure_guild(guild_id)

        if role_key in guild_config.roles:
            return False

        guild_config.roles[role_key] = RoleConfig(
            name=name,
            description=description,
            allowed_by_roles=[str(r) for r in allowed_by_roles],
            forum_tag_id=str(forum_tag_id) if forum_tag_id else None
        )
        guild_config.order.append(role_key)

        await self.save_data()
        return True

    async def update_role(
            self, guild_id: int, old_key: str, new_key: str, name: str, description: str,
            allowed_by_roles: List[int], forum_tag_id: Optional[int]
    ) -> bool:
        guild_config = self.get_guild(guild_id)
        if not guild_config or old_key not in guild_config.roles:
            return False

        # 如果改名且新名字已占用，返回失败
        if new_key != old_key and new_key in guild_config.roles:
            return False

        new_role_obj = RoleConfig(
            name=name,
            description=description,
            allowed_by_roles=[str(r) for r in allowed_by_roles],
            forum_tag_id=str(forum_tag_id) if forum_tag_id else None
        )

        if new_key != old_key:
            # 移除旧的，添加新的
            del guild_config.roles[old_key]
            guild_config.roles[new_key] = new_role_obj
            # 更新顺序列表中的位置
            if old_key in guild_config.order:
                index = guild_config.order.index(old_key)
                guild_config.order[index] = new_key
            else:
                guild_config.order.append(new_key)
        else:
            # 原地更新
            guild_config.roles[old_key] = new_role_obj

        await self.save_data()
        return True

    async def delete_role(self, guild_id: int, role_key: str) -> bool:
        guild_config = self.get_guild(guild_id)
        if not guild_config:
            return False

        if role_key not in guild_config.roles:
            return False

        del guild_config.roles[role_key]
        if role_key in guild_config.order:
            guild_config.order.remove(role_key)

        self.remove_guild_if(guild_id, lambda g: g.is_empty)

        await self.save_data()
        return True

    async def update_role_order(self, guild_id: int, new_order: List[str]) -> bool:
        """更新一个服务器的角色顺序。"""
        guild_config = self.get_guild(guild_id)
        if not guild_config:
            return False

        current_keys = set(guild_config.roles.keys())
        new_order_keys = set(new_order)

        if current_keys != new_order_keys:
            return False  # 键集合不匹配，可能是排序期间发生了增删

        guild_config.order = new_order
        await self.save_data()
        return True
