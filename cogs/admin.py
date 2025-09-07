import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timezone
import json
import os
import traceback

# --- CONFIGURACIÓN ---
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", 0))
KOTH_CHANNEL_ID = int(os.getenv("KOTH_CHANNEL_ID", 0))
TEST_GUILD_ID = int(os.getenv("TEST_GUILD_ID", 0))
STATUS_FILE = 'bot_status.json'

# --- FUNCIONES DE AYUDA ---
def load_status():
    try:
        with open(STATUS_FILE, 'r') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return {}

def save_status(data):
    with open(STATUS_FILE, 'w') as f: json.dump(data, f, indent=4)

@app_commands.guild_only()
class Admin(commands.GroupCog, name="admin", description="Comandos de administración del bot."):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__() # Inicializador requerido para GroupCog
        
        # --- REGISTRO DE COMANDOS DE MENÚ CONTEXTUAL ---
        self.process_manually_ctx_menu = app_commands.ContextMenu(
            name='Procesar Envío Manualmente',
            callback=self.process_manually_callback,
        )
        self.bot.tree.add_command(self.process_manually_ctx_menu, guild=discord.Object(id=TEST_GUILD_ID))
        
        self.clear_reactions_ctx_menu = app_commands.ContextMenu(
            name='Limpiar Reacciones de Mensaje',
            callback=self.clear_reactions_callback,
        )
        self.bot.tree.add_command(self.clear_reactions_ctx_menu, guild=discord.Object(id=TEST_GUILD_ID))
        
        self.update_last_online_time.start()

    def cog_unload(self):
        self.bot.tree.remove_command(self.process_manually_ctx_menu.name, type=self.process_manually_ctx_menu.type, guild=discord.Object(id=TEST_GUILD_ID))
        self.bot.tree.remove_command(self.clear_reactions_ctx_menu.name, type=self.clear_reactions_ctx_menu.type, guild=discord.Object(id=TEST_GUILD_ID))
        self.update_last_online_time.cancel()

    @tasks.loop(minutes=5.0)
    async def update_last_online_time(self):
        await self.bot.wait_until_ready()
        status = load_status()
        status['last_online'] = datetime.now(timezone.utc).isoformat()
        save_status(status)

    # --- COMANDOS SLASH (ahora son subcomandos de /admin) ---
    @app_commands.command(name="scan_offline", description="Escanea canales en busca de envíos hechos mientras el bot estaba desconectado.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def scan_offline_submissions(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        status = load_status()
        last_active_str = status.get('last_online')
        if not last_active_str:
            return await interaction.followup.send("No hay una marca de tiempo de la última conexión.")

        after_timestamp = datetime.fromisoformat(last_active_str)
        processed_count = 0
        scan_report = []

        cogs_to_scan = {'Ataque': 'attack-', 'Defensa': 'defenses-', 'Koth': KOTH_CHANNEL_ID, 'Tempo': 'tempo-', 'Interserver': 'interserver-'}

        for cog_name, identifier in cogs_to_scan.items():
            cog = self.bot.get_cog(cog_name)
            if not cog or not hasattr(cog, 'process_submission'): continue
            
            for channel in interaction.guild.text_channels:
                is_target_channel = (isinstance(identifier, str) and channel.name.lower().startswith(identifier)) or \
                                    (isinstance(identifier, int) and channel.id == identifier)
                
                if is_target_channel:
                    try:
                        found_in_channel = 0
                        async for message in channel.history(limit=200, after=after_timestamp, oldest_first=True):
                            if not message.author.bot:
                                try:
                                    if await cog.process_submission(message):
                                        processed_count += 1
                                        found_in_channel += 1
                                except Exception as e:
                                    print(f"Error al procesar mensaje {message.id} en {cog_name}: {e}")
                        
                        if found_in_channel > 0:
                            scan_report.append(f"Canal `#{channel.name}`: {found_in_channel} envíos encontrados.")
                    except discord.Forbidden:
                        scan_report.append(f"No tengo permisos para ver `#{channel.name}`.")
                    except Exception as e:
                        scan_report.append(f"Error en `#{channel.name}`: {e}")

        status['last_scan'] = datetime.now(timezone.utc).isoformat()
        save_status(status)
        await interaction.followup.send(f"✅ **Escaneo completado.**\nSe procesaron **{processed_count}** nuevos envíos.\n\n**Reporte:**\n- " + "\n- ".join(scan_report if scan_report else ["No se encontraron nuevos envíos."]))

    @app_commands.command(name="sync", description="Sincroniza manualmente los comandos de barra con Discord.")
    @commands.is_owner()
    async def sync_commands(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            guild_obj = discord.Object(id=TEST_GUILD_ID) if TEST_GUILD_ID != 0 else None
            synced = await self.bot.tree.sync(guild=guild_obj)
            await interaction.followup.send(f"✅ Sincronizados {len(synced)} comandos.")
        except Exception as e:
            await interaction.followup.send(f"❌ Error al sincronizar: {e}")

    @app_commands.command(name="limpiar_reacciones", description="Limpia las reacciones de los últimos mensajes de este canal.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    @app_commands.describe(cantidad="Número de mensajes a revisar y limpiar (máximo 100).")
    async def clear_channel_reactions(self, interaction: discord.Interaction, cantidad: int = 50):
        await interaction.response.defer(ephemeral=True, thinking=True)
        if cantidad > 100:
            cantidad = 100
        
        cleaned_count = 0
        try:
            async for message in interaction.channel.history(limit=cantidad):
                if message.reactions:
                    await message.clear_reactions()
                    cleaned_count += 1
            await interaction.followup.send(f"✅ Se han limpiado las reacciones de **{cleaned_count}** mensajes en este canal.")
        except discord.Forbidden:
            await interaction.followup.send("❌ No tengo los permisos necesarios para gestionar reacciones en este canal.")
        except Exception as e:
            await interaction.followup.send(f"Ocurrió un error: {e}")

    # --- FUNCIONES CALLBACK PARA MENÚS DE CONTEXTO ---
    async def process_manually_callback(self, interaction: discord.Interaction, message: discord.Message):
        if not any(role.id == ADMIN_ROLE_ID for role in interaction.user.roles):
            return await interaction.response.send_message("❌ No tienes el rol de administrador necesario.", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True, thinking=True)
        channel_name = message.channel.name.lower()
        target_cog_name = None

        if channel_name.startswith('attack-'): target_cog_name = 'Ataque'
        elif channel_name.startswith('defenses-'): target_cog_name = 'Defensa'
        elif channel_name.startswith('tempo-'): target_cog_name = 'Tempo'
        elif channel_name.startswith('interserver-'): target_cog_name = 'Interserver'
        elif message.channel.id == KOTH_CHANNEL_ID: target_cog_name = 'Koth'
        
        if not target_cog_name:
            return await interaction.followup.send("❌ Este comando solo se puede usar en un canal de evento válido.")

        cog_to_run = self.bot.get_cog(target_cog_name)
        if cog_to_run and hasattr(cog_to_run, 'process_submission'):
            if await cog_to_run.process_submission(message):
                await interaction.followup.send(f"✅ El envío en `#{message.channel.name}` ha sido añadido a la cola de pendientes.")
            else:
                await interaction.followup.send("❌ No se pudo procesar el envío. Puede que ya estuviera procesado o no sea válido.")
        else:
            await interaction.followup.send(f"❌ No se pudo encontrar la lógica para procesar envíos de tipo '{target_cog_name}'.")

    async def clear_reactions_callback(self, interaction: discord.Interaction, message: discord.Message):
        if not any(role.id == ADMIN_ROLE_ID for role in interaction.user.roles):
            return await interaction.response.send_message("❌ No tienes el rol de administrador necesario.", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        try:
            if message.reactions:
                await message.clear_reactions()
                await interaction.followup.send("✅ Todas las reacciones de este mensaje han sido eliminadas.")
            else:
                await interaction.followup.send("ℹ️ El mensaje no tenía ninguna reacción para eliminar.")
        except discord.Forbidden:
            await interaction.followup.send("❌ No tengo los permisos necesarios para gestionar reacciones en este canal.")
        except Exception as e:
            await interaction.followup.send(f"Ocurrió un error: {e}")

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, (app_commands.MissingRole, commands.NotOwner)):
            await interaction.response.send_message("❌ No tienes los permisos necesarios para esta acción.", ephemeral=True)
        else:
            print(f"Error en un comando de Admin por {interaction.user}:")
            traceback.print_exc()
            if not interaction.response.is_done():
                await interaction.response.send_message("Ocurrió un error inesperado.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Admin(bot))