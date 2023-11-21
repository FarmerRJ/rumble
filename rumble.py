import asyncio
import codecs
import csv
import random
import time
import requests
from contextlib import closing

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import bot

import db
import defaults

ADMINS = [401371729034870784, 290020410764820480]
INVITE_LINK = "https://discord.gg/r6yUPEfjbH"
ACCEPTED_PHRASE_TYPES = ['attack', 'special', 'heal', 'rand', 'revive', 'death']


class Player:
    def __init__(self, user):
        self.user = user
        self.hp = 100
        self.dead = False  # Add a new attribute to track whether a player is dead
        self.potion_used = False
        self.dart_thrown = False

    def __str__(self):
        return str(self.user)


class RumbleGame(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_phrases(self, guild_id):
        phrases = await db.select_fetchall_dict("SELECT * FROM rumble_phrases WHERE guild_id = %s", [guild_id])
        phrase_dict = {}
        for p in phrases:
            if phrase_dict.get(p['type']):
                phrase_dict[p['type']].append(p['phrase'])
            else:
                phrase_dict[p['type']] = [p['phrase']]
        if not phrase_dict.get("death"):
            phrase_dict['death'] = ["{player} has died!"]
        if not phrase_dict.get("revive"):
            phrase_dict['revive'] = ["{player} has been revived!"]
        return phrase_dict

    def game_is_active(self, channel_id):
        if game := self.bot.rumble_games.get(channel_id):
            return game
        else:
            return

    @commands.command()
    async def battle(self, ctx):

        if not (game := self.bot.rumble.get(ctx.guild.id)):
            await ctx.send(f"The command does not work in this server. Please open a ticket at The Farm to purchase.\n{INVITE_LINK}")
            return

        if not game['active']:
            await ctx.send(f"You must purchase this game first. Please open a ticket at The Farm.\n{INVITE_LINK}")
            return

        if not (game_state := self.bot.rumble_games.get(ctx.channel)):
            self.bot.rumble_games[ctx.channel.id] = {
                            "players": [],
                            "battle_in_progress": False,
                            "registration_open": False,
                            "battle_initiator": None,
                            "battle_command_in_use": False,
                            "time_start": int(time.time()),
                            "guild_id": ctx.guild.id,
                            "phrases": await self.get_phrases(ctx.guild.id)
                        }
            game_state = self.bot.rumble_games[ctx.channel.id]

        if game_state["battle_in_progress"]:
            await ctx.send(f"{game['game_name']} is already in progress.")
            return

        allowed_users = game['admins']

        # Added all server admins to the allowed list here
        if not ctx.author.guild_permissions.administrator and ctx.author.id not in allowed_users:
            await ctx.send("You are not allowed to initiate the battle command.")
            return

        if game_state["battle_command_in_use"]:
            await ctx.send("Battle registration is already in progress.")
            return

        game_state["battle_command_in_use"] = True
        game_state["registration_open"] = True
        game_state["battle_initiator"] = ctx.author
        players = game_state['players']

        join_embed = discord.Embed(title=f"Join {game['game_name']}", description=f"React with {game['emoji']} to join the battle!", color=discord.Color.blue())
        # banner = discord.File(f"./images/{ctx.guild.id}-banner.png", filename="banner.png")
        join_embed.set_thumbnail(url=game['thumbnail'])
        # join_embed.set_author(url=f"attachment://thumbnail.png")
        try:
            join_message = await ctx.channel.send(embed=join_embed)
        except discord.errors.Forbidden:
            await ctx.channel.send("I do not have the correct permissions. Please grant me the Send Messages and Embed Links permission.\n"
                                   "Game Cancelled.")
            self.remove_game(ctx)
            return

        game_state['msg_id'] = join_message.id
        await join_message.add_reaction(f"{game['emoji']}")

        def check(reaction, user):
            return user != self.bot.user and str(reaction.emoji) == f"{game['emoji']}" and reaction.message.id == join_message.id

        while game_state["registration_open"]:
            try:
                reaction, user = await self.bot.wait_for("reaction_add", timeout=1, check=check)
            except asyncio.TimeoutError:
                continue

            if user not in [player.user for player in players]:
                players.append(Player(user))
                print(players)
        try:
            await join_message.clear_reactions()
        except discord.errors.Forbidden:
            await ctx.channel.send("I do not have the correct permissions. Please grant me the Manage Messages permission.\n"
                                   "Game Cancelled.")
            self.remove_game(ctx)
            return

        game_state["players"] = players

    @commands.command()
    async def reset(self, ctx):
        if not (game := self.bot.rumble.get(ctx.guild.id)):
            await ctx.send(f"The command does not work in this server. Please open a ticket at The Farm to purchase.\n{INVITE_LINK}")
            return

        if self.bot.rumble_games.get(ctx.channel.id):
            self.remove_game(ctx)
            await ctx.channel.send("The game has been reset.")

        else:
            await ctx.channel.send("There is no active game.")

    def get_top_players(self, players_list):
        return sorted(players_list, key=lambda player: player.hp, reverse=True)[:5]

    def player_name_without_discriminator(self, player):
        return player.user.name

    def create_death_embed(self, player, game, game_state):
        death_embed = discord.Embed(title=random.choice(game_state['phrases']['death']).format(player=self.player_name_without_discriminator(player)),
                                    description="", color=discord.Color.dark_red())
        death_embed.set_image(url=game['death_gif'])
        return death_embed

    async def perform_turn(self, attacker, channel, players, game, game_state):
        defender = random.choice([player for player in players if player != attacker and player.hp > 0])
        action = random.choices(["attack", "special", "heal", "rand"], [game['attack_chance'], game['special_chance'], game['heal_chance'], game['rand_chance']])[0]

        death_embed = None

        if action == "attack":
            damage = random.randint(game['attack_min'], game['attack_max'])
            defender.hp -= damage
            if defender.hp < 0:
                defender.hp = 0

            phrase = random.choice(game_state['phrases']['attack']).format(attacker=self.player_name_without_discriminator(attacker),
                                                          defender=self.player_name_without_discriminator(defender),
                                                          dmg=damage)
        elif action == "special":
            damage = random.randint(game['special_min'], game['special_max'])
            defender.hp -= damage
            if defender.hp < 0:
                defender.hp = 0

            phrase = random.choice(game_state['phrases']['special']).format(attacker=self.player_name_without_discriminator(attacker), defender=self.player_name_without_discriminator(defender),
                                                                  dmg=damage)
        elif action == "heal":
            heal = random.randint(game['heal_min'], game['heal_max'])
            attacker.hp += heal
            if attacker.hp > 100:
                attacker.hp = 100
            phrase = random.choice(game_state['phrases']['heal']).format(attacker=self.player_name_without_discriminator(attacker), heal=heal)

        elif action == "rand":
            damage = random.randint(game['rand_min'], game['rand_max'])
            defender.hp -= damage
            if defender.hp < 0:
                defender.hp = 0
            phrase = random.choice(game_state['phrases']['rand']).format(defender=self.player_name_without_discriminator(defender),
                                                                         attacker=self.player_name_without_discriminator(attacker),
                                                                         dmg=damage)

        return phrase, death_embed

    @commands.command(aliases=['t'])
    async def throw(self, ctx, target: discord.Member):
        game = self.bot.rumble.get(ctx.guild.id)
        game_state = self.bot.rumble_games.get(ctx.channel.id)  # Get the game state
        if not game_state:
            await ctx.channel.send("There is no active battle in this channel.")
            return

        players = game_state["players"]  # Use the local players variable

        if not game_state["battle_in_progress"]:
            await ctx.channel.send("The battle hasn't started yet!")
            return

        attacker = next((p for p in players if p.user == ctx.author), None)
        defender = next((p for p in players if p.user == target), None)

        if not attacker or not defender:
            await ctx.channel.send("Both attacker and defender must be in the game.")
            return

        if attacker.dead:
            await ctx.channel.send("You can't throw a dart, you're dead!")
            return

        if attacker.dart_thrown:
            await ctx.channel.send("You have already thrown your dart this round!")
            return

        if defender.dead:
            await ctx.channel.send(f"{defender.user.name} is already dead!")
            return

        success = random.choices(['hit', 'miss'], [game['weapon1_chance'], (100 - game['weapon1_chance'])])
        if success[0] == 'hit':
            damage = random.randint(game['weapon1_min'], game['weapon1_max'])
            defender.hp -= damage

            if defender.hp <= 0:
                defender.hp = 0
                defender.dead = True

            attacker.dart_thrown = True

            dart_embed = discord.Embed(title=f"{attacker.user.name} threw a {game['weapon1_name']} at {defender.user.name}!",
                                       description=f"{defender.user.name} takes {damage} damage!",
                                       color=discord.Color.red())
            await ctx.channel.send(embed=dart_embed)
        else:
            attacker.dart_thrown = True

            dart_embed = discord.Embed(title=f"{attacker.user.name} threw a {game['weapon1_name']} at {defender.user.name} and missed",
                                       description=f"{defender.user.name} takes 0 damage!",
                                       color=discord.Color.red())
            await ctx.channel.send(embed=dart_embed)

    def get_bottom_players(self, players):
        # Filter out dead players, then sort the players by HP ascending and get the first 5.
        return sorted([p for p in players if p.hp > 0], key=lambda p: p.hp)[:5]

    async def send_battle_embed(self, ctx, description, players, game, game_state):
        top_players = self.get_top_players(players)
        top_players_text = "\n".join(
            [f"**{self.player_name_without_discriminator(p)}**: {p.hp} HP" for p in top_players])

        bottom_players = self.get_bottom_players(players)
        bottom_players_text = "\n".join(
            [f"**{self.player_name_without_discriminator(p)}**: {p.hp} HP" for p in bottom_players])

        remaining_players = len([player for player in players if player.hp > 0])

        battle_embed = discord.Embed(title=game['game_name'], description=description, color=discord.Color.red())
        battle_embed.add_field(name="Top 5 Players", value=top_players_text, inline=True)
        battle_embed.add_field(name="Bottom 5 Players", value=bottom_players_text, inline=True)
        battle_embed.set_footer(text=f"Remaining Players: {remaining_players}")
        await ctx.send(embed=battle_embed)

        # Check for players with 0 HP and send the death gif
        for player in players:
            if player.hp == 0 and not player.dead:
                player.dead = True  # Mark the player as dead
                death_embed = self.create_death_embed(player, game, game_state)
                await asyncio.sleep(1)
                await ctx.send(embed=death_embed)

        for player in players:
            if player.hp == 0 and player.dead:
                revive_chance = random.random()
                # Check the number of remaining players before reviving a player
                if revive_chance <= (game['revive_chance'] / 100) and remaining_players > 1:
                    amount = random.randrange(game['revive_min'], game['revive_max'])
                    player.hp = amount
                    player.dead = False
                    revive_embed = discord.Embed(title=random.choice(game_state['phrases']['revive']).format(player=self.player_name_without_discriminator(player)),
                                                 description=f"{self.player_name_without_discriminator(player)} comes back to life with {amount} HP!",
                                                 color=discord.Color.green())
                    revive_embed.set_image(url=game['revive_gif'])
                    await asyncio.sleep(10)
                    await ctx.channel.send(embed=revive_embed)

    @commands.command(aliases=['p'])
    async def potion(self, ctx):
        game = self.bot.rumble.get(ctx.guild.id)
        game_state = self.bot.rumble_games.get(ctx.channel.id)  # Get the game state
        if not game_state:
            await ctx.channel.send("There is no active battle in this channel.")
            return

        players = game_state["players"]  # Use the local players variable

        if not game_state["battle_in_progress"]:
            await ctx.channel.send("The battle hasn't started yet!")
            return

        player = next((p for p in players if p.user == ctx.author), None)
        if not player:
            await ctx.channel.send("You are not in the game.")
            return

        if player.dead:
            await ctx.channel.send("You can't use a potion, you're dead!")
            return

        if player.potion_used:
            await ctx.channel.send("You have already used your potion!")
            return

        success = random.choices(['hit', 'miss'], [game['potion_chance'], (100 - game['potion_chance'])])
        if success[0] == 'hit':
            heal = random.randint(game['potion_min'], game['potion_max'])
            potion_embed = discord.Embed(
                title=f"{self.player_name_without_discriminator(player)} used a {game['potion_name']}!",
                description=f"{self.player_name_without_discriminator(player)} recovered {heal} HP!",
                color=discord.Color.green())
        else:
            heal = 0
            potion_embed = discord.Embed(
                title=f"{self.player_name_without_discriminator(player)} used a {game['potion_name']}!",
                description=f"Turns out it was just pee and did nothing.",
                color=discord.Color.yellow())

        player.hp += heal
        if player.hp > 100:
            player.hp = 100
        player.potion_used = True

        await ctx.channel.send(embed=potion_embed)

    @commands.command()
    async def start(self, ctx):
        game = self.bot.rumble.get(ctx.guild.id)

        if not game['active']:
            await ctx.send(f"You must purchase this game first. Please open a ticket at The Farm.\n{INVITE_LINK}")
            return

        game_state = self.bot.rumble_games[ctx.channel.id]
        players = game_state.get("players", [])
        battle_in_progress = game_state["battle_in_progress"]
        registration_open = game_state["registration_open"]
        battle_initiator = game_state["battle_initiator"]

        if battle_in_progress:
            await ctx.send(f"{game['game_name']} is already in progress.")
            return

        if len(players) < 2:
            await ctx.send("Not enough players to start the battle.")
            return

        if ctx.author != battle_initiator:
            await ctx.send("Only the person who initiated the battle can start it.")
            return

        game_state["registration_open"] = False
        game_state["battle_command_in_use"] = False

        game_state["battle_in_progress"] = True
        await ctx.channel.send(f"{game['game_name']} has begun!")

        turn_counter = 0
        battle_description = ""

        while len([player for player in players if player.hp > 0]) > 1 and game_state["battle_in_progress"]:
            for player in players:
                if player.hp > 0:
                    turn_counter += 1
                    action_phrase, death_embed = await self.perform_turn(player, ctx.channel, players, game, game_state)  # Pass the channel
                    battle_description += action_phrase + "\n"

                    if turn_counter % 3 == 0:
                        await self.send_battle_embed(ctx, battle_description, players, game, game_state)  # Call the helper function
                        battle_description = ""
                        if death_embed:  # If there's a death embed, send it after the battle embed
                            await asyncio.sleep(1)
                            await ctx.channel.send(embed=death_embed)
                        await asyncio.sleep(10)

        if battle_description:
            await self.send_battle_embed(ctx, battle_description, players, game, game_state)

        potential_winners = [player for player in players if player.hp > 0]
        winner = potential_winners[0] if potential_winners else None
        winner_name = f"**{self.player_name_without_discriminator(winner)}**"

        victory_embed = discord.Embed(title="Victory!", description="", color=discord.Color.gold())
        victory_embed.add_field(name=f":trophy: | **{winner_name}** emerges victorious!",
                                value=f":tada: | Congratulations!", inline=False)

        no_win_embed = discord.Embed(title="No Winners!", description="", color=discord.Color.teal())
        no_win_embed.add_field(name=f"Nobody won this round of {game['game_name']}.", value="Better luck next round!", inline=False)

        if winner:
            winner_name = f"**{self.player_name_without_discriminator(winner)}**"
            victory_embed = discord.Embed(title="Victory!", description="", color=discord.Color.gold())
            victory_embed.add_field(name=f":trophy: | **{winner_name}** emerges victorious!",
                                    value=f":tada: | Congratulations!", inline=False)

            if winner.user.avatar:
                victory_embed.set_thumbnail(url=winner.user.avatar.url)
            else:
                victory_embed.set_thumbnail(
                    url="https://cdn.discordapp.com/emojis/1028000342174093362.webp?size=128&quality=lossless")
            await ctx.channel.send(embed=victory_embed)
        else:
            no_win_embed = discord.Embed(title="No Winners!", description="", color=discord.Color.teal())
            no_win_embed.add_field(name=f"Nobody won this round of {game['game_name']}.", value="Better luck next round!",
                                   inline=False)
            no_win_embed.set_thumbnail(url=game['thumbnail'])
            await ctx.channel.send(embed=no_win_embed)

        # Reset the game state after the battle ends
        self.remove_game(ctx)

    def remove_game(self, ctx):
        del self.bot.rumble_games[ctx.channel.id]

    @app_commands.command(name='import-phrases-csv')
    async def import_assets(self, interaction: discord.Interaction, guild_id: str, file: discord.Attachment):
        if interaction.user.id not in ADMINS:
            await interaction.response.send_message("You do not have permission to do this.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        url = file.url
        with closing(requests.get(url, stream=True)) as re:
            line_count = imported = error = 0
            reader = csv.reader(codecs.iterdecode(re.iter_lines(), 'utf-8'), delimiter=',', quotechar='"')
            for r in reader:
                line_count += 1
                # Check for the phrase first
                check = await db.select_fetchone_dict("SELECT * FROM rumble_phrases WHERE phrase = %s", [r[0]])
                if check:
                    continue
                else:
                    if r[1] not in ACCEPTED_PHRASE_TYPES:
                        error += 1
                        await interaction.followup.send(f"Error on line {line_count}. Incorrect Type.\n"
                                                        f"Must be one of {''.join(ACCEPTED_PHRASE_TYPES)}", ephemeral=True)
                    else:
                        imported += 1
                        await db.write("INSERT INTO rumble_phrases (guild_id, type, phrase) VALUES (%s, %s, %s)", (guild_id, r[1], r[0]))
        await interaction.followup.send(f"Imported {imported} phrases", ephemeral=True)

    @app_commands.command(name='rumble-config')
    async def config_menu(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator and interaction.user.id not in ADMINS:
            msg = "You do not have permission to run this command"
            await interaction.response.send_message(msg, ephemeral=True)
            return

        # Interactions are only good for 15 minutes so we set an expiry time.
        expire = int(time.time()) + 870
        game = self.bot.rumble.get(interaction.guild.id)
        embed = generate_config_embed(game, self.bot, expire)
        view = ConfigMenu(self.bot, interaction, game, expire)
        await interaction.response.send_message(embed=embed, view=view)


def generate_config_embed(game, bot, expire):
    embed = discord.Embed(title=game['game_name'], color=discord.Color.green())
    embed.add_field(name="", value=f"This embed will expire <t:{expire}:R>")
    value_settings = [f"Heal Chance: `{game['heal_chance']}%`\n",
                      f"Heal Amount: `{game['heal_min']}` - `{game['heal_max']}`\n",
                      f"Revive Chance: `{game['revive_chance']}%`\n"
                      f"Revive Amount: `{game['revive_min']}` - `{game['revive_max']}`\n",
                      f"{game['potion_name']} Chance: `{game['potion_chance']}%`\n",
                      f"{game['potion_name']} Amount: `{game['potion_min']}` - `{game['potion_max']}`\n",
                      f"Attack Chance: `{game['attack_chance']}%`\n",
                      f"Attack Damage: `{game['attack_min']}` - `{game['attack_max']}`\n",
                      f"Random Attack Chance: `{game['rand_chance']}%`\n",
                      f"Random Attack Damage: `{game['rand_min']}` - `{game['rand_max']}`\n",
                      f"Special Chance: `{game['special_chance']}%`\n",
                      f"Special Damage: `{game['special_min']}` - `{game['special_max']}`\n",
                      f"{game['weapon1_name']} Chance: `{game['weapon1_chance']}%`\n",
                      f"{game['weapon1_name']} Damage: `{game['weapon1_min']}` - `{game['weapon1_max']}`\n",
                      ]
    if game.get('weapon2_name'):
        value_settings.append(f"{game['weapon2_name']} Chance: `{game['weapon2_chance']}%`\n"
                              f"{game['weapon2_name']} Damage: `{game['weapon2_min']}` - `{game['weapon2_max']}`\n")
    general = [f"__Command Prefix__\n{game['prefix']}\n",
               f"__Emoji__\n{game['emoji']}\n"]
    if game['thumbnail']:
        embed.set_thumbnail(url=game['thumbnail'])
        general.append(f"__Thumbnail__:\n"
                      f"{game['thumbnail']}\n")
    if game['revive_gif']:
        general.append(f"__Revive Gif__:\n"
                      f"{game['revive_gif']}\n")
    if game['death_gif']:
        general.append(f"__Death Gif__:\n"
                      f"{game['death_gif']}\n")
    embed.add_field(name="General Info", value="".join(general), inline=False)
    embed.add_field(name="Battle Values", value="".join(value_settings), inline=False)


    return embed


class ConfigSettingsModal(discord.ui.Modal, title="Config Settings"):

    def __init__(self, bot, interaction, game, setting, expire):
        super().__init__(timeout=None)
        self.bot = bot
        self.interaction = interaction
        self.game = game
        self.setting = setting
        self.expire = expire

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if self.setting == 'attack':
            if int(self.children[0].value) < 0 or int(self.children[1].value) < 0 or int(self.children[2].value) < 0:
                await interaction.followup.send("All values must not be negative.", ephemeral=True)
                return
            if int(self.children[0].value) > 100 or int(self.children[1].value) > 100 or int(self.children[2].value) > 100:
                await interaction.followup.send("All values must be 100 or less.", ephemeral=True)
                return
            await update_settings(self.bot, 'attack_chance', int(self.children[0].value), interaction.guild.id)
            await update_settings(self.bot, 'attack_min', int(self.children[1].value), interaction.guild.id)
            await update_settings(self.bot, 'attack_max', int(self.children[2].value), interaction.guild.id)

        elif self.setting == 'special':
            if int(self.children[0].value) < 0 or int(self.children[1].value) < 0 or int(self.children[2].value) < 0:
                await interaction.followup.send("All values must not be negative.", ephemeral=True)
                return
            if int(self.children[0].value) > 100 or int(self.children[1].value) > 100 or int(self.children[2].value) > 100:
                await interaction.followup.send("All values must be 100 or less.", ephemeral=True)
                return
            await update_settings(self.bot, 'special_chance', int(self.children[0].value), interaction.guild.id)
            await update_settings(self.bot, 'special_min', int(self.children[1].value), interaction.guild.id)
            await update_settings(self.bot, 'special_max', int(self.children[2].value), interaction.guild.id)

        elif self.setting == 'rand':
            if int(self.children[0].value) < 0 or int(self.children[1].value) < 0 or int(self.children[2].value) < 0:
                await interaction.followup.send("All values must not be negative.", ephemeral=True)
                return
            if int(self.children[0].value) > 100 or int(self.children[1].value) > 100 or int(self.children[2].value) > 100:
                await interaction.followup.send("All values must be 100 or less.", ephemeral=True)
                return
            await update_settings(self.bot, 'rand_chance', int(self.children[0].value), interaction.guild.id)
            await update_settings(self.bot, 'rand_min', int(self.children[1].value), interaction.guild.id)
            await update_settings(self.bot, 'rand_max', int(self.children[2].value), interaction.guild.id)

        elif self.setting == 'revive':
            if int(self.children[0].value) < 0 or int(self.children[1].value) < 0 or int(self.children[2].value) < 0:
                await interaction.followup.send("All values must not be negative.", ephemeral=True)
                return
            if int(self.children[0].value) > 100 or int(self.children[1].value) > 100 or int(self.children[2].value) > 100:
                await interaction.followup.send("All values must be 100 or less.", ephemeral=True)
                return
            await update_settings(self.bot, 'revive_chance', int(self.children[0].value), interaction.guild.id)
            await update_settings(self.bot, 'revive_min', int(self.children[1].value), interaction.guild.id)
            await update_settings(self.bot, 'revive_max', int(self.children[2].value), interaction.guild.id)

        elif self.setting == 'potion':
            if int(self.children[2].value) < 0 or int(self.children[3].value) < 0 or int(self.children[4].value) < 0:
                await interaction.followup.send("All values must not be negative.", ephemeral=True)
                return
            if int(self.children[2].value) > 100 or int(self.children[3].value) > 100 or int(self.children[4].value) > 100:
                await interaction.followup.send("All values must be 100 or less.", ephemeral=True)
                return
            await update_settings(self.bot, 'potion_name', str(self.children[0].value), interaction.guild.id)
            await update_settings(self.bot, 'potion_alias', str(self.children[1].value), interaction.guild.id)
            await update_settings(self.bot, 'potion_chance', int(self.children[2].value), interaction.guild.id)
            await update_settings(self.bot, 'potion_min', int(self.children[3].value), interaction.guild.id)
            await update_settings(self.bot, 'potion_max', int(self.children[4].value), interaction.guild.id)

        elif self.setting == 'heal':
            if int(self.children[0].value) < 0 or int(self.children[1].value) < 0 or int(self.children[2].value) < 0:
                await interaction.followup.send("All values must not be negative.", ephemeral=True)
                return
            if int(self.children[0].value) > 100 or int(self.children[1].value) > 100 or int(self.children[2].value) > 100:
                await interaction.followup.send("All values must be 100 or less.", ephemeral=True)
                return
            await update_settings(self.bot, 'heal_chance', int(self.children[0].value), interaction.guild.id)
            await update_settings(self.bot, 'heal_min', int(self.children[1].value), interaction.guild.id)
            await update_settings(self.bot, 'heal_max', int(self.children[2].value), interaction.guild.id)

        elif self.setting == 'weapon1':
            if int(self.children[2].value) < 0 or int(self.children[3].value) < 0 or int(self.children[4].value) < 0:
                await interaction.followup.send("All values must not be negative.", ephemeral=True)
                return
            if int(self.children[2].value) > 100 or int(self.children[3].value) > 100 or int(self.children[4].value) > 100:
                await interaction.followup.send("All values must be 100 or less.", ephemeral=True)
                return
            await update_settings(self.bot, 'weapon1_name', str(self.children[0].value), interaction.guild.id)
            await update_settings(self.bot, 'weapon1_alias', str(self.children[1].value), interaction.guild.id)
            await update_settings(self.bot, 'weapon1_chance', int(self.children[2].value), interaction.guild.id)
            await update_settings(self.bot, 'weapon1_min', int(self.children[3].value), interaction.guild.id)
            await update_settings(self.bot, 'weapon1_max', int(self.children[4].value), interaction.guild.id)

        elif self.setting == 'weapon2':
            if int(self.children[2].value) < 0 or int(self.children[3].value) < 0 or int(self.children[4].value) < 0:
                await interaction.followup.send("All values must not be negative.", ephemeral=True)
                return
            if int(self.children[2].value) > 100 or int(self.children[3].value) > 100 or int(self.children[4].value) > 100:
                await interaction.followup.send("All values must be 100 or less.", ephemeral=True)
                return
            await update_settings(self.bot, 'weapon2_name', str(self.children[0].value), interaction.guild.id)
            await update_settings(self.bot, 'weapon2_alias', str(self.children[1].value), interaction.guild.id)
            await update_settings(self.bot, 'weapon2_chance', int(self.children[2].value), interaction.guild.id)
            await update_settings(self.bot, 'weapon2_min', int(self.children[3].value), interaction.guild.id)
            await update_settings(self.bot, 'weapon2_max', int(self.children[4].value), interaction.guild.id)
        else:
            await update_settings(self.bot, self.setting, str(self.children[0].value), interaction.guild.id)

        game = self.bot.rumble.get(interaction.guild.id)
        embed = generate_config_embed(game, self.bot, self.expire)
        view = ConfigMenu(self.bot, self.interaction, game, self.expire)
        await self.interaction.edit_original_response(content=None, embed=embed, view=view)


class ConfigMenu(discord.ui.View):

    def __init__(self, bot, interaction, game, expire):
        self.bot = bot
        self.interaction = interaction
        self.expire = expire
        self.game = game
        super().__init__(timeout=None)

    @discord.ui.button(label="Set Attack", style=discord.ButtonStyle.blurple, row=0)
    async def attack(self, interaction: discord.Interaction, button: discord.Button):
        modal = ConfigSettingsModal(self.bot, self.interaction, self.game, 'attack', self.expire)
        modal.add_item(discord.ui.TextInput(label=f"Attack Chance (Default: {defaults.attack_chance})", placeholder="Enter the attack chance", default=self.game['attack_chance']))
        modal.add_item(discord.ui.TextInput(label=f"Attack Min (Default: {defaults.attack_min})", placeholder="Attack minimum damage", default=self.game['attack_min']))
        modal.add_item(discord.ui.TextInput(label=f"Attack Max (Default: {defaults.attack_max})", placeholder="Attack maximum damage", default=self.game['attack_max']))
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Set Special", style=discord.ButtonStyle.blurple, row=0)
    async def special(self, interaction: discord.Interaction, button: discord.Button):
        modal = ConfigSettingsModal(self.bot, self.interaction, self.game, 'special', self.expire)
        modal.add_item(discord.ui.TextInput(label=f"Special Chance (Default: {defaults.special_chance})", placeholder="Enter the special1 chance", default=self.game['special_chance']))
        modal.add_item(discord.ui.TextInput(label=f"Special Min (Default: {defaults.special_min})", placeholder="Special minimum damage", default=self.game['special_min']))
        modal.add_item(discord.ui.TextInput(label=f"Special Max (Default: {defaults.special_max})", placeholder="Special maximum damage", default=self.game['special_max']))
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Set Weapon 1", style=discord.ButtonStyle.blurple, row=0)
    async def weapon1(self, interaction: discord.Interaction, button: discord.Button):
        modal = ConfigSettingsModal(self.bot, self.interaction, self.game, 'weapon1', self.expire)
        modal.add_item(discord.ui.TextInput(label=f"Weapon 1 Name (Default: {defaults.weapon1_name})", placeholder="Enter the name for the weapon", default=self.game['weapon1_name']))
        modal.add_item(discord.ui.TextInput(label=f"Weapon 1 Command (Default: {defaults.weapon1_alias})", placeholder="Enter the command to use", default=self.game['weapon1_alias']))
        modal.add_item(discord.ui.TextInput(label=f"Weapon 1 Chance (Default: {defaults.weapon1_chance})", placeholder="Enter the chance to hit", default=self.game['weapon1_chance']))
        modal.add_item(discord.ui.TextInput(label=f"Weapon 1 Min (Default: {defaults.weapon1_min})", placeholder="Weapon 1 minimum damage", default=self.game['weapon1_min']))
        modal.add_item(discord.ui.TextInput(label=f"Weapon 1 Max (Default: {defaults.weapon1_max})", placeholder="Weapon 1 maximum damage", default=self.game['weapon1_max']))
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Set Weapon 2", style=discord.ButtonStyle.blurple, row=0)
    async def weapon2(self, interaction: discord.Interaction, button: discord.Button):
        modal = ConfigSettingsModal(self.bot, self.interaction, self.game, 'weapon2', self.expire)
        modal.add_item(discord.ui.TextInput(label=f"Weapon 2 Name (Default: {defaults.weapon2_name})", placeholder="Enter the name for the weapon", default=self.game['weapon2_name']))
        modal.add_item(discord.ui.TextInput(label=f"Weapon 2 Command (Default: {defaults.weapon2_alias})", placeholder="Enter the command to use", default=self.game['weapon2_alias']))
        modal.add_item(discord.ui.TextInput(label=f"Weapon 2 Chance (Default: {defaults.weapon2_chance})", placeholder="Enter the chance to hit", default=self.game['weapon2_chance']))
        modal.add_item(discord.ui.TextInput(label=f"Weapon 2 Min (Default: {defaults.weapon2_min})", placeholder="Weapon minimum damage", default=self.game['weapon2_min']))
        modal.add_item(discord.ui.TextInput(label=f"Weapon 2 Max (Default: {defaults.weapon2_max})", placeholder="Weapon maximum damage", default=self.game['weapon2_max']))
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Set Random Attack", style=discord.ButtonStyle.blurple, row=0)
    async def random(self, interaction: discord.Interaction, button: discord.Button):
        modal = ConfigSettingsModal(self.bot, self.interaction, self.game, 'rand', self.expire)
        modal.add_item(discord.ui.TextInput(label=f"Random Attack Chance (Default: {defaults.rand_chance})", placeholder="Enter the chance for a random event", default=self.game['rand_chance']))
        modal.add_item(discord.ui.TextInput(label=f"Attack Min (Default: {defaults.rand_min})", placeholder="Event minimum damage", default=self.game['rand_min']))
        modal.add_item(discord.ui.TextInput(label=f"Attack Max (Default: {defaults.rand_max})", placeholder="Event maximum damage", default=self.game['rand_max']))
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Revive", style=discord.ButtonStyle.blurple, row=1)
    async def revive(self, interaction: discord.Interaction, button: discord.Button):
        modal = ConfigSettingsModal(self.bot, self.interaction, self.game, 'revive', self.expire)
        modal.add_item(discord.ui.TextInput(label=f"Revive Chance (Default: {defaults.revive_chance})", placeholder="Enter the chance for a revival", default=self.game['revive_chance']))
        modal.add_item(discord.ui.TextInput(label=f"Revive Min (Default: {defaults.revive_min})", placeholder="Revive min health", default=self.game['revive_min']))
        modal.add_item(discord.ui.TextInput(label=f"Revive Max (Default: {defaults.revive_max})", placeholder="Revive maximum health", default=self.game['revive_max']))
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Heal", style=discord.ButtonStyle.blurple, row=1)
    async def heal(self, interaction: discord.Interaction, button: discord.Button):
        modal = ConfigSettingsModal(self.bot, self.interaction, self.game, 'heal', self.expire)
        modal.add_item(discord.ui.TextInput(label=f"Heal Chance (Default: {defaults.heal_chance})", placeholder="Enter the chance for healing", default=self.game['heal_chance']))
        modal.add_item(discord.ui.TextInput(label=f"Heal Min (Default: {defaults.heal_min})", placeholder="Heal min health", default=self.game['heal_min']))
        modal.add_item(discord.ui.TextInput(label=f"Heal Max (Default: {defaults.heal_max})", placeholder="Heal maximum health", default=self.game['heal_max']))
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Potion", style=discord.ButtonStyle.blurple, row=1)
    async def potion(self, interaction: discord.Interaction, button: discord.Button):
        modal = ConfigSettingsModal(self.bot, self.interaction, self.game, 'potion', self.expire)
        modal.add_item(discord.ui.TextInput(label=f"Potion Name (Default: {defaults.potion_name})", placeholder="Enter the name for the potion", default=self.game['potion_name']))
        modal.add_item(discord.ui.TextInput(label=f"Potion Command (Default: {defaults.potion_alias})", placeholder="Enter the command to use", default=self.game['potion_alias']))
        modal.add_item(discord.ui.TextInput(label=f"Potion Chance (Default: {defaults.potion_chance})", placeholder="Enter the chance for a potion to work", default=self.game['potion_chance']))
        modal.add_item(discord.ui.TextInput(label=f"Potion Min (Default: {defaults.potion_min})", placeholder="Potion min health", default=self.game['potion_min']))
        modal.add_item(discord.ui.TextInput(label=f"Potion Max (Default: {defaults.potion_max})", placeholder="Potion maximum health", default=self.game['potion_max']))
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Main Image", style=discord.ButtonStyle.blurple, row=2)
    async def thumbnail(self, interaction: discord.Interaction, button: discord.Button):
        modal = ConfigSettingsModal(self.bot, self.interaction, self.game, 'thumbnail', self.expire)
        modal.add_item(discord.ui.TextInput(label=f"Image URL", placeholder="This is the main image"))
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Death Gif", style=discord.ButtonStyle.blurple, row=2)
    async def death(self, interaction: discord.Interaction, button: discord.Button):
        modal = ConfigSettingsModal(self.bot, self.interaction, self.game, 'death_gif', self.expire)
        modal.add_item(discord.ui.TextInput(label=f"GIF URL", placeholder="This is the death gif"))
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Revive Gif", style=discord.ButtonStyle.blurple, row=2)
    async def revive_gif(self, interaction: discord.Interaction, button: discord.Button):
        modal = ConfigSettingsModal(self.bot, self.interaction, self.game, 'revive_gif', self.expire)
        modal.add_item(discord.ui.TextInput(label=f"GIF URL", placeholder="This is the revive gif"))
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Emoji", style=discord.ButtonStyle.blurple, row=2)
    async def emoji(self, interaction: discord.Interaction, button: discord.Button):
        modal = ConfigSettingsModal(self.bot, self.interaction, self.game, 'emoji', self.expire)
        modal.add_item(discord.ui.TextInput(label=f"Emoji", placeholder="Paste the emoji. Ex. ⚔️"))
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Game Name", style=discord.ButtonStyle.blurple, row=2)
    async def game_name(self, interaction: discord.Interaction, button: discord.Button):
        modal = ConfigSettingsModal(self.bot, self.interaction, self.game, 'game_name', self.expire)
        modal.add_item(discord.ui.TextInput(label=f"Game Name", placeholder="Enter the game name"))
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Prefix", style=discord.ButtonStyle.blurple, row=3)
    async def prefix(self, interaction: discord.Interaction, button: discord.Button):
        modal = ConfigSettingsModal(self.bot, self.interaction, self.game, 'prefix', self.expire)
        modal.add_item(discord.ui.TextInput(label=f"Prefix for the Command", placeholder="Ex. !"))
        await interaction.response.send_modal(modal)


async def update_settings(bot, setting, value, guild_id):
    await db.write(f"UPDATE rumble_guild SET {setting} = %s WHERE guild_id = %s", (value, guild_id))
    bot.rumble[guild_id][setting] = value
