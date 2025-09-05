# cogs/puntos.py
import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
import json
from datetime import datetime, timezone
import os
import traceback

# --- CONFIGURACIÓN ---
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID"))
BOT_AUDIT_LOGS_CHANNEL_ID = int(os.getenv("BOT_AUDIT_LOGS_CHANNEL_ID"))
DB_FILE = 'leaderboard.db'
SNAPSHOT_FILE = 'ranking_snapshot.json'

class Puntos(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._initialize_database()
        self.snapshot_ranking_task.start()

    def cog_unload(self):
        self.snapshot_ranking_task.cancel()

    def _initialize_database(self):
        """Crea la tabla de la base de datos si no existe."""
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
            print(f"Error al inicializar la base de datos: {e}")

    @tasks.loop(hours=24)
    async def snapshot_ranking_task(self):
        """Toma una instantánea del ranking y la guarda en un archivo JSON."""
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

    async def add_points(self, interaction_or_payload, user_id: str, amount: int, category: str):
        """Añade una fila a la base de datos con los puntos otorgados."""
        if amount == 0:
            return
        
        try:
            con = sqlite3.connect(DB_FILE)
            cur = con.cursor()
            guild_id = interaction_or_payload.guild_id
            
            cur.execute(
                "INSERT INTO puntuaciones (user_id, guild_id, category, points, timestamp) VALUES (?, ?, ?, ?, ?)",
                (int(user_id), guild_id, category, amount, datetime.now(timezone.utc))
            )
            
            con.commit()
            con.close()
            print(f"Se registraron {amount} puntos para el usuario {user_id} en la categoría '{category}'.")
        except Exception as e:
            print(f"Error al añadir puntos a la base de datos: {e}")

    @app_commands.command(name="rank", description="Muestra la tabla de clasificación de puntos completa.")
    async def show_rank(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        try:
            with open(SNAPSHOT_FILE, 'r') as f: previous_ranking_snapshot = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError): previous_ranking_snapshot = {}
        
        con = sqlite3.connect(DB_FILE)
        cur = con.cursor()
        cur.execute("SELECT user_id, SUM(points) as total_points FROM puntuaciones WHERE guild_id = ? GROUP BY user_id HAVING SUM(points) != 0 ORDER BY total_points DESC", (interaction.guild.id,))
        current_ranking_data = cur.fetchall()
        con.close()

        if not current_ranking_data:
            await interaction.followup.send("Aún no se ha registrado ningún punto en este servidor.")
            return

        previous_ranks = {user_id: i for i, (user_id, _) in enumerate(sorted(previous_ranking_snapshot.items(), key=lambda item: item[1], reverse=True))}
        
        full_rank_list_text = []
        for i, (user_id, total_points) in enumerate(current_ranking_data):
            current_pos = i + 1
            previous_pos = previous_ranks.get(str(user_id))
            rank_change_emoji = ""
            if previous_pos is not None:
                if current_pos < previous_pos + 1: rank_change_emoji = "⬆️"
                elif current_pos > previous_pos + 1: rank_change_emoji = "⬇️"
            else: rank_change_emoji = "🆕"
            
            full_rank_list_text.append(f"**{current_pos}.** <@{user_id}> - `{total_points}` puntos {rank_change_emoji}")
        
        description_text = "\n".join(full_rank_list_text)
        
        if len(description_text) > 4000:
            description_text = description_text[:4000]
            last_newline = description_text.rfind('\n')
            if last_newline != -1:
                description_text = description_text[:last_newline]
            description_text += "\n\n... y más (lista demasiado larga para mostrar completamente)."

        embed = discord.Embed(
            title="🏆 Ranking de Puntos Completo 🏆",
            description=description_text or "Nadie ha puntuado aún.",
            color=discord.Color.gold()
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="points", description="Añade o resta puntos a un usuario manualmente.")
    @app_commands.describe(usuario="El usuario al que quieres modificar los puntos.", puntos="La cantidad (negativa para restar).", motivo="La razón del ajuste manual (opcional).")
    async def manual_points(self, interaction: discord.Interaction, usuario: discord.Member, puntos: int, motivo: str = "Ajuste manual"):
        # Verificación de rol manual para asegurar que el comando se registre
        if not any(role.id == ADMIN_ROLE_ID for role in interaction.user.roles):
            return await interaction.response.send_message("❌ No tienes el rol de administrador necesario para usar este comando.", ephemeral=True)
            
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

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        # Este manejador de errores es para el comando /rank que no tiene chequeo manual
        # No es estrictamente necesario para /points ya que tiene su propio chequeo, pero es una buena práctica tenerlo
        if isinstance(error, app_commands.CheckFailure):
            await interaction.response.send_message("❌ No tienes permiso para usar este comando.", ephemeral=True)
        else:
            if not interaction.response.is_done():
                await interaction.response.send_message("Ocurrió un error inesperado.", ephemeral=True)
            else:
                await interaction.followup.send("Ocurrió un error inesperado.", ephemeral=True)
            print(f"Error en un comando de Puntos por {interaction.user}: {error}")
            traceback.print_exc()

async def setup(bot):
    await bot.add_cog(Puntos(bot))