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
        await self.bot.wait_until_ready()
        print(f"[{datetime.now()}] Creando snapshot del ranking...")
        try:
            con = sqlite3.connect(DB_FILE)
            cur = con.cursor()
            cur.execute("SELECT user_id, SUM(points) as total_points FROM puntuaciones GROUP BY user_id")
            ranking_data = cur.fetchall()
            con.close()
            snapshot = {str(row[0]): row[1] for row in ranking_data}
            with open(SNAPSHOT_FILE, 'w') as f:
                json.dump(snapshot, f)
            print("Snapshot del ranking creado exitosamente.")
        except Exception as e:
            print(f"Error al crear el snapshot del ranking: {e}")

    @tasks.loop(minutes=15)
    async def update_live_rank_task(self):
        live_rank_data = self.load_live_rank_data()
        if not live_rank_data.get('message_id'):
            return

        try:
            channel = self.bot.get_channel(live_rank_data['channel_id']) or await self.bot.fetch_channel(live_rank_data['channel_id'])
            message = await channel.fetch_message(live_rank_data['message_id'])
            new_embed = await self.build_ranking_embed(message.guild)
            if new_embed:
                await message.edit(embed=new_embed)
                print(f"[{datetime.now()}] Ranking automático actualizado.")
        except (discord.NotFound, discord.Forbidden):
            print("No se pudo encontrar el mensaje del ranking automático. Desactivando...")
            self.save_live_rank_data({})
            
    @update_live_rank_task.before_loop
    async def before_update_live_rank(self):
        await self.bot.wait_until_ready()

    async def add_points(self, interaction_or_payload, user_id: str, amount: int, category: str):
        try:
            con = sqlite3.connect(DB_FILE)
            cur = con.cursor()
            guild_id = interaction_or_payload.guild_id
            cur.execute("INSERT INTO puntuaciones (user_id, guild_id, category, points, timestamp) VALUES (?, ?, ?, ?, ?)",
                        (int(user_id), guild_id, category, amount, datetime.now(timezone.utc)))
            con.commit()
            con.close()
        except Exception as e:
            print(f"Error al añadir puntos: {e}")
            traceback.print_exc()

    async def get_ranked_player_ids(self, guild_id: int):
        try:
            con = sqlite3.connect(DB_FILE)
            cur = con.cursor()
            cur.execute("SELECT user_id FROM puntuaciones WHERE guild_id = ? GROUP BY user_id HAVING SUM(points) != 0 ORDER BY SUM(points) DESC", (guild_id,))
            ranked_ids = [row[0] for row in cur.fetchall()]
            con.close()
            return ranked_ids
        except Exception as e:
            print(f"Error al obtener ranking para reparto: {e}")
            return []

    async def reset_database_for_new_season(self, archive_db_name: str):
        print(f"Iniciando reinicio de base de datos para nueva temporada...")
        
        if os.path.exists(DB_FILE):
            try:
                shutil.copyfile(DB_FILE, archive_db_name)
                print(f"Copia de seguridad de la base de datos creada como '{archive_db_name}'.")
            except Exception as e:
                print(f"Error al archivar la base de datos: {e}")
        
        try:
            con = sqlite3.connect(DB_FILE)
            cur = con.cursor()
            cur.execute("DELETE FROM puntuaciones")
            cur.execute("VACUUM")
            con.commit()
            con.close()
            print("Todos los registros de la tabla 'puntuaciones' han sido eliminados.")
        except Exception as e:
            print(f"Error al limpiar la tabla de puntuaciones: {e}")

        if os.path.exists(SNAPSHOT_FILE):
            os.remove(SNAPSHOT_FILE)
            print("Snapshot de ranking anterior eliminado.")
        
        print("Reinicio de base de datos completado.")

    async def build_ranking_embed(self, guild: discord.Guild):
        con = sqlite3.connect(DB_FILE)
        cur = con.cursor()
        cur.execute("SELECT user_id, SUM(points) as total_points FROM puntuaciones WHERE guild_id = ? GROUP BY user_id HAVING SUM(points) != 0 ORDER BY total_points DESC LIMIT 50", (guild.id,))
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

    rank_group = app_commands.Group(name="rank", description="Comandos relacionados con el ranking de puntos.")

    @rank_group.command(name="ver", description="Muestra la tabla de clasificación de puntos actual.")
    async def show_rank(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        embed = await self.build_ranking_embed(interaction.guild)
        if embed:
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send("Aún no se ha registrado ningún punto en este servidor.")

    @rank_group.command(name="setup", description="Configura un mensaje de ranking que se actualiza automáticamente.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def setup_rank(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        live_rank_data = self.load_live_rank_data()
        if live_rank_data.get('message_id'):
            return await interaction.followup.send("❌ Ya hay un ranking automático configurado. Usa `/rank stop` primero.")
            
        initial_embed = discord.Embed(title="🏆 Ranking Automático 🏆", description="Cargando ranking...", color=discord.Color.light_grey())
        message = await interaction.channel.send(embed=initial_embed)
        
        self.save_live_rank_data({'channel_id': message.channel.id, 'message_id': message.id})
        
        final_embed = await self.build_ranking_embed(interaction.guild)
        if final_embed:
            await message.edit(embed=final_embed)
            
        await interaction.followup.send(f"✅ ¡Ranking automático configurado! Se actualizará cada 15 minutos.")

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
            pass
        
        self.save_live_rank_data({})
        await interaction.followup.send("✅ Ranking automático detenido y mensaje eliminado.")

    @app_commands.command(name="points", description="Añade o resta puntos a un usuario manualmente.")
    @app_commands.describe(usuario="El usuario a modificar.", puntos="La cantidad (negativa para restar).", motivo="La razón del ajuste.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def manual_points(self, interaction: discord.Interaction, usuario: discord.Member, puntos: int, motivo: str = "Ajuste manual"):
        await self.add_points(interaction, str(usuario.id), puntos, 'manual')
        
        log_channel = self.bot.get_channel(BOT_AUDIT_LOGS_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(title="⚙️ Ajuste Manual de Puntos", color=discord.Color.blue() if puntos > 0 else discord.Color.dark_red())
            embed.add_field(name="Administrador", value=interaction.user.mention, inline=True)
            embed.add_field(name="Usuario Afectado", value=usuario.mention, inline=True)
            embed.add_field(name="Cantidad", value=f"**{puntos:+}** puntos", inline=True)
            if motivo != "Ajuste manual":
                embed.add_field(name="Motivo", value=motivo, inline=False)
            embed.set_footer(text=f"ID de Usuario: {usuario.id}")
            embed.timestamp = datetime.now(timezone.utc)
            await log_channel.send(embed=embed)
            
        await interaction.response.send_message(f"✅ Se han ajustado los puntos de {usuario.mention} en {puntos:+} puntos.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Puntos(bot))