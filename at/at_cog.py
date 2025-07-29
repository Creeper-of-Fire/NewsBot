# at_cog.py
import asyncio
from typing import List, TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import commands

from config_data import GUILD_CONFIGS  # 导入新的总配置
from utility.permison import is_admin

if TYPE_CHECKING:
    from virtual_role.virtual_role_cog import VirtualRoleCog
    from main import NewsBot


class AtCog(commands.Cog):
    """负责处理所有与 @提及 相关的功能，现已支持虚拟组。"""

    def __init__(self, bot: 'NewsBot'):
        self.bot = bot
        # 在cog加载完成后，bot会持有VirtualRoleCog实例
        self.virtual_role_cog: Optional['VirtualRoleCog'] = None

    def _get_virtual_role_cog(self) -> Optional['VirtualRoleCog']:
        """延迟获取VirtualRoleCog实例，确保它已经被加载。"""
        if not self.virtual_role_cog:
            self.virtual_role_cog = self.bot.get_cog('VirtualRoleCog')
        return self.virtual_role_cog

    async def can_user_mention(self, interaction: discord.Interaction, target_key: str) -> bool:
        if not interaction.guild: return False

        guild_config = GUILD_CONFIGS.get(interaction.guild.id)
        if not guild_config: return False

        mention_map = guild_config.get("at_config", {}).get("mention_map", {})
        target_config = mention_map.get(target_key)
        if not target_config: return False

        if interaction.user.id == interaction.guild.owner_id: return True

        allowed_roles_ids = set(target_config.get("allowed_by_roles", []))
        if not allowed_roles_ids: return False

        user_role_ids = {role.id for role in interaction.user.roles}
        return not user_role_ids.isdisjoint(allowed_roles_ids)

    @app_commands.command(name="发送at通知", description="安全地提及一个身份组或用户组")
    @app_commands.guild_only()  # 确保命令只能在服务器中使用
    @app_commands.describe(
        target="要提及的目标组 (输入时会自动提示)",
        message="[可选] 附加在提及后的消息内容",
        ghost_ping="[仅虚拟组] 是否使用幽灵提及。默认为是。"
    )
    @is_admin()
    @app_commands.default_permissions(send_messages=True)
    async def at(self, interaction: discord.Interaction, target: str, message: Optional[str] = None, ghost_ping: bool = True):
        await interaction.response.defer(ephemeral=True, thinking=True)

        guild_config = GUILD_CONFIGS.get(interaction.guild.id)
        if not guild_config or not guild_config.get("at_config"):
            await interaction.followup.send("❌ 错误：此服务器没有配置 `@` 功能。", ephemeral=True)
            return

        mention_map = guild_config["at_config"].get("mention_map", {})
        if target not in mention_map:
            await interaction.followup.send(f"❌ 错误：未找到名为 `{target}` 的可提及目标。", ephemeral=True)
            return

        target_config = mention_map[target]

        if not await self.can_user_mention(interaction, target):
            await interaction.followup.send(f"🚫 权限不足：你没有权限提及 `{target}`。", ephemeral=True)
            return

        target_type = target_config.get("type")

        try:
            # === 处理真实身份组 ===
            if target_type == "role":
                role_id = target_config.get("id")
                role = interaction.guild.get_role(role_id)
                if not role:
                    await interaction.followup.send(f"❌ 内部错误：在服务器中找不到ID为 `{role_id}` 的身份组。", ephemeral=True)
                    return

                if message:
                    embed = discord.Embed(
                        title=f"通知：{role.name}",
                        description=message,
                        color=discord.Color.blue()  # 可以选择一个颜色
                    )
                    embed.set_footer(text=f"由 {interaction.user.display_name} 发送")
                    await interaction.channel.send(
                        content=role.mention,  # 提及部分作为消息内容
                        embed=embed,
                        allowed_mentions=discord.AllowedMentions(roles=True)
                    )
                    await interaction.followup.send(f"✅ 成功发送提及给 **{role.name}** (含Embed)。", ephemeral=True)
                else:
                    # 没有消息时，保持简单提及
                    await interaction.channel.send(
                        role.mention,
                        allowed_mentions=discord.AllowedMentions(roles=True)
                    )
                    await interaction.followup.send(f"✅ 成功发送提及给 **{role.name}**。", ephemeral=True)

            # === 处理虚拟身份组 ===
            elif target_type == "virtual":
                vr_cog = self._get_virtual_role_cog()
                if not vr_cog:
                    await interaction.followup.send("❌ 内部错误：虚拟组功能模块未加载，无法执行操作。", ephemeral=True)
                    return

                user_ids = await vr_cog.data_manager.get_users_in_role(target, interaction.guild.id)

                # --- 情况1: 虚拟组无人 ---
                if not user_ids:
                    # 如果有消息，还是把消息发出去，并说明无人订阅
                    if message:
                        embed = discord.Embed(
                            title=f"⚠️ 通知：{target} (无人订阅)",
                            description=f"此通知组目前没有任何订阅成员。\n\n**原消息：**\n{message}",
                            color=discord.Color.orange()
                        )
                        embed.set_footer(text=f"由 {interaction.user.display_name} 发送")
                        await interaction.channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                        await interaction.followup.send(f"ℹ️ 虚拟组 `{target}` 当前没有任何成员，但附加消息已发送 (含Embed)。", ephemeral=True)
                    else:
                        await interaction.followup.send(f"ℹ️ 虚拟组 `{target}` 当前没有任何成员，操作已取消。", ephemeral=True)
                    return

                # --- 情况2: 幽灵提及 ---
                if ghost_ping:
                    await self.perform_ghost_ping(interaction.channel, user_ids)
                    if message:
                        # 幽灵提及后，如果附加了消息，则通过Embed发送
                        embed = discord.Embed(
                            title=f"通知：{target} (已幽灵提及)",
                            description=message,
                            color=discord.Color.purple()  # 可以选择不同的颜色，例如紫色
                        )
                        embed.set_footer(text=f"由 {interaction.user.display_name} 发送")
                        await interaction.channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())  # 幽灵提及已经完成，此处不再提及
                        await interaction.followup.send(f"✅ 成功向虚拟组 **{target}** ({len(user_ids)} 人) 发送了幽灵提及 (含Embed)。", ephemeral=True)
                    else:
                        await interaction.followup.send(f"✅ 成功向虚拟组 **{target}** ({len(user_ids)} 人) 发送了幽灵提及。", ephemeral=True)

                # --- 情况3: 普通提及 ---
                else:
                    mentions_content = " ".join([f"<@{uid}>" for uid in user_ids])
                    if message:
                        embed = discord.Embed(
                            title=f"通知：{target}",
                            description=message,
                            color=discord.Color.blue()
                        )
                        embed.set_footer(text=f"由 {interaction.user.display_name} 发送")
                        await interaction.channel.send(
                            content=mentions_content,  # 提及部分作为消息内容
                            embed=embed,
                            allowed_mentions=discord.AllowedMentions(users=True)
                        )
                        await interaction.followup.send(f"✅ 成功向虚拟组 **{target}** ({len(user_ids)} 人) 发送了消息 (含Embed)。", ephemeral=True)
                    else:
                        await interaction.channel.send(
                            mentions_content,
                            allowed_mentions=discord.AllowedMentions(users=True)
                        )
                        await interaction.followup.send(f"✅ 成功向虚拟组 **{target}** ({len(user_ids)} 人) 发送了消息。", ephemeral=True)

            else:
                await interaction.followup.send(f"❌ 内部错误：`{target}` 的配置类型 `{target_type}` 无效。", ephemeral=True)

        except discord.Forbidden:
            self.bot.logger.error(f"机器人权限不足，无法在频道 {interaction.channel.name} 中发送消息或提及。")
            await interaction.followup.send("❌ 机器人权限不足，无法完成操作。请检查机器人的身份组权限。", ephemeral=True)
        except Exception as e:
            self.bot.logger.error(f"执行 /at 命令时发生未知错误: {e}", exc_info=True)
            await interaction.followup.send(f"❌ 执行命令时发生了一个未知错误。", ephemeral=True)

    async def perform_ghost_ping(self, channel: discord.TextChannel | discord.Thread, user_ids: List[int]):
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

        guild_config = GUILD_CONFIGS.get(interaction.guild.id)
        if not guild_config or not guild_config.get("at_config"): return choices

        mention_map = guild_config["at_config"].get("mention_map", {})

        for key, config in mention_map.items():
            if await self.can_user_mention(interaction, key):
                if current.lower() in key.lower():
                    desc_type = "身份组" if config.get("type") == "role" else "虚拟组"
                    choice_name = f"{key} ({desc_type})"
                    if len(choice_name) > 100: choice_name = choice_name[:97] + "..."
                    choices.append(app_commands.Choice(name=choice_name, value=key))

        return choices[:25]


async def setup(bot: 'NewsBot') -> None:
    """Cog的入口点。"""
    await bot.add_cog(AtCog(bot))
