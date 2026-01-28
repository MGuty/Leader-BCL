import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
import json
from datetime import datetime, timezone
import os
import traceback
import shutil

# --- CONFIGURACIÓN ---
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", 0))
BOT_AUDIT_LOGS_CHANNEL_ID = int(os.getenv("BOT_AUDIT_LOGS_CHANNEL_ID", 0))
DB_FILE = 'leaderboard.db'
SNAPSHOT_FILE = 'ranking_snapshot.json'
LIVE_RANKING_FILE = 'live_ranking.json'

class Puntos(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._initialize_database()
        self.snapshot_ranking_task.start()
        self.update_live_rank_task.start()

    def cog_unload(self):
        self.snapshot_ranking_task.cancel()
        self.update_live_rank_task.cancel()

    def _initialize_database(self):
        """Crea la tabla de puntuaciones si no existe."""
        try:
            con = sqlite3.connect(DB_FILE)
            cur = con.cursor()
            cur.execute('''
                CREATE TABLE IF NOT EXISTS puntuaciones (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL, category TEXT NOT NULL,
                    points INTEGER NOT NULL, timestamp DATETIME NOT NULL
                )
            ''')
            con.commit()
            con.close()
        except Exception as e:
            print(f"Error al inicializar la base de datos: {e}")

    def load_live_rank_data(self):
        try:
            with open(LIVE_RANKING_FILE, 'r') as f: return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError): return {}

    def save_live_rank_data(self, data):
        with open(LIVE_RANKING_FILE, 'w') as f: json.dump(data, f, indent=4)

    @tasks.loop(hours=24)
    async def snapshot_ranking_task(self):
        """Crea un respaldo del ranking cada 24 horas."""
        await self.bot.wait_until_ready()
        try:
            con = sqlite3.connect(DB_FILE)
            cur = con.cursor()
            cur.execute("SELECT user_id, SUM(points) as total_points FROM puntuaciones GROUP BY user_id")
            ranking_data = cur.fetchall()
            con.close()
            snapshot = {str(row[0]): row[1] for row in ranking_data}
            with open(SNAPSHOT_FILE, 'w') as f:
                json.dump(snapshot, f)
        except Exception as e:
            print(f"Error al crear el snapshot: {e}")

    @tasks.loop(minutes=15)
    async def update_live_rank_task(self):
        """Actualiza el mensaje de ranking automático cada 15 minutos."""
        live_rank_data = self.load_live_rank_data()
        if not live_rank_data.get('message_id'): return

        try:
            channel = self.bot.get_channel(live_rank_data['channel_id']) or await self.bot.fetch_channel(live_rank_data['channel_id'])
            message = await channel.fetch_message(live_rank_data['message_id'])
            new_embed = await self.build_ranking_embed(message.guild)
            if new_embed:
                await message.edit(embed=new_embed)
        except (discord.NotFound, discord.Forbidden):
            self.save_live_rank_data({})
            
    @update_live_rank_task.before_loop
    async def before_update_live_rank(self):
        await self.bot.wait_until_ready()

    async def add_points(self, interaction_or_payload, user_id: str, amount: int, category: str):
        """Método central para añadir puntos a la base de datos."""
        try:
            con = sqlite3.connect(DB_FILE)
            cur = con.cursor()
            guild_id = interaction_or_payload.guild_id
            cur.execute("INSERT INTO puntuaciones (user_id, guild_id, category, points, timestamp) VALUES (?, ?, ?, ?, ?)",
                        (int(user_id), guild_id, category, amount, datetime.now(timezone.utc)))
            con.commit()
            con.close()
        except Exception as e:
            traceback.print_exc()

    async def get_ranked_player_ids(self, guild_id: int):
        """Obtiene la lista de IDs de jugadores ordenados por puntos (para repartozonas)."""
        try:
            con = sqlite3.connect(DB_FILE)
            cur = con.cursor()
            cur.execute("SELECT user_id FROM puntuaciones WHERE guild_id = ? GROUP BY user_id HAVING SUM(points) != 0 ORDER BY SUM(points) DESC", (guild_id,))
            ranked_ids = [row[0] for row in cur.fetchall()]
            con.close()
            return ranked_ids
        except Exception as e:
            return []

    async def reset_database_for_new_season(self, archive_db_name: str):
        """Reinicia la base de datos de forma segura para una nueva temporada."""
        if os.path.exists(DB_FILE):
            try:
                shutil.copyfile(DB_FILE, archive_db_name)
            except Exception as e:
                print(f"Error al archivar: {e}")
        
        try:
            con = sqlite3.connect(DB_FILE)
            cur = con.cursor()
            cur.execute("DELETE FROM puntuaciones")
            cur.execute("VACUUM")
            con.commit()
            con.close()
        except Exception as e:
            print(f"Error al limpiar: {e}")

        if os.path.exists(SNAPSHOT_FILE): os.remove(SNAPSHOT_FILE)

    async def build_ranking_embed(self, guild: discord.Guild):
        """Construye el Embed del ranking (Top 50)."""
        con = sqlite3.connect(DB_FILE)
        cur = con.cursor()
        cur.execute("SELECT user_id, SUM(points) as total_points FROM puntuaciones WHERE guild_id = ? GROUP BY user_id HAVING SUM(points) != 0 ORDER BY total_points DESC LIMIT 50", (guild.id,))
        current_ranking_data = cur.fetchall()
        con.close()

        if not current_ranking_data: return None

        rank_lines = []
        for i, (user_id, total_points) in enumerate(current_ranking_data):
            rank_display = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i + 1}."
            try:
                member = guild.get_member(int(user_id)) or await guild.fetch_member(int(user_id))
                display_name = member.display_name
            except discord.NotFound: display_name = f"ID: {user_id}"

            rank_lines.append(f"{rank_display.ljust(4)} {display_name.ljust(20)} {str(total_points).rjust(7)}")

        embed = discord.Embed(title=f"🏆 Ranking - {guild.name} 🏆", description=f"```\n" + "\n".join(rank_lines) + "\n```", color=discord.Color.gold(), timestamp=datetime.now(timezone.utc))
        embed.set_footer(text="Actualizado")
        return embed

    rank_group = app_commands.Group(name="rank", description="Comandos del ranking.")

    @rank_group.command(name="ver", description="Muestra el ranking actual.")
    async def show_rank(self, interaction: discord.Interaction):
        await interaction.response.defer()
        embed = await self.build_ranking_embed(interaction.guild)
        await interaction.followup.send(embed=embed if embed else "No hay puntos registrados.")

    @rank_group.command(name="setup", description="Configura el ranking automático.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def setup_rank(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if self.load_live_rank_data().get('message_id'): return await interaction.followup.send("❌ Ya existe un ranking activo.")
        
        message = await interaction.channel.send(embed=discord.Embed(title="Cargando Ranking..."))
        self.save_live_rank_data({'channel_id': message.channel.id, 'message_id': message.id})
        await interaction.followup.send("✅ Ranking configurado.")

    @rank_group.command(name="clear", description="[ADMIN] Borra todo el ranking.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    @app_commands.describe(confirmacion="Escribe 'CONFIRM' para borrar.")
    async def clear_rank(self, interaction: discord.Interaction, confirmacion: str):
        if confirmacion.upper() != 'CONFIRM': return await interaction.response.send_message("❌ Confirmación fallida.", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        archive_name = f"manual_clear_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.db"
        await self.reset_database_for_new_season(archive_name)
        await interaction.followup.send(f"✅ Ranking borrado. Respaldo: `{archive_name}`")

    @app_commands.command(name="points", description="Ajuste manual de puntos.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def manual_points(self, interaction: discord.Interaction, usuario: discord.Member, puntos: int, motivo: str = "Ajuste manual"):
        await self.add_points(interaction, str(usuario.id), puntos, 'manual')
        await interaction.response.send_message(f"✅ Puntos ajustados para {usuario.mention}.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Puntos(bot))