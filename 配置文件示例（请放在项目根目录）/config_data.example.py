# config_data.py

# ===================================================================
# 按服务器隔离的功能配置
# ===================================================================
# 结构:
# GUILD_CONFIGS = {
#     guild_id_1: {
#         "at_config": { ... },
#         "virtual_role_config": { ... }
#     },
#     guild_id_2: { ... }
# }
#
# 将你的服务器ID替换下面的 123456789012345678
# 你可以为每个服务器复制并粘贴这个模板，然后修改其内部配置

DEFAULT_VIRTUAL_ROLE_ALLOWED = []

GUILD_CONFIGS = {
    123456789012345678: {  # <--- 替换为你的第一个服务器ID

        # ================== @ 功能配置 for this guild ==================
        "at_config": {
            "mention_map": {
                "公告": {
                    "type": "role",
                    "id": 123456789012345679,  # 公告身份组ID
                    "description": "发布重要服务器公告。",
                    "allowed_by_roles": [987654321098765432] # 管理员ID
                },
                "日报": {
                    "type": "role",
                    "id": 111111111111111111,  # 日报身份组ID
                    "description": "发布每日新闻。",
                    "allowed_by_roles": [987654321098765432, 222222222222222222] # 管理员和记者
                },
                "新日报读者": {
                    "type": "virtual",
                    "description": "提及所有订阅了新日报的用户。",
                    "allowed_by_roles": [987654321098765432, 222222222222222222]
                },
            }
        },

        # ================== 虚拟身份组配置 for this guild ==================
        "virtual_role_config": {
            "groups": {
                # Key (新日报读者) 必须与上面 at_config 中的虚拟组Key一致
                "新日报读者": {
                    "name": "🔔 新日报读者",
                    "description": "加入后，您将收到新日报的发布通知。"
                },
                "活动爱好者": {
                    "name": "🎉 活动爱好者",
                    "description": "加入后，您将收到服务器活动的通知。"
                },
            }
        },

        # ================== 假封禁配置 for this guild ==================
        "fake_ban_config": {
            "enabled": True,  # 是否启用假封禁
            "allowed_by_roles": [987654321098765432],  # 允许使用假封禁的身份组ID
            "allowed_channel_ids": [123456789012345679],  # 允许生效的普通文字频道ID
            "allowed_forum_channel_ids": [123456789012345680],  # 允许生效的论坛频道ID
            "max_duration_minutes": 10080  # 最大封禁时长（分钟，最多7天）
        }
        }

    # 你可以为另一个服务器添加配置
    # 999999999999999999: {
    #     "at_config": { ... },
    #     "virtual_role_config": { ... }
    # }
}
