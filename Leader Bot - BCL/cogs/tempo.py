# cogs/tempo.py
import discord
from discord.ext import commands
import re
import os
import json
import traceback

# --- CONFIGURACIÓN ---
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID"))
BOT_AUDIT_LOGS_CHANNEL_ID = int(os.getenv("BOT_AUDIT_LOGS_CHANNEL_ID"))

# --- Emojis y Archivos de Datos ---
PENDING_EMOJI = '📝'
APPROVE_EMOJI = '✅'
DENY_EMOJI = '❌'
PENDING_TEMPO_FILE = 'pending_tempo.json'
JUDGED_TEMPO_FILE = 'judged_tempo.json'

# --- Puntos para Tempo ---
TEMPO_POINTS = {
    "5-10min": 15,
    "10-15min": 25,
    "15-20min": 40,
    "20-25min": 50,
    "25-30min": 60,
    "plus-de-30": 75,
}

class Tempo(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pending_tempo = self.load_data(PENDING_TEMPO_FILE)
        self.judged_tempo = self.load_data(JUDGED_TEMPO_FILE)

    def load_data(self, filename):
        try:
            with open(filename, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def save_data(self, data, filename):
        with open(filename, 'w') as f:
            json.dump(data, f, indent=4)

    async def process_submission(self, message: discord.Message):
        """Función centralizada para validar y registrar un envío de Tempo."""
        for reaction in message.reactions:
            if reaction.me:
                return False # Ya fue procesado

        all_mentions_in_text = re.findall(r'<@!?(\d+)>', message.content)
        if not message.attachments or not all_mentions_in_text or not any(att.content_type.startswith('image/') for att in message.attachments):
            return False

        channel_name_lower = message.channel.name.lower()
        key_part = ""
        try:
            key_part = channel_name_lower.split('tempo-', 1)[1]
        except IndexError:
            return False

        if key_part not in TEMPO_POINTS:
            return False

        points_to_award = TEMPO_POINTS[key_part]
        if points_to_award == 0:
            return False

        self.pending_tempo[str(message.id)] = {'points': points_to_award, 'allies': all_mentions_in_text}
        self.save_data(self.pending_tempo, PENDING_TEMPO_FILE)
        await message.add_reaction(PENDING_EMOJI)
        return True

    @commands.Cog.listener()
    async def on_message(self, message):
        """Escucha mensajes en tiempo real y los envía al procesador."""
        if message.author.bot or not message.channel.name.lower().startswith('tempo-'):
            return
        
        await self.process_submission(message)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        """Maneja la lógica de aprobación, rechazo y cambio de decisión."""
        if payload.member.bot or not any(role.id == ADMIN_ROLE_ID for role in payload.member.roles):
            return

        message_id_str = str(payload.message_id)
        emoji = str(payload.emoji)
        
        if emoji not in [APPROVE_EMOJI, DENY_EMOJI]:
            return
        
        is_pending = message_id_str in self.pending_tempo
        is_judged = message_id_str in self.judged_tempo
        if not is_pending and not is_judged:
            return

        original_channel = self.bot.get_channel(payload.channel_id)
        if original_channel:
            try:
                original_message = await original_channel.fetch_message(payload.message_id)
                opposite_emoji = DENY_EMOJI if emoji == APPROVE_EMOJI else APPROVE_EMOJI
                for reaction in original_message.reactions:
                    if str(reaction.emoji) == opposite_emoji:
                        async for user in reaction.users():
                            if not user.bot:
                                await original_message.remove_reaction(opposite_emoji, user)
                        break
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                print(f"No se pudieron gestionar las reacciones opuestas del mensaje {message_id_str}")

        puntos_cog = self.bot.get_cog('Puntos')

        if is_pending:
            submission = self.pending_tempo.pop(message_id_str)
            self.save_data(self.pending_tempo, PENDING_TEMPO_FILE)
            if emoji == APPROVE_EMOJI:
                if puntos_cog:
                    for user_id in submission['allies']:
                        await puntos_cog.add_points(payload, user_id, submission['points'], 'tempo')
                submission['status'] = 'approved'
                self.judged_tempo[message_id_str] = submission
                self.save_data(self.judged_tempo, JUDGED_TEMPO_FILE)
                await self.send_log_message(payload, submission, "Tempo", "aprobado")
            elif emoji == DENY_EMOJI:
                submission['status'] = 'denied'
                self.judged_tempo[message_id_str] = submission
                self.save_data(self.judged_tempo, JUDGED_TEMPO_FILE)
                await self.send_log_message(payload, submission, "Tempo", "rechazado")
        
        elif is_judged:
            submission = self.judged_tempo[message_id_str]
            old_status = submission['status']
            if emoji == APPROVE_EMOJI and old_status == 'denied':
                if puntos_cog:
                    for user_id in submission['allies']:
                        await puntos_cog.add_points(payload, user_id, submission['points'], 'tempo')
                submission['status'] = 'approved'
                self.judged_tempo[message_id_str] = submission
                self.save_data(self.judged_tempo, JUDGED_TEMPO_FILE)
                await self.log_decision_change(payload, "Tempo", "APROBADO")
            elif emoji == DENY_EMOJI and old_status == 'approved':
                if puntos_cog:
                    for user_id in submission['allies']:
                        await puntos_cog.add_points(payload, user_id, -submission['points'], 'tempo')
                submission['status'] = 'denied'
                self.judged_tempo[message_id_str] = submission
                self.save_data(self.judged_tempo, JUDGED_TEMPO_FILE)
                await self.log_decision_change(payload, "Tempo", "RECHAZADO")

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
    await bot.add_cog(Tempo(bot))