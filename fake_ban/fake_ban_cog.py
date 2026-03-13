from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import commands

import config
from config_data import GUILD_CONFIGS
from fake_ban.fake_ban_data_manager import FakeBanDataManager

if TYPE_CHECKING:
    from main import NewsBot


class FakeBanCog(commands.Cog, name="FakeBan"):
    """
    仅在特定频道/论坛内生效的“假封禁”模块。
    """

    fake_ban_group = app_commands.Group(
        name=f"{config.COMMAND_GROUP_NAME}丨假封禁",
        description="管理在指定频道内的假封禁",
        guild_ids=[gid for gid in config.GUILD_IDS],
        default_permissions=discord.Permissions(send_messages=True)
    )

    def __init__(self, bot: 'NewsBot'):
        self.bot = bot
        self.logger = bot.logger
        self.data_manager = FakeBanDataManager.get_instance()

    # ==================== 配置与权限 ====================
    def _get_guild_config(self, guild_id: int) -> dict:
        return GUILD_CONFIGS.get(guild_id, {}).get("fake_ban_config", {})

    def _is_feature_enabled(self, config_data: dict) -> bool:
        return bool(config_data.get("enabled", False))

    def _normalize_id_set(self, ids: list) -> set[int]:
        normalized = set()
        for item in ids:
            try:
                normalized.add(int(item))
            except (TypeError, ValueError):
                continue
        return normalized

    def _is_channel_allowed(self, channel: discord.abc.GuildChannel | discord.Thread, config_data: dict) -> bool:
        allowed_channel_ids = self._normalize_id_set(config_data.get("allowed_channel_ids", []))
        allowed_forum_ids = self._normalize_id_set(config_data.get("allowed_forum_channel_ids", []))

        if isinstance(channel, discord.TextChannel):
            return channel.id in allowed_channel_ids

        if isinstance(channel, discord.Thread) and isinstance(channel.parent, discord.ForumChannel):
            return channel.parent.id in allowed_forum_ids

        return False

    def _is_admin_member(self, member: discord.Member) -> bool:
        if member.id in config.SUPER_ADMIN_USER_IDS:
            return True
        if member.id in config.ADMIN_USER_IDS:
            return True
        user_role_ids = {role.id for role in member.roles}
        return not user_role_ids.isdisjoint(config.ADMIN_ROLE_IDS)

    def _is_user_allowed(self, member: discord.Member, config_data: dict) -> bool:
        if self._is_admin_member(member):
            return True

        allowed_role_ids = self._normalize_id_set(config_data.get("allowed_by_roles", []))
        if not allowed_role_ids:
            return False

        user_role_ids = {role.id for role in member.roles}
        return not user_role_ids.isdisjoint(allowed_role_ids)

    # ==================== 处罚原因提示 ====================
    def _get_reason_presets(self, config_data: dict) -> list[str]:
        presets = config_data.get("reason_presets", [])
        if not isinstance(presets, list):
            return []
        cleaned = []
        for item in presets:
            if isinstance(item, str) and item.strip():
                cleaned.append(item.strip())
        return cleaned

    async def reason_autocomplete(self, interaction: discord.Interaction, current: str):
        if not interaction.guild:
            return []
        config_data = self._get_guild_config(interaction.guild.id)
        presets = self._get_reason_presets(config_data)
        if not presets:
            return []
        current_text = (current or "").lower()
        results = []
        for item in presets:
            if not current_text or current_text in item.lower():
                results.append(app_commands.Choice(name=item, value=item))
            if len(results) >= 25:
                break
        return results

    # ==================== 时长处理 ====================
    def _get_max_duration(self, config_data: dict) -> int:
        try:
            return int(config_data.get("max_duration_minutes", 10080))
        except (TypeError, ValueError):
            return 10080

    def _get_unit_minutes(self, duration_unit: str) -> int:
        unit_map = {
            "minutes": 1,
            "hours": 60,
            "days": 1440
        }
        return unit_map.get(duration_unit, 1)

    # ==================== 消息监听 ====================
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return

        config_data = self._get_guild_config(message.guild.id)
        if not self._is_feature_enabled(config_data):
            return

        if not self._is_channel_allowed(message.channel, config_data):
            return

        ban_data = await self.data_manager.get_ban(message.guild.id, message.author.id)
        if not ban_data:
            return

        try:
            await message.delete() # reason="假封禁：自动删除消息"
        except discord.Forbidden:
            self.logger.warning(f"假封禁删除失败：缺少权限，频道 {message.channel.id}")
        except discord.HTTPException as e:
            self.logger.warning(f"假封禁删除失败：{e}")

    # ==================== 指令：设置/解除/查询 ====================
    @fake_ban_group.command(name="设置", description="在指定频道/论坛内对成员启用假封禁")
    @app_commands.guild_only()
    @app_commands.choices(
        duration_unit=[
            app_commands.Choice(name="分钟", value="minutes"),
            app_commands.Choice(name="小时", value="hours"),
            app_commands.Choice(name="天", value="days")
        ]
    )
    @app_commands.autocomplete(reason=reason_autocomplete)
    async def set_fake_ban(
            self,
            interaction: discord.Interaction,
            member: discord.Member,
            duration_value: int,
            duration_unit: app_commands.Choice[str],
            reason: Optional[str] = "无"
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)

        if not interaction.guild:
            await interaction.edit_original_response(content="❌ 此命令只能在服务器中使用。")
            return

        config_data = self._get_guild_config(interaction.guild.id)
        if not self._is_feature_enabled(config_data):
            await interaction.edit_original_response(content="❌ 本服务器未启用假封禁功能。")
            return

        if not self._is_channel_allowed(interaction.channel, config_data):
            await interaction.edit_original_response(content="❌ 此命令只能在指定频道或论坛内使用。")
            return

        if not isinstance(interaction.user, discord.Member) or not self._is_user_allowed(interaction.user, config_data):
            await interaction.edit_original_response(content="❌ 你没有权限使用假封禁。")
            return

        unit_minutes = self._get_unit_minutes(duration_unit.value)
        duration_minutes = duration_value * unit_minutes
        max_minutes = min(self._get_max_duration(config_data), 10080)
        if duration_value <= 0 or duration_minutes > max_minutes:
            max_days = max_minutes // 1440
            await interaction.edit_original_response(content=f"❌ 时长必须在 1 到 {max_days} 天以内。")
            return

        until_ts = int(time.time()) + duration_minutes * 60
        reason_text = reason or "无"
        await self.data_manager.set_ban(
            guild_id=interaction.guild.id,
            user_id=member.id,
            until_ts=until_ts,
            operator_id=interaction.user.id,
            reason=reason_text
        )

        # 在命令频道公开展示处罚信息，便于成员查看
        try:
            public_embed = discord.Embed(
                title="⛔ 假封禁",
                color=discord.Color.red()
            )
            public_embed.add_field(name="成员", value=f"{member.mention} ({member.id})", inline=False)
            public_embed.add_field(name="处罚者", value=f"{interaction.user.mention} ({interaction.user.id})", inline=False)
            public_embed.add_field(name="时长", value=f"{duration_value} {duration_unit.name}", inline=True)
            public_embed.add_field(name="结束", value=f"<t:{until_ts}:F>\n(<t:{until_ts}:R>)", inline=True)
            public_embed.add_field(name="原因", value=reason_text, inline=False)
            await interaction.channel.send(embed=public_embed)
        except (discord.Forbidden, discord.HTTPException) as e:
            self.logger.warning(f"假封禁公告发送失败：{e}")

        await interaction.edit_original_response(
            content=(
                f"✅ 已对 {member.mention} 启用假封禁。\n"
                f"- 时长: {duration_value} {duration_unit.name}\n"
                f"- 结束: <t:{until_ts}:F> (<t:{until_ts}:R>)\n"
                f"- 原因: {reason_text}"
            )
        )

    @fake_ban_group.command(name="解除", description="解除成员的假封禁")
    @app_commands.guild_only()
    @app_commands.autocomplete(reason=reason_autocomplete)
    async def clear_fake_ban(
            self,
            interaction: discord.Interaction,
            member: discord.Member,
            reason: Optional[str] = "无"
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)

        if not interaction.guild:
            await interaction.edit_original_response(content="❌ 此命令只能在服务器中使用。")
            return

        config_data = self._get_guild_config(interaction.guild.id)
        if not self._is_feature_enabled(config_data):
            await interaction.edit_original_response(content="❌ 本服务器未启用假封禁功能。")
            return

        if not self._is_channel_allowed(interaction.channel, config_data):
            await interaction.edit_original_response(content="❌ 此命令只能在指定频道或论坛内使用。")
            return

        if not isinstance(interaction.user, discord.Member) or not self._is_user_allowed(interaction.user, config_data):
            await interaction.edit_original_response(content="❌ 你没有权限使用假封禁。")
            return

        removed = await self.data_manager.clear_ban(interaction.guild.id, member.id)
        if not removed:
            await interaction.edit_original_response(content="ℹ️ 该成员当前未被假封禁。")
            return

        await interaction.edit_original_response(
            content=(
                f"✅ 已解除 {member.mention} 的假封禁。\n"
                f"- 原因: {reason or '无'}"
            )
        )

    @fake_ban_group.command(name="查询", description="查询成员的假封禁状态")
    @app_commands.guild_only()
    async def query_fake_ban(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True, thinking=True)

        if not interaction.guild:
            await interaction.edit_original_response(content="❌ 此命令只能在服务器中使用。")
            return

        config_data = self._get_guild_config(interaction.guild.id)
        if not self._is_feature_enabled(config_data):
            await interaction.edit_original_response(content="❌ 本服务器未启用假封禁功能。")
            return

        if not self._is_channel_allowed(interaction.channel, config_data):
            await interaction.edit_original_response(content="❌ 此命令只能在指定频道或论坛内使用。")
            return

        ban_data = await self.data_manager.get_ban(interaction.guild.id, member.id)
        if not ban_data:
            await interaction.edit_original_response(content="✅ 该成员未处于假封禁状态。")
            return

        until_ts = ban_data.until
        operator_id = ban_data.operator_id
        reason = ban_data.reason
        operator_mention = f"<@{operator_id}>" if operator_id else "未知"

        await interaction.edit_original_response(
            content=(
                f"⛔ {member.mention} 当前处于假封禁中。\n"
                f"- 结束: <t:{until_ts}:F> (<t:{until_ts}:R>)\n"
                f"- 操作人: {operator_mention}\n"
                f"- 原因: {reason}"
            )
        )


async def setup(bot: 'NewsBot') -> None:
    await bot.add_cog(FakeBanCog(bot))
