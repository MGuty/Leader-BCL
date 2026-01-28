import discord
from discord import app_commands
from discord.ext import commands
import os
import json

# Clase auxiliar para simular el payload de una reacción
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
        self.admin_role_id = int(os.getenv("ADMIN_ROLE_ID", 0))
        
        # --- MENÚS CONTEXTUALES (Botón derecho sobre mensajes/usuarios) ---
        self.ctx_menu_reset = app_commands.ContextMenu(
            name='Resetear Envío',
            callback=self.reset_submission,
        )
        self.bot.tree.add_command(self.ctx_menu_reset)

    async def reset_submission(self, interaction: discord.Interaction, message: discord.Message):
        """Mueve un envío juzgado de vuelta a pendientes y resta los puntos."""
        # Verificación de seguridad por rol
        if not any(role.id == self.admin_role_id for role in interaction.user.roles):
            return await interaction.response.send_message("❌ No tienes permisos de administrador.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        
        # Identificar el módulo (ataque, defenses, etc.) por el nombre del canal
        ch_name = message.channel.name.lower()
        cog_name = None
        if ch_name.startswith('ataque-'): cog_name = 'Ataque'
        elif ch_name.startswith('defenses-'): cog_name = 'Defensa'
        elif ch_name.startswith('interserver-'): cog_name = 'Interserver'
        elif ch_name.startswith('koth-'): cog_name = 'KOTH'

        if not cog_name:
            return await interaction.followup.send("❌ Este canal no pertenece a un módulo de puntos.")

        cog = self.bot.get_cog(cog_name)
        if not cog:
            return await interaction.followup.send(f"❌ El módulo {cog_name} no está cargado.")

        msg_id = str(message.id)
        if msg_id not in cog.judged_submissions:
            return await interaction.followup.send("❌ Este mensaje no está en la lista de envíos juzgados.")

        try:
            # Recuperamos el envío
            submission = cog.judged_submissions.pop(msg_id)
            
            # --- CORRECCIÓN CRÍTICA: Multiplicador sincronizado ---
            # Ahora pasamos el multiplicador guardado (o 1.0 si no existe) para que coincida con la nueva firma
            mult = submission.get('multiplier', 1.0)
            await cog._revert_points(MockPayload(message, interaction.user), submission, multiplier=mult)
            
            # Devolvemos el envío a pendientes y limpiamos reacciones
            cog.pending_submissions[msg_id] = {
                'points': submission['points'],
                'allies': submission['allies'],
                'channel_id': message.channel.id
            }
            
            cog.save_data(cog.pending_submissions, cog.pending_file)
            cog.save_data(cog.judged_submissions, cog.judged_file)
            
            await message.clear_reactions()
            await message.add_reaction('📝') # Emoji de pendiente
            
            await interaction.followup.send(f"✅ Envío reseteado. Los puntos ({int(submission['points'] * mult)}) han sido restados.")
            
        except Exception as e:
            await interaction.followup.send(f"❌ Error al resetear: {str(e)}")

    # --- COMANDO DE SINCRONIZACIÓN MANUAL ---
    @commands.command()
    @commands.is_owner() # Solo tú como dueño del bot puedes usar esto
    async def sync(self, ctx):
        """Sincroniza los comandos de barra manualmente con el VPS."""
        try:
            fmt = await self.bot.tree.sync()
            await ctx.send(f"✅ Se han sincronizado {len(fmt)} comandos en este servidor.")
        except Exception as e:
            await ctx.send(f"❌ Error de sincronización: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))