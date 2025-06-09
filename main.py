import discord
import aiohttp
import validators
import traceback
from discord.ext import commands
import cv2
import numpy as np
import asyncio
import os
import json
import tempfile
import io
import time
from typing import List, Optional, Dict
from dotenv import load_dotenv
from datetime import datetime, timedelta
from asyncio import Semaphore

# Configuration
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUESS_CHANNEL_NAME = 'guess-the-rank'
CHECK_CHANNEL_NAME = 'check-clips'
RESULTS_CHANNEL_NAME = 'result-graph'
ROLE_PING = '1379204201279782922' # ROTD ROLE ID
CLIP_DATA_FILE = 'pending_clips.json'
RESULTS_DATA_FILE = 'clip_results.json'
video_extensions = ['.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm']
MAX_CONCURRENT_PROCESSING = 3 # Max threads to not blow ffmpeg 
processing_semaphore = Semaphore(MAX_CONCURRENT_PROCESSING)
processing_queue = [] # Tuple containing user_id / message of position
CHANNEL_CONFIG_FILE = 'channel_config.json'

RANKS = [
    {"name": "Singularity", "emoji": "<:Singularity:1379365129380036618>"},
    {"name": "Superstring", "emoji": "<:Superstring:1379365132592873482>"},
    {"name": "Quark", "emoji": "<:Masters:1379365124309254146>"},
    {"name": "Electron", "emoji": "<:Electron:1379365122988048485>"},
    {"name": "Neutron", "emoji": "<:Neutron:1379365126842351706>"},
    {"name": "Proton", "emoji": "<:Proton:1379365128213893140>"},
    {"name": "Atom", "emoji": "<:Atom:1379365121176109108>"},
    {"name": "Molecule", "emoji": "<:Molecule:1379365125408034918>"},
    {"name": "Substance", "emoji": "<:Substance:1379365131129192488>"}
]

RANK_EMOJIS = {rank["name"]: rank["emoji"] for rank in RANKS}

# Bot configuration
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)
tree = bot.tree


##################################
###### SETUP CLASS ###############
##################################

class ChannelSetupModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Channel Setup Configuration")
        # Mod channel
        self.check_channel_input = discord.ui.TextInput(
            label="Check Channel Name",
            placeholder="Enter the name for the moderation channel (e.g., check-clips)",
            default="check-clips",
            max_length=100,
            required=True
        )
        #Guess my rank channel
        self.guess_channel_input = discord.ui.TextInput(
            label="Guess Channel Name", 
            placeholder="Enter the name for the guessing channel (e.g., guess-my-rank)",
            default="guess-the-rank",
            max_length=100,
            required=True
        )
        
        self.results_channel_input = discord.ui.TextInput(
            label="Results Channel Name",
            placeholder="Enter the name for the results channel (e.g., results)",
            default="result-graph",
            max_length=100,
            required=True
        )
        
        self.add_item(self.check_channel_input)
        self.add_item(self.guess_channel_input)
        self.add_item(self.results_channel_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        # Defer response immediately to prevent webhook timeout
        await interaction.response.defer(ephemeral=True)
        
        try:
            check_channel_name = self.check_channel_input.value.strip()
            guess_channel_name = self.guess_channel_input.value.strip()
            results_channel_name = self.results_channel_input.value.strip()
            
            # Save config
            save_channel_config(interaction.guild.id, check_channel_name, guess_channel_name, results_channel_name)
            
            # Get existing channels
            guess_channel = discord.utils.get(interaction.guild.channels, name=guess_channel_name)
            check_channel = discord.utils.get(interaction.guild.channels, name=check_channel_name)
            results_channel = discord.utils.get(interaction.guild.channels, name=results_channel_name)
            
            _, _, result_channel = get_channel_names(interaction.guild.id)
            
            # Update or create guess channel
            guess_embed = discord.Embed(
                title="🎮 Welcome to Guess The Rank!",
                description="In this channel, you'll see gameplay videos with the player's rank hidden.\n"
                        f"Try to guess their ranks, a chart will appear 24h later in #{result_channel} showing the rank distribution.",
                color=0x7AB0E7
            )
            
            if guess_channel:
                # Delete old messages and send new one
                try:
                    await guess_channel.purge(limit=10)
                except discord.Forbidden:
                    await interaction.followup.send(f"❌ I don't have permission to delete messages in #{guess_channel.name}", ephemeral=True)
                await guess_channel.send(embed=guess_embed)
            else:
                try:
                    guess_channel = await interaction.guild.create_text_channel(
                        guess_channel_name,
                        topic="🎮 Guess the rank of players from their videos!"
                    )
                    await guess_channel.send(embed=guess_embed)
                except Exception as e:
                    await interaction.followup.send(f"❌ Error creating {guess_channel_name}: {str(e)}", ephemeral=True)
                    return
            
            # Update or create check channel
            check_embed = discord.Embed(
                title="🔍 Clip Moderation",
                description=("This channel is for moderating clip submissions.\n"
                        "React with ✅ to approve clips or ❌ to reject them.\n"
                        f"Approved clips will be automatically posted to **{guess_channel_name}**"),
                color=0x7AB0E7
            )
            
            if check_channel:
                # Delete old messages and send new one
                try:
                    await check_channel.purge(limit=10)
                except discord.Forbidden:
                    await interaction.followup.send(f"❌ I don't have permission to delete messages in #{check_channel.name}", ephemeral=True)
                await check_channel.send(embed=check_embed)
            else:
                try:
                    check_channel = await interaction.guild.create_text_channel(
                        check_channel_name,
                        topic="🔍 Moderation channel for clip submissions"
                    )
                    await check_channel.send(embed=check_embed)
                except Exception as e:
                    await interaction.followup.send(f"❌ Error creating {check_channel_name}: {str(e)}", ephemeral=True)
                    return
            
            # Update or create results channel
            results_embed = discord.Embed(
                title="📊 Clip Results",
                description=("This channel displays the results of completed clips.\n"
                        "Results are automatically posted here 24 hours after a clip is published.\n"
                        f"Active voting happens in **{guess_channel_name}**"),
                color=0x7AB0E7
            )
        
            if results_channel:
                try:
                    await results_channel.purge(limit=10)
                except discord.Forbidden:
                    await interaction.followup.send(f"❌ I don't have permission to delete messages in #{results_channel.name}", ephemeral=True)
                await results_channel.send(embed=results_embed)
            else:
                try:
                    results_channel = await interaction.guild.create_text_channel(
                        results_channel_name,
                        topic="📊 Results channel for completed clips"
                    )
                    await results_channel.send(embed=results_embed)
                except Exception as e:
                    await interaction.followup.send(f"❌ Error creating {results_channel_name}: {str(e)}", ephemeral=True)
                    return
                    
            await interaction.followup.send(
                f"✅ Channels configured successfully:\n• #{check_channel_name}\n• #{guess_channel_name}\n• #{results_channel_name}",
                ephemeral=True
            )
            
        except Exception as e:
            await interaction.followup.send(f"❌ Setup failed: {str(e)}", ephemeral=True)

#####################################
####### RESULT SELECTOR #############
#####################################

class ResultsSelector(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=60)
        self.guild_id = guild_id
        
        # Take all the clips that are dones
        results_data = load_results_data()
        finished_clips = []
        
        if guild_id in results_data:
            server_clips = results_data[guild_id]
            for clip_id, clip_data in server_clips.items():
                if clip_data.get('expired', False):
                    end_time = datetime.fromisoformat(clip_data['end_time'])
                    date_str = end_time.strftime("%Y-%m-%d %H:%M")
                    rank_emoji = next((rank['emoji'] for rank in RANKS if rank['name'] == clip_data.get('correct_rank', '')), '🎮')
                    
                    finished_clips.append({
                        'clip_id': clip_id,
                        'date': date_str,
                        'rank': clip_data.get('correct_rank', 'Unknown'),
                        'emoji': rank_emoji,
                        'votes': clip_data.get('total_votes', 0)
                    })
        
        # Sort by date (newest first)
        finished_clips.sort(key=lambda x: x['date'], reverse=True)
        
        if not finished_clips:
            # No clip ended
            self.clip_select = discord.ui.Select(
                placeholder="No finished clips available",
                min_values=1,
                max_values=1,
                options=[discord.SelectOption(label="No clips", value="none", description="No finished clips found")]
            )
            self.clip_select.disabled = True
        else:
            # Limit is 25 (discord)
            finished_clips = finished_clips[:25]
            
            self.clip_select = discord.ui.Select(
                placeholder="Select a clip to view results...",
                min_values=1,
                max_values=1,
                options=[
                    discord.SelectOption(
                        label=f"{clip['date']} - {clip['rank']}",
                        value=clip['clip_id'],
                        description=f"{clip['votes']} votes • {clip['rank']} rank",
                        emoji=clip['emoji']
                    ) for clip in finished_clips
                ]
            )
        
        self.clip_select.callback = self.select_callback
        self.add_item(self.clip_select)
    
    async def select_callback(self, interaction: discord.Interaction):
        if self.clip_select.values[0] == "none":
            await interaction.response.send_message("❌ No clips available.", ephemeral=True)
            return
        
        clip_id = self.clip_select.values[0]
        results_embed = get_results_embed(clip_id, self.guild_id)
        
        if results_embed:
            results_embed.set_footer(text=f"Clip ID: {clip_id}")
            await interaction.response.send_message(embed=results_embed, ephemeral=True)
        else:
            await interaction.response.send_message("❌ Error loading results for this clip.", ephemeral=True)
            
            
######################################
###### Server Selector ###############
######################################

class ServerSelector(discord.ui.View):
    def __init__(self, user_id: int, video_path: str, available_servers: list):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.video_path = video_path
        self.available_servers = available_servers
        
        # Create dropdown with server options
        options = []
        for i, server_info in enumerate(available_servers):
            guild = server_info['guild']
            options.append(
                discord.SelectOption(
                    label=guild.name,
                    value=str(i),
                    description=f"Members: {guild.member_count}",
                    emoji="🎮"
                )
            )
        
        self.server_select = discord.ui.Select(
            placeholder="Choose a server...",
            min_values=1,
            max_values=1,
            options=options
        )
        self.server_select.callback = self.server_callback
        self.add_item(self.server_select)
    
    async def server_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This is not your server selection!", ephemeral=True)
            return
        
        selected_index = int(self.server_select.values[0])
        selected_server = self.available_servers[selected_index]
        
        # Now show rank selection for the chosen server
        view = RankSelector(self.user_id, self.video_path, selected_server['guild'].id)
        
        embed = discord.Embed(
            title="🎮 Rank Selection",
            description=f"Submitting to: **{selected_server['guild'].name}**\n\n"
                    "Choose your rank from the dropdown menu below.",
            color=0x7AB0E7
        )
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)



