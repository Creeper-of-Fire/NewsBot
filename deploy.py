#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NewsBot 一键部署 wrapper。

实际部署逻辑在 `shared.scripts.deploy`；显式 run_remote_deploy=False
跳过远程容器内的 post-deploy 步骤（NewsBot 没有 alembic 配置）。
"""
import sys

from shared.scripts.deploy import main as _main

if __name__ == "__main__":
    sys.exit(_main(run_remote_deploy=False))