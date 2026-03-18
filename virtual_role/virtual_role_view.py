# virtual_role_view.py (完全重构)
from __future__ import annotations

import typing

import discord
from discord import ui, Color, TextStyle

from config_data import DEFAULT_VIRTUAL_ROLE_ALLOWED
from virtual_role.virtual_role_helper import get_virtual_role_configs_for_guild

if typing.TYPE_CHECKING:
    from virtual_role_cog import VirtualRoleCog
    from virtual_role.virtual_role_config_manager import RoleConfig


# ===================================================================
# 1. 公共用户面板 (Persistent View)
# ===================================================================
class VirtualRolePanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        # 按钮回调现在从 interaction 中获取 cog
        self.add_item(OpenVirtualRoleManageButton())


class OpenVirtualRoleManageButton(ui.Button['VirtualRolePanelView']):
    def __init__(self):
        super().__init__(
            label="管理新闻订阅",
            style=discord.ButtonStyle.primary,
            custom_id="open_virtual_role_manager",
            emoji="🔔"
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild: return
        # 从 bot 实例中获取 cog
        cog: VirtualRoleCog = interaction.client.get_cog("VirtualRoleCog")
        if not cog:
            await interaction.response.send_message("发生错误，无法加载管理面板。", ephemeral=True)
            return

        private_view = VirtualRoleManageView(cog, interaction.user, interaction.guild)
        await private_view.prepare_view()
        await interaction.response.send_message(embed=private_view.embed, view=private_view, ephemeral=True)


# ===================================================================
# 2. 用户私有订阅管理界面 (Ephemeral View)
# ===================================================================
class VirtualRoleManageView(ui.View):
    def __init__(self, cog: 'VirtualRoleCog', user: discord.User, guild: discord.Guild):
        super().__init__(timeout=300)
        self.cog = cog
        self.user = user
        self.guild = guild
        self.embed = discord.Embed(title="正在加载...")

    async def prepare_view(self, interaction: discord.Interaction | None = None):
        self.clear_items()
        user_roles = await self.cog.data_manager.get_user_roles(self.user.id, self.guild.id)
        all_virtual_roles = await get_virtual_role_configs_for_guild(self.guild.id)

        if not all_virtual_roles:
            self.embed = discord.Embed(title="无可用通知组", description="此服务器没有配置任何可用的虚拟通知组。", color=Color.orange())
        else:
            description_lines = ["点击下方的按钮来加入或退出通知组。\n"]
            for role_key, config in all_virtual_roles.items():
                is_selected = role_key in user_roles
                self.add_item(VirtualRoleButton(self.cog, role_key, config.name, is_selected))
                status_emoji = "✅" if is_selected else "❌"
                description_lines.append(f"{status_emoji} **{config.name}**\n └ {config.description}")
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


# ===================================================================
# 3. 管理员专用组件 (Modals, Selects, etc.)
# ===================================================================

# 3.1 编辑/添加模态框
class RoleEditModal(ui.Modal):
    def __init__(self, title: str, cog: 'VirtualRoleCog', is_super_admin: bool, old_config: 'RoleConfig' = None, old_key: str = None):
        super().__init__(title=title)
        self.cog = cog
        self.is_super_admin = is_super_admin
        self.old_config = old_config or RoleConfig()
        self.old_key = old_key

        self.key_input = ui.TextInput(
            label="唯一标识符 (Key)",
            placeholder="服务器内唯一的ID，例如: 新日报读者",
            default=self.old_key,
            required=True
        )
        self.name_input = ui.TextInput(
            label="显示名称",
            placeholder="例如: 🔔 新日报读者",
            default=self.old_config.name,
            required=True
        )
        self.desc_input = ui.TextInput(
            label="描述",
            placeholder="订阅后会收到新日报的发布通知",
            style=TextStyle.paragraph,
            default=self.old_config.description,
            required=True
        )
        self.forum_tag_id_input = ui.TextInput(
            label="关联的论坛标签ID (可选)",
            placeholder="留空则不关联。输入论坛标签的数字ID。",
            default=self.old_config.forum_tag_id,  # JSON中可以是null或字符串
            required=False
        )
        self.add_item(self.key_input)
        self.add_item(self.name_input)
        self.add_item(self.desc_input)
        self.add_item(self.forum_tag_id_input)

        if self.is_super_admin:
            allowed_roles_str = ", ".join(self.old_config.allowed_by_roles)
            self.allowed_roles_input = ui.TextInput(
                label="允许发布通知的身份组ID (英文逗号分隔)",
                style=TextStyle.paragraph,
                default=allowed_roles_str,
                required=False
            )
            self.add_item(self.allowed_roles_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        new_key = self.key_input.value.strip()
        new_name = self.name_input.value.strip()
        new_desc = self.desc_input.value.strip()

        if not new_key:
            await interaction.followup.send("❌ 唯一标识符 (Key) 不能为空。", ephemeral=True)
            return

        # 解析 allowed_by_roles
        if self.is_super_admin:
            try:
                allowed_roles = [int(r.strip()) for r in self.allowed_roles_input.value.split(',') if r.strip()]
            except ValueError:
                await interaction.followup.send("❌ `允许发布的身份组ID` 格式错误，必须是纯数字并用英文逗号隔开。", ephemeral=True)
                return
        else:
            allowed_roles = DEFAULT_VIRTUAL_ROLE_ALLOWED

        forum_tag_id_str = self.forum_tag_id_input.value.strip()
        forum_tag_id = None
        if forum_tag_id_str:
            try:
                forum_tag_id = int(forum_tag_id_str)
            except ValueError:
                await interaction.followup.send("❌ `关联的论坛标签ID` 格式错误，必须是纯数字。", ephemeral=True)
                return

        # --- 逻辑处理 ---
        if self.old_key:  # 这是编辑操作
            success = await self.cog.config_manager.update_role(guild_id, self.old_key, new_key, new_name, new_desc, allowed_roles, forum_tag_id)
            if not success:
                await interaction.followup.send(f"❌ 编辑失败！新的唯一标识符 `{new_key}` 与服务器内其他标识符冲突。", ephemeral=True)
                return
            if self.old_key != new_key:
                await self.cog.data_manager.rename_role_key(guild_id, self.old_key, new_key)
            await interaction.followup.send(f"✅ 成功更新订阅组: **{new_name}**", ephemeral=True)
        else:  # 这是添加操作
            success = await self.cog.config_manager.add_role(guild_id, new_key, new_name, new_desc, allowed_roles, forum_tag_id)
            if not success:
                await interaction.followup.send(f"❌ 添加失败！唯一标识符 `{new_key}` 已存在。", ephemeral=True)
                return
            await interaction.followup.send(f"✅ 成功添加订阅组: **{new_name}**", ephemeral=True)


# 3.2 编辑选择视图
class RoleEditSelectView(ui.View):
    def __init__(self, cog: 'VirtualRoleCog', roles: dict[str, 'RoleConfig']):
        super().__init__(timeout=180)
        self.cog = cog
        from utility.permison import is_super_admin_check  # 延迟导入
        self.is_super_admin_check = is_super_admin_check

        options = [
            discord.SelectOption(label=config.name, value=key, description=f"Key: {key}")
            for key, config in roles.items()
        ]
        self.add_item(ui.Select(placeholder="选择一个订阅组进行编辑...", options=options, custom_id="edit_select"))
        self.children[0].callback = self.select_callback

    async def select_callback(self, interaction: discord.Interaction):
        role_key = interaction.data['values'][0]
        config = await self.cog.config_manager.get_role_config(interaction.guild.id, role_key)

        is_super = self.is_super_admin_check(interaction)

        modal = RoleEditModal(
            title=f"编辑: {config.name}",
            cog=self.cog,
            is_super_admin=is_super,
            old_config=config,
            old_key=role_key
        )
        await interaction.response.send_modal(modal)


# 3.3 删除选择视图
class RoleDeleteSelectView(ui.View):
    def __init__(self, cog: 'VirtualRoleCog', roles: dict[str, 'RoleConfig']):
        super().__init__(timeout=180)
        self.cog = cog
        options = [
            discord.SelectOption(label=config.name, value=key, description=f"Key: {key}")
            for key, config in roles.items()
        ]
        self.add_item(ui.Select(placeholder="选择一个订阅组进行删除...", options=options, custom_id="delete_select"))
        self.children[0].callback = self.select_callback

    async def select_callback(self, interaction: discord.Interaction):
        self.clear_items()
        role_key = interaction.data['values'][0]
        config = await self.cog.config_manager.get_role_config(interaction.guild.id, role_key)

        confirm_view = ConfirmDeleteView(self.cog, role_key, config.name)
        await interaction.response.edit_message(
            content=f"⚠️ 您确定要删除 **{config.name}** 吗？\n此操作不可逆，但用户的订阅记录会保留以便恢复。",
            view=confirm_view
        )


# 3.4 删除确认视图
class ConfirmDeleteView(ui.View):
    def __init__(self, cog: 'VirtualRoleCog', role_key: str, role_name: str):
        super().__init__(timeout=60)
        self.cog = cog
        self.role_key = role_key
        self.role_name = role_name

    @ui.button(label="确认删除", style=discord.ButtonStyle.danger, custom_id="confirm_delete")
    async def confirm_button(self, interaction: discord.Interaction, button: ui.Button):
        success = await self.cog.config_manager.delete_role(interaction.guild.id, self.role_key)
        if success:
            await interaction.response.edit_message(content=f"🗑️ 订阅组 **{self.role_name}** 已被删除。", view=None)
        else:
            await interaction.response.edit_message(content="❌ 删除失败，该订阅组可能已被他人删除。", view=None)

    @ui.button(label="取消", style=discord.ButtonStyle.secondary, custom_id="cancel_delete")
    async def cancel_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.edit_message(content="操作已取消。", view=None)


# ===================================================================
# 4. 管理员排序视图
# ===================================================================
class RoleSortView(ui.View):
    def __init__(self, cog: 'VirtualRoleCog', roles: dict[str, 'RoleConfig'], guild_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.roles_config = roles  # {key: {name...}}
        self.current_order = list(roles.keys())  # 仅 key 列表
        self.selected_key = None
        self.guild_id = guild_id

        self.add_components()

    def generate_embed(self) -> discord.Embed:
        """生成显示当前顺序的嵌入消息。"""
        desc_lines = ["使用下拉菜单选择一项，然后使用按钮调整其位置。\n完成后点击保存。"]
        for i, key in enumerate(self.current_order):
            prefix = "➡️ " if key == self.selected_key else ""
            desc_lines.append(f"`{i + 1}.` {prefix}**{self.roles_config[key].name}** (`{key}`)")

        embed = discord.Embed(
            title="调整新闻组顺序",
            description="\n".join(desc_lines),
            color=discord.Color.gold()
        )
        return embed

    def add_components(self):
        """动态添加/更新视图组件。"""
        self.clear_items()

        # 下拉选择菜单
        select_options = [
            discord.SelectOption(label=self.roles_config[key].name, value=key)
            for key in self.current_order
        ]
        self.add_item(ui.Select(placeholder="选择要移动的项目...", options=select_options, custom_id="sorter_select"))

        # 按钮
        has_selection = self.selected_key is not None
        is_first = has_selection and self.current_order.index(self.selected_key) == 0
        is_last = has_selection and self.current_order.index(self.selected_key) == len(self.current_order) - 1

        self.add_item(ui.Button(label="向上", style=discord.ButtonStyle.secondary, custom_id="sorter_up", disabled=not has_selection or is_first, row=1))
        self.add_item(ui.Button(label="向下", style=discord.ButtonStyle.secondary, custom_id="sorter_down", disabled=not has_selection or is_last, row=1))
        self.add_item(ui.Button(label="保存顺序", style=discord.ButtonStyle.success, custom_id="sorter_save", row=2))
        self.add_item(ui.Button(label="取消", style=discord.ButtonStyle.secondary, custom_id="sorter_cancel", row=2))

        # 绑定回调
        self.children[0].callback = self.select_callback
        self.children[1].callback = self.move_up_callback
        self.children[2].callback = self.move_down_callback
        self.children[3].callback = self.save_callback
        self.children[4].callback = self.cancel_callback

    async def refresh(self, interaction: discord.Interaction):
        """刷新视图以响应用户操作。"""
        self.add_components()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    # --- Callbacks ---
    async def select_callback(self, interaction: discord.Interaction):
        self.selected_key = interaction.data['values'][0]
        await self.refresh(interaction)

    async def move_up_callback(self, interaction: discord.Interaction):
        if self.selected_key is None: return
        idx = self.current_order.index(self.selected_key)
        if idx > 0:
            self.current_order.insert(idx - 1, self.current_order.pop(idx))
        await self.refresh(interaction)

    async def move_down_callback(self, interaction: discord.Interaction):
        if self.selected_key is None: return
        idx = self.current_order.index(self.selected_key)
        if idx < len(self.current_order) - 1:
            self.current_order.insert(idx + 1, self.current_order.pop(idx))
        await self.refresh(interaction)

    async def save_callback(self, interaction: discord.Interaction):
        success = await self.cog.config_manager.update_role_order(self.guild_id, self.current_order)
        if success:
            await interaction.response.edit_message(content="✅ 顺序已成功保存！", embed=None, view=None)
        else:
            await interaction.response.edit_message(content="❌ 保存失败。可能是配置在此期间被其他人修改，请重试。", embed=None, view=None)
        self.stop()

    async def cancel_callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(content="操作已取消。", embed=None, view=None)
        self.stop()
