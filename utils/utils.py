#################
### UTILS #######
#################

CHANNEL_CONFIG_FILE = 'channel_config.json'

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