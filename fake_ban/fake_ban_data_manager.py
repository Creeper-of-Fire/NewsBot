from __future__ import annotations

import time
from typing import Dict, Optional

from pydantic import BaseModel, Field

from utility.base_data_manager import AsyncUserGuildDataManager


# 定义单条禁言数据的结构
class FakeBanEntry(BaseModel):
    until: int = 0
    operator_id: int = 0
    reason: str = "无"
    created_at: int = Field(default_factory=lambda: int(time.time()))

class FakeBanDataManager(AsyncUserGuildDataManager[FakeBanEntry]):
    DATA_FILENAME = "fake_bans"
    USER_MODEL = FakeBanEntry

    async def get_ban(self, guild_id: int, user_id: int) -> Optional[FakeBanEntry]:
        ban = self.get_user_data(guild_id, user_id)

        now_ts = int(time.time())
        if not ban:
            return None

        # 检查过期逻辑
        if ban.until <= now_ts:
            self.remove_user_data(guild_id, user_id)
            # 数据变动，请求保存
            await self.save_data()
            return None

        return ban

    async def set_ban(self, guild_id: int, user_id: int, until_ts: int, operator_id: int, reason: str) -> FakeBanEntry:
        ban_entry = FakeBanEntry(
            until=int(until_ts),
            operator_id=int(operator_id),
            reason=reason,
            created_at=int(time.time())
        )
        ban = self.set_user_data(guild_id, user_id, ban_entry)
        await self.save_data()
        return ban

    async def clear_ban(self, guild_id: int, user_id: int) -> bool:
        if self.remove_user_data(guild_id, user_id):
            await self.save_data()
            return True
        return False
