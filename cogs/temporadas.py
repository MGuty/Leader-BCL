# cogs/temporadas.py (Corregido y Actualizado)
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
SEASONS_CATEGORY_ID = int(os.getenv("SEASONS_CATEGORY_ID", 0))
TEST_GUILD_ID = int(os.getenv("TEST_GUILD_ID", 0))
KOTH_CHANNEL_ID = int(os.getenv("KOTH_CHANNEL_ID", 0))
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
        # ... (código sin cambios)
        status = load_season_data()
        if status.get("active") and status.get("end_time"):
            end_time = datetime.fromisoformat(status["end_time"])
            if datetime.now(timezone.utc) >= end_time:
                print(f"La temporada '{status['name']}' ha finalizado automáticamente.")
                guild = self.bot.get_guild(TEST_GUILD_ID) if TEST_GUILD_ID != 0 else self.bot.guilds[0]
                if guild:
                    await self.end_season_logic(guild)

    # --- LÓGICA CENTRAL CORREGIDA ---
    async def end_season_logic(self, guild: discord.Guild, interaction_channel: discord.TextChannel = None):
        status = load_season_data()
        if not status.get("active"):
            if interaction_channel: await interaction_channel.send("No hay ninguna temporada activa para terminar.")
            return

        announcement_channel = self.bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
        final_channel = announcement_channel or interaction_channel
        if not final_channel:
            print("Error: No se encontró un canal para el anuncio de fin de temporada.")
            return

        await final_channel.send(f"🏁 **¡La Temporada '{status['name']}' ha finalizado!** 🏁")
        
        puntos_cog = self.bot.get_cog('Puntos')
        season_number = status.get('season_number', 'X')
        archive_db_name = f'season-{season_number}-leaderboard.db'
        
        if puntos_cog:
            await puntos_cog.reset_database_for_new_season(archive_db_name)
            if final_channel:
                await final_channel.send(f"La base de datos de puntos ha sido reiniciada y la temporada anterior archivada como `{archive_db_name}`.")
        
        save_season_data({"active": False, "name": None, "end_time": None, "season_number": season_number, "channel_id": None})
    
    # --- Comandos Slash ---
    @app_commands.command(name="start", description="Inicia una nueva temporada.")
    @app_commands.describe(nombre="El nombre para la nueva temporada.", duracion="Duración (ej: 30d, 4w, 12h).", limpiar_canales="Elige 'Sí' para borrar y recrear los canales de eventos.")
    @app_commands.choices(limpiar_canales=[
        app_commands.Choice(name="Sí, limpiar los canales para la nueva temporada", value=1),
        app_commands.Choice(name="No, mantener los mensajes de la temporada anterior", value=0)
    ])
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def season_start(self, interaction: discord.Interaction, nombre: str, duracion: str, limpiar_canales: int):
        # ... (código sin cambios)
        status = load_season_data()
        if status.get("active"):
            return await interaction.response.send_message("❌ Ya hay una temporada activa. Termínala primero.", ephemeral=True)
        match = re.match(r"(\d+)([dhw])", duracion.lower())
        if not match:
            return await interaction.response.send_message("❌ Formato de duración inválido.", ephemeral=True)
        
        value, unit = int(match.group(1)), match.group(2)
        delta = {'d': timedelta(days=value), 'w': timedelta(weeks=value), 'h': timedelta(hours=value)}.get(unit)
        
        await interaction.response.defer()

        if limpiar_canales == 1:
            reporte = await self.clean_event_channels_logic(interaction.guild)
            await interaction.followup.send(f"🧹 **Limpieza de Canales Completada** 🧹\n" + "\n".join(reporte), ephemeral=True)

        start_date = datetime.now(timezone.utc)
        end_date = start_date + delta
        new_season_number = status.get('season_number', 0) + 1
        new_status = {'active': True, 'name': nombre, 'end_time': end_date.isoformat(),'season_number': new_season_number, 'channel_id': None}
        save_season_data(new_status)
        
        embed = discord.Embed(title=f"✨ ¡Nueva Temporada Iniciada: {nombre}! ✨", color=discord.Color.brand_green())
        embed.add_field(name="Inicio", value=discord.utils.format_dt(start_date, 'F'), inline=False)
        embed.add_field(name="Fin", value=discord.utils.format_dt(end_date, 'F'), inline=False)
        embed.set_footer(text=f"Temporada #{new_season_number}")
        await interaction.followup.send(embed=embed)


    @app_commands.command(name="end", description="Termina la temporada actual de forma manual.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def season_end(self, interaction: discord.Interaction):
        # ... (código sin cambios)
        await interaction.response.defer(thinking=True)
        await self.end_season_logic(interaction.guild, interaction.channel)
        await interaction.followup.send("La temporada ha sido finalizada manualmente.")

    @app_commands.command(name="status", description="Muestra el estado de la temporada actual.")
    async def season_status(self, interaction: discord.Interaction):
        # ... (código sin cambios)
        status = load_season_data()
        if status.get("active"):
            end_time = datetime.fromisoformat(status["end_time"])
            embed = discord.Embed(title=f"Temporada en Curso: {status['name']}", color=discord.Color.blue())
            embed.add_field(name="Finaliza", value=f"{discord.utils.format_dt(end_time, style='F')} ({discord.utils.format_dt(end_time, style='R')})")
            embed.set_footer(text=f"Temporada #{status.get('season_number', 'N/A')}")
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("No hay ninguna temporada activa en este momento.")

    @app_commands.command(name="clean_channels", description="Borra y recrea los canales de eventos para limpiarlos.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def clean_channels_command(self, interaction: discord.Interaction):
        # ... (código sin cambios)
        await interaction.response.defer(ephemeral=True, thinking=True)
        reporte = await self.clean_event_channels_logic(interaction.guild)
        await interaction.followup.send(f"✅ **Limpieza de Canales Completada**\n" + "\n".join(reporte))
    
    # --- COMANDO MASIVO CORREGIDO ---
    @app_commands.command(name="bulk_process", description="Procesa o resetea envíos masivamente desde una fecha.")
    @app_commands.describe(accion="La acción a realizar en los mensajes.", fecha="Fecha de inicio del procesamiento (formato DD/MM/YYYY).")
    @app_commands.choices(accion=[
        app_commands.Choice(name="✅ Aprobar todos los envíos pendientes", value="approve"),
        app_commands.Choice(name="🔄 Resetear todas las reacciones y puntos", value="reset")
    ])
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def bulk_process(self, interaction: discord.Interaction, accion: str, fecha: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            start_date = datetime.strptime(fecha, "%d/%m/%Y").replace(tzinfo=timezone.utc)
        except ValueError:
            return await interaction.followup.send("❌ Formato de fecha inválido. Usa `DD/MM/YYYY`.")

        category = self.bot.get_channel(SEASONS_CATEGORY_ID)
        if not category or not isinstance(category, discord.CategoryChannel):
            return await interaction.followup.send("❌ Error: No se encontró la categoría de temporadas.")

        cog_map = {
            'Ataque': 'attack-', 'Defensa': 'defenses-', 'Koth': KOTH_CHANNEL_ID,
            'Tempo': 'tempo-', 'Interserver': 'interserver-'
        }
        count = 0
        report_lines = []

        for channel in category.text_channels:
            processed_in_channel = 0
            async for message in channel.history(limit=None, after=start_date, oldest_first=True):
                if message.author.bot: continue
                
                # Encontrar el cog responsable de este canal
                cog_to_run = None
                for cog_name, identifier in cog_map.items():
                    is_target = (isinstance(identifier, str) and channel.name.lower().startswith(identifier)) or \
                                (isinstance(identifier, int) and channel.id == identifier)
                    if is_target:
                        cog_to_run = self.bot.get_cog(cog_name)
                        break
                
                if not cog_to_run: continue

                if accion == "approve":
                    if any(r.me and str(r.emoji) == '📝' for r in message.reactions):
                        class MockPayload:
                            def __init__(self, msg, member):
                                self.message_id, self.channel_id, self.guild_id, self.member, self.emoji = msg.id, msg.channel.id, msg.guild.id, member, '✅'
                        
                        await cog_to_run.on_raw_reaction_add(MockPayload(message, interaction.user))
                        count += 1; processed_in_channel += 1
                
                elif accion == "reset":
                    is_approved = any(r.me and str(r.emoji) == '✅' for r in message.reactions)
                    if is_approved:
                        if hasattr(cog_to_run, '_revert_points'):
                            # Necesitamos la información del envío desde el archivo judged
                            submission = cog_to_run.judged_submissions.get(str(message.id))
                            if submission:
                                class MockPayload:
                                    def __init__(self, msg, member):
                                        self.message_id, self.channel_id, self.guild_id, self.member = msg.id, msg.channel.id, msg.guild.id, member
                                
                                await cog_to_run._revert_points(MockPayload(message, interaction.user), submission)
                                # Limpiar del archivo judged
                                del cog_to_run.judged_submissions[str(message.id)]
                                cog_to_run.save_data(cog_to_run.judged_submissions, cog_to_run.judged_file)
                                await message.clear_reactions()
                                count += 1; processed_in_channel += 1
            
            if processed_in_channel > 0:
                report_lines.append(f"Canal `#{channel.name}`: {processed_in_channel} mensajes afectados.")
        
        action_text = "aprobado" if accion == "approve" else "reseteado"
        await interaction.followup.send(f"✅ **Proceso masivo completado.**\nSe han {action_text} **{count}** envíos desde el {fecha}.\n\n" + "\n".join(report_lines))

    async def clean_event_channels_logic(self, guild: discord.Guild) -> list:
        # ... (código sin cambios)
        canales_a_limpiar_prefijos = ['attack-', 'defenses-', 'tempo-', 'interserver-']
        category = self.bot.get_channel(SEASONS_CATEGORY_ID)
        report = []
        if not category or not isinstance(category, discord.CategoryChannel):
            report.append("❌ Error: No se encontró la categoría de temporadas configurada.")
            return report
        for channel in category.channels:
            if isinstance(channel, discord.TextChannel):
                if any(channel.name.lower().startswith(prefix) for prefix in canales_a_limpiar_prefijos):
                    try:
                        cloned_channel = await channel.clone(reason="Limpieza de temporada")
                        await cloned_channel.edit(position=channel.position)
                        await channel.delete(reason="Limpieza de temporada")
                        report.append(f"✅ Canal `#{channel.name}` limpiado.")
                    except discord.Forbidden: report.append(f"🔒 Sin permisos para limpiar `#{channel.name}`.")
                    except Exception as e: report.append(f"❌ Error al limpiar `#{channel.name}`: {e}")
        return report

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        # ... (código sin cambios)
        if isinstance(error, app_commands.MissingRole):
            await interaction.response.send_message("❌ No tienes el rol necesario.", ephemeral=True)
        else:
            traceback.print_exc()
            if not interaction.response.is_done():
                await interaction.response.send_message("Ocurrió un error inesperado.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Temporadas(bot))