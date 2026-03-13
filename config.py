# config.py
import os
import typing

from dotenv import load_dotenv

from config_data import GUILD_CONFIGS

load_dotenv()

# 你的机器人 Token
# 优先从环境变量 'DISCORD_BOT_TOKEN' 获取，如果环境变量不存在，则使用空字符串）
TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")

# 代理设置 (如果不需要，设为 None)
# 优先从环境变量 'DISCORD_BOT_PROXY' 获取，如果环境变量不存在，则使用 None
PROXY = os.getenv("DISCORD_BOT_PROXY", None)

# 将你的服务器ID（一个或多个）放在这个列表中
GUILD_IDS = set(list(GUILD_CONFIGS.keys()))

# 机器人状态
STATUS_TYPE = "watching"  # 可以是 playing, watching, listening
STATUS_TEXT = "新闻频道"
COMMAND_GROUP_NAME = "新闻"

# Cog 模块启用/禁用配置
# 确保 "core" 和 "at" 都已启用
COGS = {
    "core": {
        "enabled": True,
    },
    "at": {
        "enabled": True,
    },
    "forum_manager": {
        "enabled": True,
    },
    "archive_channel": {
        "enabled": True,
    },
    "tread_analyzer": {
        "enabled": True
    },
    "fake_ban": {
        "enabled": True,
    },
}

# 每日论坛管理任务的全局触发时间（24小时制 "HH:MM"）
# 这决定了机器人每天什么时间点开始执行发帖和归档操作。
DAILY_TASK_TRIGGER_TIME = "00:00"  # 例如：在服务器本地时间的 00:05 执行

# --- 权限配置 ---
# 在这里硬编码拥有权限的用户和角色ID

# 超级管理员：拥有所有权限，通常是机器人所有者或最高决策者。
# 可以执行如“删除数据”等最高风险操作。
SUPER_ADMIN_USER_IDS: typing.Set[int] = {
    942388408800669707,  # 我
}

# 管理员：拥有大部分管理权限，但可能无法执行最危险的操作。
# 例如，可以发送面板、刷新缓存、获取数据备份，但不能删除数据。
# 注意：这里包含角色ID和特定的用户ID。
ADMIN_ROLE_IDS: typing.Set[int] = {
    1336732734508503163,  # 类脑记者
    1337450755791261766,  # 管理组
    1289224017789583453,  # 服务器Admin
}

ADMIN_USER_IDS: typing.Set[int] = {
    942388408800669707,  # 我
    # 如果某个管理员没有特定角色，也可以在这里单独添加他们的用户 ID
}
