import asyncio
import decimal
import os
import sys
import time

import rumble
from base_logger import main_logger


import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

import db

load_dotenv()
print = main_logger.info

TOKEN = os.getenv('DISCORD_TOKEN')
ADMINS = [401371729034870784, 290020410764820480]

if sys.platform == 'win32':
    from asyncio import WindowsSelectorEventLoopPolicy
    asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())


class MyBot(commands.Bot):

    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents, command_prefix="!", help_command=None)

    async def setup_hook(self):
        await db.open_pool()
        await cache_game_data()
        await bot.add_cog(rumble.RumbleGame(bot))


intents = discord.Intents.all()
bot = MyBot(intents=intents)
intents.presences = False
intents.message_content = True
intents.members = True


# This will cache all the game information for each server
async def cache_game_data():
    # Get the game information from the DB and put it into a dict. Store it as a bot variable
    game_info = await db.select_fetchall_dict("SELECT * FROM rumble_guild")
    rumble = {}
    for g in game_info:
        rumble[g['guild_id']] = g

        # Get admins for this guild
        admins = await db.select_fetchall("SELECT user_id FROM rumble_admins WHERE guild_id = %s", [g['guild_id']])
        rumble[g['guild_id']]['admins'] = [j for i in admins for j in i]

    bot.rumble = rumble

    # We will also initialize the game variable as well, so we can just check here instead of making a DB call.

    bot.rumble_games = {}


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    msg = f"{error}"
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)
    if isinstance(error, discord.app_commands.errors.BotMissingPermissions):
        return
    print(f"Error: {error}\n"
          f"{interaction.user} in guild {interaction.guild}")
    raise error


@bot.command()
async def sync_global(ctx):
    if ctx.author.id not in ADMINS:
        return
    synced = await bot.tree.sync()
    c_list = []
    for c in synced:
        c_list.append(f"{c}\n")
    embedVar = discord.Embed(title="")
    if c_list:
        embedVar.add_field(name="Global Commands", value="".join(c_list))
    await ctx.send(embed=embedVar)


@bot.event
async def on_ready():
    print(f'We have logged in as {bot.user}')


bot.run(TOKEN)
