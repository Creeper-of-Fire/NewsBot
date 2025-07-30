# at_cog.py (修改后)
import asyncio
import time
from typing import List, TYPE_CHECKING, Optional, Dict, Any

import discord
from discord import app_commands
from discord.ext import commands

from config_data import GUILD_CONFIGS
# 导入新的异步辅助函数来获取虚拟组配置
from virtual_role.virtual_role_helper import get_virtual_role_configs_for_guild

if TYPE_CHECKING:
    from virtual_role.virtual_role_cog import VirtualRoleCog
    from main import NewsBot


class AtCog(commands.Cog):
    """负责处理所有与 @提及 相关的功能，现已支持虚拟组。"""

    def __init__(self, bot: 'NewsBot'):
        self.bot = bot
        self.virtual_role_cog: Optional['VirtualRoleCog'] = None

    def _get_virtual_role_cog(self) -> Optional['VirtualRoleCog']:
        """延迟获取VirtualRoleCog实例，确保它已经被加载。"""
        if not self.virtual_role_cog:
            self.virtual_role_cog = self.bot.get_cog('VirtualRoleCog')
        return self.virtual_role_cog

    async def _get_combined_mention_map(self, guild_id: int) -> Dict[str, Any]:
        """
        将硬编码的真实身份组配置和动态的虚拟身份组配置合并成一个字典。
        这是此 Cog 的核心数据源。
        """
        # 1. 从 GUILD_CONFIGS 获取真实身份组的配置
        guild_config = GUILD_CONFIGS.get(guild_id, {})
        # 使用 .copy() 以免修改原始配置
        mention_map = guild_config.get("at_config", {}).get("mention_map", {}).copy()

        # 2. 从新的 Config Manager 获取虚拟身份组的配置
        virtual_roles = await get_virtual_role_configs_for_guild(guild_id)

        # 3. 将虚拟组配置合并到主 mention_map 中
        for key, config in virtual_roles.items():
            # 为虚拟组配置添加 'type' 字段，以便后续逻辑判断
            virtual_config_with_type = config.copy()
            virtual_config_with_type['type'] = 'virtual'
            mention_map[key] = virtual_config_with_type

        return mention_map

    async def can_user_mention(self, interaction: discord.Interaction, target_key: str) -> bool:
        if not interaction.guild: return False

        # 使用新的合并后的配置
        mention_map = await self._get_combined_mention_map(interaction.guild.id)
        target_config = mention_map.get(target_key)

        if not target_config: return False
        if interaction.user.id == interaction.guild.owner_id: return True

        # 兼容旧配置，如果 interaction.user 是服务器所有者，则始终允许
        if isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator:
            return True

        # allowed_by_roles 的逻辑对两种类型都适用
        allowed_roles_ids_str = target_config.get("allowed_by_roles", [])
        if not allowed_roles_ids_str: return False

        # 将字符串ID转换为整数集合
        allowed_roles_ids = {int(role_id) for role_id in allowed_roles_ids_str}
        user_role_ids = {role.id for role in interaction.user.roles}

        return not user_role_ids.isdisjoint(allowed_roles_ids)

    async def perform_temp_role_ping(
            self,
            interaction: discord.Interaction,
            user_ids: List[int],
            target_name: str,
            message: Optional[str],
            ghost_ping: bool
    ) -> None:
        """
        【新】使用临时身份组执行大规模提及，避免速率限制，并提供进度反馈。

        1.  创建一个临时的、不可见的身份组。
        2.  向用户显示一个"正在处理"的进度条 Embed。
        3.  将所有目标用户添加到该身份组，并实时更新进度条。
        4.  使身份组可提及，发送通知。
        5.  如果 ghost_ping 为 True，删除通知消息。
        6.  清理：删除临时身份组。
        """
        guild = interaction.guild
        if not guild.me.guild_permissions.manage_roles:
            raise discord.Forbidden(
                response=50013,
                message="机器人缺少 '管理身份组' 权限，无法创建临时身份组来发送通知。"
            )

        temp_role = None
        try:
            # 1. 创建临时身份组
            temp_role = await guild.create_role(
                name=f"通知-{target_name}-{int(time.time())}",
                permissions=discord.Permissions.none(),
                mentionable=False,
                reason=f"为 {interaction.user} 的 /at 命令创建的临时通知组"
            )

            # 2. 发送初始进度 Embed
            progress_embed = discord.Embed(
                title=f"🚀 正在准备通知: {target_name}",
                description="正在将成员添加到临时身份组...",
                color=discord.Color.blurple()
            )
            total_users = len(user_ids)
            progress_embed.add_field(name="进度", value="`[          ]` 0%", inline=False)
            progress_embed.set_footer(text="请稍候，此过程可能需要一些时间...")
            await interaction.edit_original_response(embed=progress_embed)

            # 3. 添加成员并更新进度
            added_count = 0
            skipped_count = 0
            last_update_time = time.time()

            for i, user_id in enumerate(user_ids):
                member = guild.get_member(user_id)
                if member:
                    try:
                        await member.add_roles(temp_role, reason="临时通知")
                        added_count += 1
                    except discord.Forbidden:
                        # 如果无法向某个特定成员添加角色（例如，机器人角色层级低于该成员），则跳过
                        skipped_count += 1
                    except discord.HTTPException:
                        # 处理其他可能的API错误
                        skipped_count += 1
                else:
                    skipped_count += 1

                # 更新进度条，避免过于频繁地编辑消息
                current_time = time.time()
                if current_time - last_update_time > 1.5 or (i + 1) == total_users:
                    percentage = (i + 1) / total_users
                    bar = '█' * int(percentage * 10) + ' ' * (10 - int(percentage * 10))
                    progress_embed.set_field_at(
                        0,
                        name="进度",
                        value=f"`[{bar}]` {int(percentage * 100)}%\n"
                              f"已处理: {i + 1}/{total_users} (成功: {added_count}, 跳过: {skipped_count})",
                        inline=False
                    )
                    await interaction.edit_original_response(embed=progress_embed)
                    last_update_time = current_time

            # 准备最终的通知内容
            final_content = temp_role.mention
            final_embed = None
            if message:
                final_embed = discord.Embed(
                    title=f"通知: {target_name}",
                    description=message,
                    color=discord.Color.purple() if ghost_ping else discord.Color.blue()
                )
                final_embed.set_footer(text=f"由 {interaction.user.display_name} 发送")

            # 4. 发送提及
            await temp_role.edit(mentionable=True, reason="准备发送通知")
            sent_message = await interaction.channel.send(
                content=final_content,
                embed=final_embed,
                allowed_mentions=discord.AllowedMentions(roles=True)
            )

            # 5. 根据 ghost_ping 处理消息
            if ghost_ping:
                await asyncio.sleep(2)  # 给予客户端足够的时间来接收和处理通知

                # 构建编辑后的、无提及效果的内容
                edited_content = f"**To:** `@{target_name}`"  # 更清晰地表明目标群体

                # 编辑消息，移除提及
                await sent_message.edit(
                    content=edited_content,
                    allowed_mentions=discord.AllowedMentions.none()  # 关键！禁止任何提及
                )

                final_response_verb = "发送了幽灵提及"
            else:
                final_response_verb = "发送了提及"

            # 更新最终状态给用户
            final_response_msg = (
                f"✅ 成功向虚拟组 **{target_name}** ({added_count} 人) {final_response_verb}。"
                f"{f' ({skipped_count} 人被跳过)' if skipped_count > 0 else ''}"
            )
            await interaction.edit_original_response(content=final_response_msg, embed=None)

        finally:
            # 6. 清理临时身份组
            if temp_role:
                try:
                    await temp_role.delete(reason="临时通知组清理")
                except discord.HTTPException as e:
                    self.bot.logger.error(f"无法删除临时身份组 {temp_role.id}: {e}")
                    # 尝试通知用户，让管理员手动删除
                    await interaction.followup.send(
                        f"⚠️ **重要提示**: 无法自动删除临时身份组 `{temp_role.name}`。"
                        f"请服务器管理员手动删除。",
                        ephemeral=True
                    )

    @app_commands.command(name="发送at通知", description="安全地提及一个身份组或用户组")
    @app_commands.guild_only()
    @app_commands.describe(
        target="要提及的目标组 (输入时会自动提示)",
        message="[可选] 附加在提及后的消息内容",
        ghost_ping="[仅虚拟组] 发送提及后立即删除消息，实现“幽灵提及”效果。默认为是。"
    )
    @app_commands.default_permissions(send_messages=True)
    async def at(self, interaction: discord.Interaction, target: str, message: Optional[str] = None, ghost_ping: bool = True):
        # 使用 defer 并将 thinking 设为 True，这样可以后续发送进度条
        await interaction.response.defer(ephemeral=True, thinking=True)

        mention_map = await self._get_combined_mention_map(interaction.guild.id)

        if not mention_map:
            await interaction.followup.send("❌ 错误：此服务器没有配置 `@` 功能或虚拟组。", ephemeral=True)
            return

        if target not in mention_map:
            await interaction.followup.send(f"❌ 错误：未找到名为 `{target}` 的可提及目标。", ephemeral=True)
            return

        target_config = mention_map[target]

        if not await self.can_user_mention(interaction, target):
            await interaction.followup.send(f"🚫 权限不足：你没有权限提及 `{target_config.get('name', target)}`。", ephemeral=True)
            return

        target_type = target_config.get("type")

        try:
            # === 处理真实身份组 (逻辑不变) ===
            if target_type == "role":
                role_id = target_config.get("id")
                role = interaction.guild.get_role(role_id)
                if not role:
                    await interaction.followup.send(f"❌ 内部错误：在服务器中找不到ID为 `{role_id}` 的身份组。", ephemeral=True)
                    return

                content = role.mention
                response_msg = f"✅ 成功发送提及给 **{role.name}**。"

                embed = None
                if message:
                    embed = discord.Embed(title=f"通知：{role.name}", description=message, color=discord.Color.blue())
                    embed.set_footer(text=f"由 {interaction.user.display_name} 发送")
                    response_msg += " (含Embed)。"

                await interaction.channel.send(
                    content=content,
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(roles=True)
                )
                await interaction.followup.send(response_msg, ephemeral=True)

            # === 【新】处理虚拟身份组 (使用临时身份组方案) ===
            elif target_type == "virtual":
                vr_cog = self._get_virtual_role_cog()
                if not vr_cog:
                    await interaction.followup.send("❌ 内部错误：虚拟组功能模块未加载。", ephemeral=True)
                    return

                user_ids = await vr_cog.data_manager.get_users_in_role(target, interaction.guild.id)
                target_name = target_config.get('name', target)

                if not user_ids:
                    # 无成员情况下的处理
                    if message:
                        embed = discord.Embed(
                            title=f"⚠️ 通知：{target_name} (无人订阅)",
                            description=f"此通知组目前没有任何订阅成员。\n\n**原消息：**\n{message}",
                            color=discord.Color.orange()
                        )
                        embed.set_footer(text=f"由 {interaction.user.display_name} 发送")
                        await interaction.channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                        await interaction.followup.send(f"ℹ️ 虚拟组 `{target_name}` 当前没有任何成员，但附加消息已发送。", ephemeral=True)
                    else:
                        await interaction.followup.send(f"ℹ️ 虚拟组 `{target_name}` 当前没有任何成员，操作已取消。", ephemeral=True)
                    return

                # 调用新的核心处理函数
                await self.perform_temp_role_ping(interaction, user_ids, target_name, message, ghost_ping)

            else:
                await interaction.followup.send(f"❌ 内部错误：`{target}` 的配置类型 `{target_type}` 无效。", ephemeral=True)

        except discord.Forbidden as e:
            self.bot.logger.error(f"机器人权限不足: {e.text} (Code: {e.code})")
            # 为用户提供更具体的错误信息
            error_message = f"❌ 机器人权限不足，无法完成操作。具体原因：\n> {e.text}"
            await interaction.edit_original_response(content=error_message, embed=None)
        except Exception as e:
            self.bot.logger.error(f"执行 /at 命令时发生未知错误: {e}", exc_info=True)
            await interaction.edit_original_response(content=f"❌ 执行命令时发生了一个未知错误。", embed=None)

    @at.autocomplete('target')
    async def at_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        choices = []
        if not interaction.guild: return choices

        mention_map = await self._get_combined_mention_map(interaction.guild.id)

        for key, config in mention_map.items():
            if await self.can_user_mention(interaction, key):
                display_name = config.get("name", key)
                if current.lower() in key.lower() or current.lower() in display_name.lower():
                    desc_type = "虚拟组" if config.get("type") == "virtual" else "身份组"
                    choice_name = f"{display_name} ({desc_type})"
                    if len(choice_name) > 100: choice_name = choice_name[:97] + "..."
                    choices.append(app_commands.Choice(name=choice_name, value=key))

        return choices[:25]


async def setup(bot: 'NewsBot') -> None:
    """Cog的入口点。"""
    await bot.add_cog(AtCog(bot))
