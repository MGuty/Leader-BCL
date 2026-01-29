# cogs/defensa.py
import discord
from discord.ext import commands
import re
import os
import json
import traceback

# --- CONFIGURACIÓN ---
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID"))
BOT_AUDIT_LOGS_CHANNEL_ID = int(os.getenv("BOT_AUDIT_LOGS_CHANNEL_ID"))

# --- Emojis y Archivos de Datos ---
PENDING_EMOJI = '📝'
APPROVE_EMOJI = '✅'
DENY_EMOJI = '❌'
BOOST_FIRE_EMOJI = '🔥'  # Multiplicador x2
BOOST_MOON_EMOJI = '🌕'  # Multiplicador x1.5
PENDING_DEFENSES_FILE = 'pending_defenses.json'
JUDGED_DEFENSES_FILE = 'judged_defenses.json'

# --- Tabla de Puntos ---
DEFENSE_POINTS = [
    [0,    120,   150,   180,   210,   240], # 1 Aliado
    [0,     90,   120,   150,   180,   210], # 2 Aliados
    [0,     60,    90,   120,   150,   180], # 3 Aliados
    [0,     15,    60,    90,   120,   150], # 4 Aliados
    [0,      5,    15,    60,    90,   120]  # 5 Aliados
]

class Defensa(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pending_defenses = self.load_data(PENDING_DEFENSES_FILE)
        self.judged_defenses = self.load_data(JUDGED_DEFENSES_FILE)

    def load_data(self, filename):
        try:
            with open(filename, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def save_data(self, data, filename):
        with open(filename, 'w') as f:
            json.dump(data, f, indent=4)

    async def process_submission(self, message: discord.Message):
        """Valida y registra un envío de Defensa."""
        for reaction in message.reactions:
            if reaction.me:
                return False

        all_mentions_in_text = re.findall(r'<@!?(\d+)>', message.content)
        if not message.attachments or not all_mentions_in_text or not any(att.content_type.startswith('image/') for att in message.attachments):
            return False

        num_allies = len(all_mentions_in_text)
        num_enemies = 0
        match = re.search(r'vs(\d+)', message.channel.name.lower())
        if match:
            num_enemies = int(match.group(1))

        if not (1 <= num_allies <= 5 and 0 <= num_enemies <= 5):
            return False
            
        points_to_award = DEFENSE_POINTS[num_allies - 1][num_enemies]
        if points_to_award == 0:
            await message.add_reaction('🤷')
            return False
        
        self.pending_defenses[str(message.id)] = {
            'points': points_to_award, 
            'base_points': points_to_award, # Guardamos el original
            'allies': all_mentions_in_text,
            'multiplier_applied': False,
            'multiplier_emoji': None
        }
        self.save_data(self.pending_defenses, PENDING_DEFENSES_FILE)
        await message.add_reaction(PENDING_EMOJI)
        return True

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.channel.name.lower().startswith('defenses-'):
            return
        await self.process_submission(message)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.member.bot or not any(role.id == ADMIN_ROLE_ID for role in payload.member.roles):
            return

        message_id_str = str(payload.message_id)
        emoji = str(payload.emoji)
        
        # --- LÓGICA DE MULTIPLICADORES ---
        if emoji in [BOOST_FIRE_EMOJI, BOOST_MOON_EMOJI]:
            if message_id_str in self.pending_defenses:
                submission = self.pending_defenses[message_id_str]
                if not submission.get('multiplier_applied', False):
                    multiplier = 2 if emoji == BOOST_FIRE_EMOJI else 1.5
                    submission['points'] = int(submission['points'] * multiplier)
                    submission['multiplier_applied'] = True
                    submission['multiplier_emoji'] = emoji
                    self.save_data(self.pending_defenses, PENDING_DEFENSES_FILE)
                    
                    channel = self.bot.get_channel(payload.channel_id)
                    msg = await channel.fetch_message(payload.message_id)
                    await msg.add_reaction(emoji)
            return

        if emoji not in [APPROVE_EMOJI, DENY_EMOJI]:
            return
        
        is_pending = message_id_str in self.pending_defenses
        is_judged = message_id_str in self.judged_defenses
        if not is_pending and not is_judged:
            return

        original_channel = self.bot.get_channel(payload.channel_id)
        original_message = None
        if original_channel:
            try:
                original_message = await original_channel.fetch_message(payload.message_id)
                # Limpiar reacción opuesta
                opposite_emoji = DENY_EMOJI if emoji == APPROVE_EMOJI else APPROVE_EMOJI
                for reaction in original_message.reactions:
                    if str(reaction.emoji) == opposite_emoji:
                        async for user in reaction.users():
                            if not user.bot:
                                await original_message.remove_reaction(opposite_emoji, user)
                        break
            except Exception:
                pass
        
        puntos_cog = self.bot.get_cog('Puntos')

        if is_pending:
            submission = self.pending_defenses[message_id_str]
            
            # --- SI SE RECHAZA: LIMPIAR MULTIPLICADORES ---
            if emoji == DENY_EMOJI:
                submission['points'] = submission.get('base_points', submission['points'])
                submission['multiplier_applied'] = False
                submission['multiplier_emoji'] = None
                
                # Quitar reacciones de bono del bot si existen
                if original_message:
                    try:
                        for b_emoji in [BOOST_FIRE_EMOJI, BOOST_MOON_EMOJI]:
                            await original_message.remove_reaction(b_emoji, self.bot.user)
                    except: pass

            # Procesar el cambio de estado
            self.pending_defenses.pop(message_id_str)
            self.save_data(self.pending_defenses, PENDING_DEFENSES_FILE)
            
            if emoji == APPROVE_EMOJI:
                if puntos_cog:
                    for user_id in submission['allies']:
                        await puntos_cog.add_points(payload, user_id, submission['points'], 'defensa')
                submission['status'] = 'approved'
                self.judged_defenses[message_id_str] = submission
                self.save_data(self.judged_defenses, JUDGED_DEFENSES_FILE)
                await self.send_log_message(payload, submission, "Defensa", "aprobada")
            elif emoji == DENY_EMOJI:
                submission['status'] = 'denied'
                self.judged_defenses[message_id_str] = submission
                self.save_data(self.judged_defenses, JUDGED_DEFENSES_FILE)
                await self.send_log_message(payload, submission, "Defensa", "rechazada")
        
        elif is_judged:
            submission = self.judged_defenses[message_id_str]
            old_status = submission['status']
            
            # Si se cambia de Aprobado a Rechazado en un mensaje ya juzgado
            if emoji == DENY_EMOJI and old_status == 'approved':
                if puntos_cog:
                    for user_id in submission['allies']:
                        await puntos_cog.add_points(payload, user_id, -submission['points'], 'defensa')
                
                # Resetear multiplicadores para que no se queden guardados en el historial
                submission['points'] = submission.get('base_points', submission['points'])
                submission['multiplier_applied'] = False
                submission['multiplier_emoji'] = None
                submission['status'] = 'denied'
                
                if original_message:
                    try:
                        for b_emoji in [BOOST_FIRE_EMOJI, BOOST_MOON_EMOJI]:
                            await original_message.remove_reaction(b_emoji, self.bot.user)
                    except: pass
                
                self.save_data(self.judged_defenses, JUDGED_DEFENSES_FILE)
                await self.log_decision_change(payload, "Defensa", "RECHAZADO (Bono eliminado)")
            
            elif emoji == APPROVE_EMOJI and old_status == 'denied':
                if puntos_cog:
                    for user_id in submission['allies']:
                        await puntos_cog.add_points(payload, user_id, submission['points'], 'defensa')
                submission['status'] = 'approved'
                self.save_data(self.judged_defenses, JUDGED_DEFENSES_FILE)
                await self.log_decision_change(payload, "Defensa", "APROBADO")

    async def send_log_message(self, payload, submission, type_str, action_str):
        log_channel = self.bot.get_channel(BOT_AUDIT_LOGS_CHANNEL_ID)
        if not log_channel: return
        message_link = f"https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}"
        
        boost_info = ""
        if submission.get('multiplier_applied'):
            emoji = submission.get('multiplier_emoji', '')
            mult = "x2" if emoji == BOOST_FIRE_EMOJI else "x1.5"
            boost_info = f" {emoji} **({mult})**"
        
        if action_str == "aprobada":
            unique_ally_mentions = [f"<@{uid}>" for uid in set(submission['allies'])]
            await log_channel.send(
                f"{APPROVE_EMOJI} **{type_str}** {action_str} por {payload.member.mention}. [Ir al envío]({message_link})\n"
                f"> Se han otorgado **`{submission['points']}`** puntos{boost_info} por mención a: {', '.join(unique_ally_mentions)}."
            )
        else:
            await log_channel.send(f"{DENY_EMOJI} **{type_str}** {action_str} por {payload.member.mention}. [Ir al envío]({message_link})")

    async def log_decision_change(self, payload, type_str, new_status_str):
        log_channel = self.bot.get_channel(BOT_AUDIT_LOGS_CHANNEL_ID)
        if not log_channel: return
        message_link = f"https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}"
        await log_channel.send(f"🔄 Decisión cambiada a **{new_status_str}** por {payload.member.mention} para un envío de **{type_str}**. [Ir al envío]({message_link})")

async def setup(bot):
    await bot.add_cog(Defensa(bot))