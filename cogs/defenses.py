import discord
from discord.ext import commands
import re
from .base_moderation import BaseModerationCog, PENDING_EMOJI

DEFENSE_POINTS = [
    [0, 120, 150, 180, 210, 240],
    [0,  90, 120, 150, 180, 210],
    [0,  60,  90, 120, 150, 180],
    [0,  15,  60,  90, 120, 150],
    [0,   8,  15,  60,  90, 120]
]

class Defensa(BaseModerationCog):
    def __init__(self, bot): super().__init__(bot, "defenses")

    def is_relevant_channel(self, channel_id):
        ch = self.bot.get_channel(channel_id)
        return ch and ch.name.lower().startswith('defenses-')

    async def _award_points(self, payload, sub, multiplier: float):
        puntos_cog = self.bot.get_cog('Puntos')
        final_pts = int(sub['points'] * multiplier)
        for uid in sub['allies']:
            await puntos_cog.add_points(payload, uid, final_pts, 'defensa')

    async def _revert_points(self, payload, sub, multiplier: float):
        puntos_cog = self.bot.get_cog('Puntos')
        final_pts = int(sub['points'] * multiplier)
        for uid in sub['allies']:
            await puntos_cog.add_points(payload, uid, -final_pts, 'defensa-revert')

    async def process_submission(self, message):
        if any(r.me for r in message.reactions): return False
        mentions = re.findall(r'<@!?(\d+)>', message.content)
        if not message.attachments or not mentions: return False
        num_allies = len(mentions)
        match = re.search(r'vs(\d+)', message.channel.name.lower())
        num_enemies = int(match.group(1)) if match else 0
        if not (1 <= num_allies <= 5 and 0 <= num_enemies <= 5): return False
        points = DEFENSE_POINTS[num_allies - 1][num_enemies]
        if points <= 0: return False
        self.pending_submissions[str(message.id)] = {'points': points, 'allies': mentions}
        self.save_data(self.pending_submissions, self.pending_file)
        await message.add_reaction(PENDING_EMOJI)
        return True

async def setup(bot): await bot.add_cog(Defensa(bot))