# cogs/defensa.py (Simplificado con Herencia)
import discord
from discord.ext import commands
import re
import json

# Importamos la plantilla y las constantes comunes
from .base_moderation import BaseModerationCog, PENDING_EMOJI

# La tabla de puntos sigue siendo única para este Cog
DEFENSE_POINTS = [
#   0 Ene, 1 Ene, 2 Ene, 3 Ene, 4 Ene, 5 Ene
    [0,    120,   150,   180,   210,   240], # 1 Aliado
    [0,     90,   120,   150,   180,   210], # 2 Aliados
    [0,     60,    90,   120,   150,   180], # 3 Aliados
    [0,     15,    60,    90,   120,   150], # 4 Aliados
    [0,      5,    15,    60,    90,   120]  # 5 Aliados
]

# La clase ahora hereda de BaseModerationCog
class Defensa(BaseModerationCog):
    def __init__(self, bot: commands.Bot):
        # Llama al __init__ de la plantilla, pasándole "defenses"
        # para que sepa qué archivos de datos usar (pending_defenses.json, etc.)
        super().__init__(bot, "defenses")

    # --- Métodos requeridos por la plantilla ---

    def is_relevant_channel(self, channel_id: int) -> bool:
        """La plantilla usa esto para saber si una reacción en un canal le concierne."""
        channel = self.bot.get_channel(channel_id)
        # Es relevante si el canal existe y su nombre empieza con 'defenses-'
        return channel and channel.name.lower().startswith('defenses-')

    async def _award_points(self, payload, submission):
        """La plantilla llama a esta función para dar puntos."""
        puntos_cog = self.bot.get_cog('Puntos')
        for user_id in submission['allies']:
            await puntos_cog.add_points(payload, user_id, submission['points'], 'defensa')

    async def _revert_points(self, payload, submission):
        """La plantilla llama a esta función para quitar puntos."""
        puntos_cog = self.bot.get_cog('Puntos')
        for user_id in submission['allies']:
            await puntos_cog.add_points(payload, user_id, -submission['points'], 'defensa-revert')

    # --- Lógica de procesamiento específica de Defensa ---

    async def process_submission(self, message: discord.Message) -> bool:
        """Valida un mensaje y, si es correcto, lo añade a pendientes."""
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
        if points_to_award == 0:
            await message.add_reaction('🤷')
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
    await bot.add_cog(Defensa(bot))