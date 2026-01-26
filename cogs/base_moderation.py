import discord
from discord.ext import commands
import json
import os
import traceback

# --- Configuración de Emojis y Multiplicadores ---
# Mapeo de emojis de aprobación a su valor multiplicador
APPROVE_EMOJIS = {
    '✅': 1.0,   # Normal
    '🔥': 2.0,   # x2
    '🌕': 1.5,   # x1.5
    '☑️': 0.5    # x0.5
}
DENY_EMOJI = '❌'
PENDING_EMOJI = '📝'

class BaseModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot, cog_name: str):
        self.bot = bot
        self.cog_name = cog_name
        self.pending_file = f'pending_{cog_name}.json'
        self.judged_file = f'judged_{cog_name}.json'
        
        # Carga de datos persistentes
        self.pending_submissions = self.load_data(self.pending_file)
        self.judged_submissions = self.load_data(self.judged_file)
        
        # Variables de entorno
        self.admin_role_id = int(os.getenv("ADMIN_ROLE_ID", 0))
        self.log_channel_id = int(os.getenv("BOT_AUDIT_LOGS_CHANNEL_ID", 0))

    def load_data(self, filename):
        try:
            with open(filename, 'r') as f: return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError): return {}

    def save_data(self, data, filename):
        with open(filename, 'w') as f: json.dump(data, f, indent=4)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Manejador central de reacciones con lógica de multiplicadores."""
        # 1. Filtros básicos
        if not self.is_relevant_channel(payload.channel_id): return
        if payload.member.bot: return
        
        # Verificar rol de admin
        if not any(role.id == self.admin_role_id for role in payload.member.roles):
            return

        message_id_str = str(payload.message_id)
        emoji = str(payload.emoji)
        
        # Validar si el emoji es uno de los nuestros
        if emoji not in APPROVE_EMOJIS and emoji != DENY_EMOJI: return
        
        is_pending = message_id_str in self.pending_submissions
        is_judged = message_id_str in self.judged_submissions
        if not is_pending and not is_judged: return

        puntos_cog = self.bot.get_cog('Puntos')

        # --- CASO A: MENSAJE PENDIENTE (Primera vez) ---
        if is_pending:
            submission = self.pending_submissions.pop(message_id_str)
            
            if emoji in APPROVE_EMOJIS:
                multiplier = APPROVE_EMOJIS[emoji]
                await self._award_points(payload, submission, multiplier)
                
                submission['status'] = 'approved'
                submission['multiplier'] = multiplier
                self.judged_submissions[message_id_str] = submission
                await self.send_log_message(payload, submission, self.cog_name.capitalize(), f"aprobado (x{multiplier})")
            
            elif emoji == DENY_EMOJI:
                submission['status'] = 'denied'
                submission['multiplier'] = 0 # No importa el mult si es rechazado
                self.judged_submissions[message_id_str] = submission
                await self.send_log_message(payload, submission, self.cog_name.capitalize(), "rechazado")
            
            self.save_data(self.pending_submissions, self.pending_file)
            self.save_data(self.judged_submissions, self.judged_file)

        # --- CASO B: MENSAJE YA JUZGADO (Cambio de opinión) ---
        elif is_judged:
            submission = self.judged_submissions[message_id_str]
            old_status = submission.get('status')
            old_mult = submission.get('multiplier', 1.0)

            # 1. De rechazado a aprobado (con cualquier multiplicador)
            if emoji in APPROVE_EMOJIS and old_status == 'denied':
                new_mult = APPROVE_EMOJIS[emoji]
                await self._award_points(payload, submission, new_mult)
                submission['status'] = 'approved'
                submission['multiplier'] = new_mult
                await self.log_decision_change(payload, self.cog_name.capitalize(), f"APROBADO (x{new_mult})")

            # 2. De aprobado a rechazado
            elif emoji == DENY_EMOJI and old_status == 'approved':
                await self._revert_points(payload, submission, old_mult)
                submission['status'] = 'denied'
                submission['multiplier'] = 0
                await self.log_decision_change(payload, self.cog_name.capitalize(), "RECHAZADO")

            # 3. Cambio de multiplicador (ej: de ✅ a 🔥)
            elif emoji in APPROVE_EMOJIS and old_status == 'approved':
                new_mult = APPROVE_EMOJIS[emoji]
                if new_mult != old_mult:
                    # Quitamos los puntos anteriores y ponemos los nuevos
                    await self._revert_points(payload, submission, old_mult)
                    await self._award_points(payload, submission, new_mult)
                    submission['multiplier'] = new_mult
                    await self.log_decision_change(payload, self.cog_name.capitalize(), f"MULTIPLICADOR CAMBIADO A x{new_mult}")
                else:
                    return # Es el mismo emoji, no hacemos nada

            self.save_data(self.judged_submissions, self.judged_file)

    # --- Métodos abstractos ---
    def is_relevant_channel(self, channel_id: int) -> bool:
        raise NotImplementedError()

    async def _award_points(self, payload, submission, multiplier):
        raise NotImplementedError()

    async def _revert_points(self, payload, submission, multiplier):
        raise NotImplementedError()

    # --- Funciones de Logs ---
    async def send_log_message(self, payload, submission, type_str, action_str):
        log_channel = self.bot.get_channel(self.log_channel_id)
        if not log_channel: return
        link = f"https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}"
        await log_channel.send(f"📌 **{type_str}** {action_str} por {payload.member.mention}. [Ir al mensaje]({link})")

    async def log_decision_change(self, payload, type_str, new_status_str):
        log_channel = self.bot.get_channel(self.log_channel_id)
        if not log_channel: return
        link = f"https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}"
        await log_channel.send(f"🔄 **{type_str}**: Decisión cambiada a **{new_status_str}** por {payload.member.mention}. [Ver]({link})")