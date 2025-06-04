import discord
from discord import app_commands
from discord.ext import commands

from utils import get_channel_names

@tree.command(name="setup", description="Setup both channels use for the game")
@commands.has_permissions(manage_channels=True)
async def setup_channels(ctx):
    """Command to configure channel names and create channels if needed"""
    
    # Vérifier la configuration actuelle
    check_channel_name, guess_channel_name = get_channel_names(ctx.guild.id)
    
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
    
    await ctx.send(embed=embed, view=SetupView())
