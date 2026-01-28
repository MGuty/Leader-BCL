import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import os
import re
from datetime import datetime, timezone
import traceback

# --- CONFIGURACIÓN ---
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", 0))
ANNOUNCEMENT_CHANNEL_ID = int(os.getenv("ANNOUNCEMENT_CHANNEL_ID", 0))
TEST_GUILD_ID = int(os.getenv("TEST_GUILD_ID", 0))
SEASON_STATUS_FILE = 'season_status.json'

# --- FUNCIONES DE AYUDA ---
def load_season_data():
    """Carga el estado de la temporada desde el archivo JSON."""
    try:
        with open(SEASON_STATUS_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {'active': False, 'name': None, 'end_time': None, 'season_number': 0}

def save_season_data(data):
    """Guarda el estado de la temporada en el archivo JSON."""
    with open(SEASON_STATUS_FILE, 'w') as f:
        json.dump(data, f, indent=4)

@app_commands.guild_only()
class Temporadas(commands.GroupCog, name="season", description="Gestión de las temporadas del ranking."):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()
        self.check_season_end.start()

    def cog_unload(self):
        self.check_season_end.cancel()

    @tasks.loop(hours=1)
    async def check_season_end(self):
        """Verifica automáticamente si la temporada ha llegado a su fin."""
        status = load_season_data()
        if status.get("active") and status.get("end_time"):
            end_time = datetime.fromisoformat(status["end_time"])
            if datetime.now(timezone.utc) >= end_time:
                guild = self.bot.get_guild(TEST_GUILD_ID) or self.bot.guilds[0]
                if guild:
                    await self.end_season_logic(guild)

    @check_season_end.before_loop
    async def before_check_season_end(self):
        await self.bot.wait_until_ready()

    async def end_season_logic(self, guild: discord.Guild, interaction_channel: discord.TextChannel = None):
        """Lógica para cerrar la temporada, archivar datos y limpiar el ranking."""
        status = load_season_data()
        if not status.get("active"):
            if interaction_channel:
                await interaction_channel.send("No hay ninguna temporada activa.")
            return

        season_number = status.get('season_number', 'X')
        save_season_data({"active": False, "name": None, "end_time": None, "season_number": season_number})

        announcement_channel = self.bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
        final_channel = announcement_channel or interaction_channel
        
        if final_channel:
            await final_channel.send(f"🏁 **¡La Temporada '{status['name']}' ha finalizado!** 🏁")
        
        # Llamada al módulo de Puntos para el reinicio real de la base de datos
        puntos_cog = self.bot.get_cog('Puntos')
        archive_db_name = f'season-{season_number}-leaderboard.db'
        
        if puntos_cog:
            await puntos_cog.reset_database_for_new_season(archive_db_name)
            if final_channel:
                await final_channel.send(f"✅ Ranking reiniciado. Datos archivados en `{archive_db_name}`.")

    @app_commands.command(name="start", description="Inicia una nueva temporada.")
    @app_commands.describe(
        nombre="Ej: Season 9",
        fecha_fin="Formato DD/MM/YYYY",
        hora_fin="Formato HH:MM (UTC)"
    )
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def season_start(self, interaction: discord.Interaction, nombre: str, fecha_fin: str, hora_fin: str = "00:00"):
        status = load_season_data()
        if status.get("active"):
            return await interaction.response.send_message("❌ Ya hay una temporada activa.", ephemeral=True)

        try:
            end_date = datetime.strptime(f"{fecha_fin} {hora_fin}", "%d/%m/%Y %H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            return await interaction.response.send_message("❌ Formato inválido. Usa `DD/MM/YYYY` y `HH:MM`.", ephemeral=True)

        if end_date <= datetime.now(timezone.utc):
            return await interaction.response.send_message("❌ La fecha de fin debe ser futura.", ephemeral=True)

        await interaction.response.defer()

        new_number = status.get('season_number', 0) + 1
        save_season_data({
            'active': True, 'name': nombre, 'end_time': end_date.isoformat(),
            'season_number': new_number
        })

        # Mensaje separador solicitado para canales de ataque, defensa e interserver
        separator = "╔═══════════ 🏆 Inicio de Season 🏆═══════════╗"
        prefixes = ['attack-', 'defenses-', 'interserver-']
        
        for channel in interaction.guild.text_channels:
            if any(channel.name.lower().startswith(p) for p in prefixes):
                try:
                    await channel.send(separator)
                except: continue

        embed = discord.Embed(title=f"✨ ¡Temporada {nombre} Iniciada! ✨", color=discord.Color.green())
        embed.add_field(name="Finaliza", value=discord.utils.format_dt(end_date, 'F'))
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="end", description="Termina la temporada manual.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def season_end(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        await self.end_season_logic(interaction.guild, interaction.channel)
        await interaction.followup.send("Temporada finalizada.")

    @app_commands.command(name="status", description="Ver estado actual.")
    async def season_status(self, interaction: discord.Interaction):
        status = load_season_data()
        if status.get("active"):
            end = datetime.fromisoformat(status["end_time"])
            await interaction.response.send_message(f"Temporada: **{status['name']}**\nTermina: {discord.utils.format_dt(end, 'R')}")
        else:
            await interaction.response.send_message("No hay temporadas activas.")

async def setup(bot: commands.Bot):
    await bot.add_cog(Temporadas(bot))