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
from typing import List, Optional, Dict
from dotenv import load_dotenv
from datetime import datetime, timedelta

# Configuration
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUESS_CHANNEL_NAME = 'guess-my-rank'
CHECK_CHANNEL_NAME = 'check-clips'
CLIP_DATA_FILE = 'pending_clips.json'
RESULTS_DATA_FILE = 'clip_results.json'
video_extensions = ['.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm']

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
            default="guess-my-rank",
            max_length=100,
            required=True
        )
        
        self.add_item(self.check_channel_input)
        self.add_item(self.guess_channel_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        check_channel_name = self.check_channel_input.value.strip()
        guess_channel_name = self.guess_channel_input.value.strip()
        
        # Save conf
        save_channel_config(interaction.guild.id, check_channel_name, guess_channel_name)
        
        # Create channel
        created_channels = []
        
        # Verify and create
        guess_channel = discord.utils.get(interaction.guild.channels, name=guess_channel_name)
        if not guess_channel:
            try:
                guess_channel = await interaction.guild.create_text_channel(
                    guess_channel_name,
                    topic="🎮 Guess the rank of players from their videos!"
                )
                
                welcome_embed = discord.Embed(
                    title="🎮 Welcome to Guess My Rank!",
                    description="In this channel, you'll see gameplay videos with the player's rank hidden.\n"
                               "Try to guess their ranks, a reveal will appear 24h later.",
                    color=0x00ff00
                )
                
                await guess_channel.send(embed=welcome_embed)
                created_channels.append(guess_channel_name)
                
            except discord.Forbidden:
                await interaction.response.send_message("❌ I don't have permissions to create channels.", ephemeral=True)
                return
            except Exception as e:
                await interaction.response.send_message(f"❌ Error creating {guess_channel_name}: {str(e)}", ephemeral=True)
                return
        
        check_channel = discord.utils.get(interaction.guild.channels, name=check_channel_name)
        if not check_channel:
            try:
                check_channel = await interaction.guild.create_text_channel(
                    check_channel_name,
                    topic="🔍 Moderation channel for clip submissions"
                )
                
                instructions_embed = discord.Embed(
                    title="🔍 Clip Moderation",
                    description=("This channel is for moderating clip submissions.\n"
                               "React with ✅ to approve clips or ❌ to reject them.\n"
                               f"Approved clips will be automatically posted to **{GUESS_CHANNEL_NAME}**")
                )
                
                await check_channel.send(embed=instructions_embed)
                created_channels.append(check_channel_name)
                
            except Exception as e:
                await interaction.response.send_message(f"❌ Error creating {check_channel_name}: {str(e)}", ephemeral=True)
                return
        
        if created_channels:
            channels_list = ", ".join([f"#{name}" for name in created_channels])
            await interaction.response.send_message(f"✅ Channels configured and created: {channels_list}", ephemeral=True)
        else:
            await interaction.response.send_message(f"✅ Channels configured: #{check_channel_name}, #{guess_channel_name}\n(Both channels already existed)", ephemeral=True)

#####################################
####### RESULT SELECTOR #############
#####################################

class ResultsSelector(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        
        # Take all the clips that are dones
        results_data = load_results_data()
        finished_clips = []
        
        for clip_id, clip_data in results_data.items():
            if clip_data['expired']:
                end_time = datetime.fromisoformat(clip_data['end_time'])
                date_str = end_time.strftime("%Y-%m-%d %H:%M")
                rank_emoji = next((rank['emoji'] for rank in RANKS if rank['name'] == clip_data['correct_rank']), '🎮')
                
                finished_clips.append({
                    'clip_id': clip_id,
                    'date': date_str,
                    'rank': clip_data['correct_rank'],
                    'emoji': rank_emoji,
                    'votes': clip_data['total_votes']
                })
        
        # SortByDate
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
        results_embed = get_results_embed(clip_id)
        
        if results_embed:
            results_embed.set_footer(text=f"Clip ID: {clip_id}")
            await interaction.response.send_message(embed=results_embed, ephemeral=True)
        else:
            await interaction.response.send_message("❌ Error loading results for this clip.", ephemeral=True)








######################################
###### DMS SELECTOR ##################
######################################


class RankSelector(discord.ui.View):
    def __init__(self, user_id: int, video_path: str):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.video_path = video_path
        self.selected_rank = None
        
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
            #Check size
            original_size_mb = os.path.getsize(self.video_path) / (1024 * 1024)
            
            if original_size_mb > 200:  # check is > 200MB
                await interaction.followup.send(
                    f"❌ Video too large ({original_size_mb:.1f}MB)!\n",
                    f"Please use a video smaller than 200MB.", 
                    ephemeral=True
                )
                cleanup_files([self.video_path])
                return
            
            
            await interaction.followup.send(
                f"🔄 Processing... (Video: {original_size_mb:.1f}MB)\n",
                f"This may take a few minutes depending on size.\n",
                f"If you using CatBox, please expect longer upload times (Maximum 15min before timeout)\n",
                ephemeral=True
            )
            
            try:
                #Blur video asynchrone
                blurred_video_path = await asyncio.wait_for(
                    blur_video(self.video_path),
                    timeout=300  # 5 minutes
                )
            except TimeoutError:
                await interaction.followup.send("❌ Video processing took too long and timed out.", ephemeral=True)
                cleanup_files([self.video_path])
                return
            # Check final size
            final_size_mb = os.path.getsize(blurred_video_path) / (1024 * 1024)
            
            if final_size_mb > 25:  # Discord limit
                await interaction.followup.send(
                    f"❌ Unable to compress video enough ({final_size_mb:.1f}MB)!\n"
                    f"Please use a shorter video or lower quality.",
                    ephemeral=True
                )
                cleanup_files([self.video_path, blurred_video_path])
                return
            
           
            check_channel = None
            for guild in bot.guilds:
                found_channel = discord.utils.get(guild.channels, name=CHECK_CHANNEL_NAME) #check if check-clips exist
                if found_channel:
                    check_channel = found_channel
                    break
            
            if not check_channel:
                await interaction.followup.send(
                    f"❌ Channel '{CHECK_CHANNEL_NAME}' not found!\n"
                    f"Make sure a channel named '{CHECK_CHANNEL_NAME}' exists on a server where the bot is present.", 
                    ephemeral=True
                )
                cleanup_files([self.video_path, blurred_video_path])
                return
            
            # Send the video in the channel
            with open(blurred_video_path, 'rb') as f:
                file = discord.File(f, filename='guess_my_rank.mp4')
                message_content = f"🎮 **Clip Submission for Review**\n\n" \
                                f"Submitted by: {interaction.user.mention}\n" \
                                f"Claimed rank: **{self.selected_rank}**\n\n" \
                                f"React with ✅ to approve or ❌ to reject this clip."
                
                moderation_message = await check_channel.send(message_content, file=file)
                # Add reactions for moderation
                await moderation_message.add_reaction("✅")
                await moderation_message.add_reaction("❌")
                
                # Store clip data in message for later use
                clip_data = {
                    'rank': self.selected_rank,
                    'user_id': interaction.user.id,
                    'user_mention': interaction.user.mention
                }
                
                # Load existing clip data (if any)
                if not hasattr(bot, 'pending_clips'):
                    if os.path.exists(CLIP_DATA_FILE):
                        with open(CLIP_DATA_FILE, 'r') as f:
                            bot.pending_clips = json.load(f)
                            # Convert keys back to int since JSON stores them as strings
                            bot.pending_clips = {int(k): v for k, v in bot.pending_clips.items()}
                    else:
                        bot.pending_clips = {}

                # Add the new clip data
                bot.pending_clips[moderation_message.id] = clip_data

                # Save to JSON file
                with open(CLIP_DATA_FILE, 'w') as f:
                    json.dump(bot.pending_clips, f, indent=2)
            
            # Confirm to user
            await interaction.followup.send(
                f"✅ Video submitted for moderation in {CHECK_CHANNEL_NAME}!\n"
                f"Final size: {final_size_mb:.1f}MB\n"
                f"Your clip will appear in guess-my-rank once approved by moderators.", 
                ephemeral=True
            )
            
            # Clean up temp (to avoid losing 40GB of video lol)
            cleanup_files([self.video_path, blurred_video_path])
            
        except discord.HTTPException as e:
            if e.code == 40005:  # Payload too large
                await interaction.followup.send(
                    "❌ Video still too large after compression!\n"
                    "Thats means that even after compression, you are still above 25MB.\n"
                    "You can try to compress it yourself, or send a clip with lower resolution or shorter",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(f"❌ Discord error, please contact vaporr on discord with a screenshot", ephemeral=True)
            cleanup_files([self.video_path])
            
        except Exception as e:
            await interaction.followup.send(f"❌ Processing error, please contact vaporr on discord with a screenshot", ephemeral=True)
            print(f"Processing Error : {e}")
            cleanup_files([self.video_path])

class GuessRankSelector(discord.ui.View):
    def __init__(self, clip_id: str, correct_rank: str):
        super().__init__(timeout=None)  # No timeout since we handle expiry manually
        self.clip_id = clip_id
        self.correct_rank = correct_rank
        self.user_votes = {}  # Track user votes to prevent double voting
        
        # Dropdown with emojis
        self.rank_select = discord.ui.Select(
            placeholder="Guess the rank...",
            min_values=1,
            max_values=1,
            custom_id=f"guess_rank_select_{clip_id}",
            options=[
                discord.SelectOption(
                    label=rank["name"], 
                    value=rank["name"], 
                    emoji=rank["emoji"]
                ) for rank in RANKS
            ]
        )
        self.rank_select.callback = self.guess_callback
        self.add_item(self.rank_select)
    
    async def guess_callback(self, interaction: discord.Interaction):
        # Already voted ?
        if interaction.user.id in self.user_votes:
            await interaction.response.send_message(
                f"You already voted for **{self.user_votes[interaction.user.id]}**!", 
                ephemeral=True
            )
            return
        
        # Check if voting period is still active
        results_data = load_results_data()
        clip_data = results_data.get(self.clip_id)
        
        if not clip_data:
            await interaction.response.send_message("❌ Clip data not found!", ephemeral=True)
            return
        
        # Check if voting has expired
        end_time = datetime.fromisoformat(clip_data['end_time'])
        if datetime.now() > end_time:
            await interaction.response.send_message("⏰ Voting period has ended!", ephemeral=True)
            return
        
        selected_rank = self.rank_select.values[0]
        self.user_votes[interaction.user.id] = selected_rank
        
        # Save vote to results
        save_vote(self.clip_id, selected_rank, interaction.user.id)
        
        await interaction.response.send_message(
            f"✅ Your guess: **{selected_rank}** has been recorded!\n"
            f"The rank in the clip was **{self.correct_rank}**", 
            ephemeral=True
        )

async def blur_video(input_path: str, target_size_mb: int = 20) -> str:
    """Apply adaptive blur and compress video using FFmpeg."""
    
    # Create temporary output file
    output_fd, output_path = tempfile.mkstemp(suffix='.mp4')
    os.close(output_fd)

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
        
        # Get video stream info
        video_stream = None
        for stream in probe_data['streams']:
            if stream['codec_type'] == 'video':
                video_stream = stream
                break
        
        if not video_stream:
            raise Exception("No video stream found")
        
        duration = float(probe_data['format']['duration'])
        width = int(video_stream['width'])
        height = int(video_stream['height'])
        
        # Here we got all the blur regions
        # left_blur -> kill feed
        # bottom blur -> replay nickname
        # voice chat -> self-explanatory
        # text_chat -> self-explanatory
        left_blur_x = 103
        left_blur_y = 98
        left_blur_width = 333
        left_blur_height = 240
        
        bottom_blur_width = 293
        bottom_blur_height = 28
        bottom_blur_x = 764
        bottom_blur_y = 1032

        voice_chat_width = 229
        voice_chat_height = 188
        voice_chat_x = 38
        voice_chat_y = 417

        text_chat_width = 425
        text_chat_height = 168
        text_chat_x = 25
        text_chat_y = 695

        # Step 2: Compute bitrate to hit target size
        target_bitrate_kbps = int((target_size_mb * 8192) / duration)
        target_bitrate_kbps = max(500, min(target_bitrate_kbps, 5000))  # Clamp to reasonable range

        # Step 3: Build FFmpeg command with adaptive blur
        ffmpeg_cmd = [
            'ffmpeg', '-y', '-i', input_path,

            # Complex filter: blur left region and bottom center region
            '-filter_complex',
            f"[0:v]split=5[main][left_crop][bottom_crop][voice_crop][text_crop];"
            f"[left_crop]crop={left_blur_width}:{left_blur_height}:{left_blur_x}:{left_blur_y},boxblur=lr=14:cr=6[left_blur];"
            f"[bottom_crop]crop={bottom_blur_width}:{bottom_blur_height}:{bottom_blur_x}:{bottom_blur_y},boxblur=lr=14:cr=6[bottom_blur];"
            f"[voice_crop]crop={voice_chat_width}:{voice_chat_height}:{voice_chat_x}:{voice_chat_y},boxblur=lr=14:cr=6[voice_blur];"
            f"[text_crop]crop={text_chat_width}:{text_chat_height}:{text_chat_x}:{text_chat_y},boxblur=lr=14:cr=6[text_blur];"
            f"[main][left_blur]overlay={left_blur_x}:{left_blur_y}[tmp1];"
            f"[tmp1][bottom_blur]overlay={bottom_blur_x}:{bottom_blur_y}[tmp2];"
            f"[tmp2][voice_blur]overlay={voice_chat_x}:{voice_chat_y}[tmp3];"
            f"[tmp3][text_blur]overlay={text_chat_x}:{text_chat_y}",


            # Video compression
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '22',
            '-maxrate', '2500k', # the higher is it, the better the quality
            '-bufsize', '5000k', # bufsize ALWAYS x2 the maxrate

            # Audio
            '-c:a', 'aac',
            '-b:a', '128k',

            # Format tuning
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',

            output_path
        ]

        # Step 4: Run FFmpeg
        proc = await asyncio.create_subprocess_exec(
            *ffmpeg_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise Exception(f"FFmpeg failed: {stderr.decode()}")

        # Step 5: Report result
        final_size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"Blurred and compressed: {input_path} -> {final_size_mb:.2f} MB at {target_bitrate_kbps} kbps")
        print(f"Video dimensions: {width}x{height}")
        print(f"Left blur region: {left_blur_width}x{left_blur_height}")
        print(f"Bottom blur region: {bottom_blur_width}x{bottom_blur_height} at ({bottom_blur_x}, {bottom_blur_y})")
        return output_path

    except Exception as e:
        if os.path.exists(output_path):
            os.remove(output_path)
        raise e
    
    
#################
### UTILS #######
#################

CHANNEL_CONFIG_FILE = 'channel_config.json'


async def download_video_from_url(url: str, max_size_mb: int = 100) -> str | None:
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

def save_channel_config(guild_id: int, check_channel: str, guess_channel: str):
    """Save channel configuration to JSON file"""
    config = load_channel_config()
    config[str(guild_id)] = {
        'check_channel': check_channel,
        'guess_channel': guess_channel
    }
    with open(CHANNEL_CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

def get_channel_names(guild_id: int) -> tuple:
    """Get configured channel names for a guild"""
    config = load_channel_config()
    guild_config = config.get(str(guild_id), {})
    
    check_channel = guild_config.get('check_channel', CHECK_CHANNEL_NAME)
    guess_channel = guild_config.get('guess_channel', GUESS_CHANNEL_NAME) 
    
    return check_channel, guess_channel    

def cleanup_files(file_paths: List[str]):
    """Clean up temporary files"""
    for path in file_paths:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            print(f"Error cleaning up {path}: {e}")

def load_results_data() -> Dict:
    """Load results data from JSON file"""
    if os.path.exists(RESULTS_DATA_FILE):
        with open(RESULTS_DATA_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_results_data(data: Dict):
    """Save results data to JSON file"""
    with open(RESULTS_DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

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

def get_results_embed(clip_id: str) -> discord.Embed:
    """Generate results embed with percentages"""
    results_data = load_results_data()
    clip_data = results_data.get(clip_id)
    
    if not clip_data:
        return None
    
    correct_rank = clip_data['correct_rank']
    total_votes = clip_data['total_votes']
    
    embed = discord.Embed(
        title="🎯 Results - Guess My Rank",
        description=f"**Correct Rank:** {correct_rank}\n**Total Votes:** {total_votes}",
        color=0x00ff00
    )
    
    # Calculate percentages
    results_text = ""
    for rank in RANKS:
        rank_name = rank['name']
        votes_count = len(clip_data['votes'].get(rank_name, []))
        percentage = (votes_count / total_votes * 100) if total_votes > 0 else 0
        
        emoji = rank['emoji']
        if rank_name == correct_rank:
            results_text += f"{emoji} **{rank_name}**: {votes_count} votes ({percentage:.1f}%) ✅\n"
        else:
            results_text += f"{emoji} {rank_name}: {votes_count} votes ({percentage:.1f}%)\n"
    
    embed.add_field(name="📊 Vote Distribution", value=results_text, inline=False)
    
    return embed

async def register_persistent_views():
    results_data = load_results_data()
    for clip_id, clip in results_data.items():
        if not clip['expired']:
            bot.add_view(GuessRankSelector(clip_id, clip['correct_rank']))

async def check_expired_clips():
    """Check for expired clips and post results"""
    results_data = load_results_data()
    current_time = datetime.now()
    
    for clip_id, clip_data in results_data.items():
        if clip_data['expired']:
            continue
            
        end_time = datetime.fromisoformat(clip_data['end_time'])
        
        if current_time > end_time:
            # Mark as expired
            clip_data['expired'] = True
            
            # Find the guess channel and post results
            for guild in bot.guilds:
                guess_channel = discord.utils.get(guild.channels, name=GUESS_CHANNEL_NAME)
                if guess_channel:
                    results_embed = get_results_embed(clip_id)
                    if results_embed:
                        await guess_channel.send(embed=results_embed)
                    break
    
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

@bot.event
async def on_ready():
    print(f'{bot.user} is connected and ready!')
    await tree.sync()
    print(f'Servers: {len(bot.guilds)}')
    
    # Load clip data if not already loaded
    if not hasattr(bot, 'pending_clips'):
        if os.path.exists(CLIP_DATA_FILE):
            with open(CLIP_DATA_FILE, 'r') as f:
                bot.pending_clips = json.load(f)
                bot.pending_clips = {int(k): v for k, v in bot.pending_clips.items()}
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

    message_id = payload.message_id

    # Check if this is a pending clip
    if message_id not in bot.pending_clips:
        return

    if str(payload.emoji) not in ["✅", "❌"]:
        return

    # Fetch necessary info
    guild = bot.get_guild(payload.guild_id)
    check_channel = guild.get_channel(payload.channel_id)
    guess_channel = discord.utils.get(guild.text_channels, name="guess-my-rank")

    if not check_channel or not guess_channel:
        return

    message = await check_channel.fetch_message(message_id)
    clip_data = bot.pending_clips[message_id]

    if str(payload.emoji) == "✅":
        # Approve: forward the video with rank selector
        if message.attachments:
            video = message.attachments[0]
            file = await video.to_file(filename=video.filename)
            
            # Create clip entry in results data
            clip_id = create_clip_entry(clip_data['rank'])
            
            # Create view with rank selector
            view = GuessRankSelector(clip_id, clip_data['rank'])
            
            await guess_channel.send(
                f"🎮 **New Guess My Rank Clip!**\n\n"
                f"Watch this video and guess the player's rank!\n"
                f"You have 24 hours to vote.",
                file=file,
                view=view
            )
        
        # Delete the moderation message
        try:
            await message.delete()
        except:
            pass
        
        # Remove from pending clips
        del bot.pending_clips[message_id]
        with open(CLIP_DATA_FILE, 'w') as f:
            json.dump(bot.pending_clips, f, indent=2)

    elif str(payload.emoji) == "❌":
        # Reject: delete the message and notify
        try:
            await message.delete()
        except:
            pass
        
        # Notify submitter if possible
        try:
            submitter = bot.get_user(clip_data['user_id'])
            if submitter:
                await submitter.send(f"❌ Your clip has been rejected by the moderators.")
        except:
            pass
        
        # Remove from pending clips
        del bot.pending_clips[message_id]
        with open(CLIP_DATA_FILE, 'w') as f:
            json.dump(bot.pending_clips, f, indent=2)

@bot.event
async def on_message(message):
    # Ignore bot messages
    if message.author == bot.user:
        return
    
    
    video_path = None
    
    # Process only private messages with attachments
    if isinstance(message.channel, discord.DMChannel):
        #Look if its a link
        url = message.content.strip()
        if url.startswith("https://files.catbox.moe/") and any(url.lower().endswith(ext) for ext in video_extensions):
            if not validators.url(url):
                await message.reply("That doesnt look like a valid link")
                return
            await message.add_reaction('⏳')
            video_path = await download_video_from_url(url)

        
        # Look for video in attachments
        if not video_path:
            for attachment in message.attachments:
                if any(attachment.filename.lower().endswith(ext) for ext in video_extensions):
                    await message.add_reaction('⏳')
                    video_path = await save_video_from_attachment(attachment)
                    break
        
        if video_path:
            # Create rank selection view
            view = RankSelector(message.author.id, video_path)
            
            embed = discord.Embed(
                title="🎮 Rank Selection",
                description="Choose your rank from the dropdown menu below.\n"
                        "Your video will be submitted for moderation before appearing in guess-my-rank.",
                color=0x00ff00
            )
            
            await message.reply(embed=embed, view=view)
            await message.remove_reaction('⏳', bot.user)
            await message.add_reaction('✅')
        else:
            await message.reply("The download failed !")
    
    else:
        # I know its not beautiful to watch
        if isinstance(message.channel, discord.DMChannel) and message.content != "!help":
            await message.reply("Hey! If you want Julian to treat your clip, just send a video(.mp4, .avi etc..)")
        if isinstance(message.channel, discord.DMChannel) and message.content != "!results":
            await message.reply("Hey! If you want Julian to treat your clip, just send a video(.mp4, .avi etc..)")
    # Process other commands
    await bot.process_commands(message)

@tree.command(name="setup", description="Setup both channels use for the game")
async def setup_channels(interaction : discord.Interaction):
    """Command to configure channel names and create channels if needed"""
    
    # Check if the user got perms to execute Setup
    
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("You don't have permission to setup the channels", ephemeral=True)
        return
    check_channel_name, guess_channel_name = get_channel_names(interaction.guild.id)
    
    embed = discord.Embed(
        title="🛠️ Channel Setup",
        description=f"Current configuration:\n"
                   f"• Check channel: `{check_channel_name}`\n"
                   f"• Guess channel: `{guess_channel_name}`\n\n"
                   f"Click the button below to modify the configuration.",
        color=0x0099ff
    )
    
    class SetupView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
        
        @discord.ui.button(label="Configure Channels", style=discord.ButtonStyle.primary, emoji="⚙️")
        async def configure_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            modal = ChannelSetupModal()
            await interaction.response.send_modal(modal)
    
    await interaction.response.send_message(embed=embed, view=SetupView(), ephemeral=True)

@tree.command(name="help", description="Show help for Guess My Rank bot")
async def help_slash_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 Guess My Rank Bot - Help",
        description="This bot allows you to create rank guessing challenges!",
        color=0x0099ff
    )
    embed.add_field(
        name="📱 How to use:",
        value="1. Send me a video in private message\n"
              "2. Select your rank from the menu\n"
              "3. Your video will be submitted for moderation\n"
              "4. Once approved, it will appear in #guess-my-rank with a voting system\n"
              "5. Results are shown after 24 hours",
        inline=False
    )
    embed.add_field(
        name="🛠️ Commands:",
        value="`/setup` - Create required channels (Admin)\n"
              "`/help` - Show this help\n"
              "`/results [clip_id]` - Show results for a specific clip",
        inline=False
    )
    embed.add_field(
        name="🎮 Supported formats:",
        value="MP4, AVI, MOV, MKV, WMV, FLV, WEBM",
        inline=False
    )
    embed.add_field(
        name="🔍 Moderation:",
        value="All clips go through moderation in #check-clips\n"
              "Moderators can approve (✅) or reject (❌) submissions\n"
              "Approved clips get 24h voting period with automatic results",
        inline=False
    )
    embed.set_footer(
        text="Created by Vapoor • Python only • DM me for any issues"
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="results", description="Display last days results")
async def show_results(interaction : discord.Interaction):
    """Show results browser for finished clips"""
    
    results_data = load_results_data()
    finished_clips = [clip_id for clip_id, clip_data in results_data.items() if clip_data['expired']]
    
    if not finished_clips:
        embed = discord.Embed(
            title="📊 No Results Available",
            description="No finished clips found yet. Wait for some clips to complete their 24-hour voting period!",
            color=0xff9900
        )
        await interaction.response.send_message(embed=embed)
        return
    
    embed = discord.Embed(
        title="📊 Browse Clip Results",
        description="Select a clip from the dropdown menu below to view its results.",
        color=0x0099ff
    )
    
    view = ResultsSelector()
    await interaction.response.send_message(embed=embed, view=view)

@tree.command(name="cleanup", description="Cleanup last clips that are outdated")
async def cleanup_expired(interaction : discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You don't have permission to cleanup", ephemeral=True)
        return
    """Clean up expired clips data (Admin only)"""
    results_data = load_results_data()
    
    expired_count = 0
    for clip_id in list(results_data.keys()):
        if results_data[clip_id]['expired']:
            # Keep data but could add archiving logic here
            expired_count += 1
    
    await interaction.response.send_message(f"📋 Found {expired_count} expired clips in database.")

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

# Additional event handlers for better error handling
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
    
    print("🤖 Starting enhanced Guess My Rank bot...")
    print("📋 Requirements:")
    print("   1. Set DISCORD_TOKEN in .env file")
    print("   2. Install dependencies: pip install discord.py opencv-python python-dotenv")
    print("   3. Install FFmpeg and add to PATH")
    print("   4. Bot needs proper Discord permissions")
    print("   5. Use !setup command to create channels")
    
    bot.run(TOKEN)