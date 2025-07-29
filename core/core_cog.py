from __future__ import annotations

import asyncio
import io
import os
import platform
import zipfile

import config
from core.embed_link.embed_manager import EmbedLinkManager
from utility.permison import is_admin

try:
    import distro

    IS_LINUX = True
except ImportError:
    IS_LINUX = False

import typing
from datetime import datetime, timezone
from typing import Dict, List

import discord
import psutil
from discord import app_commands
from discord.ext import commands, tasks


if typing.TYPE_CHECKING:
    from main import NewsBot


def _format_bytes(size: int) -> str:
    """将字节大小格式化为 KB, MB, GB 等。"""
    if size < 1024:
        return f"{size} B"
    for unit in ["", "K", "M", "G", "T", "P"]:
        if size < 1024.0:
            # 返回带有两位小数的字符串，例如 "956.00 MB"
            return f"{size:.2f} {unit}B"
        size /= 1024.0
    return f"{size:.2f} PB"


class CoreCog(commands.Cog, name="Core"):
    """
    核心协调Cog。
    - 管理全局的 role_name_cache。
    - 提供主面板入口命令。
    - 周期性地触发所有功能模块的安全缓存更新。
    - 对其他模块的具体实现和配置保持无知。
    """

    def __init__(self, bot: 'NewsBot'):
        self.bot = bot
        self.logger = bot.logger

        self.start_time = datetime.now(timezone.utc)

        self.role_name_cache: Dict[int, str] = {}

    async def cog_load(self) -> None:
        """当 Cog 被加载时，启动后台任务。"""
        self.logger.info("CoreCog 已加载，正在启动后台任务...")
        self.update_registered_embeds_task.start()

    def cog_unload(self):
        self.update_registered_embeds_task.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        """当 Cog 准备就绪时，注册持久化视图。"""
        self.logger.info("核心模块已就绪，主控制面板持久化视图已注册。")


    @tasks.loop(minutes=15)
    async def update_registered_embeds_task(self):
        """定时刷新所有已注册的EmbedLinkManager。"""
        self.bot.logger.info("开始刷新所有已注册的Embed链接...")
        managers = EmbedLinkManager.get_all_managers()
        if not managers:
            self.bot.logger.info("没有已注册的Embed链接管理器，跳过刷新。")
            return

        for manager in managers:
            await manager.refresh_from_config()
        self.bot.logger.info(f"已完成对 {len(managers)} 个管理器的刷新。")

    @update_registered_embeds_task.before_loop
    async def before_cache_update_task(self):
        """在任务开始前，等待机器人就绪并执行一次初始缓存。"""
        await self.bot.wait_until_ready()
        # 确保在第一次循环前，所有 feature_cogs 都已注册
        # setup_hook 是更稳妥的地方，但这里延迟一下也能工作
        await asyncio.sleep(5)
        self.logger.info("CoreCog 已就绪，准备执行首次缓存更新...")

    core_group = app_commands.Group(
        name=f"{config.COMMAND_GROUP_NAME}丨核心", description="机器人核心管理与状态指令",
        guild_ids=[gid for gid in config.GUILD_IDS],
        default_permissions=discord.Permissions(manage_threads=True),
    )

    async def link_module_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """为配置指令提供模块键的自动补全。"""
        keys = EmbedLinkManager.get_registered_keys()
        return [
            app_commands.Choice(name=key, value=key)
            for key in keys if current.lower() in key.lower()
        ]

    @core_group.command(name="配置embed链接", description="配置一个模块使用的Discord消息链接")
    @app_commands.describe(module="要配置的模块名", url="指向Discord消息的URL (留空以清除)")
    @app_commands.autocomplete(module=link_module_autocomplete)
    @is_admin()
    async def config_embed_link(self, interaction: discord.Interaction, module: str, url: typing.Optional[str] = None):
        """配置或清除一个模块的消息链接。"""
        manager = EmbedLinkManager.get_manager(module)
        if not manager:
            await interaction.response.send_message(f"❌ 错误：找不到名为 `{module}` 的模块。可用模块: `{'`, `'.join(EmbedLinkManager.get_registered_keys())}`",
                                                    ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            if url:
                await manager.set_from_url(url)
                await interaction.edit_original_response(content=f"✅ 成功！模块 `{module}` 的链接已更新。新的Embed已加载。")
            else:
                await manager.clear_config()
                await interaction.edit_original_response(content=f"🗑️ 成功！模块 `{module}` 的链接配置已被清除。它现在将显示默认内容。")
        except ValueError as e:
            await interaction.edit_original_response(content=f"❌ 错误: {e}")
        except Exception as e:
            self.bot.logger.error(f"配置模块 '{module}' 时发生未知错误: {e}")
            await interaction.edit_original_response(content=f"❌ 发生未知错误，请检查日志。")

    @core_group.command(name="系统状态", description="显示机器人和服务器的实时系统信息。")
    @is_admin()
    async def system_status(self, interaction: discord.Interaction):
        """
        【已增强】显示一个包含详细系统和 Redis 信息的监控面板。
        """
        await interaction.response.defer(ephemeral=False, thinking=True)

        # --- 1. 获取进程和机器人信息 ---
        process = psutil.Process()
        try:
            mem_info = process.memory_full_info()
            bot_mem_uss = mem_info.uss
            bot_mem_rss = mem_info.rss
        except AttributeError:
            mem_info = process.memory_info()
            bot_mem_rss = mem_info.rss
            bot_mem_uss = bot_mem_rss

        # --- 2. 获取系统资源信息 ---
        cpu_usage = psutil.cpu_percent(interval=1)
        ram_info = psutil.virtual_memory()

        # --- 3. 获取操作系统信息 ---
        os_display_name = ""
        kernel_display = ""
        os_ver_display = ""
        if IS_LINUX:
            os_display_name = distro.name()
            kernel_display = f"Linux {platform.release()}"
            os_ver_display = f"Linux ({distro.name()} {distro.version()})"
        else:
            os_display_name = platform.system()
            kernel_display = platform.release()
            os_ver_display = f"{platform.system()} {platform.version()}"

        # --- 4. 构建 Embed ---
        embed = discord.Embed(
            title="🤖 系统信息",
            color=discord.Color.from_rgb(107, 222, 122),
            timestamp=discord.utils.utcnow()
        )
        if self.bot.user.display_avatar:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        # Section 1: System Info
        embed.add_field(name="🖥️ 系统名称", value=f"{os_display_name}", inline=True)
        embed.add_field(name="🔧 内核版本", value=f"{kernel_display}", inline=True)
        embed.add_field(name="💻 操作系统版本", value=f"{os_ver_display}", inline=True)

        # Section 2: Resources
        embed.add_field(name="🐍 Python 版本", value=f"{platform.python_version()}", inline=True)
        embed.add_field(name="🔥 CPU 使用率", value=f"{cpu_usage}%", inline=True)
        embed.add_field(
            name="🧠 系统内存",
            value=f"{ram_info.percent}%\n"
                  f"({_format_bytes(ram_info.used)} / {_format_bytes(ram_info.total)})",
            inline=True
        )

        # Section 3: Bot Info
        uptime = datetime.now(timezone.utc) - self.start_time
        days, remainder = divmod(int(uptime.total_seconds()), 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{days}天 {hours}时 {minutes}分"

        embed.add_field(name="📊 Bot 内存 (独占)", value=f"{_format_bytes(bot_mem_uss)}", inline=True)
        embed.add_field(name="📈 Bot 内存 (常驻)", value=f"{_format_bytes(bot_mem_rss)}", inline=True)
        embed.add_field(name="👥 缓存用户数", value=f"{len(self.bot.users)}", inline=True)
        embed.add_field(name="⏱️ 机器人运行时长", value=f"{uptime_str}", inline=False)

        embed.set_footer(text=f"{self.bot.user.name} 系统监控")

        await interaction.followup.send(embed=embed)

    @core_group.command(name="获取数据备份", description="打包并发送 data 目录下的所有数据文件。")
    @is_admin()
    async def backup_data(self, interaction: discord.Interaction):
        """
        创建一个包含 'data' 目录下所有文件的 zip 压缩包，并私密地发送给命令使用者。
        """
        await interaction.response.defer(ephemeral=False, thinking=True)

        self.logger.info(
            f"数据备份操作触发: "
            f"用户: {interaction.user} ({interaction.user.id}), "
            f"服务器: {interaction.guild.name} ({interaction.guild.id})"
        )

        data_dir = "data"

        # 检查 data 目录是否存在且不为空
        if not os.path.isdir(data_dir) or not os.listdir(data_dir):
            await interaction.followup.send(f"ℹ️ `{data_dir}` 目录不存在或为空，无需备份。", ephemeral=True)
            return

        # 在内存中创建一个二进制文件对象
        memory_file = io.BytesIO()

        # 创建一个指向内存文件的 ZipFile 对象
        try:
            with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
                # 遍历 data 目录下的所有文件和子目录
                for root, dirs, files in os.walk(data_dir):
                    for file in files:
                        # 获取文件的完整路径
                        file_path = os.path.join(root, file)
                        # 计算文件在 zip 包内的相对路径，以保持目录结构
                        arcname = os.path.relpath(file_path, data_dir)
                        # 将文件写入 zip 包
                        zf.write(file_path, arcname)
        except Exception as e:
            self.logger.error(f"创建数据备份时发生错误: {e}", exc_info=True)
            await interaction.followup.send(f"❌ 创建备份失败: `{e}`", ephemeral=True)
            return

        # 在写入完成后，将内存文件的指针移回开头，以便读取
        memory_file.seek(0)

        # 创建一个带时间戳的文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.bot.user.name}的数据备份_{timestamp}.zip"

        # 创建 discord.File 对象并发送
        backup_file = discord.File(memory_file, filename=filename)
        await interaction.followup.send(content=f"📦 {interaction.user.mention}，这是您请求的数据备份文件：", file=backup_file, ephemeral=False)


async def setup(bot: 'NewsBot'):
    """Cog的入口点。"""
    await bot.add_cog(CoreCog(bot))
