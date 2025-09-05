# cogs/interserver.py
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
PENDING_INTERSERVER_FILE = 'pending_interserver.json'
JUDGED_INTERSERVER_FILE = 'judged_interserver.json'

# --- Puntos para Interserver ---
INTERSERVER_POINTS = {
    "tempo-no_def-v1": 2,
    "koth-v2-v3": 10,
    "v4-v5": 30,
}

class Interserver(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pending_interserver = self.load_data(PENDING_INTERSERVER_FILE)
        self.judged_interserver = self.load_data(JUDGED_INTERSERVER_FILE)

    def load_data(self, filename):
        try:
            with open(filename, 'r') as f: return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError): return {}

    def save_data(self, data, filename):
        with open(filename, 'w') as f: json.dump(data, f, indent=4)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.channel.name.lower().startswith('interserver-'): return
        all_mentions_in_text = re.findall(r'<@!?(\d+)>', message.content)
        if not message.attachments or not all_mentions_in_text or not any(att.content_type.startswith('image/') for att in message.attachments): return

        channel_name_lower = message.channel.name.lower()
        key_part = channel_name_lower.split('interserver-', 1)[1]
        if key_part not in INTERSERVER_POINTS: return
        
        points_to_award = INTERSERVER_POINTS[key_part]
        if points_to_award == 0: return

        self.pending_interserver[str(message.id)] = {'points': points_to_award, 'allies': all_mentions_in_text}
        self.save_data(self.pending_interserver, PENDING_INTERSERVER_FILE)
        await message.add_reaction(PENDING_EMOJI)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        message_id_str = str(payload.message_id)
        if payload.member.bot or not any(role.id == ADMIN_ROLE_ID for role in payload.member.roles): return
        if message_id_str not in self.pending_interserver and message_id_str not in self.judged_interserver: return
        
        emoji = str(payload.emoji)
        if emoji not in [APPROVE_EMOJI, DENY_EMOJI]: return

        # (Lógica de limpieza selectiva de reacciones)
        original_channel = self.bot.get_channel(payload.channel_id)
        if original_channel:
            try:
                original_message = await original_channel.fetch_message(payload.message_id)
                opposite_emoji = DENY_EMOJI if emoji == APPROVE_EMOJI else APPROVE_EMOJI
                for reaction in original_message.reactions:
                    if str(reaction.emoji) == opposite_emoji:
                        async for user in reaction.users():
                            if not user.bot: await original_message.remove_reaction(opposite_emoji, user)
                        break
            except Exception as e: print(f"No se pudieron limpiar las reacciones opuestas: {e}")

        puntos_cog = self.bot.get_cog('Puntos')

        if message_id_str in self.pending_interserver:
            submission = self.pending_interserver.pop(message_id_str)
            self.save_data(self.pending_interserver, PENDING_INTERSERVER_FILE)
            if emoji == APPROVE_EMOJI:
                if puntos_cog:
                    for user_id in submission['allies']:
                        await puntos_cog.add_points(payload, user_id, submission['points'], 'interserver')
                submission['status'] = 'approved'
                self.judged_interserver[message_id_str] = submission
                self.save_data(self.judged_interserver, JUDGED_INTERSERVER_FILE)
                await self.send_log_message(payload, submission, "Interserver", "aprobado")
            elif emoji == DENY_EMOJI:
                submission['status'] = 'denied'
                self.judged_interserver[message_id_str] = submission
                self.save_data(self.judged_interserver, JUDGED_INTERSERVER_FILE)
                await self.send_log_message(payload, submission, "Interserver", "rechazado")
        
        elif message_id_str in self.judged_interserver:
            submission = self.judged_interserver[message_id_str]
            old_status = submission['status']
            if emoji == APPROVE_EMOJI and old_status == 'denied':
                if puntos_cog:
                    for user_id in submission['allies']: await puntos_cog.add_points(payload, user_id, submission['points'], 'interserver')
                submission['status'] = 'approved'
                self.judged_interserver[message_id_str] = submission
                self.save_data(self.judged_interserver, JUDGED_INTERSERVER_FILE)
                await self.log_decision_change(payload, "Interserver", "APROBADO")
            elif emoji == DENY_EMOJI and old_status == 'approved':
                if puntos_cog:
                    for user_id in submission['allies']: await puntos_cog.add_points(payload, user_id, -submission['points'], 'interserver')
                submission['status'] = 'denied'
                self.judged_interserver[message_id_str] = submission
                self.save_data(self.judged_interserver, JUDGED_INTERSERVER_FILE)
                await self.log_decision_change(payload, "Interserver", "RECHAZADO")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        message_id_str = str(payload.message_id)
        guild = self.bot.get_guild(payload.guild_id)
        if not guild: return
        member = guild.get_member(payload.user_id)
        if not member or member.bot: return
        
        self.judged_interserver = self.load_data(JUDGED_INTERSERVER_FILE)
        if message_id_str not in self.judged_interserver: return
        if not any(role.id == ADMIN_ROLE_ID for role in member.roles): return

        submission = self.judged_interserver[message_id_str]
        emoji = str(payload.emoji)
        
        if emoji == APPROVE_EMOJI and submission['status'] == 'approved':
            puntos_cog = self.bot.get_cog('Puntos')
            if puntos_cog:
                for user_id_str in submission['allies']:
                    await puntos_cog.add_points(payload, user_id_str, -submission['points'], 'interserver')
            del self.judged_interserver[message_id_str]
            self.save_data(self.judged_interserver, JUDGED_INTERSERVER_FILE)
            log_channel = self.bot.get_channel(BOT_AUDIT_LOGS_CHANNEL_ID)
            if log_channel: await log_channel.send(f"🔄 Aprobación de **Interserver** revertida por {member.mention}.")
        elif emoji == DENY_EMOJI and submission['status'] == 'denied':
            del self.judged_interserver[message_id_str]
            self.save_data(self.judged_interserver, JUDGED_INTERSERVER_FILE)
            log_channel = self.bot.get_channel(BOT_AUDIT_LOGS_CHANNEL_ID)
            if log_channel: await log_channel.send(f"🔄 Rechazo de **Interserver** revertido por {member.mention}.")

    async def send_log_message(self, payload, submission, type_str, action_str):
        log_channel = self.bot.get_channel(BOT_AUDIT_LOGS_CHANNEL_ID)
        if not log_channel: return
        event_name = "General"
        original_channel = self.bot.get_channel(payload.channel_id)
        if original_channel and original_channel.name.lower().startswith('interserver-'):
            event_name = original_channel.name.lower().split('interserver-', 1)[1]
        message_link = f"https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}"
        if action_str == "aprobado":
            unique_ally_mentions = [f"<@{uid}>" for uid in set(submission['allies'])]
            await log_channel.send(f"{APPROVE_EMOJI} **{type_str} ({event_name})** {action_str} por {payload.member.mention}. [Ir al envío]({message_link})\n> Se han otorgado **`{submission['points']}`** puntos por mención a: {', '.join(unique_ally_mentions)}.")
        else: # Rechazado
            await log_channel.send(f"{DENY_EMOJI} **{type_str} ({event_name})** {action_str} por {payload.member.mention}. [Ir al envío]({message_link})")

    async def log_decision_change(self, payload, type_str, new_status_str):
        log_channel = self.bot.get_channel(BOT_AUDIT_LOGS_CHANNEL_ID)
        if not log_channel: return
        message_link = f"https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}"
        await log_channel.send(f"🔄 Decisión cambiada a **{new_status_str}** por {payload.member.mention} para un envío de **{type_str}**. [Ir al envío]({message_link})")

async def setup(bot):
    await bot.add_cog(Interserver(bot))