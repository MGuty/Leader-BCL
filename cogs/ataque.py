import discord
from discord.ext import commands
import re
import json
from .base_moderation import BaseModerationCog, PENDING_EMOJI

# --- TABLA DE PUNTOS OFICIAL (image_7e88eb.png) ---
ATTACK_POINTS = [
#   0 Ene, 1 Ene, 2 Ene,  3 Ene,  4 Ene,  5 Ene
    [10,      30,    75,      90,    105,   120], # 1 Aliado
    [ 8,      45,    60,      75,     90,   105], # 2 Aliados
    [ 6,      30,    45,      60,     75,    90], # 3 Aliados
    [ 4,       7,    30,      45,     60,    75], # 4 Aliados
    [ 2,       4,     7,      30,     45,    60]  # 5 Aliados
]

class Ataque(BaseModerationCog):
    def __init__(self, bot: commands.Bot):
        # Inicializa la base con el nombre del cog para los archivos JSON
        super().__init__(bot, "ataque")

    def is_relevant_channel(self, channel_id: int) -> bool:
        """Determina si el canal es de tipo attack-."""
        channel = self.bot.get_channel(channel_id)
        return channel and channel.name.lower().startswith('attack-')

    async def _award_points(self, payload, submission, multiplier: float):
        """Otorga puntos multiplicados a todos los aliados mencionados."""
        puntos_cog = self.bot.get_cog('Puntos')
        if not puntos_cog: return

        # Calculamos los puntos finales aplicando el multiplicador (🔥, 🌕 o ☑️)
        base_points = submission['points']
        final_points = int(base_points * multiplier)

        for user_id in submission['allies']:
            await puntos_cog.add_points(payload, user_id, final_points, 'ataque')

    async def _revert_points(self, payload, submission, multiplier: float):
        """Resta los puntos otorgados previamente si se cambia la decisión."""
        puntos_cog = self.bot.get_cog('Puntos')
        if not puntos_cog: return

        base_points = submission['points']
        final_points = int(base_points * multiplier)

        for user_id in submission['allies']:
            await puntos_cog.add_points(payload, user_id, -final_points, 'ataque-revert')

    async def process_submission(self, message: discord.Message) -> bool:
        """Analiza el mensaje para detectar aliados, enemigos y registrar el envío."""
        # Evita procesar si el bot ya reaccionó (ya está registrado)
        if any(r.me for r in message.reactions): return False

        # Busca menciones de usuarios en el texto
        mentions = re.findall(r'<@!?(\d+)>', message.content)
        
        # Validación: Debe tener imagen, menciones y no ser bot
        if not message.attachments or not mentions or not any(a.content_type.startswith('image/') for a in message.attachments):
            return False

        # Detectar número de enemigos desde el nombre del canal (ej: attack-vs3)
        num_allies = len(mentions)
        num_enemies = 0
        match = re.search(r'vs(\d+)', message.channel.name.lower())
        
        if match:
            num_enemies = int(match.group(1))
        elif "no-def" in message.channel.name.lower():
            num_enemies = 0

        # Validar rangos de la tabla (1-5 aliados, 0-5 enemigos)
        if not (1 <= num_allies <= 5 and 0 <= num_enemies <= 5):
            return False
        
        # Obtener puntos base de la matriz
        base_points = ATTACK_POINTS[num_allies - 1][num_enemies]
        if base_points <= 0: return False

        # Registro en la base de datos de pendientes
        self.pending_submissions[str(message.id)] = {
            'points': base_points, 
            'allies': mentions
        }
        self.save_data(self.pending_submissions, self.pending_file)
        
        # Reacción de confirmación de lectura
        await message.add_reaction(PENDING_EMOJI)
        return True

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Escucha mensajes nuevos en los canales de ataque."""
        if message.author.bot or not self.is_relevant_channel(message.channel.id):
            return
        await self.process_submission(message)

async def setup(bot):
    await bot.add_cog(Ataque(bot))