######################################
###### DMS SELECTOR ##################
######################################

class RankSelector(discord.ui.View):
    def __init__(self, user_id: int, video_path: str, guild_id: int= None):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.video_path = video_path
        self.selected_rank = None
        self.guild_id = guild_id
        
        # Dropdown DMS
        self.rank_select = discord.ui.Select(
            placeholder="Choose your rank...",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label=rank["name"], 
                    value=rank["name"], 
                    emoji=rank["emoji"]
                ) for rank in RANKS
            ]
        )
        self.rank_select.callback = self.rank_callback
        self.add_item(self.rank_select)
        
    
    async def rank_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This is not your rank selection!", ephemeral=True)
            return
        
        self.selected_rank = self.rank_select.values[0]
        await interaction.response.send_message(f"Selected rank: **{self.selected_rank}**",ephemeral=True)
        
        await self.process_and_send_video(interaction)
    
    async def process_and_send_video(self, interaction: discord.Interaction):
        try:
            # Get original file size for logging
            original_size_mb = os.path.getsize(self.video_path) / (1024 * 1024)

            # Check if we need to queue
            if processing_semaphore.locked() and len(processing_queue) == 0:
                queue_position = await add_to_queue(self.user_id, interaction)
            elif len(processing_queue) > 0:
                queue_position = await add_to_queue(self.user_id, interaction)
            
            # Wait for our turn
            async with processing_semaphore:
                # Remove from queue when processing starts
                await remove_from_queue(self.user_id)
                
                await interaction.followup.send(
                    content=f"🔄 Now processing your video... ({original_size_mb:.1f}MB)\nThis may take a few minutes.",
                    ephemeral=True
                )

                # Process the video with blur
                try:
                    blurred_video_path = await asyncio.wait_for(
                        blur_video(self.video_path),
                        timeout=600
                    )
                except TimeoutError:
                    await interaction.followup.send(
                        content="❌ Video processing took too long and timed out.",
                        ephemeral=True
                    )
                    cleanup_files([self.video_path])
                    return

                final_size_mb = os.path.getsize(blurred_video_path) / (1024 * 1024)

                # Find the moderation channel
                check_channel = None
                if self.guild_id:
                    guild = bot.get_guild(self.guild_id)
                    if guild:
                        check_channel_name,_,_ = get_channel_names(guild.id)
                        check_channel = discord.utils.get(guild.channels, name=check_channel_name)

                if not check_channel:
                    await interaction.followup.send(
                        content=f"❌ Moderation channel not found! Use /setup to configure channels.",
                        ephemeral=True
                    )
                    cleanup_files([self.video_path, blurred_video_path])
                    return

                # Always use external hosting for reliability and visual display
                video_url = await upload_to_catbox(blurred_video_path)

                if not video_url:
                    await interaction.followup.send(
                        content="❌ Failed to upload video to external hosting. Please try again.",
                        ephemeral=True
                    )
                    cleanup_files([self.video_path, blurred_video_path])
                    return

                # Create moderation message with visual embed
                message_content = (
                    f"🎮 **Clip Submission for Review**\n\n"
                    f"Submitted by: {interaction.user.mention}\n"
                    f"Claimed rank: **{self.selected_rank}**\n"
                    f"File size: {original_size_mb:.1f}MB → {final_size_mb:.1f}MB\n\n"
                    f"React with ✅ to approve or ❌ to reject this clip."
                )

                # Create embed that shows video preview directly in Discord
                embed = discord.Embed(
                    title="📹 Video Submission",
                    description="Video preview below - click link for full quality",
                    color=0x7AB0E7
                )
                embed.set_image(url=video_url)  # This shows the video preview in Discord
                embed.add_field(name="🎬 Full Quality", value=f"[Open in browser]({video_url})", inline=False)
                embed.add_field(name="👤 Submitter", value=interaction.user.mention, inline=True)
                embed.add_field(name="🏆 Claimed Rank", value=f"**{self.selected_rank}**", inline=True)

                moderation_message = await check_channel.send(message_content, embed=embed)
                await moderation_message.add_reaction("✅")
                await moderation_message.add_reaction("❌")

                # Store moderation data
                clip_data = {
                    'rank': self.selected_rank,
                    'user_id': interaction.user.id,
                    'user_mention': interaction.user.mention,
                    'video_url': video_url,
                    'file_size_mb': final_size_mb,
                    'guild_id': self.guild_id
                }

                if not hasattr(bot, 'pending_clips'):
                    if os.path.exists(CLIP_DATA_FILE):
                        with open(CLIP_DATA_FILE, 'r') as f:
                            data = json.load(f)
                            bot.pending_clips = {}
                            # Convert string keys to int for guild IDs
                            for guild_str, clips in data.items():
                                try:
                                    guild_id = int(guild_str)
                                    bot.pending_clips[guild_id] = clips
                                except ValueError:
                                    # Handle old format where clips were at root level
                                    if isinstance(clips, dict) and 'guild_id' in clips:
                                        # This is a clip data, not a server container
                                        clip_guild_id = clips.get('guild_id', self.guild_id)
                                        if clip_guild_id not in bot.pending_clips:
                                            bot.pending_clips[clip_guild_id] = {}
                                        bot.pending_clips[clip_guild_id][guild_str] = clips
                    else:
                        bot.pending_clips = {}

                # Ensure server structure exists
                if self.guild_id not in bot.pending_clips:
                    bot.pending_clips[self.guild_id] = {}

                # Store under the message ID
                bot.pending_clips[self.guild_id][str(moderation_message.id)] = clip_data

                with open(CLIP_DATA_FILE, 'w') as f:
                    json.dump(bot.pending_clips, f, indent=2)

                await interaction.followup.send(
                    content=f"✅ Video processed and uploaded successfully!\nFinal size: {final_size_mb:.1f}MB\nPreview will be visible in moderation channel.",
                    ephemeral=True
                )

                cleanup_files([self.video_path, blurred_video_path])

        except Exception as e:
            # Make sure to remove from queue on error
            await remove_from_queue(self.user_id)
            await interaction.followup.send(
                content="❌ Processing error. Please contact vaporr on Discord with a screenshot.",
                ephemeral=True
            )
            print(f"Processing Error: {e}")
            traceback.print_exc()
            cleanup_files([self.video_path])

