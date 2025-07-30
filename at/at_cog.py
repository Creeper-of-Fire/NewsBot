# at_cog.py (修改后)
import asyncio
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

        # allowed_by_roles 的逻辑对两种类型都适用
        allowed_roles_ids_str = target_config.get("allowed_by_roles", [])
        if not allowed_roles_ids_str: return False

        # 将字符串ID转换为整数集合
        allowed_roles_ids = {int(role_id) for role_id in allowed_roles_ids_str}
        user_role_ids = {role.id for role in interaction.user.roles}

        return not user_role_ids.isdisjoint(allowed_roles_ids)

    @app_commands.command(name="发送at通知", description="安全地提及一个身份组或用户组")
    @app_commands.guild_only()
    @app_commands.describe(
        target="要提及的目标组 (输入时会自动提示)",
        message="[可选] 附加在提及后的消息内容",
        ghost_ping="[仅虚拟组] 是否使用幽灵提及。默认为是。"
    )
    @app_commands.default_permissions(send_messages=True)
    async def at(self, interaction: discord.Interaction, target: str, message: Optional[str] = None, ghost_ping: bool = True):
        await interaction.response.defer(ephemeral=True, thinking=True)

        # 使用新的合并后的配置
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

            # === 处理虚拟身份组 (逻辑不变, 但现在配置是动态的) ===
            elif target_type == "virtual":
                vr_cog = self._get_virtual_role_cog()
                if not vr_cog:
                    await interaction.followup.send("❌ 内部错误：虚拟组功能模块未加载，无法执行操作。", ephemeral=True)
                    return

                user_ids = await vr_cog.data_manager.get_users_in_role(target, interaction.guild.id)
                target_name = target_config.get('name', target)  # 使用配置中的显示名称

                if not user_ids:
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

                embed = None
                content = ""
                allowed_mentions = discord.AllowedMentions.none()

                if ghost_ping:
                    await self.perform_ghost_ping(interaction.channel, user_ids)
                    response_msg = f"✅ 成功向虚拟组 **{target_name}** ({len(user_ids)} 人) 发送了幽灵提及。"
                    if message:
                        embed = discord.Embed(title=f"通知：{target_name}", description=message, color=discord.Color.purple())
                        response_msg += " (含Embed)。"
                else:  # 普通提及
                    content = " ".join([f"<@{uid}>" for uid in user_ids])
                    allowed_mentions = discord.AllowedMentions(users=True)
                    response_msg = f"✅ 成功向虚拟组 **{target_name}** ({len(user_ids)} 人) 发送了消息。"
                    if message:
                        embed = discord.Embed(title=f"通知：{target_name}", description=message, color=discord.Color.blue())
                        response_msg += " (含Embed)。"

                if embed:
                    embed.set_footer(text=f"由 {interaction.user.display_name} 发送")

                await interaction.channel.send(content=content, embed=embed, allowed_mentions=allowed_mentions)
                await interaction.followup.send(response_msg, ephemeral=True)

            else:
                await interaction.followup.send(f"❌ 内部错误：`{target}` 的配置类型 `{target_type}` 无效。", ephemeral=True)

        except discord.Forbidden:
            self.bot.logger.error(f"机器人权限不足，无法在频道 {interaction.channel.name} 中发送消息或提及。")
            await interaction.followup.send("❌ 机器人权限不足，无法完成操作。请检查机器人的身份组权限。", ephemeral=True)
        except Exception as e:
            self.bot.logger.error(f"执行 /at 命令时发生未知错误: {e}", exc_info=True)
            await interaction.followup.send(f"❌ 执行命令时发生了一个未知错误。", ephemeral=True)

    async def perform_ghost_ping(self, channel: discord.TextChannel | discord.Thread, user_ids: List[int]):
        # 此函数逻辑不变
        batch_size = 5
        user_mentions = [f"<@{uid}>" for uid in user_ids]
        for i in range(0, len(user_mentions), batch_size):
            batch = user_mentions[i:i + batch_size]
            ping_message_content = " ".join(batch)
            try:
                ping_msg = await channel.send(ping_message_content, allowed_mentions=discord.AllowedMentions(users=True))
                await ping_msg.delete()
                await asyncio.sleep(1)
            except discord.Forbidden:
                self.bot.logger.error(f"幽灵@失败：机器人无权在频道 {channel.name} 中删除消息。")
                raise
            except Exception as e:
                self.bot.logger.error(f"幽灵@过程中出错: {e}", exc_info=True)

    @at.autocomplete('target')
    async def at_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        choices = []
        if not interaction.guild: return choices

        # 使用新的合并后的配置
        mention_map = await self._get_combined_mention_map(interaction.guild.id)

        for key, config in mention_map.items():
            if await self.can_user_mention(interaction, key):
                # 使用配置中的 name 作为显示，key 作为值
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