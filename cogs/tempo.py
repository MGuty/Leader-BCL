import discord
from discord.ext import commands
import re
import os
import json
from .base_moderation import BaseModerationCog, PENDING_EMOJI

# --- PUNTOS PARA TEMPO (image_7f33eb.png) ---
TEMPO_POINTS = {
    "5-10min": 15,
    "10-15min": 25,
    "15-20min": 40,
    "20-25min": 50,
    "25-30min": 60,
    "plus-de-30": 75,
}

class Tempo(BaseModerationCog):
    def __init__(self, bot: commands.Bot):
        # Inicializa la base con el nombre del cog para los archivos JSON
        super().__init__(bot, "tempo")

    def is_relevant_channel(self, channel_id: int) -> bool:
        """Determina si el canal es de tipo tempo-."""
        channel = self.bot.get_channel(channel_id)
        return channel and channel.name.lower().startswith('tempo-')

    async def _award_points(self, payload, submission, multiplier: float):
        """Otorga puntos multiplicados a todos los aliados mencionados."""
        puntos_cog = self.bot.get_cog('Puntos')
        if not puntos_cog: return

        # Calculamos los puntos finales aplicando el multiplicador (🔥, 🌕 o ☑️)
        base_points = submission['points']
        final_points = int(base_points * multiplier)

        for user_id in submission['allies']:
            await puntos_cog.add_points(payload, user_id, final_points, 'tempo')

    async def _revert_points(self, payload, submission, multiplier: float):
        """Resta los puntos otorgados previamente si se cambia la decisión."""
        puntos_cog = self.bot.get_cog('Puntos')
        if not puntos_cog: return

        base_points = submission['points']
        final_points = int(base_points * multiplier)

        for user_id in submission['allies']:
            await puntos_cog.add_points(payload, user_id, -final_points, 'tempo-revert')

    async def process_submission(self, message: discord.Message) -> bool:
        """Analiza el mensaje para detectar aliados y asignar puntos según el canal."""
        # Evita procesar si el bot ya reaccionó (ya está registrado)
        if any(r.me for r in message.reactions): return False

        # Busca menciones de usuarios en el texto
        mentions = re.findall(r'<@!?(\d+)>', message.content)
        
        # Validación: Debe tener imagen y menciones
        if not message.attachments or not mentions or not any(a.content_type.startswith('image/') for a in message.attachments):
            return False

        # Extraer la clave de puntos desde el nombre del canal (ej: tempo-15-20min)
        channel_name = message.channel.name.lower()
        key_part = ""
        try:
            key_part = channel_name.split('tempo-', 1)[1]
        except IndexError:
            return False

        if key_part not in TEMPO_POINTS:
            return False

        points = TEMPO_POINTS[key_part]
        if points <= 0: return False

        # Registro en la base de datos de pendientes (usando la estructura de la base)
        self.pending_submissions[str(message.id)] = {
            'points': points, 
            'allies': mentions
        }
        self.save_data(self.pending_submissions, self.pending_file)
        
        # Reacción de confirmación de lectura
        await message.add_reaction(PENDING_EMOJI)
        return True

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Escucha mensajes nuevos en los canales de tempo."""
        if message.author.bot or not self.is_relevant_channel(message.channel.id):
            return
        await self.process_submission(message)

async def setup(bot):
    await bot.add_cog(Tempo(bot))