class GuessRankSelector(discord.ui.View):
    def __init__(self, clip_id: str, correct_rank: str):
        super().__init__(timeout=None)  # No timeout for persistent views
        self.clip_id = clip_id
        self.correct_rank = correct_rank
        
        # Create rank options using the RANKS list
        rank_options = []
        for rank in RANKS:
            rank_options.append(
                discord.SelectOption(label=rank["name"], value=rank["name"], emoji=rank["emoji"])
            )
        
        self.rank_select = discord.ui.Select(
            placeholder="Select your rank guess...",
            min_values=1,
            max_values=1,
            options=rank_options,
            custom_id=f"rank_select_{clip_id}"  # Add custom_id for persistence
        )
        self.rank_select.callback = self.guess_callback
        self.add_item(self.rank_select)
    
    async def guess_callback(self, interaction: discord.Interaction):
        selected_rank = self.rank_select.values[0]
        user_id = interaction.user.id
        guild_id = interaction.guild.id
        
        # Check server-specific voting data
        results_data = load_results_data()
        
        if guild_id not in results_data or self.clip_id not in results_data[guild_id]:
            await interaction.response.send_message("❌ Clip data not found for this server!", ephemeral=True)
            return
        
        clip_data = results_data[guild_id][self.clip_id]
        
        # Check if voting period has expired
        end_time = datetime.fromisoformat(clip_data['end_time'])
        if datetime.now() > end_time:
            await interaction.response.send_message("❌ Voting period has ended for this clip!", ephemeral=True)
            return
        
        # Initialize user vote tracking
        if 'user_votes' not in clip_data:
            clip_data['user_votes'] = {}
        if 'user_vote_count' not in clip_data:
            clip_data['user_vote_count'] = {}
        
        user_vote_count = clip_data['user_vote_count'].get(str(user_id), 0)
        previous_vote = clip_data['user_votes'].get(str(user_id))
        
        # Check vote limit (1 original + 1 change = 2 total)
        if user_vote_count >= 2:
            await interaction.response.send_message("❌ You've reached the vote limit! (1 original vote + 1 change allowed)", ephemeral=True)
            return
        
        if previous_vote:
            # User is changing their vote
            if previous_vote == selected_rank:
                await interaction.response.send_message("❌ You've already voted for this rank!", ephemeral=True)
                return
                
            # Remove previous vote from rank count
            if previous_vote in clip_data['votes']:
                clip_data['votes'][previous_vote] = max(0, clip_data['votes'][previous_vote] - 1)
                if clip_data['votes'][previous_vote] == 0:
                    del clip_data['votes'][previous_vote]
            
            # Update correct votes count if needed
            if previous_vote == clip_data['correct_rank']:
                clip_data['correct_votes'] = max(0, clip_data['correct_votes'] - 1)
                
            # Increment vote count for this user
            clip_data['user_vote_count'][str(user_id)] = user_vote_count + 1
            vote_text = f"changed your vote to **{selected_rank}**! (Vote changes remaining: 0)"
        else:
            # New vote
            clip_data['total_votes'] += 1
            clip_data['user_vote_count'][str(user_id)] = 1
            vote_text = f"voted **{selected_rank}**! (You can change your vote 1 more time)"
        
        # Add new vote
        clip_data['user_votes'][str(user_id)] = selected_rank
        
        # Update rank vote count
        if 'votes' not in clip_data:
            clip_data['votes'] = {}
        if selected_rank not in clip_data['votes']:
            clip_data['votes'][selected_rank] = 0
        clip_data['votes'][selected_rank] += 1
        
        # Update correct votes count
        if selected_rank == clip_data['correct_rank']:
            clip_data['correct_votes'] += 1
        
        # Save updated server-specific data
        results_data[guild_id][self.clip_id] = clip_data
        save_results_data(results_data)
        
        # Send confirmation to user
        await interaction.response.send_message(
            f"✅ You {vote_text} Results will be revealed when voting ends.",
            ephemeral=True
        )

    async def disable_view_in_message(self, guild_id: int):
        """Disable the view when the voting period expires"""
        try:
            # Find the message and disable the view
            results_data = load_results_data()
            if guild_id in results_data and self.clip_id in results_data[guild_id]:
                clip_data = results_data[guild_id][self.clip_id]
                message_id = clip_data.get('message_id')
                
                if message_id:
                    guild = bot.get_guild(guild_id)
                    if guild:
                        _, guess_channel_name, _ = get_channel_names(guild_id)
                        guess_channel = discord.utils.get(guild.channels, name=guess_channel_name)
                        
                        if guess_channel:
                            try:
                                message = await guess_channel.fetch_message(message_id)
                                # Disable all items in the view
                                for item in self.children:
                                    item.disabled = True
                                
                                # Update the message with disabled view
                                await message.edit(view=self)
                                
                                # Schedule message deletion after a short delay to allow users to see final state
                                await asyncio.sleep(10)  # Wait 10 seconds
                                await message.delete()
                                print(f"Deleted guess message for clip {self.clip_id} in guild {guild_id}")
                                
                            except discord.NotFound:
                                pass  # Message was already deleted
                            except Exception as e:
                                print(f"Error disabling view: {e}")
        except Exception as e:
            print(f"Error in disable_view_in_message: {e}")


    async def on_timeout(self):
        """Handle when the view times out (24 hours)"""
        guild_id = None
        
        # Try to get guild_id from clip_id if it follows the pattern "guild_id_timestamp"
        try:
            if "_" in self.clip_id:
                guild_id = int(self.clip_id.split("_")[0])
        except:
            pass
        
        if guild_id:
            results_data = load_results_data()
            
            if guild_id in results_data and self.clip_id in results_data[guild_id]:
                # Mark as expired
                results_data[guild_id][self.clip_id]['expired'] = True
                save_results_data(results_data)
        
        # Disable all items
        for item in self.children:
            item.disabled = True

#####################################################################################
#################################### UTILS ##########################################
#####################################################################################

async def upload_to_catbox(file_path: str) -> str | None:
    """Upload video to catbox.moe and return the URL"""
    try:
        timeout = aiohttp.ClientTimeout(total=1800)  # 30 minutes for large files
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            with open(file_path, 'rb') as f:
                data = aiohttp.FormData()
                data.add_field('reqtype', 'fileupload')
                data.add_field('fileToUpload', f, filename='video.mp4', content_type='video/mp4')
                
                async with session.post('https://catbox.moe/user/api.php', data=data) as response:
                    if response.status == 200:
                        url = await response.text()
                        if url.startswith('https://files.catbox.moe/'):
                            return url.strip()
                    
                    print(f"Catbox upload failed: {response.status}")
                    return None
                    
    except Exception as e:
        print(f"Error uploading to catbox: {e}")
        return None

