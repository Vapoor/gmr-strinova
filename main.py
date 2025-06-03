import discord
from discord.ext import commands
import cv2
import numpy as np
import asyncio
import os
import json
import tempfile
from typing import List, Optional
from dotenv import load_dotenv

# Configuration
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUESS_CHANNEL_NAME = 'guess-my-rank'
CHECK_CHANNEL_NAME = 'check-clips'

# Rank list with custom Discord emojis (replace with your actual emoji IDs)
RANKS = [
    {"name": "Substance", "emoji": "<:Substance:1379365131129192488>"},
    {"name": "Molecule", "emoji": "<:Molecule:1379365125408034918>"},
    {"name": "Atom", "emoji": "<:Atom:1379365121176109108>"},
    {"name": "Proton", "emoji": "<:Proton:1379365128213893140>"},
    {"name": "Neutron", "emoji": "<:Neutron:1379365126842351706>"},
    {"name": "Electron", "emoji": "<:Electron:1379365122988048485>"},
    {"name": "Quark", "emoji": "<:Masters:1379365124309254146>"},
    {"name": "Superstring", "emoji": "<:Superstring:1379365132592873482>"},
    {"name": "Singularity", "emoji": "<:Singularity:1379365129380036618>"}
]
# Bot configuration
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
bot = commands.Bot(command_prefix='!', intents=intents)

