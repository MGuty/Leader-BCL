import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
import json
import os
from datetime import datetime, timezone
import shutil

# --- CONFIGURACIÓN ---
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

    # --- LÓGICA DE RANKING ---
    async def build_ranking_embed(self, guild: discord.Guild):
        """Construye el ranking sumando puntos y contando capturas."""
        try:
            with sqlite3.connect(DB_FILE) as con:
                cur = con.cursor()
                # Modificamos la query para incluir COUNT(*) que son las capturas
                cur.execute("""
                    SELECT user_id, SUM(points) as total, COUNT(*) as capturas
                    FROM puntuaciones WHERE guild_id = ? 
                    GROUP BY user_id HAVING total != 0 
                    ORDER BY total DESC LIMIT 50
                """, (guild.id,))
                data = cur.fetchall()
            
            if not data: return None

            rank_lines = []
            header = f"{'Pos':<4} {'Usuario':<16} {'Pts':>6} {'(Caps)':>6}"
            rank_lines.append(header)
            rank_lines.append("-" * len(header))

            for i, (user_id, total_points, num_capturas) in enumerate(data):
                medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i + 1}."
                member = guild.get_member(int(user_id))
                name = member.display_name if member else f"ID:{user_id}"
                
                # Formato: 1.  NombreJugador    1500   (25)
                rank_lines.append(f"{medal:<4} {name[:15]:<16} {str(total_points):>6} ({num_capturas})")

            embed = discord.Embed(
                title=f"🏆 Ranking de Temporada - {guild.name} 🏆",
                description=f"```\n" + "\n".join(rank_lines) + "\n```",
                color=discord.Color.gold(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_footer(text="Se actualiza automáticamente cada 15 min")
            return embed
        except Exception as e:
            print(f"❌ Error construyendo ranking: {e}")
            return None

    # --- TAREA DE ACTUALIZACIÓN AUTOMÁTICA ---
    @tasks.loop(minutes=15)
    async def update_live_rank_task(self):
        """Busca el mensaje guardado y lo actualiza."""
        try:
            if not os.path.exists(LIVE_RANKING_FILE): return
            
            with open(LIVE_RANKING_FILE, 'r') as f:
                config = json.load(f)
            
            channel = self.bot.get_channel(config['channel_id'])
            if not channel: return
            
            message = await channel.fetch_message(config['message_id'])
            new_embed = await self.build_ranking_embed(message.guild)
            
            if new_embed:
                await message.edit(embed=new_embed)
        except Exception as e:
            print(f"⚠️ No se pudo actualizar el ranking automático: {e}")

    # --- COMANDOS /rank ---
    rank_group = app_commands.Group(name="rank", description="Gestión del ranking.")

    @rank_group.command(name="ver", description="Muestra el Top 50 actual.")
    async def show_rank(self, interaction: discord.Interaction):
        await interaction.response.defer()
        embed = await self.build_ranking_embed(interaction.guild)
        await interaction.followup.send(embed=embed if embed else "No hay datos aún.")

    @rank_group.command(name="setup_live", description="Crea un ranking que se actualiza solo.")
    @app_commands.checks.has_role(int(os.getenv("ADMIN_ROLE_ID", 0)))
    async def setup_live(self, interaction: discord.Interaction):
        """Crea el mensaje inicial y guarda su ID para actualizarlo luego."""
        await interaction.response.defer(ephemeral=True)
        
        embed = await self.build_ranking_embed(interaction.guild)
        if not embed:
            return await interaction.followup.send("❌ Necesitas al menos un envío validado para iniciar el ranking.")

        # Enviamos el mensaje al canal actual
        message = await interaction.channel.send(embed=embed)
        
        # Guardamos la ubicación del mensaje en el JSON
        config = {
            'guild_id': interaction.guild_id,
            'channel_id': interaction.channel_id,
            'message_id': message.id
        }
        
        with open(LIVE_RANKING_FILE, 'w') as f:
            json.dump(config, f, indent=4)
            
        await interaction.followup.send(f"✅ Ranking Live configurado en este canal. Se actualizará cada 15 minutos.")

    async def add_points(self, interaction_or_payload, user_id: str, amount: int, category: str):
        """Añade puntos a la DB (llamado por otros módulos)."""
        try:
            with sqlite3.connect(DB_FILE) as con:
                cur = con.cursor()
                guild_id = interaction_or_payload.guild_id
                cur.execute("INSERT INTO puntuaciones (user_id, guild_id, category, points, timestamp) VALUES (?, ?, ?, ?, ?)",
                            (int(user_id), guild_id, category, amount, datetime.now(timezone.utc)))
                con.commit()
        except Exception as e:
            print(f"❌ Error al añadir puntos: {e}")

async def setup(bot):
    await bot.add_cog(Puntos(bot))