async def add_to_queue(user_id: int, interaction: discord.Interaction) -> int:
    """Add user to processing queue and return their position"""
    position = len(processing_queue) + 1
    
    # Send initial queue message
    queue_embed = discord.Embed(
        title="⏳ Added to Processing Queue",
        description=f"You are **#{position}** in the queue.\nProcessing up to {MAX_CONCURRENT_PROCESSING} videos simultaneously.",
        color=0x7AB0E7
    )
    
    try:
        message = await interaction.followup.send(embed=queue_embed, ephemeral=True)
        processing_queue.append((user_id, message))
        
        # Start background task to update queue position
        asyncio.create_task(update_queue_position(user_id))
        
        return position
    except:
        return position

async def remove_from_queue(user_id: int):
    """Remove user from queue and update positions for others"""
    global processing_queue
    
    # Remove user from queue
    processing_queue = [(uid, msg) for uid, msg in processing_queue if uid != user_id]
    
    # Update positions for remaining users
    for i, (uid, message) in enumerate(processing_queue):
        new_position = i + 1
        try:
            queue_embed = discord.Embed(
                title="⏳ Queue Position Updated",
                description=f"You are now **#{new_position}** in the queue.\nProcessing up to {MAX_CONCURRENT_PROCESSING} videos simultaneously.",
                color=0x7AB0E7
            )
            await message.edit(embed=queue_embed)
        except:
            pass  # Message might be deleted or expired

async def update_queue_position(user_id: int):
    """Background task to update queue position every 2 minutes"""
    while True:
        await asyncio.sleep(120)  # 2 minutes
        
        # Find user in queue
        user_found = False
        for i, (uid, message) in enumerate(processing_queue):
            if uid == user_id:
                user_found = True
                position = i + 1
                try:
                    queue_embed = discord.Embed(
                        title="⏳ Queue Position Update",
                        description=f"You are **#{position}** in the queue.\nProcessing up to {MAX_CONCURRENT_PROCESSING} videos simultaneously.\n\n*Updated every 2 minutes*",
                        color=0x7AB0E7
                    )
                    await message.edit(embed=queue_embed)
                except:
                    pass  # Message might be deleted
                break
        
        if not user_found:
            break  # User no longer in queue, stop updating

async def download_video_from_url(url: str, max_size_mb: int = 200) -> str | None:
    try:
        timeout = aiohttp.ClientTimeout(total=600) #10min timeout
        headers = {"User-Agent": "Mozilla/5.0"}

        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    print(f"HTTP error: {response.status}")
                    return None

                content_type = response.headers.get("Content-Type", "")
                if "video" not in content_type and not url.lower().endswith(tuple(video_extensions)):
                    print(f"Invalid content-type: {content_type}")
                    return None

                suffix = os.path.splitext(url.split("?")[0])[1]
                fd, temp_path = tempfile.mkstemp(suffix=suffix)
                os.close(fd)

                max_bytes = max_size_mb * 1024 * 1024
                total_downloaded = 0

                with open(temp_path, "wb") as f:
                    async for chunk in response.content.iter_chunked(64 * 1024):  # 64KB chunks
                        total_downloaded += len(chunk)
                        if total_downloaded > max_bytes:
                            print("File too large, aborting")
                            os.remove(temp_path)
                            return None
                        f.write(chunk)

                return temp_path
    except Exception as e:
        print(f"Download error: {e}")
        traceback.print_exc()
        return None

