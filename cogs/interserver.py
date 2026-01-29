# cogs/interserver.py (Simplificado con Herencia)
import discord
from discord.ext import commands
import re
import json

# Importamos la plantilla y las constantes comunes
from .base_moderation import BaseModerationCog, PENDING_EMOJI

# La tabla de puntos sigue siendo única para este Cog
INTERSERVER_POINTS = {
    "tempo-no_def-v1": 2,
    "koth-v2-v3": 10,
    "v4-v5": 30,
}

# La clase ahora hereda de BaseModerationCog
class Interserver(BaseModerationCog):
    def __init__(self, bot: commands.Bot):
        # Llama al __init__ de la plantilla, pasándole "interserver"
        super().__init__(bot, "interserver")

    # --- Métodos requeridos por la plantilla ---

    def is_relevant_channel(self, channel_id: int) -> bool:
        """La plantilla usa esto para saber si una reacción en un canal le concierne."""
        channel = self.bot.get_channel(channel_id)
        # Es relevante si el canal existe y su nombre empieza con 'interserver-'
        return channel and channel.name.lower().startswith('interserver-')

    async def _award_points(self, payload, submission):
        """La plantilla llama a esta función para dar puntos."""
        puntos_cog = self.bot.get_cog('Puntos')
        # La lógica es simple: 100% de los puntos a todos los aliados.
        for user_id in submission['allies']:
            await puntos_cog.add_points(payload, user_id, submission['points'], 'interserver')

    async def _revert_points(self, payload, submission):
        """La plantilla llama a esta función para quitar puntos."""
        puntos_cog = self.bot.get_cog('Puntos')
        for user_id in submission['allies']:
            await puntos_cog.add_points(payload, user_id, -submission['points'], 'interserver-revert')

    # --- Lógica de procesamiento específica de Interserver ---

    async def process_submission(self, message: discord.Message) -> bool:
        """Valida un mensaje y, si es correcto, lo añade a pendientes."""
        if any(reaction.me for reaction in message.reactions):
            return False

        all_mentions_in_text = re.findall(r'<@!?(\d+)>', message.content)
        if not message.attachments or not all_mentions_in_text or not any(att.content_type.startswith('image/') for att in message.attachments):
            return False

        channel_name_lower = message.channel.name.lower()
        try:
            key_part = channel_name_lower.split('interserver-', 1)[1]
            if key_part not in INTERSERVER_POINTS:
                return False
            points_to_award = INTERSERVER_POINTS[key_part]
        except IndexError:
            return False
        
        if points_to_award == 0:
            return False

        # Usa las propiedades de la clase base para manejar los datos
        self.pending_submissions[str(message.id)] = {'points': points_to_award, 'allies': all_mentions_in_text}
        self.save_data(self.pending_submissions, self.pending_file)
        await message.add_reaction(PENDING_EMOJI)
        return True

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """El listener de entrada que inicia el proceso."""
        if message.author.bot or not self.is_relevant_channel(message.channel.id):
            return
        
        await self.process_submission(message)

# El setup no cambia
async def setup(bot):
    await bot.add_cog(Interserver(bot))