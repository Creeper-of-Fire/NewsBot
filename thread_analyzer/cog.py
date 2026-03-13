from __future__ import annotations

import csv
import io
import typing
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.utils import snowflake_time
from discord.ext import commands

import config

if typing.TYPE_CHECKING:
    from main import NewsBot

# 定义 UTC+8 时区，确保时间显示符合本地习惯
UTC8 = timezone(timedelta(hours=8))

class ThreadAnalyzerCog(commands.Cog, name="ThreadAnalyzer"):
    """
    活跃子区（Thread）分析模块。
    用于导出当前服务器内所有活跃子区的详细构成情况。
    """

    def __init__(self, bot: 'NewsBot'):
        self.bot = bot
        self.logger = bot.logger

    # 定义指令组
    analyze_group = app_commands.Group(
        name=f"{config.COMMAND_GROUP_NAME}丨管理丨子区",
        description="服务器子区（Thread）分析相关指令",
        guild_ids=[gid for gid in config.GUILD_IDS],
        default_permissions=discord.Permissions(manage_messages=True),
    )

    def _generate_progress_bar(self, current: int, total: int, length: int = 15) -> str:
        """生成文本进度条"""
        percent = current / total
        filled_length = int(length * percent)
        bar = "■" * filled_length + "□" * (length - filled_length)
        return f"[{bar}] {int(percent * 100)}%"

    @app_commands.command(name="导出活跃子区深度报告", description="导出含唤醒检测（挖坟分析）的活跃子区CSV")
    @app_commands.checks.has_permissions(manage_threads=True)
    async def export_active_threads_detail_command(self, interaction: discord.Interaction):
        """
        导出活跃子区列表，包含最后发言时间推算，并检测“挖坟”行为。
        """
        self.logger.info(f"管理员 {interaction.user} 正在请求导出活跃子区深度报告 (含挖坟检测)...")
        await interaction.response.defer(ephemeral=True, thinking=True)

        guild = interaction.guild
        if not guild:
            await interaction.followup.send("❌ 无法获取服务器信息。", ephemeral=True)
            return

        try:
            # 1. 获取实时活跃数据
            self.logger.debug(f"正在从 API 拉取服务器 {guild.name} 的活跃子区数据...")
            threads_list = await guild.active_threads()

            total_threads = len(threads_list)
            if total_threads == 0:
                await interaction.followup.send("⚠️ 当前服务器没有任何活跃的子区。", ephemeral=True)
                return

            msg_ref = await interaction.followup.send(
                f"📊 获取成功，共找到 `{total_threads}` 个活跃子区。\n"
                f"🔎 正在逐个扫描消息历史以检测“挖坟”行为，这可能需要几分钟，请稍候...\n"
                f"{self._generate_progress_bar(0, total_threads)} (0/{total_threads})",
                ephemeral=True
            )

            # 2. 准备 CSV 数据
            output_buffer = io.StringIO()
            writer = csv.writer(output_buffer)

            # 更新表头：增加了 上次发言时间、唤醒间隔
            headers = [
                "子区名称", "所属频道", "类型", "创建者ID",
                "总消息数(近似)", "创建时间(UTC+8)", "自动归档(分)",
                "最后发言时间(UTC+8)", "当前空闲天数",
                "倒数第二条时间(UTC+8)", "唤醒间隔(天)",  # 新增核心字段
                "是否锁定", "子区ID"
            ]
            writer.writerow(headers)

            now = datetime.now(UTC8)
            count_processed = 0

            # 3. 遍历并处理数据
            for index, thread in enumerate(threads_list):
                # 每处理 10 个更新一次进度条，避免触发 API 速率限制
                if index % 10 == 0 or index == total_threads - 1:
                    await msg_ref.edit(content=
                                       f"📊 正在分析活跃子区数据...\n"
                                       f"🔎 正在检测幽灵唤醒/挖坟行为 (API 请求中)...\n"
                                       f"{self._generate_progress_bar(index + 1, total_threads)} ({index + 1}/{total_threads})"
                                       )

                # 基础信息
                parent_name = thread.parent.name if thread.parent else "未知/无父频道"
                created_at_str = thread.created_at.astimezone(UTC8).strftime('%Y-%m-%d %H:%M:%S') if thread.created_at else "未知"

                thread_type_map = {
                    discord.ChannelType.public_thread: "公开",
                    discord.ChannelType.private_thread: "私密",
                    discord.ChannelType.news_thread: "公告",
                }
                type_str = thread_type_map.get(thread.type, str(thread.type))

                # --- 核心逻辑 1: 基于 ID 推算最后时间 (快速) ---
                last_active_str = "无消息"
                idle_days_str = "-"
                last_msg_dt_local = None

                if thread.last_message_id:
                    last_msg_dt_utc = snowflake_time(thread.last_message_id)
                    last_msg_dt_local = last_msg_dt_utc.astimezone(UTC8)
                    last_active_str = last_msg_dt_local.strftime('%Y-%m-%d %H:%M:%S')

                    delta = now - last_msg_dt_local
                    idle_days_str = f"{delta.days + (delta.seconds / 86400):.1f}"

                # --- 核心逻辑 2: 挖坟检测 (慢速，需 API) ---
                prev_msg_time_str = "无法读取/无"
                wake_gap_days_str = "0"  # 默认为0，表示连续或新建

                try:
                    # 获取最后两条消息
                    # 注意：如果机器人没有权限读取该子区（如私密子区），这里会报错
                    if thread.permissions_for(guild.me).read_message_history:
                        messages = [m async for m in thread.history(limit=2)]

                        if len(messages) == 2:
                            # messages[0] 是最新的, messages[1] 是上一条
                            latest_msg = messages[0]
                            prev_msg = messages[1]

                            prev_msg_local = prev_msg.created_at.astimezone(UTC8)
                            prev_msg_time_str = prev_msg_local.strftime('%Y-%m-%d %H:%M:%S')

                            # 计算两条消息之间的时间差
                            gap_delta = latest_msg.created_at - prev_msg.created_at
                            wake_gap_days = gap_delta.total_seconds() / 86400
                            wake_gap_days_str = f"{wake_gap_days:.1f}"

                        elif len(messages) == 1:
                            prev_msg_time_str = "仅一条消息(新建)"
                            wake_gap_days_str = "新建"
                    else:
                        prev_msg_time_str = "无权限读取"
                        wake_gap_days_str = "-"

                except Exception as e:
                    # 捕获权限错误或其他网络错误，不打断循环
                    prev_msg_time_str = "读取错误"
                    self.logger.warning(f"读取子区 {thread.id} 历史消息失败: {e}")

                # 组装行数据
                row = [
                    thread.name,
                    parent_name,
                    type_str,
                    str(thread.owner_id) if thread.owner_id else "未知",
                    str(thread.message_count),
                    created_at_str,
                    str(thread.auto_archive_duration),
                    last_active_str,
                    idle_days_str,
                    prev_msg_time_str,  # 新增: 上一条消息时间
                    wake_gap_days_str,  # 新增: 唤醒间隔 (重点关注数据)
                    "是" if thread.locked else "否",
                    str(thread.id)
                ]
                writer.writerow(row)
                count_processed += 1

            # 4. 生成文件发送
            output_buffer.seek(0)
            csv_bytes = output_buffer.getvalue().encode('utf-8-sig')

            filename_time = datetime.now().strftime('%Y%m%d_%H%M%S')
            file_obj = discord.File(
                fp=io.BytesIO(csv_bytes),
                filename=f"活跃子区_挖坟分析_{guild.id}_{filename_time}.csv"
            )

            result_msg = (
                f"✅ **活跃子区深度分析报告已生成**\n"
                f"服务器：`{guild.name}`\n"
                f"已扫描子区：`{count_processed}` 个\n\n"
                f"🔎 **数据解读指南**：\n"
                f"- **唤醒间隔(天)**：这是检测“挖坟”的关键指标。\n"
                f"  - 如果此数值 **很大** (如 >30天)，说明该子区沉默了很久，最近突然有人发了一条消息将其“唤醒”。\n"
                f"  - 如果数值很小，说明是正常连续对话。\n"
                f"- **当前空闲天数**：如果此数值很大，说明它虽然在活跃列表里，但最近其实没人说话（可能被手动取消归档了）。"
            )

            await msg_ref.edit(content=result_msg, attachments=[file_obj])
            self.logger.info(f"成功导出 {count_processed} 条活跃子区数据 (含挖坟分析)。")

        except Exception as e:
            self.logger.error(f"导出活跃子区报告时发生错误: {e}", exc_info=True)
            if 'msg_ref' in locals():
                await msg_ref.edit(content=f"❌ 导出过程中发生错误: {e}")
            else:
                await interaction.followup.send(f"❌ 导出失败，请检查后台日志。\n错误信息: {e}", ephemeral=True)


async def setup(bot: 'NewsBot'):
    """Cog的入口点。"""
    await bot.add_cog(ThreadAnalyzerCog(bot))