import discord
from discord import app_commands
from discord.ext import commands
import json
import re
import os

# Importamos la plantilla y las constantes comunes
from .base_moderation import BaseModerationCog, PENDING_EMOJI

# Constantes específicas de Koth
KOTH_CHANNEL_ID = int(os.getenv("KOTH_CHANNEL_ID", 0))
KOTH_EVENT_FILE = 'koth_event.json'

# La clase hereda del GroupCog de discord.py y de nuestra plantilla
class Koth(commands.GroupCog, BaseModerationCog, name="koth", description="Comandos para gestionar eventos KOTH"):
    def __init__(self, bot: commands.Bot):
        # Llama al inicializador de la cadena de herencia
        super().__init__(bot, "koth")
        
        # Carga los datos específicos del evento Koth
        self.koth_event = self.load_koth_event()

    # --- Métodos de gestión de datos específicos de Koth ---
    def load_koth_event(self):
        try:
            with open(KOTH_EVENT_FILE, 'r') as f: return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError): return {'active': False, 'name': None, 'points_per_tag': 0}
    
    def save_koth_event(self, data):
        with open(KOTH_EVENT_FILE, 'w') as f: json.dump(data, f, indent=4)

    # --- Métodos requeridos por la plantilla ---
    def is_relevant_channel(self, channel_id: int) -> bool:
        return channel_id == KOTH_CHANNEL_ID

    async def _award_points(self, payload, submission):
        puntos_cog = self.bot.get_cog('Puntos')
        points_base = self.koth_event.get('points_per_tag', 0)
        # Lógica de puntos: 100% al primero, 75% a los demás
        for i, user_id in enumerate(submission['allies']):
            points = points_base if i == 0 else int(points_base * 0.75)
            if points > 0:
                await puntos_cog.add_points(payload, user_id, points, 'koth')

    async def _revert_points(self, payload, submission):
        puntos_cog = self.bot.get_cog('Puntos')
        points_base = submission.get('points_base', 0)
        for i, user_id in enumerate(submission['allies']):
            points = points_base if i == 0 else int(points_base * 0.75)
            if points > 0:
                await puntos_cog.add_points(payload, user_id, -points, 'koth-revert')

    # --- Lógica de procesamiento específica de Koth ---
    async def process_submission(self, message: discord.Message) -> bool:
        if not self.koth_event.get('active'): return False
        if any(reaction.me for reaction in message.reactions): return False
        
        all_mentions_in_text = re.findall(r'<@!?(\d+)>', message.content)
        if not message.attachments or not all_mentions_in_text or not any(att.content_type.startswith('image/') for att in message.attachments):
            return False

        submission_data = {
            'allies': all_mentions_in_text,
            'points_base': self.koth_event.get('points_per_tag', 0)
        }
        self.pending_submissions[str(message.id)] = submission_data
        self.save_data(self.pending_submissions, self.pending_file)
        await message.add_reaction(PENDING_EMOJI)
        return True

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not self.is_relevant_channel(message.channel.id): return
        await self.process_submission(message)
    
    # --- Comandos Slash específicos de Koth ---
    @app_commands.command(name="start", description="Inicia un nuevo evento KOTH.")
    @app_commands.describe(nombre="El nombre del evento.", puntos="Puntos base a dar.")
    async def koth_start(self, interaction: discord.Interaction, nombre: str, puntos: int):
        if not any(role.id == self.admin_role_id for role in interaction.user.roles):
            return await interaction.response.send_message("❌ No tienes permisos para usar este comando.", ephemeral=True)
            
        if self.koth_event.get('active'):
            return await interaction.response.send_message(f"❌ Ya hay un evento KOTH activo: '{self.koth_event['name']}'.", ephemeral=True)
        
        self.koth_event = {'active': True, 'name': nombre, 'points_per_tag': puntos}
        self.save_koth_event(self.koth_event)
        
        embed = discord.Embed(title=f"⚔️ ¡Evento KOTH Iniciado! ⚔️", color=discord.Color.red())
        embed.add_field(name="Nombre del Evento", value=nombre, inline=False)
        embed.add_field(name="Puntos Base", value=f"`{puntos}` puntos (100% para el primero, 75% para los demás)", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="end", description="Finaliza el evento KOTH actual.")
    async def koth_end(self, interaction: discord.Interaction):
        if not any(role.id == self.admin_role_id for role in interaction.user.roles):
            return await interaction.response.send_message("❌ No tienes permisos para usar este comando.", ephemeral=True)

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
            embed.add_field(name="Puntos Base", value=f"`{self.koth_event['points_per_tag']}` puntos")
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("No hay ningún evento KOTH activo en este momento.")

async def setup(bot):
    await bot.add_cog(Koth(bot))