# cogs/ataque.py (Simplificado con Herencia)
import discord
from discord.ext import commands
import re
import json
# Importamos la plantilla
from .base_moderation import BaseModerationCog, PENDING_EMOJI

# La tabla de puntos sigue siendo única para este Cog
ATTACK_POINTS = [
#   0 Ene, 1 Ene, 2 Ene, 3 Ene, 4 Ene, 5 Ene
    [2,     60,    75,   90,   105,   120], # 1 Aliado
    [2,      45,   60,   75,    90,   105], # 2 Aliados
    [2,      30,   45,   60,    75,    90], # 3 Aliados
    [2,      15,   30,   45,    60,    75], # 4 Aliados
    [2,      7,    15,   30,    45,   120]  # 5 Aliados
]

class Ataque(BaseModerationCog):
    def __init__(self, bot: commands.Bot):
        # Llama al __init__ de la plantilla, pasándole "ataque"
        # para que sepa qué archivos de datos usar (pending_attacks.json, etc.)
        super().__init__(bot, "ataque")

    # --- Lógica específica de este Cog ---

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
        if any(reaction.me for reaction in message.reactions): return False

        all_mentions_in_text = re.findall(r'<@!?(\d+)>', message.content)
        if not message.attachments or not all_mentions_in_text or not any(att.content_type.startswith('image/') for att in message.attachments):
            return False

        num_allies = len(all_mentions_in_text)
        num_enemies = 0
        match = re.search(r'vs(\d+)', message.channel.name.lower())
        if match:
            num_enemies = int(match.group(1))
        elif "no-def" in message.channel.name.lower():
            num_enemies = 0

        if not (1 <= num_allies <= 5 and 0 <= num_enemies <= 5): return False

        points_to_award = ATTACK_POINTS[num_allies - 1][num_enemies]
        
        # Esta es la corrección clave: ahora solo se ignoran los que valen 0 o menos.
        if points_to_award <= 0:
            return False

        # Usamos self.pending_submissions y self.pending_file de la clase base
        self.pending_submissions[str(message.id)] = {'points': points_to_award, 'allies': all_mentions_in_text}
        self.save_data(self.pending_submissions, self.pending_file)
        await message.add_reaction(PENDING_EMOJI)
        return True

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """El listener de entrada sigue siendo específico."""
        if message.author.bot or not self.is_relevant_channel(message.channel.id):
            return
        await self.process_submission(message)

async def setup(bot):
    await bot.add_cog(Ataque(bot))