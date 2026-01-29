# cogs/tempo.py
import discord
from discord.ext import commands
import re
import json

# Importamos la plantilla y las constantes comunes
from .base_moderation import BaseModerationCog, PENDING_EMOJI

# La tabla de puntos sigue siendo única para este Cog
TEMPO_POINTS = {
    "5-10min": 5,
    "10-15min": 15,
    "15-20min": 30,
    "20-25min": 45,
    "25-30min": 60,
    "plus-de-30": 75,
}

# La clase hereda de BaseModerationCog
class Tempo(BaseModerationCog):
    def __init__(self, bot: commands.Bot):
        # Llama al __init__ de la plantilla usando el identificador "tempo"
        super().__init__(bot, "tempo")

    # --- Métodos requeridos por la plantilla ---

    def is_relevant_channel(self, channel_id: int) -> bool:
        """Determina si el canal es de tipo tempo por su nombre."""
        channel = self.bot.get_channel(channel_id)
        return channel and channel.name.lower().startswith('tempo-')

    async def _award_points(self, payload, submission, multiplier: float = 1.0):
        """
        Otorga puntos aplicando el multiplicador del emoji seleccionado (✅, 🔥 o 🌕).
        """
        puntos_cog = self.bot.get_cog('Puntos')
        if puntos_cog:
            # Calculamos los puntos finales con el multiplicador
            final_points = int(submission['points'] * multiplier)
            for user_id in submission['allies']:
                await puntos_cog.add_points(payload, user_id, final_points, 'tempo')

    async def _revert_points(self, payload, submission):
        """
        Revierte los puntos exactos consultando el multiplicador guardado en el historial.
        """
        puntos_cog = self.bot.get_cog('Puntos')
        if puntos_cog:
            # Recuperamos el multiplicador del registro JSON
            multiplier = submission.get('multiplier', 1.0)
            final_points = int(submission['points'] * multiplier)
            for user_id in submission['allies']:
                await puntos_cog.add_points(payload, user_id, -final_points, 'tempo-revert')

    # --- Lógica de procesamiento específica de Tempo ---

    async def process_submission(self, message: discord.Message) -> bool:
        """Valida un mensaje y lo añade a la cola de pendientes."""
        if any(reaction.me for reaction in message.reactions):
            return False

        all_mentions_in_text = re.findall(r'<@!?(\d+)>', message.content)
        if not message.attachments or not all_mentions_in_text or not any(att.content_type.startswith('image/') for att in message.attachments):
            return False

        channel_name_lower = message.channel.name.lower()
        try:
            key_part = channel_name_lower.split('tempo-', 1)[1]
        except IndexError:
            return False

        if key_part not in TEMPO_POINTS:
            return False

        points_to_award = TEMPO_POINTS[key_part]
        if points_to_award == 0:
            return False

        # Guardamos el envío en la clase base para su moderación
        self.pending_submissions[str(message.id)] = {
            'points': points_to_award, 
            'allies': all_mentions_in_text
        }
        self.save_data(self.pending_submissions, self.pending_file)
        await message.add_reaction(PENDING_EMOJI)
        return True

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listener para capturar nuevos envíos en canales tempo-."""
        if message.author.bot or not self.is_relevant_channel(message.channel.id):
            return
        
        await self.process_submission(message)

async def setup(bot):
    await bot.add_cog(Tempo(bot))