import asyncio
import decimal
import os
import sys
import time
from pprint import pprint

import defaults
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


def get_prefix(bot, msg):
    prefix = ['!']
    if game := bot.rumble.get(msg.guild.id):
        prefix = [game['prefix']]

    return prefix


class MyBot(commands.Bot):

    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents, command_prefix=get_prefix, help_command=None)

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
async def print_info(ctx):
    pprint(bot.rumble)


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


@bot.event
async def on_guild_join(guild):
    # Check if the guild is already in the db.
    check = await db.select_fetchone_dict("SELECT * FROM rumble_guild WHERE guild_id = %s", [guild.id])
    if check:
        return

    # Add the guild info to the database if it is not there already
    try:
        thumbnail = guild.icon.url
    except AttributeError:
        thumbnail = defaults.thumbnail
    await db.write("INSERT INTO rumble_guild (guild_id, game_name, revive_chance, revive_gif, death_gif, emoji, weapon1_name, active, thumbnail,"
                                  "attack_min, attack_max, special_min, special_max, heal_min, heal_max, revive_min, revive_max, weapon1_min, weapon1_max, special_chance, "
                                  "weapon1_chance, attack_chance, heal_chance, rand_chance, rand_min, rand_max, weapon2_name, weapon2_chance, weapon2_min, weapon2_max,"
                                  "potion_name, potion_chance, potion_max, potion_min, potion_alias, weapon1_alias, weapon2_alias, prefix) VALUES (%s, %s, %s, %s, "
                                  "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                                  (guild.id, defaults.game_name, defaults.revive_chance, defaults.revive_gif, defaults.death_gif, defaults.emoji, defaults.weapon1_name, False, thumbnail,
                                   defaults.attack_min, defaults.attack_max, defaults.special_min, defaults.special_max, defaults.heal_min, defaults.heal_max, defaults.revive_min,
                                   defaults.revive_max, defaults.weapon1_min, defaults.weapon1_max, defaults.special_chance, defaults.weapon1_chance, defaults.attack_chance,
                                   defaults.heal_chance, defaults.rand_chance, defaults.rand_min, defaults.rand_max, defaults.weapon2_name, defaults.weapon2_chance, defaults.weapon2_min,
                                   defaults.weapon2_max, defaults.potion_name, defaults.potion_chance, defaults.potion_max, defaults.potion_min, defaults.potion_alias,
                                   defaults.weapon1_alias, defaults.weapon2_alias, defaults.prefix))

    # Add the server to the cache
    game_info = await db.select_fetchone_dict("SELECT * FROM rumble_guild WHERE guild_id = %s", [guild.id])
    game_info['admins'] = []
    bot.rumble[guild.id] = game_info


bot.run(TOKEN)
