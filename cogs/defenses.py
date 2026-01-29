import discord
from discord.ext import commands
import re
from .base_moderation import BaseModerationCog, PENDING_EMOJI

# Tabla de puntos oficial para Defensas (Aliados vs Enemigos)
DEFENSE_POINTS = [
    # 0 Ene, 1 Ene, 2 Ene, 3 Ene, 4 Ene, 5 Ene
    [0, 120, 150, 180, 210, 240], # 1 Aliado
    [0,  90, 120, 150, 180, 210], # 2 Aliados
    [0,  60,  90, 120, 150, 180], # 3 Aliados
    [0,  15,  60,  90, 120, 150], # 4 Aliados
    [0,   8,  15,  60,  90, 120]  # 5 Aliados
]

class Defensa(BaseModerationCog):
    def __init__(self, bot: commands.Bot):
        # Inicializa la base con el nombre "defenses" para los archivos JSON
        super().__init__(bot, "defenses")

    def is_relevant_channel(self, channel_id: int):
        """Verifica si el canal comienza con 'defenses-'."""
        ch = self.bot.get_channel(channel_id)
        return ch and ch.name.lower().startswith('defenses-')

    async def _award_points(self, payload: discord.RawReactionActionEvent, sub: dict, multiplier: float):
        """Suma puntos aplicando el multiplicador del evento (x2, x1.5, etc.)."""
        puntos_cog = self.bot.get_cog('Puntos')
        if not puntos_cog: return

        # Calculamos los puntos finales asegurando que sean enteros
        final_pts = int(sub['points'] * multiplier)
        
        for user_id in sub['allies']:
            await puntos_cog.add_points(payload, user_id, final_pts, 'defensa')

    async def _revert_points(self, payload: discord.RawReactionActionEvent, sub: dict, multiplier: float):
        """Resta los puntos si el administrador corrige la reacción."""
        puntos_cog = self.bot.get_cog('Puntos')
        if not puntos_cog: return

        final_pts = int(sub['points'] * multiplier)
        
        for user_id in sub['allies']:
            await puntos_cog.add_points(payload, user_id, -final_pts, 'defensa-revert')

    async def process_submission(self, message: discord.Message):
        """Procesa las capturas de pantalla enviadas para defensa."""
        # Evita duplicados si el bot ya puso el emoji de pendiente
        if any(r.me for r in message.reactions): return False

        # Verifica que el mensaje tenga imagen y menciones de aliados
        mentions = re.findall(r'<@!?(\d+)>', message.content)
        if not message.attachments or not mentions: return False

        # Obtiene el número de enemigos del nombre del canal (ej: defenses-vs4)
        match = re.search(r'vs(\d+)', message.channel.name.lower())
        num_enemies = int(match.group(1)) if match else 0
        num_allies = len(mentions)

        # Valida que los datos estén dentro de los límites de la tabla
        if not (1 <= num_allies <= 5 and 0 <= num_enemies <= 5):
            return False

        # Busca los puntos correspondientes en la matriz
        points = DEFENSE_POINTS[num_allies - 1][num_enemies]
        if points <= 0: return False

        # Registra el envío como pendiente de aprobación
        self.pending_submissions[str(message.id)] = {
            'points': points,
            'allies': mentions,
            'channel_id': message.channel.id
        }
        self.save_data(self.pending_submissions, self.pending_file)
        
        # Añade la reacción de revisión (📝)
        await message.add_reaction(PENDING_EMOJI)
        return True

async def setup(bot: commands.Bot):
    await bot.add_cog(Defensa(bot))