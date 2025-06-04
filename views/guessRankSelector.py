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