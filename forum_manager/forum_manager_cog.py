# NewsBot/forum_manager/forum_manager_cog.py
from __future__ import annotations

import asyncio
import re
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Optional

import discord
import pytz
from discord import app_commands
from discord.ext import commands, tasks

import config
from config_data import GUILD_CONFIGS
from utility.permison import is_admin

# 我们需要从 virtual_role cog 中导入视图，以便附加到新帖子上

if TYPE_CHECKING:
    from main import NewsBot


class ForumManagerCog(commands.Cog, name="ForumManager"):
    """
    负责新闻论坛的每日自动化管理，包括发帖、归档和更新快讯。
    """
    __cog_tasks__: list[tasks.Loop]

    def __init__(self, bot: 'NewsBot'):
        self.bot = bot
        self.logger = bot.logger
        # 启动主任务循环
        self.master_daily_task.start()

    def cog_unload(self):
        # 当cog卸载时，自动停止所有任务
        self.master_daily_task.cancel()

    # ==================== 核心任务循环 ====================
    @tasks.loop(time=time(hour=0, minute=0, second=0, tzinfo=pytz.timezone("Asia/Shanghai")))
    async def master_daily_task(self):
        """
        主每日任务循环。每天0点触发，然后遍历所有服务器执行管理。
        """
        self.logger.info("主每日任务触发，开始为所有已配置的服务器执行论坛管理...")

        # 确保在机器人准备就绪后才执行
        await self.bot.wait_until_ready()

        for guild in self.bot.guilds:
            guild_config = GUILD_CONFIGS.get(guild.id, {})
            fm_config = guild_config.get("forum_manager_config")

            # 检查此服务器是否启用了该功能
            if fm_config and fm_config.get("enabled", False):
                self.logger.info(f"-> 正在为服务器 '{guild.name}' ({guild.id}) 执行任务...")
                try:
                    # 调用为单个服务器设计的管理函数
                    await self.daily_forum_management(guild.id)
                except Exception as e:
                    self.logger.error(f"在为服务器 '{guild.name}' 执行每日任务时捕获到未处理的异常: {e}", exc_info=True)

        self.logger.info("所有服务器的每日论坛管理执行完毕。")

    @master_daily_task.before_loop
    async def before_master_daily_task(self):
        """在任务循环开始前，等待机器人完全准备就绪。"""
        self.logger.info("每日主任务正在等待机器人上线...")
        await self.bot.wait_until_ready()
        self.logger.info("机器人已上线，每日主任务准备就绪。")

    # --- 辅助函数 ---
    async def find_daily_briefing_thread(self, forum: discord.ForumChannel, target_date: datetime.date) -> Optional[discord.Thread]:
        """通过标题和标签在论坛中查找指定日期的快讯帖子。(已使用健壮的日期匹配)"""
        # ==================== 正则表达式构建 ====================
        # 分别处理月和日
        month = target_date.month
        day = target_date.day

        # 如果月份是单位数，则构建一个可以匹配带或不带前导零的模式 (e.g., (0?7))
        # 否则，直接使用两位数
        month_pattern = f"(0?{month})" if month < 10 else str(month)

        # 对日期做同样处理
        day_pattern = f"(0?{day})" if day < 10 else str(day)

        # 组合成最终的日期匹配模式
        date_pattern_str = f"{target_date.year}年{month_pattern}月{day_pattern}日"

        title_pattern = re.compile(f"🗞️.*?每日快讯.*?-.*?{date_pattern_str}")
        # =============================================================

        # 检查活跃帖子
        for thread in forum.threads:
            if title_pattern.search(thread.name):
                return thread

        # 检查归档帖子 (更耗时)
        try:
            async for thread in forum.archived_threads(limit=200):  # 限制查找范围
                if title_pattern.search(thread.name):
                    return thread
        except discord.Forbidden:
            self.logger.warning(f"无法在论坛 '{forum.name}' 中搜索归档帖子，权限不足。")

        return None

    # --- 核心每日任务逻辑 ---
    async def daily_forum_management(self, guild_id: int):
        """每日任务的主体，由tasks.loop调用。"""
        # 从 task 对象获取 guild_id
        guild = self.bot.get_guild(guild_id)
        if not guild:
            self.logger.warning(f"每日任务：找不到服务器 {guild_id}。")
            return

        guild_config = GUILD_CONFIGS.get(guild.id, {})
        fm_config = guild_config.get("forum_manager_config")
        if not fm_config or not fm_config.get("enabled", False):
            return  # 如果服务器禁用了此功能，则跳过

        self.logger.info(f"[{guild.name}] 开始执行每日论坛管理任务...")

        # 获取配置
        forum_id = fm_config["forum_channel_id"]
        briefing_tag_id = fm_config["briefing_tag_id"]
        past_briefing_tag_id = fm_config["past_briefing_tag_id"]
        long_term_tag_id = fm_config["long_term_tag_id"]

        forum = guild.get_channel(forum_id)
        if not isinstance(forum, discord.ForumChannel):
            self.logger.error(f"[{guild.name}] 配置的论坛频道ID {forum_id} 无效或不是论坛频道。")
            return

        today = datetime.now(pytz.timezone(fm_config.get("timezone", "UTC"))).date()
        yesterday = today - timedelta(days=1)

        self.logger.info(f"[{guild.name}] 正在查找今天的快讯帖子...")
        today_thread = await self.find_daily_briefing_thread(forum, today)
        if today_thread:
            self.logger.info(f"[{guild.name}] 已找到今天的快讯帖子: {today_thread.name} (ID: {today_thread.id})")
        else:
            self.logger.info(f"[{guild.name}] 未找到今天的快讯帖子，将在稍后创建。")

        self.logger.info(f"[{guild.name}] 正在开始归档旧的快讯帖子")
        # --- 任务1: 归档旧的快讯帖子 ---
        try:
            briefing_tag = forum.get_tag(briefing_tag_id)
            past_tag = forum.get_tag(past_briefing_tag_id)

            if not briefing_tag or not past_tag:
                self.logger.error(f"[{guild.name}] 快讯或PAST快讯标签ID无效。")
            else:
                for thread in forum.threads:
                    # 如果帖子已经归档，直接跳过
                    if thread.archived:
                        continue

                    is_briefing = briefing_tag in thread.applied_tags
                    is_past = past_tag in thread.applied_tags

                    # 确定是否需要归档
                    should_archive = False

                    # 情况1: 帖子是“每日快讯”，但不是今天的帖子
                    if is_briefing:
                        # 如果是今天的帖子，就跳过它
                        if today_thread and thread.id == today_thread.id:
                            continue
                        # 否则，它就是一个需要归档的旧快讯
                        should_archive = True

                    # 情况2: 帖子被标记为 "PAST"，但还没归档
                    elif is_past:
                        should_archive = True

                    # 如果确定需要归档，就执行操作
                    if should_archive:
                        self.logger.info(f"[{guild.name}] 准备归档帖子: {thread.name}")

                        # 准备新的标签列表：确保有PAST标签，移除每日快讯标签
                        new_tags = [tag for tag in thread.applied_tags if tag.id != briefing_tag_id]
                        if past_tag not in new_tags:
                            new_tags.append(past_tag)

                        await thread.edit(
                            pinned=False,
                            locked=True,
                            archived=True,
                            applied_tags=new_tags
                        )
                        self.logger.info(f"[{guild.name}] 已成功归档: {thread.name}")
                        await asyncio.sleep(1)  # 避免速率限制

        except Exception as e:
            self.logger.error(f"[{guild.name}] 归档旧快讯时出错: {e}", exc_info=True)

        self.logger.info(f"[{guild.name}] 正在开始发布今天的新闻快讯")
        # --- 任务2: 发布今天的新闻快讯 ---
        try:
            # 检查是否已存在今天的帖子
            if today_thread:
                self.logger.info(f"[{guild.name}] 已有{today_thread.name}，进行置顶。")
                await today_thread.edit(pinned=True, locked=True)
            else:
                # 使用固定格式，避免 strftime 的平台差异
                today_str = f"{today.year}年{today.month}月{today.day}日"

                post_title = f"🗞️ | 每日快讯-{today_str}"
                # 引用你提供的帖子模板
                post_content = \
                    f"""
## 欢迎来到新闻论坛，类脑记者组向您问好，若您首次来到本版块，请阅读以下内容
> 我们将对信息进行数据评定，暂定为以下五维度： （商榷中，暂不实行）
> **· 社区影响： DCBA · 规模：DCBA · 可参照性：DCBA · 性质：X · 重要：0-100**

### 这里主要存在三大专栏，接下来为您介绍：
> **社区快递：极简的新闻，辅助您立刻了解社区动态和社区新闻
> 社区纪实：重大事件、社区meme、档案馆，辅助您了解社区文化
> 人物志：社区成员人物志与记者专访
> 博您一笑：好笑事物的集锦**
若您想回顾以往的每日快讯，可以仅查看 **每日快讯·PAST**
## 新闻杂谈：https://discord.com/channels/1134557553011998840/1399023716674834492
> 若有信息且您希望展示在这里 请以 "类脑新闻：///(您欲提供的信息) (若可以，遵照以上五维给出您预评定的数据)" 格式向记者组发起私信，谢谢
> {today_str} 每日快讯

### ⚠️ 点击下方链接前往订阅新闻通知：
https://discord.com/channels/1134557553011998840/1383603412956090578/1399856491745382512
"""
                briefing_tag = forum.get_tag(briefing_tag_id)

                new_thread, _ = await forum.create_thread(
                    name=post_title,
                    content=post_content,
                    applied_tags=[briefing_tag] if briefing_tag else [],
                )
                await new_thread.edit(pinned=True, locked=True)
                self.logger.info(f"[{guild.name}] 已成功创建、置顶并锁定今日快讯: {new_thread.name}")
        except Exception as e:
            self.logger.error(f"[{guild.name}] 创建今日快讯时出错: {e}", exc_info=True)

        self.logger.info(f"[{guild.name}] 正在开始归档其他过时帖子")

        # --- 任务3: 归档其他过时帖子 ---
        try:
            cutoff_time = datetime.now(pytz.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            # 遍历活跃帖子
            for thread in forum.threads:
                if thread.created_at < cutoff_time and \
                        not thread.locked and \
                        long_term_tag_id not in [tag.id for tag in thread.applied_tags]:
                    # 额外检查，确保不会意外归档今天的快讯（双重保险）
                    if today_thread and thread.id == today_thread.id:
                        continue
                    await thread.edit(locked=True, archived=True)
                    self.logger.info(f"[{guild.name}] 已归档过时帖子: {thread.name}")
                    await asyncio.sleep(1)
        except Exception as e:
            self.logger.error(f"[{guild.name}] 归档其他过时帖子时出错: {e}", exc_info=True)

        self.logger.info(f"[{guild.name}] 每日论坛管理任务执行完毕。")

    # --- 斜杠指令 ---
    forum_group = app_commands.Group(
        name=f"{config.COMMAND_GROUP_NAME}丨论坛", description="新闻论坛管理指令",
        guild_ids=[gid for gid in config.GUILD_IDS],
        default_permissions=discord.Permissions(manage_threads=True)
    )

    @forum_group.command(name="手动执行每日任务", description="[记者] 手动触发一次每日发帖和归档流程。")
    @is_admin()
    async def manual_run_daily_task(self, interaction: discord.Interaction):
        await interaction.response.send_message("⌛ 正在手动执行每日论坛管理任务...", ephemeral=True)
        await self.daily_forum_management(interaction.guild.id)
        await interaction.followup.send("✅ 任务执行完毕。", ephemeral=True)

    @forum_group.command(name="通知并更新快讯", description="[记者] 在当前帖子中使用，以通知订阅者并更新到每日快讯。")
    @is_admin()
    async def notify_and_update(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.Thread) or not isinstance(interaction.channel.parent, discord.ForumChannel):
            await interaction.response.send_message("❌ 此命令只能在论坛帖子内使用。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        thread = interaction.channel
        forum = thread.parent
        guild_config = GUILD_CONFIGS.get(interaction.guild_id, {})
        fm_config = guild_config.get("forum_manager_config", {})

        if forum.id != fm_config.get("forum_channel_id"):
            await interaction.followup.send("❌ 此命令不能在此论坛使用。", ephemeral=True)
            return

        # 1. 幽灵提及
        vr_cog = self.bot.get_cog("VirtualRoleCog")
        at_cog = self.bot.get_cog("AtCog")
        if not vr_cog or not at_cog:
            await interaction.followup.send("❌ 内部错误：虚拟身份组或@模块未加载。", ephemeral=True)
            return

        tag_map = fm_config.get("tag_to_virtual_role_map", {})
        mentioned_keys = []
        for tag in thread.applied_tags:
            if str(tag.id) in tag_map:
                role_key = tag_map[str(tag.id)]
                user_ids = await vr_cog.data_manager.get_users_in_role(role_key, interaction.guild_id)
                if user_ids:
                    await at_cog.perform_ghost_ping(thread, user_ids)
                    self.logger.info(f"为帖子 '{thread.name}' 的 '{role_key}' ({len(user_ids)}人) 执行了幽灵提及。")
                    mentioned_keys.append(role_key)

        # 2. 更新快讯帖子
        today = datetime.now(pytz.timezone(fm_config.get("timezone", "UTC"))).date()
        briefing_thread = await self.find_daily_briefing_thread(forum, today)

        if not briefing_thread:
            await interaction.followup.send("⚠️ 提及完成，但未找到今日快讯帖子，无法更新。", ephemeral=True)
            return

        try:
            long_term_tag_id = fm_config.get("long_term_tag_id")

            # 判断是否为长期更新
            is_long_term = long_term_tag_id in [tag.id for tag in thread.applied_tags]
            update_prefix = "🔄 **更新**：\n" if is_long_term else ""

            # 构建带表情符号且排除长期更新标签的标题列表
            formatted_tag_names = []
            for tag in thread.applied_tags:
                # 跳过长期更新标签本身，不让它显示在标题里
                if tag.id == long_term_tag_id:
                    continue

                # 如果标签有表情，就加上表情前缀
                if tag.emoji:
                    formatted_tag_names.append(f"{tag.emoji} {tag.name}")
                else:
                    formatted_tag_names.append(tag.name)

            # 组合成最终标题内容
            tag_content = " & ".join(formatted_tag_names)

            # 如果处理后标题为空 (例如帖子只有一个长期更新tag)，提供一个默认值
            if not tag_content and is_long_term:
                tag_content = "内容更新"
            elif not tag_content:
                tag_content = "新闻速递"  # 默认情况

            embed_footer = f"{tag_content}"

            embed_title = thread.name

            new_embed = discord.Embed(
                title=update_prefix + embed_title,
                description=f"{thread.jump_url}",
                color=discord.Color.green() if is_long_term else discord.Color.blue(),
                timestamp=datetime.now(pytz.utc)
            )
            new_embed.set_footer(text=embed_footer)
            new_embed.set_author(
                name=f"由 {interaction.user.display_name} 发布",
                url=f"https://discord.com/users/{interaction.user.id}",
                icon_url=interaction.user.display_avatar.url
            )

            await briefing_thread.send(embed=new_embed)

            msg = f"✅ 提及完成，并已成功更新至今日快讯！"
            if not mentioned_keys:
                msg = f"✅ 无人被提及，但已成功更新至今日快讯！"
            await interaction.followup.send(msg, ephemeral=True)

        except Exception as e:
            self.logger.error(f"更新快讯帖子时出错: {e}", exc_info=True)
            await interaction.followup.send("❌ 更新快讯时发生内部错误。", ephemeral=True)


async def setup(bot: 'NewsBot'):
    await bot.add_cog(ForumManagerCog(bot))
