import discord
from discord import app_commands
from discord.ext import commands

@tree.command(name="results", description="Display last days results")
async def show_results(ctx):
    """Show results browser for finished clips"""
    
    results_data = load_results_data()
    finished_clips = [clip_id for clip_id, clip_data in results_data.items() if clip_data['expired']]
    
    if not finished_clips:
        embed = discord.Embed(
            title="📊 No Results Available",
            description="No finished clips found yet. Wait for some clips to complete their 24-hour voting period!",
            color=0xff9900
        )
        await ctx.send(embed=embed)
        return
    
    embed = discord.Embed(
        title="📊 Browse Clip Results",
        description="Select a clip from the dropdown menu below to view its results.",
        color=0x0099ff
    )
    
    view = ResultsSelector()
    await ctx.send(embed=embed, view=view)