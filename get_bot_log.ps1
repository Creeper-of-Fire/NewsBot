﻿<#
.SYNOPSIS
    一键SSH连接到RoleBot的ECS服务器并获取日志。

.DESCRIPTION
    此脚本使用指定的私钥文件和服务器IP，从 deploy.env 加载配置，
    然后自动执行SSH连接命令，并显示远程服务器上的RoleBot日志。

.NOTES
    作者: AI助手
    日期: 2024年6月26日
    版本: 1.0

    请确保：
    1. 你的私钥文件 (id_rsa_rolebot) 位于 $env:USERPROFILE\.ssh\ 目录下。
    2. 你的Windows系统已安装 OpenSSH 客户端 (Windows 10/11 通常内置)。
    3. 如果首次运行此脚本，可能需要调整PowerShell的执行策略。
#>

# --- 脚本配置 ---
$ErrorActionPreference = "Stop" # 遇到任何错误就停止脚本

# --- 1. 加载配置 ---
Write-Host "⚙️ 正在加载部署配置..." -ForegroundColor Yellow

$config = @{}
try {
    Get-Content ".\deploy.env" | ForEach-Object {
        if ($_ -match '^(.*?)=(.*)') {
            $key = $Matches[1].Trim()
            $value = $Matches[2].Trim()
            $config[$key] = $value
        }
    }
}
catch {
    Write-Host "❌ 错误: 无法读取 'deploy.env' 文件。请确保它存在且格式正确。" -ForegroundColor Red
    exit 1
}

# 从配置中提取变量
$sshHost = $config["SSH_HOST"]
$sshUser = $config["SSH_USER"]
$sshKeyPath = $config["SSH_PRIVATE_KEY_PATH"]
$remoteProjectDir = "/root/NewsBot" # 机器人代码在服务器上的存放位置
# Docker 容器名称，从 docker-compose.yml 中获取
$dockerContainerName = "newsbot"

# --- 脚本开始 ---

Write-Host "`n█████████████████████████████████████████████████████" -ForegroundColor DarkCyan
Write-Host "███ NewsBot ECS 日志获取脚本                  ███" -ForegroundColor DarkCyan
Write-Host "█████████████████████████████████████████████████████`n" -ForegroundColor DarkCyan

# 检查私钥文件是否存在
if (-not (Test-Path $sshKeyPath)) {
    Write-Host "❌ 错误: SSH 私钥文件未在 '$sshKeyPath' 找到。" -ForegroundColor Red
    Write-Host "   请检查 deploy.env 中的 SSH_PRIVATE_KEY_PATH 配置。" -ForegroundColor Gray
    exit 1
}

# 检查SSH客户端是否可用
# Get-Command 尝试找到 'ssh' 命令的路径
$sshExePath = Get-Command ssh -ErrorAction SilentlyContinue
if (-not $sshExePath) {
    Write-Host "错误: 'ssh' 命令未找到。" -ForegroundColor Red
    Write-Host "请确保已安装 OpenSSH 客户端或 Git Bash，并将其添加到 PATH 环境变量中。" -ForegroundColor Red
    Write-Host "Windows 10/11 用户通常可以在 '设置' -> '应用' -> '可选功能' 中安装 'OpenSSH 客户端'。" -ForegroundColor Yellow
    exit 1
}

# 调整私钥文件的权限 (可选但推荐，某些SSH客户端对权限要求严格)
try {
    # 权限调整代码保持注释，因为在Windows上通常不需要，且可能引起不必要的复杂性
    # 如果需要，用户可以手动取消注释并根据需要调整
}
catch {
    Write-Host "警告: 调整私钥文件权限失败。这通常不会阻止连接，但如果遇到权限问题，请手动检查。" -ForegroundColor Yellow
    Write-Host "错误信息: $($_.Exception.Message)" -ForegroundColor Yellow
}


# 执行SSH命令获取日志
Write-Host "🔧 正在连接到服务器 ($sshHost) 并获取 Docker 容器 '$dockerContainerName' 的日志..." -ForegroundColor Cyan
try {
    # 使用 docker logs -f 命令实时查看 Docker 容器日志
    ssh "$sshUser@$sshHost" -i "$sshKeyPath" "docker logs -f $dockerContainerName"
} catch {
    Write-Host "❌ 错误: 获取 Docker 日志失败。请检查以下事项：" -ForegroundColor Red
    Write-Host "- 用户名 '$sshUser' 是否正确？" -ForegroundColor Red
    Write-Host "- 服务器IP '$sshHost' 是否可达？" -ForegroundColor Red
    Write-Host "- 私钥文件 '$sshKeyPath' 是否对应服务器上的公钥？" -ForegroundColor Red
    Write-Host "- ECS实例的安全组（入方向22端口）是否允许你的IP连接？" -ForegroundColor Red
    Write-Host "- 远程服务器上 Docker 是否正在运行，并且容器 '$dockerContainerName' 是否存在且正在运行？" -ForegroundColor Red
    Write-Host "原始错误信息: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`n日志获取尝试结束。" -ForegroundColor Cyan