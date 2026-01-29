# bot.py (Estructura Final y Corregida)
import discord
from discord.ext import commands
import os
import asyncio
from dotenv import load_dotenv

# --- Carga de Variables de Entorno ---
# Esto buscará un archivo llamado exactamente ".env"
found_dotenv = load_dotenv()
if found_dotenv:
    print("✅ Archivo .env encontrado y cargado exitosamente.")
else:
    print("❌ ¡ERROR CRÍTICO! No se encontró el archivo .env.")

TOKEN = os.getenv("DISCORD_TOKEN")
TEST_GUILD_ID = int(os.getenv("TEST_GUILD_ID", 0))

# --- SUBCLASE DE BOT PERSONALIZADA ---
# Crear una subclase de commands.Bot nos permite usar el `setup_hook`
# para una inicialización asíncrona más controlada y fiable.
class KompanyBot(commands.Bot):
    def __init__(self):
        # Definimos los intents aquí, en el constructor de nuestra clase.
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.reactions = True
        # Llamamos al constructor de la clase padre (commands.Bot)
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        """
        El setup_hook se ejecuta automáticamente después de que el bot se conecta
        pero antes de que esté completamente listo. Es el lugar perfecto para
        cargar cogs y sincronizar comandos.
        """
        print("--- Cargando Módulos (Cogs) ---")
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py') and not filename.startswith('__'):
                extension_name = f'cogs.{filename[:-3]}'
                try:
                    await self.load_extension(extension_name)
                    print(f"✅ Módulo '{filename}' cargado exitosamente.")
                except Exception as e:
                    print(f"❌ Error al cargar el módulo '{filename}':")
                    print(f"   - {type(e).__name__}: {e}")
        
        print("\n--- Sincronizando comandos de barra (Slash Commands) ---")
        # Sincronizamos los comandos DESPUÉS de haber cargado todos los cogs.
        # Esto garantiza que todos los comandos se registren antes de la sincronización.
        try:
            if TEST_GUILD_ID != 0:
                # Sincronización específica para el servidor de pruebas (instantánea).
                guild = discord.Object(id=TEST_GUILD_ID)
                self.tree.copy_global_to(guild=guild)
                synced_commands = await self.tree.sync(guild=guild)
                print(f"✅ ¡Se sincronizaron {len(synced_commands)} comandos para el servidor de pruebas!")
            else:
                # Sincronización global (puede tardar hasta 1 hora).
                synced_commands = await self.tree.sync()
                print(f"✅ ¡Se sincronizaron {len(synced_commands)} comandos globalmente!")

        except Exception as e:
            print(f"❌ Error al sincronizar comandos: {e}")

    async def on_ready(self):
        """
        Este evento se dispara cuando el bot está completamente listo y operativo.
        Ahora solo lo usamos para confirmar la conexión.
        """
        print('--------------------------------------------------')
        print(f'✅ ¡Bot conectado como {self.user}!')
        print(f'   ID del Bot: {self.user.id}')
        print('--------------------------------------------------')

# --- PUNTO DE ENTRADA ---
async def main():
    # Creamos una instancia de nuestro bot personalizado.
    bot = KompanyBot()

    if TOKEN is None:
        print("❌ ERROR FATAL: No se encontró el DISCORD_TOKEN en el archivo .env. El bot no puede iniciar.")
        return
    
    # Iniciamos el bot.
    await bot.start(TOKEN)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot desconectado manualmente.")