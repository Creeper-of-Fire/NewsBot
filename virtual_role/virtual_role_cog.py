# virtual_role_cog.py
import typing

import discord
from discord import app_commands, Color
from discord.ext import commands

from virtual_role.virtual_role_data_manager import VirtualRoleDataManager
from virtual_role.virtual_role_helper import get_virtual_role_configs_for_guild
from virtual_role.virtual_role_view import VirtualRolePanelView
from utility.permison import is_admin, is_admin_check

if typing.TYPE_CHECKING:
    from main import NewsBot


class VirtualRoleCog(commands.Cog):
    def __init__(self, bot: 'NewsBot'):
        self.bot = bot
        self.data_manager = VirtualRoleDataManager()
        # 视图现在不需要cog实例，因为它将在回调中从交互中获取
        self.bot.add_view(VirtualRolePanelView(self))
        self.bot.logger.info("持久化视图 'VirtualRolePanelView' 已注册。")

    @app_commands.command(name="发送新闻面板", description="获取新闻订阅面板 (记者可公开发送，成员私下获取)")
    @app_commands.guild_only()  # 确保在服务器内使用
    @app_commands.default_permissions(send_messages=True)
    async def setup_virtual_role_panel(self, interaction: discord.Interaction):
        # 检查此服务器是否有配置
        if not get_virtual_role_configs_for_guild(interaction.guild.id):
            await interaction.response.send_message("❌ 此服务器尚未配置任何虚拟身份组。请在 `config_data.py` 的 `at_config` 中添加 `type: 'virtual'` 的条目。",
                                                    ephemeral=True)
            return

        # 在内部检查用户是否为管理员
        user_is_admin = is_admin_check(interaction)

        # 根据权限准备不同的 Embed
        if user_is_admin:
            embed = discord.Embed(
                title="🗞️ 新闻通知自助服务",
                description="点击下方按钮，管理你想要接收的新闻通知。\n注意这不会赋予你真正的身份组。",
                color=Color.from_rgb(88, 101, 242)
            )
            embed.set_footer(text="这是一个永久面板，随时可以使用。")
        else:
            embed = discord.Embed(
                title="🗞️ 新闻通知自助服务 (仅您可见)",
                description="点击下方按钮，管理你想要接收的新闻通知。\n注意这不会赋予你真正的身份组。",
                color=Color.from_rgb(88, 101, 242)
            )
            embed.set_footer(text="此面板为临时私有面板，可随时通过本指令再次获取。")

        # 视图对于两种情况是相同的
        view = VirtualRolePanelView(self)

        # 根据权限发送消息
        if user_is_admin:
            # 管理员公开发送
            await interaction.channel.send(embed=embed, view=view)
            await interaction.response.send_message("✅ 永久管理面板已成功在当前频道发送！", ephemeral=True)
        else:
            # 普通成员私下接收
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="查询订阅人数", description="查询服务器内所有新闻订阅组的成员数量。")
    @app_commands.guild_only()
    @app_commands.default_permissions(send_messages=True)
    async def query_subscriber_stats(self, interaction: discord.Interaction):
        """查询并显示所有虚拟身份组的订阅人数统计。"""
        await interaction.response.defer(ephemeral=True, thinking=True)

        guild_id = interaction.guild.id
        virtual_roles_config = get_virtual_role_configs_for_guild(guild_id)

        if not virtual_roles_config:
            await interaction.followup.send("ℹ️ 此服务器尚未配置任何虚拟新闻订阅组。", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"📊 {interaction.guild.name} - 新闻订阅统计",
            description="以下是服务器内各新闻订阅组的当前成员数量。",
            color=discord.Color.from_rgb(114, 137, 218)  # Discord Blurple
        )

        stats_lines = []
        total_subscribers = 0
        unique_subscribers = set()

        # 对虚拟身份组按名称进行排序，以便显示
        sorted_roles = sorted(virtual_roles_config.items(), key=lambda item: item[1]['name'])

        for role_key, config in sorted_roles:
            user_ids = await self.data_manager.get_users_in_role(role_key, guild_id)
            subscriber_count = len(user_ids)
            stats_lines.append(f"**{config['name']}**: `{subscriber_count}` 人")
            total_subscribers += subscriber_count
            unique_subscribers.update(user_ids)

        if stats_lines:
            embed.description += "\n\n" + "\n".join(stats_lines)
        else:
            embed.description = "目前没有配置任何订阅组。"

        embed.add_field(name="总订阅人次", value=str(total_subscribers), inline=True)
        embed.add_field(name="独立订阅人数", value=str(len(unique_subscribers)), inline=True)
        embed.set_footer(text=f"由 {interaction.user.display_name} 查询")

        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: 'NewsBot') -> None:
    """Cog的入口点。"""
    await bot.add_cog(VirtualRoleCog(bot))
