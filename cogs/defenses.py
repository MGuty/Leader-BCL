# cogs/defenses.py
import discord
from discord.ext import commands
import re
import json

# Importamos la plantilla y las constantes comunes
from .base_moderation import BaseModerationCog, PENDING_EMOJI

# La tabla de puntos sigue siendo única para este Cog
DEFENSE_POINTS = [
#   0 Ene, 1 Ene, 2 Ene, 3 Ene, 4 Ene, 5 Ene
    [0,    120,   150,   180,   210,   240], # 1 Aliado
    [0,     90,   120,   150,   180,   210], # 2 Aliados
    [0,     60,    90,   120,   150,   180], # 3 Aliados
    [0,     15,    60,    90,   120,   150], # 4 Aliados
    [0,      5,    15,    60,    90,   120]  # 5 Aliados
]

class Defensa(BaseModerationCog):
    def __init__(self, bot: commands.Bot):
        # Llama al __init__ de la plantilla usando el identificador "defenses"
        super().__init__(bot, "defenses")

    # --- Métodos requeridos por la plantilla ---

    def is_relevant_channel(self, channel_id: int) -> bool:
        """Determina si el canal es de tipo defensa por su nombre."""
        channel = self.bot.get_channel(channel_id)
        return channel and channel.name.lower().startswith('defenses-')

    async def _award_points(self, payload, submission, multiplier: float = 1.0):
        """
        Calcula y otorga los puntos aplicando el multiplicador del emoji (✅, 🔥 o 🌕).
        """
        puntos_cog = self.bot.get_cog('Puntos')
        if puntos_cog:
            # Multiplicamos los puntos base por el valor del emoji seleccionado
            final_points = int(submission['points'] * multiplier)
            for user_id in submission['allies']:
                await puntos_cog.add_points(payload, user_id, final_points, 'defensa')

    async def _revert_points(self, payload, submission):
        """
        Revierte la cantidad exacta de puntos otorgados consultando el multiplicador guardado.
        """
        puntos_cog = self.bot.get_cog('Puntos')
        if puntos_cog:
            # Recuperamos el multiplicador del registro JSON
            multiplier = submission.get('multiplier', 1.0)
            final_points = int(submission['points'] * multiplier)
            for user_id in submission['allies']:
                await puntos_cog.add_points(payload, user_id, -final_points, 'defensa-revert')

    # --- Lógica de procesamiento específica de Defensa ---

    async def process_submission(self, message: discord.Message) -> bool:
        """Valida el mensaje y lo añade a pendientes si cumple los requisitos."""
        if any(reaction.me for reaction in message.reactions):
            return False

        all_mentions_in_text = re.findall(r'<@!?(\d+)>', message.content)
        if not message.attachments or not all_mentions_in_text or not any(att.content_type.startswith('image/') for att in message.attachments):
            return False

        num_allies = len(all_mentions_in_text)
        num_enemies = 0
        match = re.search(r'vs(\d+)', message.channel.name.lower())
        if match:
            num_enemies = int(match.group(1))

        if not (1 <= num_allies <= 5 and 0 <= num_enemies <= 5):
            return False
            
        points_to_award = DEFENSE_POINTS[num_allies - 1][num_enemies]
        
        # Si los puntos son 0, marcamos con emoji de duda y no procesamos
        if points_to_award == 0:
            await message.add_reaction('🤷')
            return False
        
        # Registramos el envío en la cola de pendientes de la clase base
        self.pending_submissions[str(message.id)] = {
            'points': points_to_award, 
            'allies': all_mentions_in_text
        }
        self.save_data(self.pending_submissions, self.pending_file)
        await message.add_reaction(PENDING_EMOJI)
        return True

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Escucha mensajes nuevos en los canales de defensa."""
        if message.author.bot or not self.is_relevant_channel(message.channel.id):
            return
        
        await self.process_submission(message)

async def setup(bot):
    await bot.add_cog(Defensa(bot))