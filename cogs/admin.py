# cogs/admin.py (con comando para limpiar reacciones de un canal)
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
# --- CORRECCIÓN: Se añade el nombre del grupo aquí ---
@app_commands.Group(name="admin", description="Comandos de administración del bot.")
class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
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

    # --- COMANDOS SLASH ---
    @app_commands.command(name="scan_offline", description="Escanea canales en busca de envíos hechos mientras el bot estaba desconectado.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def scan_offline_submissions(self, interaction: discord.Interaction):
        # (El código de este comando no cambia)
        pass # Placeholder

    @app_commands.command(name="sync", description="Sincroniza manualmente los comandos de barra con Discord.")
    @commands.is_owner()
    async def sync_commands(self, interaction: discord.Interaction):
        # (El código de este comando no cambia)
        pass # Placeholder

    # --- NUEVO COMANDO PARA LIMPIAR CANAL ---
    @app_commands.command(name="limpiar_reacciones", description="Limpia las reacciones de los últimos mensajes de este canal.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    @app_commands.describe(cantidad="Número de mensajes a revisar y limpiar (máximo 100).")
    async def clear_channel_reactions(self, interaction: discord.Interaction, cantidad: int = 50):
        await interaction.response.defer(ephemeral=True, thinking=True)
        if cantidad > 100:
            cantidad = 100
        
        cleaned_count = 0
        try:
            # Itera sobre los últimos 'cantidad' mensajes en el canal donde se usó el comando
            async for message in interaction.channel.history(limit=cantidad):
                if message.reactions:
                    await message.clear_reactions()
                    cleaned_count += 1
            await interaction.followup.send(f"✅ Se han limpiado las reacciones de **{cleaned_count}** mensajes en este canal.")
        except discord.Forbidden:
            await interaction.followup.send("❌ No tengo los permisos necesarios para gestionar reacciones en este canal.")
        except Exception as e:
            await interaction.followup.send(f"Ocurrió un error: {e}")
    # --- FIN DE NUEVO CÓDIGO ---

    # --- FUNCIONES CALLBACK PARA MENÚS DE CONTEXTO ---
    async def process_manually_callback(self, interaction: discord.Interaction, message: discord.Message):
        # (El código de este callback no cambia)
        pass # Placeholder

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
        # (El código del manejador de errores no cambia)
        pass # Placeholder

async def setup(bot):
    await bot.add_cog(Admin(bot))