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
        await interaction.response.send_message(f"Selected rank: **{self.selected_rank}**\nProcessing video...", ephemeral=True)
        
        
        await self.process_and_send_video(interaction)
    
    async def process_and_send_video(self, interaction: discord.Interaction):
        try:
            #Check size
            original_size_mb = os.path.getsize(self.video_path) / (1024 * 1024)
            
            if original_size_mb > 100:  # check is > 100MB
                await interaction.followup.send(
                    f"❌ Video too large ({original_size_mb:.1f}MB)!\n"
                    f"Please use a video smaller than 100MB.", 
                    ephemeral=True
                )
                cleanup_files([self.video_path])
                return
            
            
            await interaction.followup.send(
                f"🔄 Processing... (Video: {original_size_mb:.1f}MB)\n"
                f"This may take a few minutes depending on size.",
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
