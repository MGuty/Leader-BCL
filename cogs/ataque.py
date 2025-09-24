import discord
from discord.ext import commands
import re
import json
from .base_moderation import BaseModerationCog, PENDING_EMOJI

# --- TABLA DE PUNTOS ACTUALIZADA ---
ATTACK_POINTS = [
#   0 Ene, 1 Ene, 2 Ene, 3 Ene, 4 Ene, 5 Ene
    [2,      30,    75,   175,   300,   375], # 1 Aliado
    [2,      10,    60,   115,   255,   340], # 2 Aliados
    [2,      10,    45,    85,   225,   310], # 3 Aliados
    [2,      10,    10,    50,   170,   250], # 4 Aliados
    [2,      10,    10,    10,    75,   225]  # 5 Aliados
]

class Ataque(BaseModerationCog):
    def __init__(self, bot: commands.Bot):
        super().__init__(bot, "ataque")

    def is_relevant_channel(self, channel_id: int) -> bool:
        """La plantilla usa esto para saber si una reacción le concierne."""
        channel = self.bot.get_channel(channel_id)
        return channel and channel.name.lower().startswith('attack-')

    async def _award_points(self, payload, submission):
        """La plantilla llama a esta función para dar puntos."""
        puntos_cog = self.bot.get_cog('Puntos')
        for user_id in submission['allies']:
            await puntos_cog.add_points(payload, user_id, submission['points'], 'ataque')

    async def _revert_points(self, payload, submission):
        """La plantilla llama a esta función para quitar puntos."""
        puntos_cog = self.bot.get_cog('Puntos')
        for user_id in submission['allies']:
            await puntos_cog.add_points(payload, user_id, -submission['points'], 'ataque-revert')

    async def process_submission(self, message: discord.Message) -> bool:
        if any(r.me for r in message.reactions): return False

        mentions = re.findall(r'<@!?(\d+)>', message.content)
        if not message.attachments or not mentions or not any(a.content_type.startswith('image/') for a in message.attachments):
            return False

        num_allies, num_enemies = len(mentions), 0
        match = re.search(r'vs(\d+)', message.channel.name.lower())
        if match:
            num_enemies = int(match.group(1))
        elif "no-def" in message.channel.name.lower():
            num_enemies = 0

        if not (1 <= num_allies <= 5 and 0 <= num_enemies <= 5): return False
        
        points = ATTACK_POINTS[num_allies - 1][num_enemies]
        if points <= 0: return False

        self.pending_submissions[str(message.id)] = {'points': points, 'allies': mentions}
        self.save_data(self.pending_submissions, self.pending_file)
        await message.add_reaction(PENDING_EMOJI)
        return True

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not self.is_relevant_channel(message.channel.id):
            return
        await self.process_submission(message)

async def setup(bot):
    await bot.add_cog(Ataque(bot))