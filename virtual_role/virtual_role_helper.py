from typing import Dict, Any

from config_data import GUILD_CONFIGS


def get_virtual_role_configs_for_guild(guild_id: int) -> Dict[str, Dict[str, Any]]:
    """
    从总配置 (GUILD_CONFIGS) 中为特定服务器提取所有“虚拟身份组”的配置。

    这个函数会遍历指定服务器的 at_config -> mention_map，
    筛选出所有 type 为 "virtual" 的条目，并以 VirtualRolePanelView
    所需的格式返回它们。

    Args:
        guild_id: 服务器的ID。

    Returns:
        一个字典，键是虚拟身份组的key，值是包含 'name' 和 'description' 的字典。
        例如:
        {
            "新日报读者": {
                "name": "🔔 新日报读者",
                "description": "加入后，您将收到新日报的发布通知。"
            }
        }
    """
    virtual_roles = {}
    guild_config = GUILD_CONFIGS.get(guild_id)

    if not guild_config:
        return {}

    mention_map = guild_config.get("at_config", {}).get("mention_map", {})

    for key, config in mention_map.items():
        if config.get("type") == "virtual":
            # 确保虚拟身份组的配置包含 name 和 description
            if "name" in config and "description" in config:
                virtual_roles[key] = {
                    "name": config["name"],
                    "description": config["description"]
                }

    return virtual_roles