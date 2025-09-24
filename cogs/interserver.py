# cogs/interserver.py (con Puntos por Tabla)
import discord
from discord.ext import commands
import re
import json

# Importamos la plantilla y las constantes comunes
from .base_moderation import BaseModerationCog, PENDING_EMOJI

# --- NUEVA TABLA DE PUNTOS BASE ---
# Esta es la tabla que me proporcionaste.
BASE_POINTS_TABLE = [
#   0 Ene, 1 Ene, 2 Ene,  3 Ene,  4 Ene,  5 Ene
    [0,     300,   700,    1500,   2000,   2500], # 1 Aliado
    [0,      50,   410,     880,   1500,   2000], # 2 Aliados
    [0,      50,   150,     560,   1100,   1500], # 3 Aliados
    [0,      50,    50,     330,    830,   1380], # 4 Aliados
    [0,      50,    50,      50,    600,   1100]  # 5 Aliados
]

class Interserver(BaseModerationCog):
    def __init__(self, bot: commands.Bot):
        super().__init__(bot, "interserver")

    # --- Métodos requeridos por la plantilla ---

    def is_relevant_channel(self, channel_id: int) -> bool:
        channel = self.bot.get_channel(channel_id)
        return channel and channel.name.lower().startswith('interserver-')

    async def _award_points(self, payload, submission):
        puntos_cog = self.bot.get_cog('Puntos')
        for user_id in submission['allies']:
            await puntos_cog.add_points(payload, user_id, submission['points'], 'interserver')

    async def _revert_points(self, payload, submission):
        puntos_cog = self.bot.get_cog('Puntos')
        for user_id in submission['allies']:
            await puntos_cog.add_points(payload, user_id, -submission['points'], 'interserver-revert')

    # --- LÓGICA DE PROCESAMIENTO ACTUALIZADA ---
    async def process_submission(self, message: discord.Message) -> bool:
        if any(reaction.me for reaction in message.reactions): return False

        all_mentions_in_text = re.findall(r'<@!?(\d+)>', message.content)
        if not message.attachments or not all_mentions_in_text or not any(att.content_type.startswith('image/') for att in message.attachments):
            return False

        # 1. Se calcula el número de aliados y enemigos
        num_allies = len(all_mentions_in_text)
        num_enemies = 0
        match = re.search(r'vs(\d+)', message.channel.name.lower())
        if match:
            num_enemies = int(match.group(1))
        # Se añade el caso "no-def" para mayor flexibilidad
        elif "no-def" in message.channel.name.lower():
            num_enemies = 0

        # 2. Se valida que los números estén dentro del rango de la tabla
        if not (1 <= num_allies <= 5 and 0 <= num_enemies <= 5): return False

        # 3. Se busca el valor base en la tabla
        base_points = BASE_POINTS_TABLE[num_allies - 1][num_enemies]
        
        # 4. Se calcula el 30% del valor base
        points_to_award = int(base_points * 0.30)
        
        if points_to_award <= 0:
            return False

        self.pending_submissions[str(message.id)] = {'points': points_to_award, 'allies': all_mentions_in_text}
        self.save_data(self.pending_submissions, self.pending_file)
        await message.add_reaction(PENDING_EMOJI)
        return True

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not self.is_relevant_channel(message.channel.id):
            return
        await self.process_submission(message)

async def setup(bot):
    await bot.add_cog(Interserver(bot))