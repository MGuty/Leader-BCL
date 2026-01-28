import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timezone
import json
import os
import traceback

# --- CONFIGURACIÓN Y ESTADO ---
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", 0))
STATUS_FILE = 'bot_status.json'

def load_status():
    try:
        with open(STATUS_FILE, 'r') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return {}

def save_status(data):
    with open(STATUS_FILE, 'w') as f: json.dump(data, f, indent=4)

# Clase para simular datos de reacción al revertir puntos
class MockPayload:
    def __init__(self, message, user):
        self.message_id = message.id
        self.channel_id = message.channel.id
        self.guild_id = message.guild.id
        self.member = user
        self.user_id = user.id

class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
        # --- REGISTRO DE MENÚS CONTEXTUALES (Clic Derecho) ---
        self.ctx_process = app_commands.ContextMenu(name='Procesar Manualmente', callback=self.process_manually)
        self.ctx_reset = app_commands.ContextMenu(name='Resetear Envío', callback=self.reset_submission)
        
        self.bot.tree.add_command(self.ctx_process)
        self.bot.tree.add_command(self.ctx_reset)
        
        self.update_last_online_time.start()

    def cog_unload(self):
        self.update_last_online_time.cancel()

    @tasks.loop(minutes=5.0)
    async def update_last_online_time(self):
        """Mantiene un registro de cuándo estuvo el bot activo por última vez."""
        await self.bot.wait_until_ready()
        status = load_status()
        status['last_online'] = datetime.now(timezone.utc).isoformat()
        save_status(status)

    # --- COMANDOS SLASH ---
    @app_commands.command(name="scan_offline", description="Procesa mensajes enviados mientras el bot estaba apagado.")
    async def scan_offline(self, interaction: discord.Interaction):
        """Escanea canales buscando imágenes con menciones desde la última conexión."""
        if not any(role.id == ADMIN_ROLE_ID for role in interaction.user.roles):
            return await interaction.response.send_message("❌ No eres administrador.", ephemeral=True)

        await interaction.response.defer(ephemeral=True, thinking=True)
        status = load_status()
        last_active_str = status.get('last_online')
        
        if not last_active_str:
            return await interaction.followup.send("No hay registro de última conexión.")

        after_ts = datetime.fromisoformat(last_active_str)
        count = 0
        
        # Módulos que tienen lógica de procesamiento
        cogs_to_scan = ['Ataque', 'Defensa', 'Interserver']
        
        for channel in interaction.guild.text_channels:
            # Filtramos por los nombres de tus canales de Dofus
            if any(channel.name.lower().startswith(pre) for pre in ['attack-', 'ataque-', 'defenses-', 'interserver-']):
                async for message in channel.history(limit=100, after=after_ts, oldest_first=True):
                    if message.author.bot or any(r.me for r in message.reactions): continue
                    
                    for name in cogs_to_scan:
                        cog = self.bot.get_cog(name)
                        if cog and await cog.process_submission(message):
                            count += 1
                            break
        
        await interaction.followup.send(f"✅ Escaneo completado. Se marcaron **{count}** envíos nuevos con 📝.")

    @app_commands.command(name="sync", description="Sincroniza botones y menús con Discord.")
    async def sync_slash(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        synced = await self.bot.tree.sync()
        await interaction.followup.send(f"✅ Sincronizados {len(synced)} comandos.")

    # --- FUNCIONES DE CLIC DERECHO (CALLBACKS) ---
    async def process_manually(self, interaction: discord.Interaction, message: discord.Message):
        """Fuerza el reconocimiento de una imagen ignorada."""
        await interaction.response.defer(ephemeral=True)
        
        success = False
        for name in ['Ataque', 'Defensa', 'Interserver']:
            cog = self.bot.get_cog(name)
            if cog and await cog.process_submission(message):
                success = True
                break
        
        msg = "✅ Procesado. Ahora puedes usar reacciones." if success else "❌ No es un envío válido o ya fue procesado."
        await interaction.followup.send(msg)

    async def reset_submission(self, interaction: discord.Interaction, message: discord.Message):
        """Revierte puntos y devuelve a pendiente."""
        await interaction.response.defer(ephemeral=True)
        
        # Identificar módulo
        cog = None
        for name in ['Ataque', 'Defensa', 'Interserver']:
            temp_cog = self.bot.get_cog(name)
            if temp_cog and str(message.id) in temp_cog.judged_submissions:
                cog = temp_cog
                break
        
        if not cog:
            return await interaction.followup.send("❌ Este mensaje no ha sido juzgado aún.")

        # Revertir usando el multiplicador original guardado
        submission = cog.judged_submissions.pop(str(message.id))
        mult = submission.get('multiplier', 1.0)
        
        await cog._revert_points(MockPayload(message, interaction.user), submission, multiplier=mult)
        
        # Devolver a pendientes
        cog.pending_submissions[str(message.id)] = {
            'points': submission['points'],
            'allies': submission['allies'],
            'channel_id': message.channel.id
        }
        cog.save_data(cog.pending_submissions, cog.pending_file)
        cog.save_data(cog.judged_submissions, cog.judged_file)
        
        await message.clear_reactions()
        await message.add_reaction('📝')
        await interaction.followup.send(f"✅ Puntos revertidos ({int(submission['points']*mult)} pts) y devuelto a 📝.")

async def setup(bot):
    await bot.add_cog(Admin(bot))