# cogs/koth.py (Corregido)
import discord
from discord import app_commands
from discord.ext import commands
import json
import re
import traceback
import os
from datetime import datetime, timezone

# --- CONFIGURACIÓN ---
KOTH_CHANNEL_ID = int(os.getenv("KOTH_CHANNEL_ID", 0))
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", 0))
BOT_AUDIT_LOGS_CHANNEL_ID = int(os.getenv("BOT_AUDIT_LOGS_CHANNEL_ID", 0))

# --- Emojis y Archivos de Datos ---
PENDING_EMOJI = '📝'
APPROVE_EMOJI = '✅'
DENY_EMOJI = '❌'
KOTH_EVENT_FILE = 'koth_event.json'
PENDING_KOTH_FILE = 'pending_koth.json'
JUDGED_KOTH_FILE = 'judged_koth.json'

# --- Clase del Cog ---
@app_commands.guild_only()
class Koth(commands.GroupCog, name="koth", description="Comandos para gestionar eventos de King of the Hill"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()
        self.pending_koth = self.load_data(PENDING_KOTH_FILE)
        self.judged_koth = self.load_data(JUDGED_KOTH_FILE)
        self.koth_event = self.load_koth_event()

    # --- Métodos de gestión de datos ---
    def load_data(self, filename):
        try:
            with open(filename, 'r') as f: return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError): return {}

    def save_data(self, data, filename):
        with open(filename, 'w') as f: json.dump(data, f, indent=4)

    def load_koth_event(self):
        try:
            with open(KOTH_EVENT_FILE, 'r') as f: return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError): return {'active': False, 'name': None, 'points_per_tag': 0}
    
    def save_koth_event(self, data):
        with open(KOTH_EVENT_FILE, 'w') as f: json.dump(data, f, indent=4)

    # --- LÓGICA CENTRALIZADA DE PROCESAMIENTO ---
    async def process_submission(self, message: discord.Message) -> bool:
        """
        Procesa un mensaje para ver si es un envío de KOTH válido.
        Devuelve True si se procesa, False si no.
        """
        if not self.koth_event.get('active'): return False
        if any(reaction.me for reaction in message.reactions): return False
        
        all_mentions_in_text = re.findall(r'<@!?(\d+)>', message.content)
        if not message.attachments or not all_mentions_in_text or not any(att.content_type.startswith('image/') for att in message.attachments):
            return False

        self.pending_koth[str(message.id)] = {'allies': all_mentions_in_text}
        self.save_data(self.pending_koth, PENDING_KOTH_FILE)
        await message.add_reaction(PENDING_EMOJI)
        return True

    # --- LISTENERS ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Escucha mensajes en el canal de KOTH y los procesa."""
        if message.author.bot or message.channel.id != KOTH_CHANNEL_ID: return
        await self.process_submission(message)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.member.bot or payload.channel_id != KOTH_CHANNEL_ID: return
        if not any(role.id == ADMIN_ROLE_ID for role in payload.member.roles): return
        
        message_id_str = str(payload.message_id)
        emoji = str(payload.emoji)
        if emoji not in [APPROVE_EMOJI, DENY_EMOJI]: return
        
        is_pending = message_id_str in self.pending_koth
        is_judged = message_id_str in self.judged_koth
        if not is_pending and not is_judged: return

        puntos_cog = self.bot.get_cog('Puntos')
        points_to_award = self.koth_event.get('points_per_tag', 0)

        if is_pending:
            submission = self.pending_koth.pop(message_id_str)
            if emoji == APPROVE_EMOJI:
                if puntos_cog and points_to_award > 0:
                    for user_id in submission['allies']:
                        await puntos_cog.add_points(payload, user_id, points_to_award, 'koth')
                submission['status'] = 'approved'
                submission['points'] = points_to_award # Guardamos los puntos para referencia
                self.judged_koth[message_id_str] = submission
                await self.send_log_message(payload, submission, "KOTH", "aprobado")
            elif emoji == DENY_EMOJI:
                submission['status'] = 'denied'
                self.judged_koth[message_id_str] = submission
                await self.send_log_message(payload, submission, "KOTH", "rechazado")
            self.save_data(self.pending_koth, PENDING_KOTH_FILE)
            self.save_data(self.judged_koth, JUDGED_KOTH_FILE)
        
        elif is_judged:
            # Lógica para cambiar una decisión ya tomada
            submission = self.judged_koth[message_id_str]
            old_status = submission['status']
            if emoji == APPROVE_EMOJI and old_status == 'denied':
                if puntos_cog and points_to_award > 0:
                    for user_id in submission['allies']:
                        await puntos_cog.add_points(payload, user_id, points_to_award, 'koth')
                submission['status'] = 'approved'
                await self.log_decision_change(payload, "KOTH", "APROBADO")
            elif emoji == DENY_EMOJI and old_status == 'approved':
                if puntos_cog and points_to_award > 0:
                    for user_id in submission['allies']:
                        await puntos_cog.add_points(payload, user_id, -points_to_award, 'koth')
                submission['status'] = 'denied'
                await self.log_decision_change(payload, "KOTH", "RECHAZADO")
            self.judged_koth[message_id_str] = submission
            self.save_data(self.judged_koth, JUDGED_KOTH_FILE)

    # --- COMANDOS SLASH ---
    @app_commands.command(name="start", description="Inicia un nuevo evento KOTH.")
    @app_commands.describe(nombre="El nombre del evento.", puntos="Puntos a dar por cada etiqueta.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def koth_start(self, interaction: discord.Interaction, nombre: str, puntos: int):
        if interaction.channel.id != KOTH_CHANNEL_ID:
            return await interaction.response.send_message("Este comando solo se puede usar en el canal de KOTH.", ephemeral=True)
        if self.koth_event.get('active'):
            return await interaction.response.send_message(f"❌ Ya hay un evento KOTH activo: '{self.koth_event['name']}'.", ephemeral=True)
        
        self.koth_event = {'active': True, 'name': nombre, 'points_per_tag': puntos}
        self.save_koth_event(self.koth_event)
        
        embed = discord.Embed(title=f"⚔️ ¡Evento KOTH Iniciado! ⚔️", color=discord.Color.red())
        embed.add_field(name="Nombre del Evento", value=nombre, inline=False)
        embed.add_field(name="Puntos por Etiqueta", value=f"`{puntos}` puntos", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="end", description="Finaliza el evento KOTH actual.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def koth_end(self, interaction: discord.Interaction):
        if not self.koth_event.get('active'):
            return await interaction.response.send_message("❌ No hay ningún evento KOTH activo para finalizar.", ephemeral=True)
        
        event_name = self.koth_event['name']
        self.koth_event = {'active': False, 'name': None, 'points_per_tag': 0}
        self.save_koth_event(self.koth_event)
        
        await interaction.response.send_message(f"✅ El evento KOTH '{event_name}' ha sido finalizado.")

    @app_commands.command(name="status", description="Muestra el estado del evento KOTH actual.")
    async def koth_status(self, interaction: discord.Interaction):
        if self.koth_event.get('active'):
            embed = discord.Embed(title=f"Evento KOTH en Curso: {self.koth_event['name']}", color=discord.Color.blue())
            embed.add_field(name="Puntos por Etiqueta", value=f"`{self.koth_event['points_per_tag']}` puntos")
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("No hay ningún evento KOTH activo en este momento.")

    # --- FUNCIONES DE LOGS Y ERRORES ---
    async def send_log_message(self, payload, submission, type_str, action_str):
        log_channel = self.bot.get_channel(BOT_AUDIT_LOGS_CHANNEL_ID)
        if not log_channel: return
        message_link = f"https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}"
        points = submission.get('points', self.koth_event.get('points_per_tag', 0))
        if action_str == "aprobado":
            unique_ally_mentions = [f"<@{uid}>" for uid in set(submission['allies'])]
            await log_channel.send(f"{APPROVE_EMOJI} **{type_str}** {action_str} por {payload.member.mention}. [Ir al envío]({message_link})\n> Se han otorgado **`{points}`** puntos por mención a: {', '.join(unique_ally_mentions)}.")
        else: # Rechazado
            await log_channel.send(f"{DENY_EMOJI} **{type_str}** {action_str} por {payload.member.mention}. [Ir al envío]({message_link})")

    async def log_decision_change(self, payload, type_str, new_status_str):
        log_channel = self.bot.get_channel(BOT_AUDIT_LOGS_CHANNEL_ID)
        if not log_channel: return
        message_link = f"https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}"
        await log_channel.send(f"🔄 Decisión cambiada a **{new_status_str}** por {payload.member.mention} para un envío de **{type_str}**. [Ir al envío]({message_link})")

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingRole):
            await interaction.response.send_message("❌ No tienes el rol de administrador necesario.", ephemeral=True)
        else:
            if not interaction.response.is_done():
                await interaction.response.send_message("Ocurrió un error inesperado.", ephemeral=True)
            else:
                await interaction.followup.send("Ocurrió un error inesperado.", ephemeral=True)
            print(f"Error en un comando de Koth por {interaction.user}: {error}")
            traceback.print_exc()

async def setup(bot):
    await bot.add_cog(Koth(bot))
