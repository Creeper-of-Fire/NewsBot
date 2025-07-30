from typing import Dict, Any

from virtual_role.virtual_role_config_manager import VirtualRoleConfigManager


async def get_virtual_role_configs_for_guild(guild_id: int) -> Dict[str, Dict[str, Any]]:
    """
    从 VirtualRoleConfigManager 为特定服务器提取所有“虚拟身份组”的配置。

    Args:
        guild_id: 服务器的ID。

    Returns:
        一个字典，键是虚拟身份组的key，值是包含 'name' 和 'description' 等的字典。
    """
    config_manager = VirtualRoleConfigManager()
    return await config_manager.get_guild_config(guild_id)