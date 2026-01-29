import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
import json
import os
from datetime import datetime, timezone
import shutil

# --- CONFIGURACIÓN DE RUTA ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.join(BASE_DIR, 'leaderboard.db')
LIVE_RANKING_FILE = os.path.join(BASE_DIR, 'live_ranking.json')

class Puntos(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._initialize_database()
        self.update_live_rank_task.start()
        
        # IMPORTANTE: Esto asegura que el bot registre el grupo /rank correctamente
        try:
            self.bot.tree.add_command(self.rank_group)
        except:
            pass # Evita errores si ya estaba registrado

    def cog_unload(self):
        self.update_live_rank_task.cancel()

    def _initialize_database(self):
        """Inicializa la tabla de puntuaciones con manejo de errores mejorado."""
        try:
            with sqlite3.connect(DB_FILE) as con:
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
        except Exception as e:
            print(f"❌ Error al inicializar DB: {e}")

    # --- LÓGICA DE DATOS ---
    async def add_points(self, interaction_or_payload, user_id: str, amount: int, category: str):
        try:
            with sqlite3.connect(DB_FILE) as con:
                cur = con.cursor()
                guild_id = interaction_or_payload.guild_id
                cur.execute("INSERT INTO puntuaciones (user_id, guild_id, category, points, timestamp) VALUES (?, ?, ?, ?, ?)",
                            (int(user_id), guild_id, category, amount, datetime.now(timezone.utc)))
                con.commit()
        except Exception as e:
            print(f"❌ Error al añadir puntos: {e}")

    async def build_ranking_embed(self, guild: discord.Guild):
        """Construye el ranking optimizado."""
        try:
            with sqlite3.connect(DB_FILE) as con:
                cur = con.cursor()
                cur.execute("""
                    SELECT user_id, SUM(points) as total 
                    FROM puntuaciones WHERE guild_id = ? 
                    GROUP BY user_id HAVING total != 0 
                    ORDER BY total DESC LIMIT 50
                """, (guild.id,))
                data = cur.fetchall()
            
            if not data: return None

            rank_lines = []
            for i, (user_id, total_points) in enumerate(data):
                # Medallas para el podio
                medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i + 1}."
                
                # Intentamos obtener el nombre del miembro
                member = guild.get_member(int(user_id))
                display_name = member.display_name if member else f"ID:{user_id}"
                
                # Formateo visual (como eres diseñador, esto te gustará: alineación limpia)
                rank_lines.append(f"{medal:<4} {display_name[:18]:<20} {str(total_points):>7}")

            embed = discord.Embed(
                title=f"🏆 Ranking - {guild.name} 🏆",
                description=f"```\n" + "\n".join(rank_lines) + "\n```",
                color=discord.Color.gold(),
                timestamp=datetime.now(timezone.utc)
            )
            return embed
        except Exception as e:
            print(f"❌ Error al construir el ranking: {e}")
            return None

    # --- COMANDOS DE BARRA (GROUP) ---
    rank_group = app_commands.Group(name="rank", description="Gestión del ranking.")

    @rank_group.command(name="ver", description="Muestra el Top 50 del servidor.")
    async def show_rank(self, interaction: discord.Interaction):
        # PRIMERO: Avisamos a Discord que estamos trabajando para que no nos corte (defer)
        await interaction.response.defer()
        
        try:
            embed = await self.build_ranking_embed(interaction.guild)
            if embed:
                await interaction.followup.send(embed=embed)
            else:
                await interaction.followup.send("No hay puntos registrados aún.")
        except Exception as e:
            print(f"❌ Error en /rank ver: {e}")
            await interaction.followup.send("Ocurrió un error al cargar el ranking.")

    @tasks.loop(minutes=15)
    async def update_live_rank_task(self):
        """Actualiza el mensaje de ranking automático."""
        try:
            if not os.path.exists(LIVE_RANKING_FILE): return
            with open(LIVE_RANKING_FILE, 'r') as f: data = json.load(f)
            
            channel = self.bot.get_channel(data['channel_id'])
            if not channel: return
            
            message = await channel.fetch_message(data['message_id'])
            new_embed = await self.build_ranking_embed(message.guild)
            if new_embed: await message.edit(embed=new_embed)
        except: pass

async def setup(bot):
    await bot.add_cog(Puntos(bot))