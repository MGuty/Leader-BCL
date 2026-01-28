import discord
from discord.ext import commands
import re
from .base_moderation import BaseModerationCog, PENDING_EMOJI

# Nueva tabla de puntos proporcionada por el usuario
ATTACK_POINTS = [
    # 0 Ene, 1 Ene, 2 Ene, 3 Ene, 4 Ene, 5 Ene
    [10, 30, 75, 90, 105, 120], # 1 Aliado
    [8, 45, 60, 75, 90, 105],   # 2 Aliados
    [6, 30, 45, 60, 75, 90],    # 3 Aliados
    [4, 7, 30, 45, 60, 75],     # 4 Aliados
    [2, 4, 7, 30, 45, 60]       # 5 Aliados
]

class Ataque(BaseModerationCog):
    def __init__(self, bot: commands.Bot):
        # Inicializa la base con el nombre "ataque" para los archivos de datos
        super().__init__(bot, "ataque")

    def is_relevant_channel(self, channel_id: int):
        """Verifica si el mensaje proviene de un canal de ataque."""
        ch = self.bot.get_channel(channel_id)
        return ch and ch.name.lower().startswith('ataque-')

    async def _award_points(self, payload: discord.RawReactionActionEvent, sub: dict, multiplier: float):
        """Suma puntos aplicando el multiplicador (🔥 x2, 🌕 x1.5, etc.)."""
        puntos_cog = self.bot.get_cog('Puntos')
        if not puntos_cog: return

        # Calculamos puntos finales redondeando a entero
        final_pts = int(sub['points'] * multiplier)
        
        for user_id in sub['allies']:
            await puntos_cog.add_points(payload, user_id, final_pts, 'ataque')

    async def _revert_points(self, payload: discord.RawReactionActionEvent, sub: dict, multiplier: float):
        """Resta los puntos si el administrador cambia la reacción."""
        puntos_cog = self.bot.get_cog('Puntos')
        if not puntos_cog: return

        final_pts = int(sub['points'] * multiplier)
        
        for user_id in sub['allies']:
            await puntos_cog.add_points(payload, user_id, -final_pts, 'ataque-revert')

    async def process_submission(self, message: discord.Message):
        """Detecta nuevos envíos de capturas en los canales de ataque."""
        # Evita procesar mensajes que el bot ya marcó
        if any(r.me for r in message.reactions): return False

        # Busca menciones de usuarios y verifica que haya una imagen adjunta
        mentions = re.findall(r'<@!?(\d+)>', message.content)
        if not message.attachments or not mentions: return False

        # Extrae el número de enemigos del nombre del canal (ej: ataque-vs3)
        match = re.search(r'vs(\d+)', message.channel.name.lower())
        num_enemies = int(match.group(1)) if match else 0
        num_allies = len(mentions)

        # Valida que los números estén dentro del rango de la tabla (1-5 aliados, 0-5 enemigos)
        if not (1 <= num_allies <= 5 and 0 <= num_enemies <= 5):
            return False

        # Obtiene el valor base de la tabla proporcionada
        base_points = ATTACK_POINTS[num_allies - 1][num_enemies]
        if base_points <= 0: return False

        # Guarda el registro en la lista de pendientes esperando aprobación
        self.pending_submissions[str(message.id)] = {
            'points': base_points,
            'allies': mentions,
            'channel_id': message.channel.id
        }
        self.save_data(self.pending_submissions, self.pending_file)
        
        # Añade la reacción de "pendiente" (📝)
        await message.add_reaction(PENDING_EMOJI)
        return True

async def setup(bot: commands.Bot):
    await bot.add_cog(Ataque(bot))