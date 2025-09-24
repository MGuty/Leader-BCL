import discord
from discord.ext import commands
import json
import os
import traceback

# --- Emojis Comunes ---
PENDING_EMOJI = '📝'
APPROVE_EMOJI = '✅'
DENY_EMOJI = '❌'

# Esta clase es la "plantilla" y debe heredar de commands.Cog
class BaseModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot, cog_name: str):
        self.bot = bot
        self.cog_name = cog_name
        self.pending_file = f'pending_{cog_name}.json'
        self.judged_file = f'judged_{cog_name}.json'
        self.pending_submissions = self.load_data(self.pending_file)
        self.judged_submissions = self.load_data(self.judged_file)
        self.admin_role_id = int(os.getenv("ADMIN_ROLE_ID", 0))
        self.log_channel_id = int(os.getenv("BOT_AUDIT_LOGS_CHANNEL_ID", 0))

    def load_data(self, filename):
        """Carga datos desde un archivo JSON, devolviendo un diccionario vacío si falla."""
        try:
            with open(filename, 'r') as f: return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError): return {}

    def save_data(self, data, filename):
        """Guarda datos en un archivo JSON con formato legible."""
        with open(filename, 'w') as f: json.dump(data, f, indent=4)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """
        Listener central que maneja las reacciones para todos los cogs de moderación.
        """
        # 1. Comprueba si la reacción ocurrió en un canal relevante para el cog hijo.
        if not self.is_relevant_channel(payload.channel_id):
            return

        # 2. Ignora a los bots y a los miembros sin el rol de administrador.
        if payload.member.bot or not any(role.id == self.admin_role_id for role in payload.member.roles): return
        
        message_id_str = str(payload.message_id)
        emoji = str(payload.emoji)
        
        # 3. Ignora emojis que no son de aprobación o rechazo.
        if emoji not in [APPROVE_EMOJI, DENY_EMOJI]: return
        
        # 4. Comprueba si el mensaje está en la base de datos de pendientes o ya juzgados.
        is_pending = message_id_str in self.pending_submissions
        is_judged = message_id_str in self.judged_submissions
        if not is_pending and not is_judged: return

        # 5. Lógica para eliminar todas las reacciones opuestas de otros administradores.
        opposite_emoji = DENY_EMOJI if emoji == APPROVE_EMOJI else APPROVE_EMOJI
        try:
            channel = self.bot.get_channel(payload.channel_id)
            if channel:
                message = await channel.fetch_message(payload.message_id)
                for reaction in message.reactions:
                    if str(reaction.emoji) == opposite_emoji:
                        async for user in reaction.users():
                            if not user.bot:
                                await message.remove_reaction(opposite_emoji, user)
                        break
        except (discord.NotFound, discord.Forbidden):
            print(f"No se pudo eliminar la reacción opuesta del mensaje {message_id_str}.")

        # 6. Lógica principal de aprobación y rechazo
        puntos_cog = self.bot.get_cog('Puntos')
        
        if is_pending:
            submission = self.pending_submissions.pop(message_id_str)
            self.save_data(self.pending_submissions, self.pending_file)
            
            if emoji == APPROVE_EMOJI:
                if puntos_cog:
                    await self._award_points(payload, submission)
                submission['status'] = 'approved'
                if 'points' in submission:
                    submission['points_base'] = submission['points']
                self.judged_submissions[message_id_str] = submission
                self.save_data(self.judged_submissions, self.judged_file)
                await self.send_log_message(payload, submission, self.cog_name.capitalize(), "aprobado")
            
            elif emoji == DENY_EMOJI:
                submission['status'] = 'denied'
                self.judged_submissions[message_id_str] = submission
                self.save_data(self.judged_submissions, self.judged_file)
                await self.send_log_message(payload, submission, self.cog_name.capitalize(), "rechazado")
        
        elif is_judged:
            submission = self.judged_submissions[message_id_str]
            old_status = submission.get('status')

            if (emoji == APPROVE_EMOJI and old_status == 'approved') or (emoji == DENY_EMOJI and old_status == 'denied'):
                return

            if emoji == APPROVE_EMOJI and old_status == 'denied':
                if puntos_cog:
                    await self._award_points(payload, submission)
                submission['status'] = 'approved'
                self.judged_submissions[message_id_str] = submission
                self.save_data(self.judged_submissions, self.judged_file)
                await self.log_decision_change(payload, self.cog_name.capitalize(), "APROBADO")

            elif emoji == DENY_EMOJI and old_status == 'approved':
                if puntos_cog:
                    await self._revert_points(payload, submission)
                submission['status'] = 'denied'
                self.judged_submissions[message_id_str] = submission
                self.save_data(self.judged_submissions, self.judged_file)
                await self.log_decision_change(payload, self.cog_name.capitalize(), "RECHAZADO")

    # --- Métodos abstractos (deben ser implementados por los cogs hijos) ---
    def is_relevant_channel(self, channel_id: int) -> bool:
        """Comprueba si un canal es relevante para este módulo específico."""
        raise NotImplementedError("Cada cog debe implementar 'is_relevant_channel'")

    async def _award_points(self, payload, submission):
        """Define la lógica específica para otorgar puntos."""
        raise NotImplementedError("Cada cog debe implementar su propia lógica para dar puntos.")

    async def _revert_points(self, payload, submission):
        """Define la lógica específica para revertir puntos."""
        raise NotImplementedError("Cada cog debe implementar su propia lógica para quitar puntos.")

    # --- Funciones de Logs (Comunes a todos) ---
    async def send_log_message(self, payload, submission, type_str, action_str):
        log_channel = self.bot.get_channel(self.log_channel_id)
        if not log_channel: return
        
        message_link = f"https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}"
        
        if action_str == "aprobado":
            points = submission.get('points_base', submission.get('points', 'N/A'))
            unique_ally_mentions = [f"<@{uid}>" for uid in set(submission['allies'])]
            log_text = f"{APPROVE_EMOJI} **{type_str}** {action_str} por {payload.member.mention}. [Ir al envío]({message_link})"
            
            # Mensaje de log inteligente: genérico para puntos variables, específico para puntos fijos.
            if self.cog_name in ['koth']: 
                 log_text += f"\n> Se han otorgado puntos a: {', '.join(unique_ally_mentions)}."
            else:
                 log_text += f"\n> Se han otorgado **`{points}`** puntos por mención a: {', '.join(unique_ally_mentions)}."
            await log_channel.send(log_text)
        else: # Rechazado
            await log_channel.send(f"{DENY_EMOJI} **{type_str}** {action_str} por {payload.member.mention}. [Ir al envío]({message_link})")

    async def log_decision_change(self, payload, type_str, new_status_str):
        log_channel = self.bot.get_channel(self.log_channel_id)
        if not log_channel: return
        message_link = f"https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}"
        await log_channel.send(f"🔄 Decisión cambiada a **{new_status_str}** por {payload.member.mention} para un envío de **{type_str}**. [Ir al envío]({message_link})")