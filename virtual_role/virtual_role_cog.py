# virtual_role_cog.py (完全重构)
import typing

import discord
from discord import app_commands, Color
from discord.ext import commands

from config_data import DEFAULT_VIRTUAL_ROLE_ALLOWED
from virtual_role.virtual_role_config_manager import VirtualRoleConfigManager
from virtual_role.virtual_role_data_manager import VirtualRoleDataManager
from virtual_role.virtual_role_helper import get_virtual_role_configs_for_guild
from virtual_role.virtual_role_view import (
    VirtualRolePanelView, RoleEditSelectView, RoleDeleteSelectView, RoleEditModal, RoleSortView
)
# 假设您有 is_super_admin_check 函数
from utility.permison import is_admin, is_admin_check, is_super_admin_check

if typing.TYPE_CHECKING:
    from main import NewsBot


class VirtualRoleCog(commands.Cog):
    def __init__(self, bot: 'NewsBot'):
        self.bot = bot
        self.data_manager = VirtualRoleDataManager()
        self.config_manager = VirtualRoleConfigManager()
        # 持久化视图现在不需要 cog 实例
        self.bot.add_view(VirtualRolePanelView())
        self.bot.logger.info("持久化视图 'VirtualRolePanelView' 已注册。")

    # ===================================================================
    # 用户命令
    # ===================================================================

    @app_commands.command(name="发送新闻面板", description="获取新闻订阅面板 (管理员可公开发送，成员私下获取)")
    @app_commands.guild_only()
    @app_commands.default_permissions(send_messages=True)
    async def setup_virtual_role_panel(self, interaction: discord.Interaction):
        # 检查此服务器是否有配置
        if not await get_virtual_role_configs_for_guild(interaction.guild.id):
            await interaction.response.send_message(
                "❌ 此服务器尚未配置任何虚拟身份组。请管理员使用 `/管理新闻组 添加` 命令来创建。",
                ephemeral=True
            )
            return

        user_is_admin = is_admin_check(interaction)
        embed_title = "🗞️ 新闻通知自助服务"
        embed_footer = "这是一个永久面板，随时可以使用。"
        if not user_is_admin:
            embed_title += " (仅您可见)"
            embed_footer = "此面板为临时私有面板，可随时通过本指令再次获取。"

        embed = discord.Embed(
            title=embed_title,
            description="点击下方按钮，管理你想要接收的新闻通知。\n注意这不会赋予你真正的身份组。",
            color=Color.from_rgb(88, 101, 242)
        ).set_footer(text=embed_footer)

        view = VirtualRolePanelView()

        if user_is_admin:
            await interaction.channel.send(embed=embed, view=view)
            await interaction.response.send_message("✅ 永久管理面板已成功在当前频道发送！", ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="查询订阅人数", description="查询服务器内所有新闻订阅组的成员数量。")
    @app_commands.guild_only()
    @app_commands.default_permissions(send_messages=True)
    async def query_subscriber_stats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild_id = interaction.guild.id
        virtual_roles_config = await get_virtual_role_configs_for_guild(guild_id)

        if not virtual_roles_config:
            await interaction.followup.send("ℹ️ 此服务器尚未配置任何虚拟新闻订阅组。", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"📊 {interaction.guild.name} - 新闻订阅统计",
            description="以下是服务器内各新闻订阅组的当前成员数量。",
            color=discord.Color.from_rgb(114, 137, 218)
        )
        stats_lines = []
        total_subscribers, unique_subscribers = 0, set()
        sorted_roles = sorted(virtual_roles_config.items(), key=lambda item: item[1]['name'])

        for role_key, config in sorted_roles:
            user_ids = await self.data_manager.get_users_in_role(role_key, guild_id)
            subscriber_count = len(user_ids)
            stats_lines.append(f"**{config['name']}**: `{subscriber_count}` 人")
            total_subscribers += subscriber_count
            unique_subscribers.update(user_ids)

        if stats_lines:
            embed.description += "\n\n" + "\n".join(stats_lines)

        embed.add_field(name="总订阅人次", value=str(total_subscribers), inline=True)
        embed.add_field(name="独立订阅人数", value=str(len(unique_subscribers)), inline=True)
        embed.set_footer(text=f"由 {interaction.user.display_name} 查询")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ===================================================================
    # 管理员命令组
    # ===================================================================
    manage_roles_group = app_commands.Group(
        name="管理新闻组",
        description="管理服务器的虚拟新闻订阅组",
        guild_only=True,
        default_permissions=discord.Permissions(manage_messages=True)
    )

    @manage_roles_group.command(name="添加", description="添加一个新的新闻订阅组。")
    @is_admin()
    async def add_role(self, interaction: discord.Interaction):
        """打开一个模态框来添加新的虚拟角色"""
        is_super = is_super_admin_check(interaction)
        modal = RoleEditModal(
            title="添加新的新闻订阅组",
            cog=self,
            is_super_admin=is_super
        )
        await interaction.response.send_modal(modal)

    @manage_roles_group.command(name="编辑", description="编辑一个已存在的新闻订阅组。")
    @is_admin()
    async def edit_role(self, interaction: discord.Interaction):
        """显示一个选择菜单来编辑虚拟角色"""
        guild_id = interaction.guild.id
        roles = await self.config_manager.get_guild_roles_ordered(guild_id)
        if not roles:
            await interaction.response.send_message("❌ 本服务器没有可编辑的新闻订阅组。", ephemeral=True)
            return

        view = RoleEditSelectView(self, roles)
        await interaction.response.send_message("请选择您想编辑的新闻订阅组:", view=view, ephemeral=True)

    @manage_roles_group.command(name="删除", description="删除一个新闻订阅组（订阅记录会保留）。")
    @is_admin()
    async def delete_role(self, interaction: discord.Interaction):
        """显示一个选择菜单来删除虚拟角色"""
        guild_id = interaction.guild.id
        roles = await self.config_manager.get_guild_roles_ordered(guild_id)
        if not roles:
            await interaction.response.send_message("❌ 本服务器没有可删除的新闻订阅组。", ephemeral=True)
            return

        view = RoleDeleteSelectView(self, roles)
        await interaction.response.send_message("请选择您想删除的新闻订阅组:", view=view, ephemeral=True)

    @manage_roles_group.command(name="排序", description="调整新闻订阅组在面板中的显示顺序。")
    @is_admin()
    async def sort_roles(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        roles = await self.config_manager.get_guild_roles_ordered(guild_id)
        if not roles:
            await interaction.response.send_message("❌ 本服务器没有可排序的新闻订阅组。", ephemeral=True)
            return
        if len(roles) < 2:
            await interaction.response.send_message("ℹ️ 至少需要两个新闻订阅组才能进行排序。", ephemeral=True)
            return

        view = RoleSortView(self, roles, guild_id)
        await interaction.response.send_message(embed=view.generate_embed(), view=view, ephemeral=True)

async def setup(bot: 'NewsBot') -> None:
    await bot.add_cog(VirtualRoleCog(bot))