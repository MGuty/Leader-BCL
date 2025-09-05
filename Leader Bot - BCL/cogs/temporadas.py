# cogs/temporadas.py
import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import os
import re
from datetime import datetime, timedelta, timezone
import traceback
import sqlite3

# --- CONFIGURACIÓN ---
# Carga de IDs desde el archivo .env para mantener la configuración centralizada y segura.
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", 0))
ANNOUNCEMENT_CHANNEL_ID = int(os.getenv("ANNOUNCEMENT_CHANNEL_ID", 0))
SEASONS_CATEGORY_ID = int(os.getenv("SEASONS_CATEGORY_ID", 0))
TEST_GUILD_ID = int(os.getenv("TEST_GUILD_ID", 0))

# --- CONSTANTES DE ARCHIVOS ---
DB_FILE = 'leaderboard.db'
SEASON_STATUS_FILE = 'season_status.json'

# --- FUNCIONES DE AYUDA PARA GESTIÓN DE ESTADO ---
def load_season_data():
    """Carga el estado de la temporada desde un archivo JSON. Si no existe, devuelve un estado por defecto."""
    try:
        with open(SEASON_STATUS_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Estado inicial si no hay temporada o el archivo está corrupto.
        return {'active': False, 'name': None, 'end_time': None, 'channel_id': None, 'season_number': 0}

def save_season_data(data):
    """Guarda el estado actual de la temporada en el archivo JSON."""
    with open(SEASON_STATUS_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# --- COG DE TEMPORADAS ---
# Usamos un GroupCog para agrupar todos los subcomandos bajo /season (ej. /season start)
@app_commands.guild_only()
class Temporadas(commands.GroupCog, name="season", description="Comandos para gestionar las temporadas del ranking."):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()
        # Inicia la tarea en segundo plano al cargar el Cog.
        self.check_season_end.start()

    def cog_unload(self):
        """Se llama automáticamente cuando el Cog se descarga, asegurando que la tarea se detenga limpiamente."""
        self.check_season_end.cancel()

    # --- TAREA EN SEGUNDO PLANO ---
    @tasks.loop(hours=1)
    async def check_season_end(self):
        """Verifica cada hora si la temporada activa ha llegado a su fin."""
        status = load_season_data()
        if status.get("active") and status.get("end_time"):
            end_time = datetime.fromisoformat(status["end_time"])
            # Compara la fecha de fin con la fecha actual (con zona horaria UTC para consistencia).
            if datetime.now(timezone.utc) >= end_time:
                print(f"Temporada '{status['name']}' finalizada automáticamente.")
                guild = self.bot.get_guild(TEST_GUILD_ID)
                if guild:
                    # Llama a la lógica principal de finalización de temporada.
                    await self.end_season_logic(guild)

    @check_season_end.before_loop
    async def before_check_season_end(self):
        """Espera a que el bot esté completamente listo antes de iniciar el bucle de la tarea."""
        await self.bot.wait_until_ready()

    # --- LÓGICA CENTRALIZADA ---
    async def end_season_logic(self, guild: discord.Guild, interaction_channel: discord.TextChannel = None):
        """Lógica reutilizable para finalizar una temporada, usada tanto por el comando manual como por la tarea automática."""
        status = load_season_data()
        if not status.get("active"):
            if interaction_channel:
                await interaction_channel.send("No hay ninguna temporada activa para terminar.")
            return

        # Determina el canal para los anuncios. Prioriza el canal de anuncios, si no, usa el canal de la interacción.
        announcement_channel = self.bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
        final_channel = announcement_channel or interaction_channel
        if not final_channel:
            print("Error: No se encontró un canal para enviar el anuncio de fin de temporada.")
            return

        await final_channel.send(f"🏁 **¡La Temporada '{status['name']}' ha finalizado!** 🏁\nAquí está el ranking final:")

        # Interactúa con el Cog 'Puntos' para obtener el ranking final.
        puntos_cog = self.bot.get_cog('Puntos')
        if puntos_cog:
            final_ranking_embed = await puntos_cog._build_ranking_embed(guild.id)
            if final_ranking_embed:
                await final_channel.send(embed=final_ranking_embed)
            else:
                await final_channel.send("No se registraron puntos en esta temporada.")

        # Archiva la base de datos de la temporada y resetea el estado.
        season_number = status.get('season_number', 'X')
        archive_db_name = f'season-{season_number}-leaderboard.db'
        if os.path.exists(DB_FILE):
            os.rename(DB_FILE, archive_db_name)
            if final_channel:
                await final_channel.send(f"La base de datos de puntos ha sido archivada como `{archive_db_name}`.")
        
        # Resetea la base de datos para la nueva temporada.
        if puntos_cog:
            puntos_cog._initialize_database()
        
        # Actualiza el estado a inactivo.
        save_season_data({"active": False, "name": None, "end_time": None, "season_number": season_number, "channel_id": None})

    # --- COMANDOS ---
    @app_commands.command(name="start", description="Inicia una nueva temporada.")
    @app_commands.describe(nombre="El nombre para esta nueva temporada.", duracion="Duración (ej: 30d, 4w, 12h).")
    @app_commands.checks.has_role(ADMIN_ROLE_ID) # Usando el decorador de chequeo de rol.
    async def season_start(self, interaction: discord.Interaction, nombre: str, duracion: str):
        status = load_season_data()
        if status.get("active"):
            return await interaction.response.send_message("❌ Ya hay una temporada activa. Termínala primero.", ephemeral=True)

        match = re.match(r"(\d+)([dhw])", duracion.lower())
        if not match:
            return await interaction.response.send_message("❌ Formato de duración inválido. Usa un número seguido de 'd', 'w', o 'h'.", ephemeral=True)

        value, unit = int(match.group(1)), match.group(2)
        delta = {'d': timedelta(days=value), 'w': timedelta(weeks=value), 'h': timedelta(hours=value)}.get(unit)

        await interaction.response.defer()

        start_date = datetime.now(timezone.utc)
        end_date = start_date + delta
        new_season_number = status.get('season_number', 0) + 1

        # Lógica para crear el canal (a implementar)
        # category = self.bot.get_channel(SEASONS_CATEGORY_ID)
        # new_channel = await category.create_text_channel(f"🏁-temporada-{new_season_number}-{nombre}")

        new_status = {
            'active': True,
            'name': nombre,
            'end_time': end_date.isoformat(),
            'season_number': new_season_number,
            'channel_id': None # Aquí iría new_channel.id
        }
        save_season_data(new_status)

        embed = discord.Embed(title=f"✨ ¡Nueva Temporada Iniciada: {nombre}! ✨", color=discord.Color.brand_green())
        embed.add_field(name="Inicio", value=discord.utils.format_dt(start_date, 'F'), inline=False)
        embed.add_field(name="Finaliza", value=discord.utils.format_dt(end_date, 'F'), inline=False)
        embed.set_footer(text=f"Temporada #{new_season_number}")
        
        await interaction.followup.send(embed=embed)

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

    # --- MANEJO DE ERRORES ---
    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Manejador de errores local para este Cog."""
        if isinstance(error, app_commands.MissingRole):
            await interaction.response.send_message("❌ No tienes el rol de administrador necesario para usar este comando.", ephemeral=True)
        else:
            if not interaction.response.is_done():
                await interaction.response.send_message("Ocurrió un error inesperado.", ephemeral=True)
            else:
                await interaction.followup.send("Ocurrió un error inesperado.", ephemeral=True)
            print(f"Error en un comando de Temporadas por {interaction.user}: {error}")
            traceback.print_exc()

async def setup(bot: commands.Bot):
    await bot.add_cog(Temporadas(bot))
