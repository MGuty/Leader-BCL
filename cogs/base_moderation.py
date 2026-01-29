# base_moderation.py
import discord
from discord.ext import commands
import json
import os
import traceback

# --- Emojis ---
PENDING_EMOJI = '📝'
APPROVE_EMOJI = '✅'
DENY_EMOJI = '❌'
FIRE_EMOJI = '🔥'  # Multiplicador x2
MOON_EMOJI = '🌕'  # Multiplicador x1.5

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
        """Carga datos desde un archivo JSON."""
        try:
            with open(filename, 'r') as f: return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError): return {}

    def save_data(self, data, filename):
        """Guarda datos en un archivo JSON."""
        with open(filename, 'w') as f: json.dump(data, f, indent=4)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """
        Listener central que maneja las reacciones y multiplicadores.
        """
        if not self.is_relevant_channel(payload.channel_id):
            return

        # Solo administradores pueden procesar
        if payload.member.bot or not any(role.id == self.admin_role_id for role in payload.member.roles): 
            return
        
        message_id_str = str(payload.message_id)
        emoji = str(payload.emoji)
        
        # Definir grupos de emojis
        approve_emojis = [APPROVE_EMOJI, FIRE_EMOJI, MOON_EMOJI]
        all_status_emojis = approve_emojis + [DENY_EMOJI]

        if emoji not in all_status_emojis: 
            return
        
        is_pending = message_id_str in self.pending_submissions
        is_judged = message_id_str in self.judged_submissions
        
        if not is_pending and not is_judged: 
            return

        # 1. Determinar el multiplicador basado en el emoji
        multiplier = 1.0
        if emoji == FIRE_EMOJI: multiplier = 2.0
        elif emoji == MOON_EMOJI: multiplier = 1.5

        # 2. Limpieza de reacciones opuestas (Si pones ✅, quita ❌, 🔥 y 🌕)
        try:
            channel = self.bot.get_channel(payload.channel_id)
            if channel:
                message = await channel.fetch_message(payload.message_id)
                for reaction in message.reactions:
                    react_str = str(reaction.emoji)
                    if react_str in all_status_emojis and react_str != emoji:
                        async for user in reaction.users():
                            if not user.bot:
                                await message.remove_reaction(react_str, user)
        except (discord.NotFound, discord.Forbidden):
            pass

        puntos_cog = self.bot.get_cog('Puntos')
        
        # CASO A: El envío está pendiente
        if is_pending:
            submission = self.pending_submissions.pop(message_id_str)
            submission['multiplier'] = multiplier # Guardamos el multiplicador usado
            
            if emoji in approve_emojis:
                if puntos_cog:
                    await self._award_points(payload, submission, multiplier)
                
                submission['status'] = 'approved'
                if 'points' in submission:
                    submission['points_base'] = submission['points']
                
                self.judged_submissions[message_id_str] = submission
                self.save_data(self.pending_submissions, self.pending_file)
                self.save_data(self.judged_submissions, self.judged_file)
                await self.send_log_message(payload, submission, self.cog_name.capitalize(), "aprobado", multiplier)
            
            elif emoji == DENY_EMOJI:
                submission['status'] = 'denied'
                self.judged_submissions[message_id_str] = submission
                self.save_data(self.pending_submissions, self.pending_file)
                self.save_data(self.judged_submissions, self.judged_file)
                await self.send_log_message(payload, submission, self.cog_name.capitalize(), "rechazado")
        
        # CASO B: El envío ya fue juzgado (cambio de decisión)
        elif is_judged:
            submission = self.judged_submissions[message_id_str]
            old_status = submission.get('status')
            old_multiplier = submission.get('multiplier', 1.0)

            # Si reaccionan con el mismo estado y mismo multiplicador, no hacer nada
            if emoji == DENY_EMOJI and old_status == 'denied': return
            if emoji in approve_emojis and old_status == 'approved' and multiplier == old_multiplier: return

            # Si cambia de Denegado a Aprobado (o cambia el multiplicador de aprobación)
            if emoji in approve_emojis:
                if puntos_cog:
                    # Si ya estaba aprobado, primero revertimos los puntos viejos
                    if old_status == 'approved':
                        await self._revert_points(payload, submission)
                    # Otorgamos con el nuevo multiplicador
                    await self._award_points(payload, submission, multiplier)
                
                submission['status'] = 'approved'
                submission['multiplier'] = multiplier
                self.save_data(self.judged_submissions, self.judged_file)
                await self.log_decision_change(payload, self.cog_name.capitalize(), f"APROBADO (x{multiplier})")

            # Si cambia de Aprobado a Denegado
            elif emoji == DENY_EMOJI and old_status == 'approved':
                if puntos_cog:
                    await self._revert_points(payload, submission)
                
                submission['status'] = 'denied'
                # Mantenemos el multiplicador en el registro por si se vuelve a activar
                self.save_data(self.judged_submissions, self.judged_file)
                await self.log_decision_change(payload, self.cog_name.capitalize(), "RECHAZADO")

    # --- Métodos abstractos (Deben actualizarse en los Cogs hijos) ---
    def is_relevant_channel(self, channel_id: int) -> bool:
        raise NotImplementedError()

    async def _award_points(self, payload, submission, multiplier: float):
        raise NotImplementedError()

    async def _revert_points(self, payload, submission):
        raise NotImplementedError()

    # --- Logs ---
    async def send_log_message(self, payload, submission, type_str, action_str, multiplier=1.0):
        log_channel = self.bot.get_channel(self.log_channel_id)
        if not log_channel: return
        
        message_link = f"https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}"
        
        if action_str == "aprobado":
            points_base = submission.get('points_base', submission.get('points', 0))
            total_points = int(points_base * multiplier)
            unique_ally_mentions = [f"<@{uid}>" for uid in set(submission['allies'])]
            
            # Icono dinámico según multiplicador
            icon = APPROVE_EMOJI
            if multiplier == 2.0: icon = FIRE_EMOJI
            elif multiplier == 1.5: icon = MOON_EMOJI

            mult_text = f" (Multiplicador x{multiplier})" if multiplier != 1.0 else ""
            
            log_text = f"{icon} **{type_str}** aprobado por {payload.member.mention}. [Ir al envío]({message_link})"
            log_text += f"\n> Se han otorgado **`{total_points}`** puntos{mult_text} a: {', '.join(unique_ally_mentions)}."
            await log_channel.send(log_text)
        else:
            await log_channel.send(f"{DENY_EMOJI} **{type_str}** rechazado por {payload.member.mention}. [Ir al envío]({message_link})")

    async def log_decision_change(self, payload, type_str, new_status_str):
        log_channel = self.bot.get_channel(self.log_channel_id)
        if not log_channel: return
        message_link = f"https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}"
        await log_channel.send(f"🔄 Decisión cambiada a **{new_status_str}** por {payload.member.mention} para un envío de **{type_str}**. [Ir al envío]({message_link})")