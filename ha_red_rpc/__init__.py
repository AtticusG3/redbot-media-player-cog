from redbot.core.bot import Red

from .ha_red_rpc import HARedRPC


async def setup(bot: Red) -> None:
    await bot.add_cog(HARedRPC(bot))
