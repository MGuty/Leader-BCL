import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import re
import traceback

# --- CONFIGURACIÓN ---
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", 0))
ANNOUNCEMENT_CHANNEL_ID = int(os.getenv("ANNOUNCEMENT_CHANNEL_ID", 0))
REPARTO_STATE_FILE = 'reparto_zonas.json'

class RepartoZonas(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print("✅ Cog 'RepartoZonas' (Versión Nombrada) cargado.")

    # --- Grupo de Comandos /reparto ---
    reparto = app_commands.Group(name="reparto", description="Comandos para el reparto de zonas por fases.")

    # --- Funciones de Ayuda de Estado ---
    def load_state(self):
        """Carga el estado actual de todos los repartos desde el archivo JSON."""
        try:
            with open(REPARTO_STATE_FILE, 'r') as f: return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def save_state(self, data):
        """Guarda el estado de todos los repartos en el archivo JSON."""
        with open(REPARTO_STATE_FILE, 'w') as f: json.dump(data, f, indent=4)

    def _get_active_draft(self, state):
        """Encuentra y devuelve el reparto activo y su nombre."""
        for name, draft_data in state.items():
            if draft_data.get('active'):
                return name, draft_data
        return None, None

    def _parse_zones_from_content(self, content: str):
        """Extrae zonas marcadas como 'Libre' del contenido de un mensaje."""
        found_zones = []
        pattern = re.compile(r"•\s*(.*?)\s*→\s*Libre", re.IGNORECASE)
        for line in content.split('\n'):
            match = pattern.search(line)
            if match:
                found_zones.append(match.group(1).strip())
        return found_zones

    # --- Lógica Central del Turno ---
    def _get_current_turn_info(self, draft_data):
        """Determina a quién le toca jugar según el estado del reparto activo."""
        if not draft_data.get('active'): return None
        try:
            tier_config = draft_data['config']['tiers'][draft_data['current_tier_index']]
            tier_range = tier_config['range']
            player_absolute_index = tier_range[0] + draft_data['current_player_index_in_tier']
            if player_absolute_index >= len(draft_data['ranked_players']): return None
            player_id = draft_data['ranked_players'][player_absolute_index]
            return {
                "player_id": player_id, "tier_index": draft_data['current_tier_index'],
                "pick_round": draft_data['current_pick_round'], "total_picks": tier_config['picks']
            }
        except (IndexError, KeyError): return None
        
    def _advance_turn(self, draft_data):
        """Avanza el estado al siguiente turno."""
        draft_data['current_player_index_in_tier'] += 1
        current_tier_config = draft_data['config']['tiers'][draft_data['current_tier_index']]
        tier_range = current_tier_config['range']
        tier_size = tier_range[1] - tier_range[0] + 1
        if draft_data['current_player_index_in_tier'] >= tier_size:
            draft_data['current_player_index_in_tier'] = 0
            draft_data['current_pick_round'] += 1
            if draft_data['current_pick_round'] >= current_tier_config['picks']:
                draft_data['current_pick_round'] = 0
                draft_data['current_tier_index'] += 1
                if draft_data['current_tier_index'] >= len(draft_data['config']['tiers']):
                    draft_data['active'] = False
        return draft_data

    # --- Comandos de Administración ---
    @reparto.command(name="iniciar", description="Inicia un nuevo reparto con un nombre único.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    @app_commands.describe(nombre="Nombre único para este reparto (ej. season8).", canal_zonas="Canal con las zonas libres.")
    async def start_reparto(self, interaction: discord.Interaction, nombre: str, canal_zonas: discord.TextChannel):
        state = self.load_state()
        active_draft_name, _ = self._get_active_draft(state)
        if active_draft_name:
            return await interaction.response.send_message(f"❌ Ya hay un reparto activo: **{active_draft_name}**. Finalízalo primero.", ephemeral=True)
        if nombre in state:
            return await interaction.response.send_message(f"❌ Ya existe un reparto con el nombre '{nombre}'. Elige otro.", ephemeral=True)

        await interaction.response.defer(thinking=True, ephemeral=True)

        puntos_cog = self.bot.get_cog('Puntos')
        ranked_players = await puntos_cog.get_ranked_player_ids(interaction.guild.id)
        if len(ranked_players) < 25:
            return await interaction.followup.send(f"❌ Se necesitan al menos 25 jugadores con puntos. Encontrados: {len(ranked_players)}.")

        available_zones = []
        async for message in canal_zonas.history(limit=50):
            available_zones.extend(self._parse_zones_from_content(message.content))
        available_zones = sorted(list(set(available_zones)))

        if not available_zones:
            return await interaction.followup.send(f"❌ No encontré zonas 'Libre' en `#{canal_zonas.name}`.")

        new_draft = {
            'active': True,
            'config': { "tiers": [
                    { "range": [0, 4], "picks": 5 }, { "range": [5, 9], "picks": 4 },
                    { "range": [10, 14], "picks": 3 }, { "range": [15, 19], "picks": 2 },
                    { "range": [20, 24], "picks": 1 }
            ]},
            'current_tier_index': 0, 'current_pick_round': 0, 'current_player_index_in_tier': 0,
            'ranked_players': ranked_players, 'available_zones': available_zones, 'selections': {}
        }
        state[nombre] = new_draft
        self.save_state(state)

        turn_info = self._get_current_turn_info(new_draft)
        announcement_channel = self.bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
        if announcement_channel and turn_info:
            msg = (f"🎉 **¡Ha comenzado el reparto de zonas: '{nombre}'!** 🎉\n\n"
                   f"Es el turno de <@{turn_info['player_id']}> (Pick {turn_info['pick_round'] + 1}/{turn_info['total_picks']}).")
            await announcement_channel.send(msg)
        
        await interaction.followup.send(f"✅ Reparto '{nombre}' iniciado.", ephemeral=True)

    @reparto.command(name="finalizar", description="Termina manualmente el reparto de zonas activo.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def end_reparto(self, interaction: discord.Interaction):
        state = self.load_state()
        active_draft_name, _ = self._get_active_draft(state)
        if not active_draft_name:
            return await interaction.response.send_message("No hay ningún reparto activo para finalizar.", ephemeral=True)
        
        state[active_draft_name]['active'] = False
        self.save_state(state)
        await interaction.response.send_message(f"✅ El reparto '{active_draft_name}' ha sido finalizado manualmente.", ephemeral=True)
        
        announcement_channel = self.bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
        if announcement_channel:
            await announcement_channel.send(f"🛑 El reparto '{active_draft_name}' ha sido finalizado por un administrador.")

    @reparto.command(name="estado", description="Muestra el estado del reparto de zonas activo.")
    async def status_reparto(self, interaction: discord.Interaction):
        await interaction.response.defer()
        state = self.load_state()
        draft_name, draft_data = self._get_active_draft(state)
        if not draft_data:
            return await interaction.followup.send("No hay ningún reparto activo.")
        
        turn_info = self._get_current_turn_info(draft_data)
        if not turn_info:
            return await interaction.followup.send("El reparto ha concluido o hay un error de estado.")

        tier_config = draft_data['config']['tiers'][turn_info['tier_index']]
        tier_range_str = f"Top {tier_config['range'][0] + 1} al {tier_config['range'][1] + 1}"

        embed = discord.Embed(title=f"🏆 Estado del Reparto: {draft_name} 🏆", color=discord.Color.blue())
        embed.description = (f"**Fase Actual:** {tier_range_str}\n"
                             f"**Ronda de Pick:** {turn_info['pick_round'] + 1} de {turn_info['total_picks']}\n"
                             f"**▶️ Turno de:** <@{turn_info['player_id']}>")
        
        await interaction.followup.send(embed=embed)
        
    @reparto.command(name="ver", description="Muestra los resultados de un reparto anterior.")
    @app_commands.describe(nombre="El nombre del reparto que quieres ver.")
    async def view_reparto(self, interaction: discord.Interaction, nombre: str):
        await interaction.response.defer()
        state = self.load_state()
        draft_data = state.get(nombre)
        if not draft_data:
            return await interaction.followup.send(f"No se encontró ningún reparto con el nombre '{nombre}'.")
            
        embed = discord.Embed(title=f"📜 Resultados del Reparto: {nombre} 📜", color=discord.Color.green())
        selections_text = []
        if not draft_data.get('selections'):
            selections_text.append("No se realizó ninguna selección en este reparto.")
        else:
            for player_id_str, zones in sorted(draft_data['selections'].items(), key=lambda item: draft_data['ranked_players'].index(int(item[0]))):
                try:
                    member = await interaction.guild.fetch_member(int(player_id_str))
                    name = member.display_name
                except (discord.NotFound, ValueError):
                    name = f"ID({player_id_str})"
                selections_text.append(f"**{name}**: {', '.join(zones)}")
        
        embed.description = "\n".join(selections_text)
        await interaction.followup.send(embed=embed)

    @view_reparto.autocomplete('nombre')
    async def view_reparto_autocomplete(self, interaction: discord.Interaction, current: str):
        state = self.load_state()
        return [
            app_commands.Choice(name=name, value=name)
            for name in state.keys() if current.lower() in name.lower()
        ][:25]

    # --- COMANDO INDIVIDUAL /elegir_zona ---
    @app_commands.command(name="elegir_zona", description="Elige una zona durante el reparto.")
    @app_commands.describe(zona="La zona que quieres elegir.")
    async def elegir_zona(self, interaction: discord.Interaction, zona: str):
        state = self.load_state()
        draft_name, draft_data = self._get_active_draft(state)

        if not draft_data:
            return await interaction.response.send_message("No hay ningún reparto de zonas activo.", ephemeral=True)

        turn_info = self._get_current_turn_info(draft_data)
        if not turn_info or interaction.user.id != turn_info['player_id']:
            return await interaction.response.send_message("❌ No es tu turno.", ephemeral=True)

        if zona not in draft_data['available_zones']:
            return await interaction.response.send_message(f"❌ La zona '{zona}' no está disponible o no existe.", ephemeral=True)
        
        await interaction.response.defer(thinking=True)

        player_id_str = str(interaction.user.id)
        if player_id_str not in draft_data['selections']:
            draft_data['selections'][player_id_str] = []
        draft_data['selections'][player_id_str].append(zona)
        draft_data['available_zones'].remove(zona)
        
        new_draft_data = self._advance_turn(draft_data)
        state[draft_name] = new_draft_data
        self.save_state(state)

        announcement_channel = self.bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
        if announcement_channel:
            await announcement_channel.send(f"✅ <@{interaction.user.id}> ha elegido la zona: **{zona}**")
            
            next_turn_info = self._get_current_turn_info(new_draft_data)
            if new_draft_data['active'] and next_turn_info:
                next_tier_cfg = new_draft_data['config']['tiers'][next_turn_info['tier_index']]
                msg = (f"➡️ Es el turno de <@{next_turn_info['player_id']}> "
                       f"(Pick {next_turn_info['pick_round'] + 1}/{next_tier_cfg['picks']}).")
                await announcement_channel.send(msg)
            else:
                await announcement_channel.send("🏁 **¡Todas las fases del reparto han finalizado!**")

        await interaction.followup.send("¡Tu elección ha sido registrada!", ephemeral=True)

    @elegir_zona.autocomplete('zona')
    async def zona_autocomplete(self, interaction: discord.Interaction, current: str):
        state = self.load_state()
        _, draft_data = self._get_active_draft(state)
        if not draft_data: return []
        
        available_zones = draft_data.get('available_zones', [])
        return [
            app_commands.Choice(name=zona, value=zona)
            for zona in available_zones if current.lower() in zona.lower()
        ][:25]


async def setup(bot: commands.Bot):
    await bot.add_cog(RepartoZonas(bot))