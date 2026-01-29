import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timezone
import json
import os
import re
import traceback

# --- CONFIGURACIÓN Y ESTADO ---
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", 0))
STATUS_FILE = 'bot_status.json'

def load_status():
    """Carga el registro de la última vez que el bot estuvo activo."""
    try:
        with open(STATUS_FILE, 'r') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return {}

def save_status(data):
    """Guarda el registro de actividad en un archivo JSON."""
    with open(STATUS_FILE, 'w') as f: json.dump(data, f, indent=4)

# Clase auxiliar para simular datos de reacción al revertir puntos
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

    # --- LÓGICA INTERNA DE PROCESAMIENTO ---
    async def _run_logic(self, message: discord.Message):
        """Intenta procesar un mensaje revisando todos los módulos disponibles."""
        # Lista de módulos que tienen la función process_submission
        cogs_to_check = ['Ataque', 'Defensa', 'Interserver', 'Koth', 'Tempo']
        
        for name in cogs_to_check:
            cog = self.bot.get_cog(name)
            if cog and hasattr(cog, 'process_submission'):
                # Si el módulo acepta el mensaje, devuelve True
                if await cog.process_submission(message):
                    return True
        return False

    # --- COMANDOS SLASH ---

    @app_commands.command(name="escanear_canal", description="Escanea los últimos mensajes de este canal buscando envíos pendientes.")
    @app_commands.describe(limite="Número de mensajes a revisar (máximo 100)")
    async def scan_recent(self, interaction: discord.Interaction, limite: int = 50):
        """Revisa el historial del canal actual para marcar envíos ignorados."""
        if not any(role.id == ADMIN_ROLE_ID for role in interaction.user.roles):
            return await interaction.response.send_message("❌ No tienes permisos.", ephemeral=True)

        await interaction.response.defer(ephemeral=True, thinking=True)
        count = 0
        
        # Limitamos a 100 para evitar bloqueos de Discord (Rate Limits)
        async for message in interaction.channel.history(limit=min(limite, 100)):
            if message.author.bot: continue
            
            # Verificamos si ya tiene reacciones nuestras (para no repetir)
            if any(r.me for r in message.reactions): continue
            
            if await self._run_logic(message):
                count += 1
        
        await interaction.followup.send(f"✅ Escaneo finalizado. Se marcaron **{count}** envíos nuevos con 📝.")

    @app_commands.command(name="procesar_link", description="Procesa un mensaje específico usando su enlace directo.")
    @app_commands.describe(enlace="Copia el link del mensaje de Discord aquí")
    async def process_link(self, interaction: discord.Interaction, enlace: str):
        """Busca y procesa un mensaje individual mediante su link."""
        if not any(role.id == ADMIN_ROLE_ID for role in interaction.user.roles):
            return await interaction.response.send_message("❌ Sin permisos.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        # Extraer IDs del enlace: discord.com/channels/SERVER/CANAL/MENSAJE
        match = re.search(r'channels/(\d+)/(\d+)/(\d+)', enlace)
        if not match:
            return await interaction.followup.send("❌ El enlace proporcionado no es válido.")

        channel_id = int(match.group(2))
        message_id = int(match.group(3))

        try:
            channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            message = await channel.fetch_message(message_id)
            
            if await self._run_logic(message):
                await interaction.followup.send(f"✅ Mensaje de {message.author.display_name} procesado correctamente.")
            else:
                await interaction.followup.send("❌ El mensaje no es un envío válido o no tiene imágenes/menciones.")
        except Exception as e:
            await interaction.followup.send(f"❌ No se pudo encontrar el mensaje: {e}")

    @app_commands.command(name="scan_offline", description="Escanea todos los canales desde la última conexión del bot.")
    async def scan_offline(self, interaction: discord.Interaction):
        """Escanea canales relevantes buscando mensajes enviados mientras el bot estaba apagado."""
        if not any(role.id == ADMIN_ROLE_ID for role in interaction.user.roles):
            return await interaction.response.send_message("❌ No eres administrador.", ephemeral=True)

        await interaction.response.defer(ephemeral=True, thinking=True)
        status = load_status()
        last_active_str = status.get('last_online')
        
        if not last_active_str:
            return await interaction.followup.send("No hay registro de la última conexión.")

        after_ts = datetime.fromisoformat(last_active_str)
        count = 0
        
        for channel in interaction.guild.text_channels:
            # Filtrar por prefijos comunes de tus canales de Dofus
            prefixes = ['attack-', 'ataque-', 'defenses-', 'interserver-', 'tempo-']
            if any(channel.name.lower().startswith(pre) for pre in prefixes):
                async for message in channel.history(limit=100, after=after_ts, oldest_first=True):
                    if message.author.bot or any(r.me for r in message.reactions): continue
                    
                    if await self._run_logic(message):
                        count += 1
        
        await interaction.followup.send(f"✅ Escaneo global completado. Se marcaron **{count}** envíos nuevos.")

    @app_commands.command(name="sync", description="Sincroniza los comandos de barra con Discord.")
    async def sync_slash(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        synced = await self.bot.tree.sync()
        await interaction.followup.send(f"✅ Sincronizados {len(synced)} comandos.")

    # --- FUNCIONES DE CLIC DERECHO (CALLBACKS) ---
    
    async def process_manually(self, interaction: discord.Interaction, message: discord.Message):
        """Fuerza el reconocimiento de una imagen ignorada mediante clic derecho."""
        await interaction.response.defer(ephemeral=True)
        success = await self._run_logic(message)
        msg = "✅ Procesado. Ya puedes usar las reacciones." if success else "❌ No es un envío válido o ya tiene reacciones."
        await interaction.followup.send(msg)

    async def reset_submission(self, interaction: discord.Interaction, message: discord.Message):
        """Revierte los puntos de un mensaje ya juzgado y lo devuelve a estado pendiente (📝)."""
        await interaction.response.defer(ephemeral=True)
        
        # Buscamos en qué módulo está registrado el mensaje juzgado
        cog = None
        cogs_to_search = ['Ataque', 'Defensa', 'Interserver', 'Koth']
        for name in cogs_to_search:
            temp_cog = self.bot.get_cog(name)
            if temp_cog and hasattr(temp_cog, 'judged_submissions') and str(message.id) in temp_cog.judged_submissions:
                cog = temp_cog
                break
        
        if not cog:
            return await interaction.followup.send("❌ Este mensaje no ha sido juzgado o no se encuentra en los registros.")

        # Obtener datos guardados para revertir exactamente lo mismo
        submission = cog.judged_submissions.pop(str(message.id))
        mult = submission.get('multiplier', 1.0)
        
        # Revertir puntos llamando a la función del módulo correspondiente
        await cog._revert_points(MockPayload(message, interaction.user), submission, multiplier=mult)
        
        # Devolver el registro a la lista de pendientes
        cog.pending_submissions[str(message.id)] = {
            'points': submission['points'],
            'allies': submission['allies'],
            'channel_id': message.channel.id
        }
        
        # Guardar cambios en los archivos JSON
        cog.save_data(cog.pending_submissions, cog.pending_file)
        cog.save_data(cog.judged_submissions, cog.judged_file)
        
        await message.clear_reactions()
        await message.add_reaction('📝')
        await interaction.followup.send(f"✅ Puntos revertidos y envío devuelto a estado pendiente.")

async def setup(bot):
    await bot.add_cog(Admin(bot))