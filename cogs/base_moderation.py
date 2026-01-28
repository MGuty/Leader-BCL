import discord
from discord.ext import commands
import json
import os
import traceback

# --- CONFIGURACIÓN DE EMOJIS Y MULTIPLICADORES ---
# Define cuánto vale cada reacción de administrador
APPROVE_EMOJIS = {
    '✅': 1.0,  # Normal
    '🔥': 2.0,  # Evento Fuego / Bonus
    '🌕': 1.5,  # Evento Luna
    '☑️': 0.5   # Penalización o mitad de puntos
}
DENY_EMOJI = '❌'
PENDING_EMOJI = '📝'

class BaseModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot, cog_name: str):
        self.bot = bot
        self.cog_name = cog_name
        # Rutas dinámicas para archivos de datos según el módulo (ataque, defenses, etc.)
        self.pending_file = f'pending_{cog_name}.json'
        self.judged_file = f'judged_{cog_name}.json'
        
        self.pending_submissions = self.load_data(self.pending_file)
        self.judged_submissions = self.load_data(self.judged_file)
        
        # Carga de IDs desde el archivo .env
        self.admin_role_id = int(os.getenv("ADMIN_ROLE_ID", 0))
        self.log_channel_id = int(os.getenv("BOT_AUDIT_LOGS_CHANNEL_ID", 0))

    def load_data(self, filename):
        """Carga datos desde archivos JSON de forma segura."""
        try:
            if os.path.exists(filename):
                with open(filename, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error al cargar {filename}: {e}")
        return {}

    def save_data(self, data, filename):
        """Guarda los registros actuales en el disco."""
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Error al guardar {filename}: {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Escucha global de reacciones para aprobar o denegar puntos."""
        # Ignora si la reacción no es en un canal relevante o si es un bot
        if not self.is_relevant_channel(payload.channel_id) or payload.member.bot:
            return

        # Verifica si el usuario tiene el rol de administrador configurado
        if not any(role.id == self.admin_role_id for role in payload.member.roles):
            return

        msg_id = str(payload.message_id)
        emoji = str(payload.emoji)

        # Solo actúa si el emoji es de aprobación o denegación
        if emoji not in APPROVE_EMOJIS and emoji != DENY_EMOJI:
            return

        if msg_id in self.pending_submissions:
            submission = self.pending_submissions.pop(msg_id)
            
            if emoji in APPROVE_EMOJIS:
                multiplier = APPROVE_EMOJIS[emoji]
                # Llama a la función del módulo hijo (ataque/defensa) pasando el multiplicador
                await self._award_points(payload, submission, multiplier)
                
                submission.update({
                    'status': 'approved',
                    'multiplier': multiplier,
                    'judged_by': payload.member.display_name,
                    'emoji_used': emoji
                })
                self.judged_submissions[msg_id] = submission
                
            elif emoji == DENY_EMOJI:
                submission.update({
                    'status': 'denied',
                    'judged_by': payload.member.display_name
                })
                self.judged_submissions[msg_id] = submission

            # Actualiza los archivos JSON para reflejar el cambio
            self.save_data(self.pending_submissions, self.pending_file)
            self.save_data(self.judged_submissions, self.judged_file)

    # --- MÉTODOS QUE DEBEN SER DEFINIDOS EN LOS HIJOS (ATAQUE, DEFENSES, ETC) ---
    def is_relevant_channel(self, channel_id: int):
        """Debe devolver True si el canal pertenece al módulo."""
        raise NotImplementedError("Debes implementar is_relevant_channel en el Cog hijo.")

    async def _award_points(self, payload, submission, multiplier: float):
        """Debe sumar los puntos en la base de datos."""
        raise NotImplementedError("Debes implementar _award_points en el Cog hijo.")

    async def _revert_points(self, payload, submission, multiplier: float):
        """Debe restar los puntos en la base de datos."""
        raise NotImplementedError("Debes implementar _revert_points en el Cog hijo.")