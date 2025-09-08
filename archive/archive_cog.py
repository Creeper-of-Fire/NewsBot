import asyncio
import io
import re
import time
import typing

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from utility.permison import is_admin

# 假设你的主机器人文件中的Bot类叫做 'NewsBot'
# 如果不是，请将 'NewsBot' 替换为你的Bot类名
if typing.TYPE_CHECKING:
    from main import NewsBot

# 在两条消息之间主动等待的时间（秒）。可以减少撞上速率限制的几率。
# 0.5 是一个比较安全和通用的值。如果频道非常小，可以设为0。
INTER_MESSAGE_DELAY = 1


class ArchiveCog(commands.Cog):
    """
    一个用于将文本频道备份到论坛帖子中的Cog。
    """

    def __init__(self, bot: 'NewsBot'):
        self.bot = bot
        # 创建一个可复用的 aiohttp.ClientSession
        self.session = aiohttp.ClientSession()
        self.bot.logger.info("ArchiveCog loaded.")
        # 正则表达式用于匹配自定义表情符号 <a?:name:id>
        self.emoji_pattern = re.compile(r'<a?:(\w+):(\d+)>')

    async def cog_unload(self):
        # 在Cog卸载时关闭 aiohttp.ClientSession
        await self.session.close()

    async def _split_content(self, content: str, limit: int = 2000) -> list[str]:
        """
        一个“Markdown感知”的分割函数，优先保护代码块的完整性。
        """
        if len(content) <= limit:
            return [content]

        chunks = []
        lines = content.split('\n')
        current_chunk = ""
        in_code_block = False
        code_block_lang = ""

        for line in lines:
            # 检查是否是代码块的分隔符
            if line.strip().startswith("```"):
                if in_code_block:
                    # 结束代码块
                    in_code_block = False
                else:
                    # 开始代码块
                    in_code_block = True
                    code_block_lang = line.strip()[3:]

            # 尝试将当前行加入块中
            # +1 是为了换行符
            if len(current_chunk) + len(line) + 1 > limit:
                # 当前块已满，需要保存
                chunks.append(current_chunk)

                # 开始新块
                # 如果我们刚刚因为空间不足而切断了一个代码块，
                # 需要在新块的开头重新打开它以保持语法。
                if in_code_block:
                    current_chunk = f"```{code_block_lang}\n"
                else:
                    current_chunk = ""

            # 将行添加到当前块
            if current_chunk:  # 如果不是块的开头
                current_chunk += "\n"
            current_chunk += line

        # 添加最后剩余的块
        if current_chunk:
            chunks.append(current_chunk)

        # 最终检查和修复：确保所有代码块都正确闭合
        final_chunks = []
        is_open = False
        lang = ""
        for chunk in chunks:
            # 检查这个块是否以未闭合的代码块结束
            if chunk.count("```") % 2 == 1:
                if is_open:  # 之前是打开的，这个块的```是关闭
                    final_chunks.append(chunk)
                    is_open = False
                else:  # 之前是关闭的，这个块的```是打开
                    # 在这个块的末尾添加闭合标记
                    final_chunks.append(chunk + "\n```")
                    is_open = True
                    # 从```行中提取语言，为下一个块做准备
                    for line in chunk.split('\n'):
                        if line.strip().startswith("```"):
                            lang = line.strip()[3:]

            elif is_open:
                # 这个块完全位于一个巨大的代码块内部
                # 在它的开头和结尾都加上标记
                final_chunks.append(f"```{lang}\n[代码块继续...]\n{chunk}\n```")
            else:
                # 普通块
                final_chunks.append(chunk)

        return final_chunks

    async def _get_or_create_webhook(self, channel: discord.TextChannel) -> discord.Webhook:
        """获取或创建一个用于备份的webhook。"""
        webhooks = await channel.webhooks()
        # 尝试寻找一个由我们机器人创建的webhook
        for webhook in webhooks:
            if webhook.user == self.bot.user:
                self.bot.logger.info(f"在频道 #{channel.name} 中找到已存在的webhook: {webhook.name}")
                return webhook

        # 如果没找到，就创建一个新的
        self.bot.logger.info(f"在频道 #{channel.name} 中未找到可用webhook，正在创建一个...")
        new_webhook = await channel.create_webhook(name="Channel Archiver Bot")
        self.bot.logger.info(f"已创建新的webhook: {new_webhook.name}")
        return new_webhook

    async def _parse_channel_from_url(self, url: str) -> typing.Optional[discord.abc.GuildChannel]:
        """从URL解析并获取频道对象。"""
        match = re.search(r'channels/\d+/(\d+)', url)
        if not match:
            return None

        channel_id = int(match.group(1))
        try:
            channel = await self.bot.fetch_channel(channel_id)
            return channel
        except (discord.NotFound, discord.Forbidden):
            return None

    async def _process_emojis(self, content: str) -> tuple[str, list[discord.File]]:
        """
        处理消息内容中的自定义表情。
        可访问的表情保持原样。
        不可访问的表情将被下载为文件，并在文本中替换为 :emoji_name:。
        """
        inaccessible_emoji_files = []

        # 使用 re.sub 的回调函数来处理每个匹配项
        async def replace_emoji(match):
            emoji_name = match.group(1)
            emoji_id = int(match.group(2))
            is_animated = match.group(0).startswith('<a:')

            def to_pure_text():
                if is_animated:
                    return f"<a:{emoji_name}.{emoji_id}>"
                return f"<:{emoji_name}.{emoji_id}>"

            original_text = to_pure_text()

            # 检查机器人是否能访问这个表情
            if self.bot.get_emoji(emoji_id) is None:
                # 无法访问，下载它
                extension = 'gif' if is_animated else 'png'
                emoji_url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{extension}"

                try:
                    async with self.session.get(emoji_url) as resp:
                        if resp.status == 200:
                            file_bytes = await resp.read()
                            filename = f"{emoji_name}.{extension}"
                            inaccessible_emoji_files.append(discord.File(io.BytesIO(file_bytes), filename=filename))
                            # 在文本中替换为纯文本格式
                            return f"`{original_text}`"
                        else:
                            # 如果下载失败，也返回纯文本
                            return f"`{original_text}` (无法加载)"
                except Exception as e:
                    self.bot.logger.error(f"下载无法访问的表情时出错 {emoji_url}: {e}")
                    return f"`{original_text}` (下载错误)"

            # 如果可以访问，保持原样
            return match.group(0)

        # re.sub 不直接支持异步回调，所以我们需要手动迭代
        processed_content = content
        matches = list(self.emoji_pattern.finditer(content))
        # 从后往前替换，避免索引错乱
        for match in reversed(matches):
            replacement = await replace_emoji(match)
            processed_content = processed_content[:match.start()] + replacement + processed_content[match.end():]

        return processed_content, inaccessible_emoji_files

    @app_commands.command(name="archive_channel", description="将一个文本频道完整备份到论坛频道的新帖子中(使用URL)。")
    @app_commands.describe(
        source_channel_url="要备份的源文本频道的URL。",
        destination_forum_url="用于存放备份贴的目标论坛频道的URL。",
        post_title="在论坛中创建的备份帖子的标题。"
    )
    @is_admin()
    async def archive_channel(
            self,
            interaction: discord.Interaction,
            source_channel_url: str,
            destination_forum_url: str,
            post_title: str
    ):
        """核心的备份命令。"""
        thread = None

        await interaction.response.defer(ephemeral=False, thinking=True)
        # 先用 interaction.followup 发送初始消息
        initial_status_message = await interaction.followup.send("⏳ 正在初始化备份任务...", wait=True, ephemeral=False)
        # 然后，立即通过其所在频道 fetch 它，得到一个常规的 discord.Message 对象。
        # 这个新对象的 .edit() 方法将使用机器人的永久 token，而不是临时的 interaction token。
        try:
            status_message = await initial_status_message.channel.fetch_message(initial_status_message.id)
        except (discord.NotFound, discord.Forbidden):
            # 极端情况：消息刚发出就被删了，或者机器人失去了查看权限。
            # 在这种情况下，我们无法更新状态，但可以继续执行任务。
            self.bot.logger.warning("无法获取状态消息的永久句柄，将无法更新进度。")
            status_message = None  # 将其设为None，后续的更新逻辑会跳过它。

        try:
            # 1. 解析URL并验证频道
            self.bot.logger.info("正在解析URL并获取频道对象...")
            source_channel = await self._parse_channel_from_url(source_channel_url)
            destination_forum = await self._parse_channel_from_url(destination_forum_url)

            # 验证源频道
            if not source_channel:
                await interaction.followup.send("无法找到或访问源频道URL。请检查链接是否正确，以及我是否在该服务器中。", ephemeral=True)
                return
            if not isinstance(source_channel, (discord.TextChannel, discord.Thread)):
                await interaction.followup.send(f"源频道必须是普通文本频道/子区，但提供的URL指向了一个 `{type(source_channel).__name__}`。", ephemeral=True)
                return

            # 验证目标频道
            if not destination_forum:
                await interaction.followup.send("无法找到或访问目标论坛URL。请检查链接是否正确，以及我是否在该服务器中。", ephemeral=True)
                return
            if not isinstance(destination_forum, discord.ForumChannel):
                await interaction.followup.send(f"目标频道必须是论坛频道，但提供的URL指向了一个 `{type(destination_forum).__name__}`。", ephemeral=True)
                return

            self.bot.logger.info(
                f"用户 {interaction.user} 请求备份频道 #{source_channel.name} 到论坛 #{destination_forum.name}，标题为 '{post_title}'"
            )

            # 1. 获取或创建 Webhook
            webhook = await self._get_or_create_webhook(destination_forum)

            # 2. 获取源频道的所有消息 (按时间从旧到新)
            self.bot.logger.info(f"正在从 #{source_channel.name} 获取历史消息...")
            history = [msg async for msg in source_channel.history(limit=None, oldest_first=True)]
            total_messages = len(history)
            self.bot.logger.info(f"共找到 {total_messages} 条消息需要备份。")

            if not history:
                await interaction.followup.send("源频道中没有任何消息，无需备份。", ephemeral=True)
                return

            # 3. 在论坛频道中创建帖子 (使用机器人身份，使其可编辑)
            start_content = (
                f"**频道备份开始**\n\n"
                f"源频道: {source_channel.mention}\n"
                f"总消息数: {total_messages}\n"
                f"操作人: {interaction.user.mention}"
            )
            # 使用 ForumChannel.create_thread 让机器人自己发帖
            # 这会返回一个 thread 对象，它的 starter_message 就是我们刚发的这条
            thread, thread_start_message = await destination_forum.create_thread(
                name=post_title,
                content=start_content,
                allowed_mentions=discord.AllowedMentions.none()
            )

            self.bot.logger.info(f"已在论坛 #{destination_forum.name} 中创建帖子: '{post_title}' (ID: {thread.id})")

            # 4. 迭代并复制每条消息
            message_map = {}
            start_time = time.time()

            for index, message in enumerate(history):
                # --- 改进的进度更新 ---
                if index % 10 == 0 or index == total_messages - 1:
                    elapsed_time = time.time() - start_time
                    if elapsed_time > 0:
                        msgs_per_sec = (index + 1) / elapsed_time
                        remaining_msgs = total_messages - (index + 1)
                        eta_seconds = remaining_msgs / msgs_per_sec if msgs_per_sec > 0 else 0
                        eta = time.strftime("%H:%M:%S", time.gmtime(eta_seconds)) if eta_seconds > 0 else "很快"
                        progress_text = f"⚙️ 正在备份... `({index + 1}/{total_messages})`\n速度: `{msgs_per_sec:.1f}条/秒` | 预计剩余: `{eta}`"
                        if status_message:
                            try:
                                await status_message.edit(content=progress_text)
                            except discord.errors.HTTPException as e:
                                self.bot.logger.warning(f"无法更新状态消息 (可能因网络波动或权限变更): {e}")
                            except Exception as e:
                                self.bot.logger.error(f"更新状态消息时发生未知错误: {e}", exc_info=False)

                if not message.content and not message.attachments and not message.embeds:
                    continue

                # ----- 处理发送者信息（包括已离开的用户） -----
                author_name = "未知用户"
                author_avatar_url = self.bot.user.display_avatar.url  # 默认使用机器人头像
                author_id_str = "N/A"

                if message.author:
                    author_id_str = str(message.author.id)
                    # 检查用户是否仍在服务器内
                    if isinstance(message.author, discord.Member):
                        author_name = message.author.display_name
                        author_avatar_url = message.author.display_avatar.url
                    else:  # 用户已离开服务器 (是 discord.User 对象)
                        author_name = f"{message.author.name}"
                        author_avatar_url = message.author.default_avatar.url

                # ----- 处理附件 -----
                files_to_upload = []
                for attachment in message.attachments:
                    try:
                        async with self.session.get(attachment.url) as resp:
                            if resp.status == 200:
                                file_bytes = await resp.read()
                                discord_file = discord.File(io.BytesIO(file_bytes), filename=attachment.filename)
                                files_to_upload.append(discord_file)
                            else:
                                self.bot.logger.warning(f"下载附件失败 {attachment.url}, status: {resp.status}")
                    except Exception as e:
                        self.bot.logger.error(f"处理附件 {attachment.url} 时发生错误: {e}")

                # ----- 处理内容和自定义表情 -----
                processed_content, inaccessible_emoji_files = await self._process_emojis(message.content)
                files_to_upload.extend(inaccessible_emoji_files)

                # ----- 处理回复和空内容占位符 -----
                final_content = processed_content
                if not final_content and (files_to_upload or message.embeds):
                    final_content = "*无消息内容*"

                if message.reference and message.reference.message_id in message_map:
                    replied_to_new_msg = message_map[message.reference.message_id]
                    # 使用我们处理过的 author_name
                    replied_to_author_name = replied_to_new_msg.author.display_name
                    reply_header = f"> [回复 @{replied_to_author_name}]({replied_to_new_msg.jump_url})\n"
                    final_content = reply_header + final_content

                # ----- 添加元数据 -----
                # 使用 Discord 的动态时间戳格式，它会自动适应用户的时区
                timestamp = int(message.created_at.timestamp())
                metadata_line = (
                    f"\n"
                    f"> -# 用户UID: {author_id_str} | 时间: <t:{timestamp}:F>"
                )
                final_content += metadata_line

                # ----- 发送 Webhook 消息 -----
                if not final_content.strip() and not message.embeds and not files_to_upload:
                    continue

                try:
                    # 使用我们新的分割函数
                    content_chunks = await self._split_content(final_content)

                    # 发送第一块，带上所有附件和embed
                    first_chunk = content_chunks.pop(0) if content_chunks else ""

                    new_message = await webhook.send(
                        content=first_chunk,
                        username=author_name,
                        avatar_url=author_avatar_url,
                        embeds=message.embeds,
                        files=files_to_upload,
                        thread=thread,
                        allowed_mentions=discord.AllowedMentions.none(),
                        wait=True
                    )
                    message_map[message.id] = new_message

                    # 如果还有后续的块，分开发送它们
                    for chunk in content_chunks:
                        await asyncio.sleep(INTER_MESSAGE_DELAY)  # 在发送每个块之间也稍作等待
                        await webhook.send(
                            content=chunk,
                            username=author_name,
                            avatar_url=author_avatar_url,
                            thread=thread,
                            allowed_mentions=discord.AllowedMentions.none(),
                            wait=True  # 等待可以保证顺序
                        )

                    await asyncio.sleep(INTER_MESSAGE_DELAY)

                except Exception as e:
                    self.bot.logger.error(f"发送消息时遇到异常: {e}", exc_info=True)
                    error_text = str(e)
                    if hasattr(e, 'text'): error_text = e.text
                    await thread.send(f"⚠️ **警告**: 备份源消息(ID: {message.id})时失败。错误: `{error_text}`", allowed_mentions=discord.AllowedMentions.none())

                if (index + 1) % 25 == 0 or (index + 1) == total_messages:
                    self.bot.logger.info(f"备份进度: {index + 1}/{total_messages}")

            # 5. 完成后更新占位消息或发送完成消息
            await thread.send(f"✅ **频道备份完成！** 共计 {len(message_map)} 条有效消息已成功迁移。{interaction.user.mention}")
            await status_message.edit(content=f"✅ **频道备份完成！** 共计 {len(message_map)} 条有效消息已成功迁移。")
            self.bot.logger.info(f"频道 #{source_channel.name} 的备份任务成功完成。")

        except discord.errors.Forbidden:
            self.bot.logger.error(f"权限不足，无法在 #{destination_forum_url} 或 #{source_channel_url} 中操作。")
            error_message = (
                "错误：我没有足够的权限来执行此操作。\n"
                "请确保我拥有在源频道**读取历史消息**和在目标论坛频道**发送消息**、**管理Webhook**和**创建帖子**的权限。"
            )
            # 如果 interaction token 还有效，就用它回复
            if not interaction.is_expired():
                await interaction.followup.send(error_message, ephemeral=True)
            # 如果 token 过期了，至少在日志里记录
            else:
                self.bot.logger.error("Interaction token已过期，无法发送最终错误消息给用户。")


        except Exception as e:
            self.bot.logger.error(f"备份频道时发生未知错误: {e}", exc_info=True)
            error_message = f"发生了一个意外错误: `{e}`\n请检查控制台日志获取详细信息。"
            # 如果帖子已经创建，就在帖子中发送错误消息，因为 interaction 可能已过期。
            if thread:
                await thread.send(f"❌ **备份任务意外终止！**\n{error_message}")
            # 如果帖子还没创建，尝试用 interaction 回复
            elif not interaction.is_expired():
                await interaction.followup.send(error_message, ephemeral=True)
            # 如果两者都不可用，则只记录日志（已经在上面记录过了）


async def setup(bot: 'NewsBot') -> None:
    """Cog的入口点。"""
    await bot.add_cog(ArchiveCog(bot))