def load_channel_config() -> Dict:
    """Load channel configuration from JSON file"""
    if os.path.exists(CHANNEL_CONFIG_FILE):
        with open(CHANNEL_CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_channel_config(guild_id: int, check_channel: str, guess_channel: str, results_channel: str):
    """Save channel configuration to JSON file"""
    config = load_channel_config()
    config[str(guild_id)] = {
        'check_channel': check_channel,
        'guess_channel': guess_channel,
        'results_channel': results_channel
    }
    with open(CHANNEL_CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

def get_channel_names(guild_id: int) -> tuple:
    """Get configured channel names for a guild"""
    config = load_channel_config()
    guild_config = config.get(str(guild_id), {})
    
    check_channel = guild_config.get('check_channel', CHECK_CHANNEL_NAME)
    guess_channel = guild_config.get('guess_channel', GUESS_CHANNEL_NAME) 
    results_channel = guild_config.get('results_channel', RESULTS_CHANNEL_NAME)    
    return check_channel, guess_channel, results_channel   

def cleanup_files(file_paths: List[str]):
    """Clean up temporary files"""
    for path in file_paths:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            print(f"Error cleaning up {path}: {e}")

def load_results_data():
    """Load results data with server-specific structure"""
    if os.path.exists(RESULTS_DATA_FILE):
        with open(RESULTS_DATA_FILE, 'r') as f:
            data = json.load(f)
            # Convert string server IDs back to int, but keep clip IDs as strings
            server_data = {}
            for server_id, clips in data.items():
                server_data[int(server_id)] = clips  # Don't convert clip_id keys to int
            return server_data
    return {}

def save_results_data(data):
    """Save results data with server-specific structure"""
    # Convert int server IDs to strings for JSON serialization, keep clip IDs as strings
    server_data = {}
    for server_id, clips in data.items():
        server_data[str(server_id)] = clips  # Keep clip data as-is
    
    with open(RESULTS_DATA_FILE, 'w') as f:
        json.dump(server_data, f, indent=2)

def save_vote(clip_id, rank, user_id, guild_id):
    """Save a vote for a specific server"""
    results_data = load_results_data()
    
    if guild_id not in results_data:
        results_data[guild_id] = {}
    
    if clip_id not in results_data[guild_id]:
        results_data[guild_id][clip_id] = {
            'votes': {},
            'total_votes': 0,
            'correct_votes': 0,
            'created_time': datetime.now().isoformat(),
            'end_time': (datetime.now() + timedelta(hours=24)).isoformat(),
            'expired': False
        }
    
    # Remove previous vote if exists
    if str(user_id) in results_data[guild_id][clip_id]['votes']:
        old_rank = results_data[guild_id][clip_id]['votes'][str(user_id)]
        results_data[guild_id][clip_id]['votes'][old_rank] = results_data[guild_id][clip_id]['votes'][old_rank] - 1
    else:
        results_data[guild_id][clip_id]['total_votes'] += 1
    
    # Add new vote
    results_data[guild_id][clip_id]['votes'][str(user_id)] = rank
    if rank not in results_data[guild_id][clip_id]['votes']:
        results_data[guild_id][clip_id]['votes'][rank] = 0
    results_data[guild_id][clip_id]['votes'][rank] += 1
    
    save_results_data(results_data)

def create_clip_entry(correct_rank: str) -> str:
    """Create a new clip entry in results data"""
    results_data = load_results_data()
    # Generate unique clip ID
    clip_id = f"clip_{len(results_data) + 1}_{int(datetime.now().timestamp())}"
    # Create entry
    end_time = datetime.now() + timedelta(hours=24)
    
    clip_entry = {
        'correct_rank': correct_rank,
        'end_time': end_time.isoformat(),
        'votes': {rank['name']: [] for rank in RANKS},  # Store user IDs
        'total_votes': 0,
        'expired': False
    }  
    results_data[clip_id] = clip_entry
    save_results_data(results_data)
    
    return clip_id

def save_vote(clip_id: str, guessed_rank: str, user_id: int):
    """Save a user's vote"""
    results_data = load_results_data()
    
    if clip_id not in results_data:
        return False
    
    # Check if user already voted
    for rank_votes in results_data[clip_id]['votes'].values():
        if user_id in rank_votes:
            return False  # User already voted
    
    # Add vote
    results_data[clip_id]['votes'][guessed_rank].append(user_id)
    results_data[clip_id]['total_votes'] += 1
    
    save_results_data(results_data)
    return True

def get_results_embed(clip_id: str, guild_id: int) -> discord.Embed:
    """Generate results embed with percentages for a specific server"""
    results_data = load_results_data()
    
    # Check if server and clip exist
    if guild_id not in results_data or clip_id not in results_data[guild_id]:
        return None
    
    clip_data = results_data[guild_id][clip_id]
    correct_rank = clip_data.get('correct_rank', 'Unknown')
    total_votes = clip_data.get('total_votes', 0)
    
    embed = discord.Embed(
        title="🎯 Results - Guess The Rank",
        description=f"**Correct Rank:** {correct_rank}\n**Total Votes:** {total_votes}",
        color=0x7AB0E7
    )
    
    # Calculate percentages from vote data
    votes_data = clip_data.get('votes', {})
    results_text = ""
    
    for rank in RANKS:
        rank_name = rank['name']
        votes_count = votes_data.get(rank_name, 0)
        percentage = (votes_count / total_votes * 100) if total_votes > 0 else 0
        
        emoji = rank['emoji']
        if rank_name == correct_rank:
            results_text += f"{emoji} **{rank_name}**: {votes_count} votes ({percentage:.1f}%) ✅\n"
        else:
            results_text += f"{emoji} {rank_name}: {votes_count} votes ({percentage:.1f}%)\n"
    
    embed.add_field(name="📊 Vote Distribution", value=results_text, inline=False)
    
    return embed

async def register_persistent_views():
    """Register persistent views for all active clips across all servers"""
    results_data = load_results_data()
    current_time = datetime.now()
    
    for guild_id, server_clips in results_data.items():
        for clip_id, clip_data in server_clips.items():
            # Only register views for clips that haven't expired
            if not clip_data.get('expired', False):
                try:
                    # Double-check if the clip should have expired by now
                    end_time = datetime.fromisoformat(clip_data['end_time'])
                    if current_time <= end_time:
                        # Clip is still active, register the view
                        view = GuessRankSelector(clip_id, clip_data.get('correct_rank', 'Unknown'))
                        bot.add_view(view)
                        print(f"Registered persistent view for clip {clip_id} in guild {guild_id}")
                    else:
                        # Clip should have expired, mark it as such
                        clip_data['expired'] = True
                        print(f"Marked clip {clip_id} as expired during registration")
                except Exception as e:
                    print(f"Error registering view for clip {clip_id}: {e}")
    
    # Save any changes made during registration
    save_results_data(results_data)

async def check_expired_clips():
    """Check for expired clips and post results for each server"""
    results_data = load_results_data()
    current_time = datetime.now()
    
    for guild_id, server_clips in results_data.items():
        for clip_id, clip_data in server_clips.items():
            if clip_data.get('expired', False):
                continue
                
            end_time = datetime.fromisoformat(clip_data['end_time'])
            
            if current_time > end_time:
                # Mark as expired
                clip_data['expired'] = True
                
                # Disable the voting view
                try:
                    # Create a temporary view instance to disable it
                    temp_view = GuessRankSelector(clip_id, clip_data.get('correct_rank', 'Unknown'))
                    await temp_view.disable_view_in_message(guild_id)
                except Exception as e:
                    print(f"Error disabling view for clip {clip_id}: {e}")
                
                # Find the results channel for this specific server
                guild = bot.get_guild(guild_id)
                if guild:
                    _, _, results_channel_name = get_channel_names(guild.id)
                    results_channel = discord.utils.get(guild.channels, name=results_channel_name)
                    
                    if results_channel:
                        results_embed = get_results_embed(clip_id, guild_id)
                        if results_embed:
                            try:
                                await results_channel.send(embed=results_embed)
                            except Exception as e:
                                print(f"Error posting results to {guild.name}: {e}")
    
    save_results_data(results_data)


async def save_video_from_attachment(attachment: discord.Attachment) -> Optional[str]:
    """Download and save video from Discord attachment"""
    
    # Supported video extensions
    video_extensions = ['.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm']
    
    # Check if it's a video
    if not any(attachment.filename.lower().endswith(ext) for ext in video_extensions):
        return None
    
    # Create temporary file
    fd, temp_path = tempfile.mkstemp(suffix=os.path.splitext(attachment.filename)[1])
    os.close(fd)
    
    try:
        # DL File
        await attachment.save(temp_path)
        return temp_path
    except Exception as e:
        print(f"Download error: {e}")
        cleanup_files([temp_path])
        return None

import os
import json
import tempfile
import asyncio
import subprocess

async def blur_video(input_path: str, target_size_mb: int = 20) -> str:
    """Apply adaptive blur and compress video using FFmpeg."""
    # Create temporary output file
    output_fd, output_path = tempfile.mkstemp(suffix='.mp4')
    os.close(output_fd)

    # FFprobe to get video info
    try:
        probe_cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_format', '-show_streams', input_path
        ]
        probe_proc = await asyncio.create_subprocess_exec(
            *probe_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await probe_proc.communicate()
        if probe_proc.returncode != 0:
            raise Exception(f"FFprobe failed: {stderr.decode()}")

        probe_data = json.loads(stdout.decode())

        # Extract resolution and duration
        video_stream = next((s for s in probe_data['streams'] if s['codec_type'] == 'video'), None)
        if not video_stream:
            raise Exception("No video stream found")

        width = int(video_stream['width'])
        height = int(video_stream['height'])
        duration = float(probe_data['format']['duration'])

        # Compute bitrate
        target_bitrate_kbps = int((target_size_mb * 8192) / duration)
        target_bitrate_kbps = max(500, min(target_bitrate_kbps, 5000))

        # Build base FFmpeg command
        ffmpeg_cmd = ['ffmpeg', '-y', '-i', input_path]

        # Conditional blur
        if width == 1920 and height == 1080:
            # Blur parameters
            left_blur_x = 103
            left_blur_y = 98
            left_blur_width = 333
            left_blur_height = 240

            bottom_blur_width = 293
            bottom_blur_height = 28
            bottom_blur_x = 764
            bottom_blur_y = 1032

            voice_chat_width = 198
            voice_chat_height = 502
            voice_chat_x = 38
            voice_chat_y = 357

            text_chat_width = 425
            text_chat_height = 168
            text_chat_x = 25
            text_chat_y = 695

            replay_name_x = 730
            replay_name_y = 1043
            replay_name_width = 241
            replay_name_height = 25

            # Filter complex for blur
            filter_complex = (
                f"[0:v]split=6[main][left_crop][bottom_crop][voice_crop][text_crop][replay_crop];"
                f"[left_crop]crop={left_blur_width}:{left_blur_height}:{left_blur_x}:{left_blur_y},boxblur=lr=12:cr=6[left_blur];"
                f"[bottom_crop]crop={bottom_blur_width}:{bottom_blur_height}:{bottom_blur_x}:{bottom_blur_y},boxblur=lr=12:cr=6[bottom_blur];"
                f"[voice_crop]crop={voice_chat_width}:{voice_chat_height}:{voice_chat_x}:{voice_chat_y},boxblur=lr=12:cr=6[voice_blur];"
                f"[text_crop]crop={text_chat_width}:{text_chat_height}:{text_chat_x}:{text_chat_y},boxblur=lr=12:cr=6[text_blur];"
                f"[replay_crop]crop={replay_name_width}:{replay_name_height}:{replay_name_x}:{replay_name_y},boxblur=lr=12:cr=6[replay_blur];"
                f"[main][left_blur]overlay={left_blur_x}:{left_blur_y}[tmp1];"
                f"[tmp1][bottom_blur]overlay={bottom_blur_x}:{bottom_blur_y}[tmp2];"
                f"[tmp2][voice_blur]overlay={voice_chat_x}:{voice_chat_y}[tmp3];"
                f"[tmp3][replay_blur]overlay={replay_name_x}:{replay_name_y}[tmp4];"
                f"[tmp4][text_blur]overlay={text_chat_x}:{text_chat_y}[vout]"
            )

            ffmpeg_cmd += ['-filter_complex', filter_complex, '-map', '[vout]']
        else:
            ffmpeg_cmd += ['-map', '0:v']

        # Final encoding settings
        ffmpeg_cmd += [
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '22',
            '-maxrate', f'{target_bitrate_kbps}k',
            '-bufsize', f'{2 * target_bitrate_kbps}k',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
            output_path
        ]

        # Execute FFmpeg
        proc = await asyncio.create_subprocess_exec(
            *ffmpeg_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise Exception(f"FFmpeg failed: {stderr.decode()}")

        print(f"Output video size: {os.path.getsize(output_path) / (1024 * 1024):.2f} MB")
        return output_path

    except Exception as e:
        if os.path.exists(output_path):
            os.remove(output_path)
        raise e

@bot.event
async def on_ready():
    print(f'{bot.user} is connected and ready!')
    await tree.sync()
    print(f'Servers: {len(bot.guilds)}')
    
    # Load clip data if not already loaded
    if not hasattr(bot, 'pending_clips'):
        if os.path.exists(CLIP_DATA_FILE):
            with open(CLIP_DATA_FILE, 'r') as f:
                data = json.load(f)
                bot.pending_clips = {}
                # Convert string keys to int for guild IDs, handle migration
                for key, value in data.items():
                    try:
                        guild_id = int(key)
                        if isinstance(value, dict):
                            # Check if this is a server container or individual clip
                            if any(isinstance(v, dict) and 'rank' in v for v in value.values()):
                                # This is a proper server container
                                bot.pending_clips[guild_id] = value
                            else:
                                # This might be an individual clip
                                bot.pending_clips[guild_id] = {key: value}
                        else:
                            bot.pending_clips[guild_id] = {}
                    except ValueError:
                        # Handle old format - this key is actually a message ID
                        if isinstance(value, dict) and 'guild_id' in value:
                            clip_guild_id = value.get('guild_id')
                            if clip_guild_id not in bot.pending_clips:
                                bot.pending_clips[clip_guild_id] = {}
                            bot.pending_clips[clip_guild_id][key] = value
        else:
            bot.pending_clips = {}
    
    # Start background task to check expired clips
    bot.loop.create_task(background_check_expired())
    # Put back the views so we can votes even if the bot dc for a seconds, we didn't lose states
    bot.loop.create_task(register_persistent_views())

async def background_check_expired():
    """Background task to check for expired clips every minute"""
    while True:
        try:
            await check_expired_clips()
        except Exception as e:
            print(f"Error checking expired clips: {e}")
        await asyncio.sleep(60)  # Check every minute

@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id:
        return

    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return Exception

    channel = guild.get_channel(payload.channel_id)
    if not channel:
        return Exception

    # Check if this is a moderation channel for this specific server
    check_channel_name, guess_channel_name, results_channel_name = get_channel_names(guild.id)
    if channel.name != check_channel_name:
        return

    message_id = payload.message_id
    
    # Check server-specific pending clips
    if not hasattr(bot, 'pending_clips'):
        bot.pending_clips = {}

    if guild.id not in bot.pending_clips:
        # Try to load from file for this server
        if os.path.exists(CLIP_DATA_FILE):
            with open(CLIP_DATA_FILE, 'r') as f:
                all_clips = json.load(f)
                bot.pending_clips = {}
                # Convert string keys to int for guild IDs and handle migration
                for key, value in all_clips.items():
                    try:
                        server_id = int(key)
                        if isinstance(value, dict):
                            # Check if this looks like a server container
                            if any(isinstance(v, dict) and 'rank' in v for v in value.values()):
                                bot.pending_clips[server_id] = value
                            else:
                                bot.pending_clips[server_id] = {}
                        else:
                            bot.pending_clips[server_id] = {}
                    except ValueError:
                        # This is an old format message ID at root level
                        if isinstance(value, dict) and 'guild_id' in value:
                            clip_guild_id = value.get('guild_id')
                            if clip_guild_id not in bot.pending_clips:
                                bot.pending_clips[clip_guild_id] = {}
                            bot.pending_clips[clip_guild_id][key] = value
        else:
            bot.pending_clips[guild.id] = {}
        
    # Check if this message has clip data for this server
    if guild.id not in bot.pending_clips or str(message_id) not in bot.pending_clips[guild.id]:
        return

    clip_data = bot.pending_clips[guild.id][str(message_id)]
    message = await channel.fetch_message(message_id)
    check_channel = channel
    
    # Find the guess channel for this server
    guess_channel = discord.utils.get(guild.channels, name=guess_channel_name)
    if not guess_channel:
        return

    if str(payload.emoji) == "✅":
        # Approval - post to guess channel
        try:
            # Get video content
            video_content = None
            video_url = clip_data.get('video_url')
            
            if video_url:
                # External hosting - create embed
                embed = discord.Embed(
                    title="🎮 Guess the Rank!",
                    description="Watch the video and guess what rank this player is!",
                    color=0x7AB0E7
                )
                embed.add_field(name="🎬 Video", value=f"[Watch Video]({video_url})", inline=False)
                embed.add_field(name="⏰ Voting Time", value="24 hours", inline=True)
                embed.set_footer(text="Select your guess from the dropdown below!")
                
                guess_message = await guess_channel.send(content=f"<@&{ROLE_PING}>",embed=embed)
            else:
                # Discord attachment - check if message has attachments
                if message.attachments:
                    # Re-upload the video to guess channel
                    attachment = message.attachments[0]
                    
                    # Download the attachment
                    video_data = await attachment.read()
                    video_file = discord.File(
                        io.BytesIO(video_data), 
                        filename=attachment.filename
                    )
                    
                    embed = discord.Embed(
                        title="🎮 Guess the Rank!",
                        description="Watch the video and guess what rank this player is!",
                        color=0x7AB0E7
                    )
                    embed.add_field(name="⏰ Voting Time", value="24 hours", inline=True)
                    embed.add_field(name="📊 Current Votes", value="0", inline=True)
                    embed.set_footer(text="Select your guess from the dropdown below!")
                    
                    guess_message = await guess_channel.send(embed=embed, file=video_file)
                else:
                    await check_channel.send("❌ Error: No video found in the original message.")
                    return

            # Create voting interface
            clip_id = f"{guild.id}_{int(time.time())}"
            view = GuessRankSelector(clip_id, clip_data['rank'])
            
            # Edit the guess message to add the selector
            await guess_message.edit(view=view)

            # Initialize server-specific results data
            results_data = load_results_data()
            if guild.id not in results_data:
                results_data[guild.id] = {}
                
            results_data[guild.id][clip_id] = {
                'correct_rank': clip_data['rank'],
                'votes': {},
                'total_votes': 0,
                'correct_votes': 0,
                'created_time': datetime.now().isoformat(),
                'end_time': (datetime.now() + timedelta(hours=24)).isoformat(),
                'expired': False,
                'video_url': clip_data.get('video_url'),
                'submitter_id': clip_data['user_id'],
                'message_id': guess_message.id,
                'guild_id': guild.id
            }
            save_results_data(results_data)

            # Notify submitter of approval
            try:
                user = bot.get_user(clip_data['user_id'])
                if not user:
                    user = await bot.fetch_user(clip_data['user_id'])
                
                if user:
                    approval_embed = discord.Embed(
                        title="✅ Clip Approved!",
                        description=f"Your clip has been approved and posted to **{guild.name}**!\n\n"
                                  f"Claimed rank: **{clip_data['rank']}**\n"
                                  f"Voting period: 24 hours",
                        color=0x00FF00
                    )
                    approval_embed.add_field(
                        name="📊 Track Results", 
                        value=f"Check {guess_channel.mention} to see how people vote!", 
                        inline=False
                    )
                    await user.send(embed=approval_embed)
                    
                    await check_channel.send(f"✅ Clip approved and user notified via DM.", delete_after=10)
            except Exception as e:
                await check_channel.send(f"✅ Clip approved but couldn't notify user: {str(e)}", delete_after=10)

        except Exception as e:
            await check_channel.send(f"❌ Error posting to guess channel: {str(e)}")
            return

        # Clean up the moderation message
        try:
            await message.delete()
        except:
            pass

        # Remove from pending clips for this server
        del bot.pending_clips[guild.id][str(message_id)]
        with open(CLIP_DATA_FILE, 'w') as f:
            json.dump(bot.pending_clips, f, indent=2)

    elif str(payload.emoji) == "❌":
        # Rejection - ask for reason
        await check_channel.send(
            f"Please type the reason for rejecting this clip (within 5min):"
        )

        def check(msg):
            return msg.author.id == payload.user_id and msg.channel.id == payload.channel_id

        try:
            reason_msg = await bot.wait_for("message", timeout=300.0, check=check)
            reason = reason_msg.content.strip()
            
            # Try to get user from cache first, then fetch if not found
            user = bot.get_user(clip_data['user_id'])
            
            if not user:
                try:
                    # Fetch user from Discord API if not in cache
                    user = await bot.fetch_user(clip_data['user_id'])
                except discord.NotFound:
                    await check_channel.send(f"❗ User with ID {clip_data['user_id']} not found. They may have deleted their account.")
                    # Still clean up the clip
                    try:
                        await message.delete()
                    except:
                        pass
                    del bot.pending_clips[guild.id][message_id]
                    with open(CLIP_DATA_FILE, 'w') as f:
                        json.dump(bot.pending_clips, f, indent=2)
                    return
                except Exception as e:
                    await check_channel.send(f"❗ Error fetching user: {str(e)}")
                    return
            
            if user:
                try:
                    rejection_embed = discord.Embed(
                        title="❌ Clip Rejected",
                        description=f"Your clip has been rejected by a moderator in **{guild.name}**.\n\n**Reason:**\n{reason}",
                        color=0xFF0000
                    )
                    rejection_embed.set_footer(text="You can submit a new clip anytime!")
                    await user.send(embed=rejection_embed)
                    
                    # Confirm to moderator that DM was sent
                    await check_channel.send(f"✅ User {user.display_name} (ID: {user.id}) has been notified of the rejection via DM.", delete_after=10)
                    
                except discord.Forbidden:
                    await check_channel.send(f"❗ Couldn't send DM to {user.display_name} (ID: {user.id}). They have DMs disabled from server members.")
                except Exception as e:
                    await check_channel.send(f"❗ Error sending DM to {user.display_name}: {str(e)}")
            
            # Delete the reason message for cleanliness
            try:
                await reason_msg.delete()
            except:
                pass

        except asyncio.TimeoutError:
            await check_channel.send("❗ No reason provided in time. Rejection canceled.")
            return

        # Delete the original clip message
        try:
            await message.delete()
        except:
            pass

        # Clean up server-specific clip record
        del bot.pending_clips[guild.id][str(message_id)]
        with open(CLIP_DATA_FILE, 'w') as f:
            json.dump(bot.pending_clips, f, indent=2)
@bot.event
async def on_message(message):
    # Ignore bot messages
    if message.author == bot.user:
        return
    
    video_path = None
    
    # Process only private messages with attachments or URLs
    if isinstance(message.channel, discord.DMChannel):
        # Check for catbox or other video URLs
        url = message.content.strip()
        if url and validators.url(url):
            if (url.startswith("https://files.catbox.moe/") or 
                url.startswith("https://cdn.discordapp.com/") or
                any(url.lower().endswith(ext) for ext in video_extensions)):
                
                await message.add_reaction('⏳')
                video_path = await download_video_from_url(url)
                if not video_path:
                    await message.reply("❌ Failed to download video from URL!")
                    await message.remove_reaction('⏳', bot.user)
                    return

        # Look for video in attachments if no URL processed
        if not video_path:
            for attachment in message.attachments:
                if any(attachment.filename.lower().endswith(ext) for ext in video_extensions):
                    await message.add_reaction('⏳')
                    video_path = await save_video_from_attachment(attachment)
                    if not video_path:
                        await message.reply("❌ Failed to download video attachment!")
                        await message.remove_reaction('⏳', bot.user)
                        return
                    break
        
        if video_path:
            # Find all servers with configured channels
            available_servers = []
            for guild in bot.guilds:
                check_channel_name, guess_channel_name, _ = get_channel_names(guild.id)
                check_channel = discord.utils.get(guild.channels, name=check_channel_name)
                guess_channel = discord.utils.get(guild.channels, name=guess_channel_name)
                
                if check_channel and guess_channel:
                    available_servers.append({
                        'guild': guild,
                        'check_channel': check_channel,
                        'guess_channel': guess_channel
                    })
            
            if not available_servers:
                await message.reply("❌ No servers found with properly configured channels!")
                cleanup_files([video_path])
                return
            elif len(available_servers) == 1:
                # Only one server available, use it directly
                selected_server = available_servers[0]
                view = RankSelector(message.author.id, video_path, selected_server['guild'].id)
                
                embed = discord.Embed(
                    title="🎮 Rank Selection",
                    description=f"Submitting to: **{selected_server['guild'].name}**\n\n"
                            "Choose your rank from the dropdown menu below.",
                    color=0x7AB0E7
                )
                
                await message.reply(embed=embed, view=view)
            else:
                # Multiple servers available, let user choose
                view = ServerSelector(message.author.id, video_path, available_servers)
                
                embed = discord.Embed(
                    title="🎮 Server Selection",
                    description="Choose which server to submit your clip to:",
                    color=0x7AB0E7
                )
                
                await message.reply(embed=embed, view=view)
            
            await message.remove_reaction('⏳', bot.user)
            await message.add_reaction('✅')
        elif not message.content.startswith('!'):
            # Show available servers in help message
            server_list = []
            for guild in bot.guilds:
                check_channel_name, guess_channel_name, _ = get_channel_names(guild.id)
                check_channel = discord.utils.get(guild.channels, name=check_channel_name)
                if check_channel:
                    server_list.append(f"• **{guild.name}**")
            
            server_text = "\n".join(server_list) if server_list else "• No configured servers found"
            
            await message.reply(
                "🎮 **Send me a video to get started!**\n\n"
                "**Available servers:**\n"
                f"{server_text}\n\n"
                "**Supported methods:**\n"
                "• Upload a video file (MP4, AVI, MOV, etc.) with embed File\n"
                "• Send a catbox.moe link\n"
                "## Normal URL or CDN Discord is not handled\n"
                "**File size limit:** 200MB"
            )
    
    # Process other commands
    await bot.process_commands(message)

@tree.command(name="setup", description="Setup channels used for the game")
async def setup_channels(interaction: discord.Interaction):
    """Command to configure channel names and create channels if needed"""
    
    # Check comprehensive permissions
    required_perms = [
        interaction.user.guild_permissions.manage_channels,
        interaction.guild.me.guild_permissions.manage_channels,
        interaction.guild.me.guild_permissions.send_messages,
        interaction.guild.me.guild_permissions.manage_messages
    ]
    
    if not all(required_perms):
        missing = []
        if not interaction.user.guild_permissions.manage_channels:
            missing.append("You need Manage Channels permission")
        if not interaction.guild.me.guild_permissions.manage_channels:
            missing.append("Bot needs Manage Channels permission")
        if not interaction.guild.me.guild_permissions.send_messages:
            missing.append("Bot needs Send Messages permission")
        if not interaction.guild.me.guild_permissions.manage_messages:
            missing.append("Bot needs Manage Messages permission")
        
        await interaction.response.send_message(
            f"❌ **Missing permissions:**\n" + "\n".join(f"• {perm}" for perm in missing), 
            ephemeral=True
        )
        return
    
    check_channel_name, guess_channel_name, results_channel_name = get_channel_names(interaction.guild.id)
    
    embed = discord.Embed(
        title="🛠️ Channel Setup",
        description=f"**Current configuration:**\n"
                   f"• Check channel: `{check_channel_name}`\n"
                   f"• Guess channel: `{guess_channel_name}`\n"
                   f"• Results channel: `{results_channel_name}`\n\n"
                   f"Click the button below to modify the configuration.",
        color=0x7AB0E7
    )
    
    class SetupView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
        
        @discord.ui.button(label="Configure Channels", style=discord.ButtonStyle.primary, emoji="⚙️")
        async def configure_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            modal = ChannelSetupModal()
            await interaction.response.send_modal(modal)
    
    await interaction.response.send_message(embed=embed, view=SetupView(), ephemeral=True)

@tree.command(name="help", description="Show help for Guess The Rank bot")
async def help_slash_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 Guess The Rank Bot - Help",
        description="This bot allows you to create rank guessing challenges!",
        color=0x7AB0E7
    )
    embed.add_field(
        name="📱 How to submit clips:",
        value="1. Send me a video in private message (DM), either catbox link or normal embed link, other methodes will NOT work!\n"
              "2. Select your rank from the dropdown menu\n"
              "3. Your video will be processed and submitted for moderation\n"
              "4. Once approved, it will appear in the guess channel with voting\n"
              "5. Results are automatically posted after 24 hours",
        inline=False
    )
    embed.add_field(
        name="🎬 Supported video sources:",
        value="• Direct file upload (up to 200MB)\n"
              "• Catbox.moe links\n"
              "• Formats: MP4, AVI, MOV, MKV, WMV, FLV, WEBM",
        inline=False
    )
    embed.add_field(
        name="🛠️ Commands:",
        value="`/setup` - Configure channels (Admin)\n"
              "`/help` - Show this help\n"
              "`/results` - Browse results from past clips (last 25)\n"
              "`/cleanup` - Cleanup expired clips (Admin)",
        inline=False
    )
    embed.add_field(
        name="🔍 Moderation:",
        value="All clips go through moderation with automatic blur processing\n"
              "Moderators can approve (✅) or reject (❌) submissions\n"
              "Approved clips get 24h voting period with automatic results",
        inline=False
    )
    embed.set_footer(
        text="Created by Vapoor • Send any video in DM to get started!"
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="results", description="Display results from completed clips")
async def show_results(interaction: discord.Interaction):
    """Show results browser for finished clips in this server"""
    
    guild_id = interaction.guild.id
    results_data = load_results_data()
    
    # Check if this server has any results
    finished_clips = []
    if guild_id in results_data:
        server_clips = results_data[guild_id]
        finished_clips = [clip_id for clip_id, clip_data in server_clips.items() if clip_data.get('expired', False)]
    
    if not finished_clips:
        embed = discord.Embed(
            title="📊 No Results Available",
            description="No finished clips found yet for this server. Wait for some clips to complete their 24-hour voting period!",
            color=0x7AB0E7
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    embed = discord.Embed(
        title="📊 Browse Clip Results",
        description="Select a clip from the dropdown menu below to view its results.",
        color=0x7AB0E7
    )
    
    view = ResultsSelector(guild_id)
    await interaction.response.send_message(embed=embed, view=view)

@tree.command(name="cleanup", description="Delete expired clips from this server's database")
async def cleanup_expired(interaction: discord.Interaction, count: int = 5):
    """Clean up expired clips data for this server only (Admin only)"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return
    
    # Validate count parameter
    if count < 1 or count > 15:
        await interaction.response.send_message("❌ Count must be between 1 and 15.", ephemeral=True)
        return
        
    await interaction.response.defer(ephemeral=True)
    
    try:
        guild_id = interaction.guild.id
        results_data = load_results_data()
        
        # Check if this server has any data
        if guild_id not in results_data:
            await interaction.followup.send("📋 No clip data found for this server.", ephemeral=True)
            return
        
        server_clips = results_data[guild_id]
        
        # Find all expired clips for this server
        expired_clips = []
        for clip_id, clip_data in server_clips.items():
            if clip_data.get('expired', False):
                end_time = datetime.fromisoformat(clip_data['end_time'])
                expired_clips.append({
                    'clip_id': clip_id,
                    'end_time': end_time,
                    'rank': clip_data.get('correct_rank', 'Unknown'),
                    'votes': clip_data.get('total_votes', 0)
                })
        
        if not expired_clips:
            await interaction.followup.send("📋 No expired clips found for this server.", ephemeral=True)
            return
        
        # Sort by end time (oldest first)
        expired_clips.sort(key=lambda x: x['end_time'])
        
        # Limit to requested count
        clips_to_delete = expired_clips[:count]
        actual_count = len(clips_to_delete)
        
        # Delete the clips from this server only
        deleted_info = []
        for clip in clips_to_delete:
            clip_id = clip['clip_id']
            if clip_id in server_clips:
                del server_clips[clip_id]
                deleted_info.append(f"• {clip['end_time'].strftime('%Y-%m-%d %H:%M')} - {clip['rank']} ({clip['votes']} votes)")
        
        # Save updated data
        results_data[guild_id] = server_clips
        save_results_data(results_data)
        
        # Create response
        embed = discord.Embed(
            title="🗑️ Server Cleanup Complete",
            description=f"Deleted {actual_count} expired clip(s) from **{interaction.guild.name}** database:",
            color=0x7AB0E7
        )
        
        if deleted_info:
            embed.add_field(
                name="Deleted Clips:",
                value="\n".join(deleted_info[:10]) + (f"\n... and {len(deleted_info)-10} more" if len(deleted_info) > 10 else ""),
                inline=False
            )
        
        remaining_expired = len(expired_clips) - actual_count
        embed.add_field(
            name="Server Summary:",
            value=f"• Deleted: {actual_count}\n• Remaining expired: {remaining_expired}\n• Total clips in server: {len(server_clips)}",
            inline=False
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        
    except Exception as e:
        await interaction.followup.send(f"❌ Error during cleanup: {str(e)}", ephemeral=True)
        print(f"Cleanup error: {e}")
        
# Error handling
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have the necessary permissions for this command.")
    elif isinstance(error, commands.CommandNotFound):
        pass  # Ignore unknown commands
    else:
        await ctx.send(f"❌ An error occurred: {str(error)}")
        print(f"Command error: {error}")

@bot.event
async def on_error(event, *args, **kwargs):
    print(f"Bot error in {event}: {args}")
    traceback.print_exc()

if __name__ == "__main__":
    # Dependency checks
    try:
        import cv2
        import numpy as np
    except ImportError:
        print("❌ Error: OpenCV is not installed.")
        print("Install it with: pip install opencv-python")
        exit(1)
    
    # Check for FFmpeg
    try:
        import subprocess
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
        if result.returncode != 0:
            print("❌ Error: FFmpeg is not installed or not in PATH.")
            print("Please install FFmpeg: https://ffmpeg.org/download.html")
            exit(1)
    except FileNotFoundError:
        print("❌ Error: FFmpeg is not installed or not in PATH.")
        print("Please install FFmpeg: https://ffmpeg.org/download.html")
        exit(1)
    
    print("🤖 Starting enhanced Guess The Rank bot...")
    print("\n🔧 Requirements:")
    print("   1. Set DISCORD_TOKEN in .env file")
    print("   2. Install dependencies: pip install discord.py opencv-python python-dotenv aiohttp validators")
    print("   3. Install FFmpeg and add to PATH")
    print("   4. Use /setup command to configure channels")
    
    bot.run(TOKEN)