class RankSelector(discord.ui.View):
    def __init__(self, user_id: int, video_path: str):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.video_path = video_path
        self.selected_rank = None
        
        # Create dropdown menu with all ranks and emojis
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
        await interaction.response.send_message(f"Selected rank: **{self.selected_rank}**\nProcessing video...", ephemeral=True)
        
        # Process and send video
        await self.process_and_send_video(interaction)
    
    async def process_and_send_video(self, interaction: discord.Interaction):
        try:
            # Check original file size
            original_size_mb = os.path.getsize(self.video_path) / (1024 * 1024)
            
            if original_size_mb > 100:  # Reasonable limit to avoid very large files
                await interaction.followup.send(
                    f"❌ Video too large ({original_size_mb:.1f}MB)!\n"
                    f"Please use a video smaller than 100MB.", 
                    ephemeral=True
                )
                cleanup_files([self.video_path])
                return
            
            # Create blurred video with automatic compression
            await interaction.followup.send(
                f"🔄 Processing... (Video: {original_size_mb:.1f}MB)\n"
                f"This may take a few minutes depending on size.",
                ephemeral=True
            )
            
            try:
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
            
            # Find the check-clips channel in all servers where the bot is present
            check_channel = None
            for guild in bot.guilds:
                found_channel = discord.utils.get(guild.channels, name=CHECK_CHANNEL_NAME)
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
            
            # Send video to check-clips channel for moderation
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
                # We'll use the message ID to track the data
                clip_data = {
                    'rank': self.selected_rank,
                    'user_id': interaction.user.id,
                    'user_mention': interaction.user.mention
                }
                
                # Store in bot's memory (in production, you'd want to use a database)
                if not hasattr(bot, 'pending_clips'):
                    bot.pending_clips = {}
                bot.pending_clips[moderation_message.id] = clip_data
            
            # Confirm to user
            await interaction.followup.send(
                f"✅ Video submitted for moderation in {CHECK_CHANNEL_NAME}!\n"
                f"Final size: {final_size_mb:.1f}MB\n"
                f"Your clip will appear in guess-my-rank once approved by moderators.", 
                ephemeral=True
            )
            
            # Clean up temporary files
            cleanup_files([self.video_path, blurred_video_path])
            
        except discord.HTTPException as e:
            if e.code == 40005:  # Payload too large
                await interaction.followup.send(
                    "❌ Video still too large after compression!\n"
                    "Try with a shorter video (less than 30 seconds) or lower resolution.\n"
                    "If the bot is answering a size under 25MB, contact vaporr on discord (I love Discord payload)",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(f"❌ Discord error, please contact vaporr on discord with a screenshot", ephemeral=True)
            cleanup_files([self.video_path])
            
        except Exception as e:
            await interaction.followup.send(f"❌ Processing error, please contact vaporr on discord with a screenshot", ephemeral=True)
            print(f"Processing Error : {e}")
            cleanup_files([self.video_path])

async def blur_video(input_path: str, blur_width: int = 400, blur_height: int = 200, target_size_mb: int = 20) -> str:
    """Always apply top-left blur and compress video using FFmpeg."""

    # Create temporary output file
    output_fd, output_path = tempfile.mkstemp(suffix='.mp4')
    os.close(output_fd)

    try:
        # Step 1: Get video duration
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
        duration = float(probe_data['format']['duration'])

        # Step 2: Compute bitrate to hit target size
        # bitrate (kbps) = size_MB * 8192 / duration_sec
        target_bitrate_kbps = int((target_size_mb * 8192) / duration)
        target_bitrate_kbps = max(500, min(target_bitrate_kbps, 5000))  # Clamp to reasonable range

        # Step 3: Build FFmpeg command
        ffmpeg_cmd = [
            'ffmpeg', '-y', '-i', input_path,

            # Complex filter: blur top-left region
            '-filter_complex',
            f"[0:v]crop={blur_width}:{blur_height}:0:0,boxblur=10:1[blur];[0:v][blur]overlay=0:0",

            # Video compression
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '22',
            '-maxrate', '2500k',
            '-bufsize', '5000k',

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
        return output_path

    except Exception as e:
        if os.path.exists(output_path):
            os.remove(output_path)
        raise e
def cleanup_files(file_paths: List[str]):
    """Clean up temporary files"""
    for path in file_paths:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            print(f"Error cleaning up {path}: {e}")

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
        # Download file
        await attachment.save(temp_path)
        return temp_path
    except Exception as e:
        print(f"Download error: {e}")
        cleanup_files([temp_path])
        return None

@bot.event
async def on_ready():
    print(f'{bot.user} is connected and ready!')
    print(f'Servers: {len(bot.guilds)}')
    
    # Initialize pending clips storage
    if not hasattr(bot, 'pending_clips'):
        bot.pending_clips = {}

@bot.event
async def on_reaction_add(reaction, user):
    """Handle moderation reactions in check-clips channel"""
    
    # Ignore bot reactions
    if user == bot.user:
        return
    
    # Only handle reactions in check-clips channel
    if reaction.message.channel.name != CHECK_CHANNEL_NAME:
        return
    
    # Check if this message has pending clip data
    if not hasattr(bot, 'pending_clips') or reaction.message.id not in bot.pending_clips:
        return
    
    clip_data = bot.pending_clips[reaction.message.id]
    
    # Handle approval (✅)
    if str(reaction.emoji) == "✅":
        # Find guess-my-rank channel
        guess_channel = None
        for guild in bot.guilds:
            found_channel = discord.utils.get(guild.channels, name=GUESS_CHANNEL_NAME)
            if found_channel:
                guess_channel = found_channel
                break
        
        if guess_channel:
            # Get the video attachment from the moderation message
            video_attachment = None
            for attachment in reaction.message.attachments:
                if attachment.filename.endswith('.mp4'):
                    video_attachment = attachment
                    break
            
            if video_attachment:
                # Download and re-upload to guess-my-rank channel
                temp_path = await save_video_from_attachment(video_attachment)
                if temp_path:
                    try:
                        with open(temp_path, 'rb') as f:
                            file = discord.File(f, filename='guess_my_rank.mp4')
                            message = f"🎮 **New Challenge - Guess My Rank!**\n\n" \
                                     f"Watch this video and guess the player's rank!\n" \
                                     f"Answer: ||{clip_data['rank']}||"
                            
                            await guess_channel.send(message, file=file)
                        
                        # Add success reaction to moderation message
                        await reaction.message.add_reaction("🎉")
                        
                        # Notify submitter if possible
                        try:
                            submitter = bot.get_user(clip_data['user_id'])
                            if submitter:
                                await submitter.send(f"✅ Your clip has been approved and posted in {GUESS_CHANNEL_NAME}!")
                        except:
                            pass  # Ignore if can't send DM
                            
                    except Exception as e:
                        print(f"Error posting approved clip: {e}")
                    finally:
                        cleanup_files([temp_path])
        
        # Remove from pending clips
        del bot.pending_clips[reaction.message.id]
    
    # Handle rejection (❌)
    elif str(reaction.emoji) == "❌":
        # Add rejection reaction
        await reaction.message.add_reaction("🗑️")
        
        # Notify submitter if possible
        try:
            submitter = bot.get_user(clip_data['user_id'])
            if submitter:
                await submitter.send(f"❌ Your clip has been rejected from the mods.")
        except:
            pass  # Ignore if can't send DM
        
        # Remove from pending clips
        del bot.pending_clips[reaction.message.id]

@bot.event
async def on_message(message):
    # Ignore bot messages
    if message.author == bot.user:
        return
    
    # Process only private messages with attachments
    if isinstance(message.channel, discord.DMChannel) and message.attachments:
        
        # Look for video in attachments
        video_attachment = None
        for attachment in message.attachments:
            video_extensions = ['.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm']
            if any(attachment.filename.lower().endswith(ext) for ext in video_extensions):
                video_attachment = attachment
                break
        
        if video_attachment:
            # Download video
            await message.add_reaction('⏳')  # Processing reaction
            
            video_path = await save_video_from_attachment(video_attachment)
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
                await message.reply("❌ Error downloading video. Make sure the file is a valid video.")
        else:
            await message.reply("📹 Please send a video (.mp4, .avi, .mov, etc.) to use the bot!")
    
    # Process other commands
    await bot.process_commands(message)

@bot.command(name='setup')
@commands.has_permissions(manage_channels=True)
async def setup_channels(ctx):
    """Command to create both guess-my-rank and check-clips channels"""
    
    created_channels = []
    
    # Check and create guess-my-rank channel
    guess_channel = discord.utils.get(ctx.guild.channels, name=GUESS_CHANNEL_NAME)
    if not guess_channel:
        try:
            guess_channel = await ctx.guild.create_text_channel(
                GUESS_CHANNEL_NAME,
                topic="🎮 Guess the rank of players from their videos!"
            )
            
            # Welcome message
            welcome_embed = discord.Embed(
                title="🎮 Welcome to Guess My Rank!",
                description="In this channel, you'll see gameplay videos with the player's rank hidden.\n"
                           "Try to guess the rank before revealing the answer!",
                color=0x00ff00
            )
            
            await guess_channel.send(embed=welcome_embed)
            created_channels.append(GUESS_CHANNEL_NAME)
            
        except discord.Forbidden:
            await ctx.send("❌ I don't have permissions to create channels.")
            return
        except Exception as e:
            await ctx.send(f"❌ Error creating {GUESS_CHANNEL_NAME}")
            return
    
    # Check and create check-clips channel
    check_channel = discord.utils.get(ctx.guild.channels, name=CHECK_CHANNEL_NAME)
    if not check_channel:
        try:
            check_channel = await ctx.guild.create_text_channel(
                CHECK_CHANNEL_NAME,
                topic="🔍 Moderation channel for clip submissions"
            )
            
            # Instructions message
            instructions_embed = discord.Embed(
                title="🔍 Clip Moderation",
                description="This channel is for moderating clip submissions.\n"
                           "React with ✅ to approve clips or ❌ to reject them.\n"
                           "Approved clips will be automatically posted to guess-my-rank.",
                color=0xff9900
            )
            
            await check_channel.send(embed=instructions_embed)
            created_channels.append(CHECK_CHANNEL_NAME)
            
        except Exception as e:
            await ctx.send(f"❌ Error creating {CHECK_CHANNEL_NAME}")
            return
    
    if created_channels:
        channels_list = ", ".join([f"#{name}" for name in created_channels])
        await ctx.send(f"✅ Created channels: {channels_list}")
    else:
        await ctx.send("ℹ️ All required channels already exist!")

@bot.command(name='help_rank')
async def help_command(ctx):
    """Help command"""
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
              "4. Once approved, it will appear in #guess-my-rank",
        inline=False
    )
    
    embed.add_field(
        name="🛠️ Commands:",
        value="`!setup` - Create required channels (Admin)\n"
              "`!help_rank` - Show this help",
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
              "Moderators can approve (✅) or reject (❌) submissions",
        inline=False
    )
    
    await ctx.send(embed=embed)

# Error handling
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have the necessary permissions for this command.")
    elif isinstance(error, commands.CommandNotFound):
        pass  # Ignore unknown commands
    else:
        await ctx.send(f"❌ An error occurred")

if __name__ == "__main__":
    # Dependency checks
    try:
        import cv2
        import numpy as np
    except ImportError:
        print("❌ Error: OpenCV is not installed.")
        print("Install it with: pip install opencv-python")
        exit(1)
    
    print("🤖 Starting bot...")
    print("📝 Don't forget to:")
    print("   1. Replace TOKEN with your bot token")
    print("   2. Install dependencies: pip install discord.py opencv-python")
    print("   3. Give proper permissions to the bot on Discord")
    print("   4. Create both #guess-my-rank and #check-clips channels")
    
    bot.run(TOKEN)