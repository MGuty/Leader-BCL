# bot.py (Final y Corregido)
import discord
from discord.ext import commands
import os
import asyncio
import sys
from dotenv import load_dotenv

# --- Carga de Variables de Entorno ---
found_dotenv = load_dotenv()
if not found_dotenv:
    print("❌ ¡ERROR CRÍTICO! No se encontró el archivo .env.")
    sys.exit()

TOKEN = os.getenv("DISCORD_TOKEN")
TEST_GUILD_ID = int(os.getenv("TEST_GUILD_ID", 0))

class KompanyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.reactions = True
        intents.members = True # Importante para que el bot vea a los miembros
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        print("--- Cargando Módulos (Cogs) ---")
        for filename in os.listdir('./cogs'):
            # CORRECCIÓN: Ignora el archivo de la plantilla base
            if filename.endswith('.py') and not filename.startswith('__') and filename != 'base_moderation.py':
                extension_name = f'cogs.{filename[:-3]}'
                try:
                    await self.load_extension(extension_name)
                    print(f"✅ Módulo '{filename}' cargado exitosamente.")
                except Exception as e:
                    print(f"❌ Error al cargar el módulo '{filename}':")
                    print(f"   - {type(e).__name__}: {e}")
        
        print("\n--- Sincronizando comandos de barra (Slash Commands) ---")
        try:
            if TEST_GUILD_ID != 0:
                guild = discord.Object(id=TEST_GUILD_ID)
                self.tree.copy_global_to(guild=guild)
                synced_commands = await self.tree.sync(guild=guild)
                print(f"✅ ¡Se sincronizaron {len(synced_commands)} comandos para el servidor de pruebas!")
            else:
                synced_commands = await self.tree.sync()
                print(f"✅ ¡Se sincronizaron {len(synced_commands)} comandos globalmente!")
        except Exception as e:
            print(f"❌ Error al sincronizar comandos: {e}")

    async def on_ready(self):
        print('--------------------------------------------------')
        print(f'✅ ¡Bot conectado como {self.user}!')
        print(f'   ID del Bot: {self.user.id}')
        print('--------------------------------------------------')

async def main():
    if not TOKEN:
        print("❌ ERROR FATAL: No se encontró el DISCORD_TOKEN.")
        return
    
    bot = KompanyBot()
    await bot.start(TOKEN)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot desconectado manualmente.")