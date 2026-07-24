#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NewsBot 远程部署 wrapper（容器内执行）。

由 deploy.py 通过 `docker compose run ... python3 /app/remote_deploy.py` 调用。
实际逻辑在 `shared.scripts.remote_deploy`。

NewsBot 没有 alembic 配置；deploy.py 通过 run_alembic=False 跳过这一步，
本文件通常不会被调用。保留作为统一结构（三个 bot 都有 remote_deploy.py）。
"""
from shared.scripts.remote_deploy import main

main()