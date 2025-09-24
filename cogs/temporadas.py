# cogs/temporadas.py (con Fechas Específicas)
import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import os
import re
from datetime import datetime, timedelta, timezone
import traceback

# --- CONFIGURACIÓN ---
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", 0))
ANNOUNCEMENT_CHANNEL_ID = int(os.getenv("ANNOUNCEMENT_CHANNEL_ID", 0))
TEST_GUILD_ID = int(os.getenv("TEST_GUILD_ID", 0))
SEASON_STATUS_FILE = 'season_status.json'

# --- Funciones de ayuda ---
def load_season_data():
    try:
        with open(SEASON_STATUS_FILE, 'r') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return {'active': False, 'name': None, 'end_time': None, 'channel_id': None, 'season_number': 0}

def save_season_data(data):
    with open(SEASON_STATUS_FILE, 'w') as f: json.dump(data, f, indent=4)

@app_commands.guild_only()
class Temporadas(commands.GroupCog, name="season", description="Comandos para gestionar las temporadas del ranking."):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()
        self.check_season_end.start()

    def cog_unload(self):
        self.check_season_end.cancel()

    @tasks.loop(hours=1)
    async def check_season_end(self):
        status = load_season_data()
        if status.get("active") and status.get("end_time"):
            end_time = datetime.fromisoformat(status["end_time"])
            if datetime.now(timezone.utc) >= end_time:
                print(f"Temporada '{status['name']}' finalizada automáticamente.")
                guild = self.bot.get_guild(TEST_GUILD_ID) if TEST_GUILD_ID != 0 else self.bot.guilds[0]
                if guild:
                    await self.end_season_logic(guild)

    @check_season_end.before_loop
    async def before_check_season_end(self):
        await self.bot.wait_until_ready()

    async def end_season_logic(self, guild: discord.Guild, interaction_channel: discord.TextChannel = None):
        status = load_season_data()
        if not status.get("active"):
            if interaction_channel:
                await interaction_channel.send("No hay ninguna temporada activa para terminar.")
            return
        
        season_number = status.get('season_number', 'X')
        save_season_data({"active": False, "name": None, "end_time": None, "season_number": season_number, "channel_id": None})
        
        announcement_channel = self.bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
        final_channel = announcement_channel or interaction_channel
        if not final_channel:
            print("Error: No se encontró un canal para el anuncio de fin de temporada.")
            return

        await final_channel.send(f"🏁 **¡La Temporada '{status['name']}' ha finalizado!** 🏁")
        
        puntos_cog = self.bot.get_cog('Puntos')
        archive_db_name = f'season-{season_number}-leaderboard.db'
        
        if puntos_cog:
            await puntos_cog.reset_database_for_new_season(archive_db_name)
            if final_channel:
                await final_channel.send(f"La base de datos de puntos ha sido reiniciada y la temporada anterior archivada como `{archive_db_name}`.")

    # --- COMANDO /season start MODIFICADO ---
    @app_commands.command(name="start", description="Inicia una nueva temporada con fechas y horas específicas.")
    @app_commands.describe(
        nombre="El nombre para esta nueva temporada (ej. Season 9).",
        fecha_inicio="Fecha de inicio de la temporada (formato DD/MM/YYYY).",
        fecha_fin="Fecha de finalización de la temporada (formato DD/MM/YYYY).",
        hora_inicio="[Opcional] Hora de inicio en UTC (formato HH:MM, por defecto 00:00).",
        hora_fin="[Opcional] Hora de finalización en UTC (formato HH:MM, por defecto 00:00)."
    )
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def season_start(self, interaction: discord.Interaction, nombre: str, fecha_inicio: str, fecha_fin: str, hora_inicio: str = "00:00", hora_fin: str = "00:00"):
        status = load_season_data()
        if status.get("active"):
            return await interaction.response.send_message("❌ Ya hay una temporada activa. Termínala primero.", ephemeral=True)

        # 1. Validar y combinar las fechas y horas
        try:
            start_date = datetime.strptime(f"{fecha_inicio} {hora_inicio}", "%d/%m/%Y %H:%M").replace(tzinfo=timezone.utc)
            end_date = datetime.strptime(f"{fecha_fin} {hora_fin}", "%d/%m/%Y %H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            return await interaction.response.send_message("❌ Formato de fecha u hora inválido. Usa `DD/MM/YYYY` y `HH:MM`.", ephemeral=True)

        # 2. Comprobar que las fechas sean lógicas
        if end_date <= start_date:
            return await interaction.response.send_message("❌ La fecha de finalización debe ser posterior a la fecha de inicio.", ephemeral=True)

        if end_date <= datetime.now(timezone.utc):
            return await interaction.response.send_message("❌ La fecha de finalización no puede estar en el pasado.", ephemeral=True)

        # 3. Guardar el nuevo estado de la temporada
        new_season_number = status.get('season_number', 0) + 1
        new_status = {
            'active': True,
            'name': nombre,
            'end_time': end_date.isoformat(), # Guardamos la fecha de fin para el cierre automático
            'season_number': new_season_number,
            'channel_id': None
        }
        save_season_data(new_status)

        # 4. Anunciar la nueva temporada
        embed = discord.Embed(title=f"✨ ¡Nueva Temporada Programada: {nombre}! ✨", color=discord.Color.brand_green())
        # Usamos format_dt para que la fecha se muestre en la zona horaria de cada usuario
        embed.add_field(name="Inicio", value=discord.utils.format_dt(start_date, 'F'), inline=False)
        embed.add_field(name="Finaliza", value=discord.utils.format_dt(end_date, 'F'), inline=False)
        embed.set_footer(text=f"Temporada #{new_season_number}")
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="end", description="Termina la temporada actual de forma manual.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def season_end(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        await self.end_season_logic(interaction.guild, interaction.channel)
        await interaction.followup.send("La temporada ha sido finalizada manualmente.")

    @app_commands.command(name="status", description="Muestra el estado de la temporada actual.")
    async def season_status(self, interaction: discord.Interaction):
        status = load_season_data()
        if status.get("active"):
            end_time = datetime.fromisoformat(status["end_time"])
            embed = discord.Embed(title=f"Temporada en Curso: {status['name']}", color=discord.Color.blue())
            embed.add_field(name="Finaliza", value=f"{discord.utils.format_dt(end_time, style='F')} ({discord.utils.format_dt(end_time, style='R')})")
            embed.set_footer(text=f"Temporada #{status.get('season_number', 'N/A')}")
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("No hay ninguna temporada activa en este momento.")

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingRole):
            await interaction.response.send_message("❌ No tienes el rol de administrador necesario.", ephemeral=True)
        else:
            error_message = "Ocurrió un error inesperado."
            if interaction.response.is_done():
                await interaction.followup.send(error_message, ephemeral=True)
            else:
                await interaction.response.send_message(error_message, ephemeral=True)
            print(f"Error en un comando de Temporadas por {interaction.user}:")
            traceback.print_exc()

async def setup(bot: commands.Bot):
    await bot.add_cog(Temporadas(bot))