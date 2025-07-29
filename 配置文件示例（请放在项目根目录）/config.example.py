# config.py
import os

from dotenv import load_dotenv

from config_data import GUILD_CONFIGS

load_dotenv()

# 你的机器人 Token
# 现在优先从环境变量 'DISCORD_BOT_TOKEN' 获取，如果环境变量不存在，则使用空字符串）
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
    }
}