# cogs/puntos.py (con ranking automático)
import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
import json
from datetime import datetime, timezone
import os
import traceback

# --- CONFIGURACIÓN ---
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", 0))
BOT_AUDIT_LOGS_CHANNEL_ID = int(os.getenv("BOT_AUDIT_LOGS_CHANNEL_ID", 0))
DB_FILE = 'leaderboard.db'
SNAPSHOT_FILE = 'ranking_snapshot.json'
LIVE_RANKING_FILE = 'live_ranking.json' # Nuevo archivo de estado

class Puntos(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._initialize_database()
        self.snapshot_ranking_task.start()
        # --- NUEVO ---
        self.update_live_rank_task.start()

    def cog_unload(self):
        self.snapshot_ranking_task.cancel()
        # --- NUEVO ---
        self.update_live_rank_task.cancel()

    # --- NUEVA FUNCIÓN DE AYUDA ---
    def load_live_rank_data(self):
        try:
            with open(LIVE_RANKING_FILE, 'r') as f: return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError): return {}

    def save_live_rank_data(self, data):
        with open(LIVE_RANKING_FILE, 'w') as f: json.dump(data, f, indent=4)

    # --- NUEVA TAREA EN SEGUNDO PLANO ---
    @tasks.loop(minutes=15)
    async def update_live_rank_task(self):
        live_rank_data = self.load_live_rank_data()
        if not live_rank_data.get('message_id'):
            return # No hay ranking configurado, no hacer nada.

        try:
            channel = self.bot.get_channel(live_rank_data['channel_id']) or await self.bot.fetch_channel(live_rank_data['channel_id'])
            message = await channel.fetch_message(live_rank_data['message_id'])
        except (discord.NotFound, discord.Forbidden):
            print("No se pudo encontrar el mensaje del ranking automático. Desactivando...")
            self.save_live_rank_data({}) # Limpia la configuración si el mensaje fue borrado.
            return
            
        # Reutilizamos la lógica del comando /rank ver para generar el embed
        new_embed = await self.build_ranking_embed(message.guild)
        if new_embed:
            await message.edit(embed=new_embed)
            print(f"[{datetime.now()}] Ranking automático actualizado.")

    @update_live_rank_task.before_loop
    async def before_update_live_rank(self):
        await self.bot.wait_until_ready()

    # --- Lógica del ranking extraída a su propia función para ser reutilizable ---
    async def build_ranking_embed(self, guild: discord.Guild):
        con = sqlite3.connect(DB_FILE)
        cur = con.cursor()
        cur.execute("SELECT user_id, SUM(points) as total_points FROM puntuaciones WHERE guild_id = ? GROUP BY user_id HAVING SUM(points) != 0 ORDER BY total_points DESC LIMIT 25", (guild.id,))
        current_ranking_data = cur.fetchall()
        con.close()

        if not current_ranking_data:
            return None

        rank_lines = []
        for i, (user_id, total_points) in enumerate(current_ranking_data):
            rank_display = ""
            if i == 0: rank_display = "🥇"
            elif i == 1: rank_display = "🥈"
            elif i == 2: rank_display = "🥉"
            else: rank_display = f"{i + 1}."

            try:
                member = guild.get_member(int(user_id)) or await guild.fetch_member(int(user_id))
                display_name = member.display_name
            except discord.NotFound:
                display_name = f"Usuario Desconocido ({user_id})"

            rank_padded = rank_display.ljust(4)
            name_padded = display_name.ljust(20)
            points_padded = str(total_points).rjust(7)
            rank_lines.append(f"{rank_padded} {name_padded} {points_padded}")

        description_text = "```\n" + "\n".join(rank_lines) + "\n```"
        embed = discord.Embed(
            title=f"🏆 Ranking - {guild.name} 🏆",
            description=description_text,
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Actualizado")
        return embed

    # --- GRUPO DE COMANDOS /rank ---
    rank_group = app_commands.Group(name="rank", description="Comandos relacionados con el ranking de puntos.")

    @rank_group.command(name="ver", description="Muestra la tabla de clasificación de puntos completa.")
    async def show_rank(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        embed = await self.build_ranking_embed(interaction.guild)
        if embed:
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send("Aún no se ha registrado ningún punto en este servidor.")

    @rank_group.command(name="setup", description="Configura un mensaje de ranking que se actualiza automáticamente en este canal.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def setup_rank(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        live_rank_data = self.load_live_rank_data()
        if live_rank_data.get('message_id'):
            return await interaction.followup.send("❌ Ya hay un ranking automático configurado. Detén el anterior primero con `/rank stop`.")
            
        initial_embed = discord.Embed(title="🏆 Ranking Automático 🏆", description="Cargando ranking...", color=discord.Color.light_grey())
        message = await interaction.channel.send(embed=initial_embed)
        
        self.save_live_rank_data({'channel_id': message.channel.id, 'message_id': message.id})
        
        # Forzar la primera actualización inmediatamente
        final_embed = await self.build_ranking_embed(interaction.guild)
        if final_embed:
            await message.edit(embed=final_embed)
            
        await interaction.followup.send(f"✅ ¡Ranking automático configurado en este canal! Se actualizará cada 15 minutos.")

    @rank_group.command(name="stop", description="Detiene y elimina el mensaje de ranking automático.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def stop_rank(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        live_rank_data = self.load_live_rank_data()
        if not live_rank_data.get('message_id'):
            return await interaction.followup.send("No hay ningún ranking automático configurado para detener.")
        
        try:
            channel = await self.bot.fetch_channel(live_rank_data['channel_id'])
            message = await channel.fetch_message(live_rank_data['message_id'])
            await message.delete()
        except (discord.NotFound, discord.Forbidden):
            pass # Si el mensaje ya no existe, no importa.
        
        self.save_live_rank_data({}) # Limpia la configuración
        await interaction.followup.send("✅ Ranking automático detenido y mensaje eliminado.")

    # --- El resto de funciones (_initialize_database, add_points, etc.) y el comando /points no cambian ---
    # ...
    
async def setup(bot):
    await bot.add_cog(Puntos(bot))