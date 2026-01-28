import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
import json
import os
from datetime import datetime, timezone
import shutil

# --- CONFIGURACIÓN DE RUTA ABSOLUTA ---
# Esto evita que el bot cree bases de datos "fantasma" en otras carpetas
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.join(BASE_DIR, 'leaderboard.db')
LIVE_RANKING_FILE = os.path.join(BASE_DIR, 'live_ranking.json')

class Puntos(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._initialize_database()
        self.update_live_rank_task.start()

    def cog_unload(self):
        self.update_live_rank_task.cancel()

    def _initialize_database(self):
        """Inicializa la tabla de puntuaciones si no existe."""
        try:
            con = sqlite3.connect(DB_FILE)
            cur = con.cursor()
            cur.execute('''
                CREATE TABLE IF NOT EXISTS puntuaciones (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, 
                    user_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL, 
                    category TEXT NOT NULL,
                    points INTEGER NOT NULL, 
                    timestamp DATETIME NOT NULL
                )
            ''')
            con.commit()
            con.close()
        except Exception as e:
            print(f"❌ Error al inicializar DB: {e}")

    # --- TAREAS AUTOMÁTICAS ---
    @tasks.loop(minutes=15)
    async def update_live_rank_task(self):
        """Actualiza el mensaje de ranking automático cada 15 minutos."""
        try:
            if not os.path.exists(LIVE_RANKING_FILE): return
            with open(LIVE_RANKING_FILE, 'r') as f: data = json.load(f)
            
            channel = self.bot.get_channel(data['channel_id']) or await self.bot.fetch_channel(data['channel_id'])
            message = await channel.fetch_message(data['message_id'])
            new_embed = await self.build_ranking_embed(message.guild)
            if new_embed: await message.edit(embed=new_embed)
        except: pass

    # --- LÓGICA DE DATOS ---
    async def add_points(self, interaction_or_payload, user_id: str, amount: int, category: str):
        """Añade puntos a la base de datos."""
        try:
            con = sqlite3.connect(DB_FILE)
            cur = con.cursor()
            guild_id = interaction_or_payload.guild_id
            cur.execute("INSERT INTO puntuaciones (user_id, guild_id, category, points, timestamp) VALUES (?, ?, ?, ?, ?)",
                        (int(user_id), guild_id, category, amount, datetime.now(timezone.utc)))
            con.commit()
            con.close()
        except Exception as e:
            print(f"❌ Error al añadir puntos: {e}")

    async def reset_database_for_new_season(self, archive_db_name: str):
        """Borra los puntos corrigiendo el error de transacción y VACUUM."""
        if os.path.exists(DB_FILE):
            shutil.copyfile(DB_FILE, archive_db_name)
        
        con = sqlite3.connect(DB_FILE)
        cur = con.cursor()
        cur.execute("DELETE FROM puntuaciones")
        # PRIMERO hacemos commit para cerrar la transacción de borrado
        con.commit() 
        # AHORA ejecutamos VACUUM fuera de la transacción para limpiar el archivo
        cur.execute("VACUUM") 
        con.close()

    async def build_ranking_embed(self, guild: discord.Guild):
        """Construye el ranking optimizado para evitar 'Timeouts'."""
        try:
            con = sqlite3.connect(DB_FILE)
            cur = con.cursor()
            cur.execute("""
                SELECT user_id, SUM(points) as total 
                FROM puntuaciones WHERE guild_id = ? 
                GROUP BY user_id HAVING total != 0 
                ORDER BY total DESC LIMIT 50
            """, (guild.id,))
            data = cur.fetchall()
            con.close()
        except: return None

        if not data: return None

        rank_lines = []
        for i, (user_id, total_points) in enumerate(data):
            medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i + 1}."
            
            # OPTIMIZACIÓN: Solo usamos get_member para evitar peticiones lentas a internet
            member = guild.get_member(int(user_id))
            display_name = member.display_name if member else f"ID:{user_id}"
            
            rank_lines.append(f"{medal:<4} {display_name[:18]:<20} {str(total_points):>7}")

        embed = discord.Embed(
            title=f"🏆 Ranking - {guild.name} 🏆",
            description=f"```\n" + "\n".join(rank_lines) + "\n```",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc)
        )
        return embed

    # --- COMANDOS DE BARRA ---
    rank_group = app_commands.Group(name="rank", description="Gestión del ranking.")

    @rank_group.command(name="ver", description="Muestra el Top 50 del servidor.")
    async def show_rank(self, interaction: discord.Interaction):
        await interaction.response.defer() # Ganamos tiempo para procesar
        embed = await self.build_ranking_embed(interaction.guild)
        await interaction.followup.send(embed=embed if embed else "No hay puntos registrados aún.")

    @rank_group.command(name="clear", description="[ADMIN] Borra el ranking actual.")
    @app_commands.describe(confirmacion="Escribe 'CONFIRM' para borrar.")
    async def clear_rank(self, interaction: discord.Interaction, confirmacion: str):
        admin_role_id = int(os.getenv("ADMIN_ROLE_ID", 0))
        if not any(role.id == admin_role_id for role in interaction.user.roles):
            return await interaction.response.send_message("❌ No tienes permisos.", ephemeral=True)
            
        if confirmacion.upper() != 'CONFIRM':
            return await interaction.response.send_message("❌ Debes escribir 'CONFIRM' para validar.", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        archive_name = f"respaldo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        await self.reset_database_for_new_season(archive_name)
        await interaction.followup.send(f"✅ Ranking borrado. Respaldo creado: `{archive_name}`")

async def setup(bot):
    await bot.add_cog(Puntos(bot))