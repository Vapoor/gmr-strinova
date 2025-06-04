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
