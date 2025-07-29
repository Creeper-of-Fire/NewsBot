# virtual_role_cog.py
import typing

import discord
from discord import app_commands, Color
from discord.ext import commands

from virtual_role.virtual_role_data_manager import VirtualRoleDataManager
from virtual_role.virtual_role_helper import get_virtual_role_configs_for_guild
from virtual_role.virtual_role_view import VirtualRolePanelView
from utility.permison import is_admin

if typing.TYPE_CHECKING:
    from main import NewsBot


class VirtualRoleCog(commands.Cog):
    def __init__(self, bot: 'NewsBot'):
        self.bot = bot
        self.data_manager = VirtualRoleDataManager()
        # 视图现在不需要cog实例，因为它将在回调中从交互中获取
        self.bot.add_view(VirtualRolePanelView(self))
        self.bot.logger.info("持久化视图 'VirtualRolePanelView' 已注册。")

    @app_commands.command(name="发送永久新闻面板", description="在当前频道创建一个永久的虚拟通知组管理面板。")
    @app_commands.guild_only()  # 确保在服务器内使用
    @is_admin()
    @app_commands.default_permissions(send_messages=True)
    async def setup_virtual_role_panel(self, interaction: discord.Interaction):
        # 检查此服务器是否有配置
        if not get_virtual_role_configs_for_guild(interaction.guild.id):
            await interaction.response.send_message("❌ 此服务器尚未配置任何虚拟身份组。请在 `config_data.py` 的 `at_config` 中添加 `type: 'virtual'` 的条目。",
                                                    ephemeral=True)
            return

        embed = discord.Embed(
            title="🗞️ 新闻通知自助服务",
            description="点击下方按钮，管理你想要接收的新闻通知。\n注意这不会赋予你真正的身份组。",
            color=Color.from_rgb(88, 101, 242)
        )
        embed.set_footer(text="这是一个永久面板，随时可以使用。")

        await interaction.channel.send(embed=embed, view=VirtualRolePanelView(self))
        await interaction.response.send_message("✅ 永久管理面板已成功创建！", ephemeral=True)


async def setup(bot: 'NewsBot') -> None:
    """Cog的入口点。"""
    await bot.add_cog(VirtualRoleCog(bot))
