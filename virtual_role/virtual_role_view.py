# at/virtual_role_view.py
from __future__ import annotations
from typing import TYPE_CHECKING
import discord
from discord import ui, Color

from virtual_role.virtual_role_helper import get_virtual_role_configs_for_guild

if TYPE_CHECKING:
    from virtual_role_cog import VirtualRoleCog


# ===================================================================
# 持久化视图 (The Public Panel)
# ===================================================================
class VirtualRolePanelView(ui.View):
    def __init__(self, cog: 'VirtualRoleCog'):
        super().__init__(timeout=None)
        self.add_item(OpenVirtualRoleManageButton(cog))


class OpenVirtualRoleManageButton(ui.Button):
    def __init__(self, cog: 'VirtualRoleCog'):
        self.cog = cog
        super().__init__(
            label="管理我的通知组",
            style=discord.ButtonStyle.primary,
            custom_id="open_virtual_role_manager",
            emoji="🔔"
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("此操作只能在服务器内进行。", ephemeral=True)
            return

        private_view = VirtualRoleManageView(self.cog, interaction.user, interaction.guild)
        await private_view.prepare_view()

        await interaction.response.send_message(
            embed=private_view.embed,
            view=private_view,
            ephemeral=True
        )


# ===================================================================
# 临时私有视图 (The Private Management UI)
# ===================================================================
class VirtualRoleManageView(ui.View):
    def __init__(self, cog: 'VirtualRoleCog', user: discord.User, guild: discord.Guild):
        super().__init__(timeout=300)
        self.cog = cog
        self.user = user
        self.guild = guild
        self.embed = discord.Embed(title="正在加载...")

    async def prepare_view(self, interaction: discord.Interaction | None = None):
        """准备或刷新视图的内容（Embed和按钮）。"""
        self.clear_items()

        user_roles = await self.cog.data_manager.get_user_roles(self.user.id, self.guild.id)

        # 使用新的辅助函数获取所有虚拟身份组
        all_virtual_roles = get_virtual_role_configs_for_guild(self.guild.id)

        if not all_virtual_roles:
            self.embed = discord.Embed(title="无可用通知组", description="此服务器没有配置任何可用的虚拟通知组。", color=Color.orange())
            if interaction:
                await interaction.response.edit_message(embed=self.embed, view=self)
            return

        description_lines = ["点击下方的按钮来加入或退出通知组。\n"]
        for role_key, config in all_virtual_roles.items():
            is_selected = role_key in user_roles
            self.add_item(VirtualRoleButton(self.cog, role_key, config["name"], is_selected))
            status_emoji = "✅" if is_selected else "❌"
            description_lines.append(f"{status_emoji} **{config['name']}**\n └ {config['description']}")

        self.embed = discord.Embed(
            title=f"🔔 {self.guild.name} - 通知组管理",
            description="\n".join(description_lines),
            color=Color.blurple()
        ).set_footer(text=f"此面板为 {self.user.display_name} 私有，5分钟后失效。")

        if interaction:
            await interaction.response.edit_message(embed=self.embed, view=self)


class VirtualRoleButton(ui.Button):
    def __init__(self, cog: 'VirtualRoleCog', role_key: str, role_name: str, is_selected: bool):
        self.cog = cog
        self.role_key = role_key
        super().__init__(
            label=role_name,
            style=discord.ButtonStyle.success if is_selected else discord.ButtonStyle.secondary,
            custom_id=f"toggle_virtual_role:{role_key}"
        )

    async def callback(self, interaction: discord.Interaction):
        if not isinstance(self.view, VirtualRoleManageView):
            return

        is_currently_selected = self.style == discord.ButtonStyle.success
        guild_id = self.view.guild.id

        if is_currently_selected:
            await self.cog.data_manager.remove_role_from_user(interaction.user.id, self.role_key, guild_id)
        else:
            await self.cog.data_manager.add_role_to_user(interaction.user.id, self.role_key, guild_id)

        await self.view.prepare_view(interaction)