# cogs/ataque.py (Final)
import discord
from discord.ext import commands
import re
import os
import json
import traceback

# --- CONFIGURACIÓN ---
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", 0))
BOT_AUDIT_LOGS_CHANNEL_ID = int(os.getenv("BOT_AUDIT_LOGS_CHANNEL_ID", 0))

# --- Emojis y Archivos de Datos ---
PENDING_EMOJI = '📝'
APPROVE_EMOJI = '✅'
DENY_EMOJI = '❌'
PENDING_ATTACKS_FILE = 'pending_attacks.json'
JUDGED_ATTACKS_FILE = 'judged_attacks.json'

# --- Tabla de Puntos ---
# Mantenemos la tabla de puntos original.
ATTACK_POINTS = [
#   0 Ene, 1 Ene, 2 Ene, 3 Ene, 4 Ene, 5 Ene
    [5,     120,   150,   180,   210,   240], # 1 Aliado
    [5,      90,   120,   150,   180,   210], # 2 Aliados
    [5,      60,    90,   120,   150,   180], # 3 Aliados
    [5,      30,    60,    90,   120,   150], # 4 Aliados
    [5,      15,    30,    60,    90,   120]  # 5 Aliados
]

class Ataque(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pending_attacks = self.load_data(PENDING_ATTACKS_FILE)
        self.judged_attacks = self.load_data(JUDGED_ATTACKS_FILE)

    def load_data(self, filename):
        """Carga datos desde un archivo JSON, devolviendo un diccionario vacío si falla."""
        try:
            with open(filename, 'r') as f: return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError): return {}

    def save_data(self, data, filename):
        """Guarda datos en un archivo JSON con formato legible."""
        with open(filename, 'w') as f: json.dump(data, f, indent=4)

    # --- FUNCIÓN CENTRALIZADA DE PROCESAMIENTO ---
    async def process_submission(self, message: discord.Message) -> bool:
        """
        Procesa un mensaje para ver si es un envío de ataque válido.
        Esta función ahora puede ser llamada por on_message y por el Cog de Admin.
        Devuelve True si el mensaje se añade a pendientes, False en caso contrario.
        """
        # Ignora mensajes que ya tienen reacciones del bot (ya procesados)
        if any(reaction.me for reaction in message.reactions):
            return False

        # Condiciones para un envío válido: debe tener imagen y menciones.
        all_mentions_in_text = re.findall(r'<@!?(\d+)>', message.content)
        if not message.attachments or not all_mentions_in_text or not any(att.content_type.startswith('image/') for att in message.attachments):
            return False

        # Lógica para calcular puntos basada en el nombre del canal.
        num_allies = len(all_mentions_in_text)
        num_enemies = 0
        match = re.search(r'vs(\d+)', message.channel.name.lower())
        if match:
            num_enemies = int(match.group(1))
        elif "no-def" in message.channel.name.lower():
            num_enemies = 0

        if not (1 <= num_allies <= 5 and 0 <= num_enemies <= 5):
            return False

        points_to_award = ATTACK_POINTS[num_allies - 1][num_enemies]
        if points_to_award == 0:
            await message.add_reaction('🤷')
            return False

        # Si todo es válido, se añade a la lista de pendientes.
        self.pending_attacks[str(message.id)] = {'points': points_to_award, 'allies': all_mentions_in_text}
        self.save_data(self.pending_attacks, PENDING_ATTACKS_FILE)
        await message.add_reaction(PENDING_EMOJI)
        return True

    # --- LISTENERS ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Escucha mensajes en los canales de ataque y los procesa."""
        if message.author.bot or not message.channel.name.lower().startswith('attack-'):
            return
        
        # Simplemente llama a la función de procesamiento central.
        await self.process_submission(message)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Maneja la lógica de aprobación, rechazo y cambio de decisión por parte de un admin."""
        if payload.member.bot or not any(role.id == ADMIN_ROLE_ID for role in payload.member.roles): return
        message_id_str = str(payload.message_id)
        emoji = str(payload.emoji)
        if emoji not in [APPROVE_EMOJI, DENY_EMOJI]: return
        
        is_pending = message_id_str in self.pending_attacks
        is_judged = message_id_str in self.judged_attacks
        if not is_pending and not is_judged: return

        puntos_cog = self.bot.get_cog('Puntos')

        if is_pending:
            submission = self.pending_attacks.pop(message_id_str)
            if emoji == APPROVE_EMOJI:
                if puntos_cog:
                    for user_id in submission['allies']:
                        await puntos_cog.add_points(payload, user_id, submission['points'], 'ataque')
                submission['status'] = 'approved'
                self.judged_attacks[message_id_str] = submission
                await self.send_log_message(payload, submission, "Ataque", "aprobado")
            elif emoji == DENY_EMOJI:
                submission['status'] = 'denied'
                self.judged_attacks[message_id_str] = submission
                await self.send_log_message(payload, submission, "Ataque", "rechazado")
            self.save_data(self.pending_attacks, PENDING_ATTACKS_FILE)
            self.save_data(self.judged_attacks, JUDGED_ATTACKS_FILE)

        elif is_judged:
            submission = self.judged_attacks[message_id_str]
            old_status = submission['status']
            if emoji == APPROVE_EMOJI and old_status == 'denied':
                if puntos_cog:
                    for user_id in submission['allies']:
                        await puntos_cog.add_points(payload, user_id, submission['points'], 'ataque')
                submission['status'] = 'approved'
                await self.log_decision_change(payload, "Ataque", "APROBADO")
            elif emoji == DENY_EMOJI and old_status == 'approved':
                if puntos_cog:
                    for user_id in submission['allies']:
                        await puntos_cog.add_points(payload, user_id, -submission['points'], 'ataque')
                submission['status'] = 'denied'
                await self.log_decision_change(payload, "Ataque", "RECHAZADO")
            self.judged_attacks[message_id_str] = submission
            self.save_data(self.judged_attacks, JUDGED_ATTACKS_FILE)

    # --- FUNCIONES DE LOGS ---
    async def send_log_message(self, payload, submission, type_str, action_str):
        log_channel = self.bot.get_channel(BOT_AUDIT_LOGS_CHANNEL_ID)
        if not log_channel: return
        message_link = f"https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}"
        if action_str == "aprobado":
            unique_ally_mentions = [f"<@{uid}>" for uid in set(submission['allies'])]
            await log_channel.send(f"{APPROVE_EMOJI} **{type_str}** {action_str} por {payload.member.mention}. [Ir al envío]({message_link})\n> Se han otorgado **`{submission['points']}`** puntos por mención a: {', '.join(unique_ally_mentions)}.")
        else: # Rechazado
            await log_channel.send(f"{DENY_EMOJI} **{type_str}** {action_str} por {payload.member.mention}. [Ir al envío]({message_link})")

    async def log_decision_change(self, payload, type_str, new_status_str):
        log_channel = self.bot.get_channel(BOT_AUDIT_LOGS_CHANNEL_ID)
        if not log_channel: return
        message_link = f"https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}"
        await log_channel.send(f"🔄 Decisión cambiada a **{new_status_str}** por {payload.member.mention} para un envío de **{type_str}**. [Ir al envío]({message_link})")

async def setup(bot):
    await bot.add_cog(Ataque(bot))
