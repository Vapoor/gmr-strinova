

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
    await interaction.response.send_message(embed=embed, ephemeral=True)