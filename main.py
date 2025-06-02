import discord
from discord.ext import commands
import cv2
import numpy as np
import asyncio
import os
import tempfile
from typing import List, Optional
from dotenv import load_dotenv

# Configuration
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUESS_CHANNEL_NAME = 'guess-my-rank'

# Liste des rangs (adaptez selon votre jeu)
RANKS = [
    "Substance","Molecule","Atom","Proton","Neutron","Electron","Quark","Superstring","Singularity"
]
# Configuration du bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

class RankSelector(discord.ui.View):
    def __init__(self, user_id: int, video_path: str):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.video_path = video_path
        self.selected_rank = None
        
        # Créer un menu déroulant avec tous les rangs
        self.rank_select = discord.ui.Select(
            placeholder="Choisissez votre rang...",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label=rank, value=rank) for rank in RANKS]
        )
        self.rank_select.callback = self.rank_callback
        self.add_item(self.rank_select)
    
    async def rank_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Ce n'est pas votre sélection de rang!", ephemeral=True)
            return
        
        self.selected_rank = self.rank_select.values[0]
        await interaction.response.send_message(f"Rang sélectionné: **{self.selected_rank}**\nTraitement de la vidéo en cours...", ephemeral=True)
        
        # Traiter et envoyer la vidéo
        await self.process_and_send_video(interaction)
    
    async def process_and_send_video(self, interaction: discord.Interaction):
        try:
            # Vérifier la taille du fichier original
            original_size_mb = os.path.getsize(self.video_path) / (1024 * 1024)
            
            if original_size_mb > 100:  # Limite raisonnable pour éviter les très gros fichiers
                await interaction.followup.send(
                    f"❌ Vidéo trop volumineuse ({original_size_mb:.1f}MB)!\n"
                    f"Veuillez utiliser une vidéo de moins de 100MB.", 
                    ephemeral=True
                )
                cleanup_files([self.video_path])
                return
            
            # Créer la vidéo floutée avec compression automatique
            await interaction.followup.send(
                f"🔄 Traitement en cours... (Vidéo: {original_size_mb:.1f}MB)\n"
                f"Cela peut prendre quelques minutes selon la taille.",
                ephemeral=True
            )
            
            blurred_video_path = await blur_video(self.video_path)
            
            # Vérifier la taille finale
            final_size_mb = os.path.getsize(blurred_video_path) / (1024 * 1024)
            
            if final_size_mb > 25:  # Limite Discord
                await interaction.followup.send(
                    f"❌ Impossible de compresser suffisamment la vidéo ({final_size_mb:.1f}MB)!\n"
                    f"Veuillez utiliser une vidéo plus courte ou de moindre qualité.",
                    ephemeral=True
                )
                cleanup_files([self.video_path, blurred_video_path])
                return
            
            # Chercher le channel dans tous les serveurs où le bot est présent
            channel = None
            for guild in bot.guilds:
                found_channel = discord.utils.get(guild.channels, name=GUESS_CHANNEL_NAME)
                if found_channel:
                    channel = found_channel
                    break
            
            if not channel:
                await interaction.followup.send(
                    f"❌ Channel '{GUESS_CHANNEL_NAME}' non trouvé!\n"
                    f"Assurez-vous qu'un channel nommé '{GUESS_CHANNEL_NAME}' existe sur un serveur où le bot est présent.", 
                    ephemeral=True
                )
                cleanup_files([self.video_path, blurred_video_path])
                return
            
            # Envoyer la vidéo dans le channel
            with open(blurred_video_path, 'rb') as f:
                file = discord.File(f, filename='guess_my_rank.mp4')
                message = f"🎮 **Nouveau défi - Devinez mon rang !**\n\n" \
                         f"Regardez cette vidéo et devinez le rang du joueur !\n" \
                         f"Réponse: ||{self.selected_rank}||"
                
                await channel.send(message, file=file)
            
            # Confirmer à l'utilisateur
            await interaction.followup.send(
                f"✅ Vidéo postée avec succès dans le channel guess-my-rank!\n"
                f"Taille finale: {final_size_mb:.1f}MB", 
                ephemeral=True
            )
            
            # Nettoyer les fichiers temporaires
            cleanup_files([self.video_path, blurred_video_path])
            
        except discord.HTTPException as e:
            if e.code == 40005:  # Payload too large
                await interaction.followup.send(
                    "❌ Vidéo encore trop volumineuse après compression!\n"
                    "Essayez avec une vidéo plus courte (moins de 30 secondes) ou de plus faible résolution.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(f"❌ Erreur Discord: {str(e)}", ephemeral=True)
            cleanup_files([self.video_path])
            
        except Exception as e:
            await interaction.followup.send(f"❌ Erreur lors du traitement: {str(e)}", ephemeral=True)
            cleanup_files([self.video_path])

async def blur_video(input_path: str, blur_width: int = 400, blur_height: int = 200, max_size_mb: int = 20) -> str:
    """Applique un floutage rectangulaire en haut à gauche de la vidéo avec compression automatique"""
    
    # Créer un fichier temporaire pour la sortie
    output_fd, output_path = tempfile.mkstemp(suffix='.mp4')
    os.close(output_fd)
    
    # Ouvrir la vidéo
    cap = cv2.VideoCapture(input_path)
    
    # Propriétés de la vidéo
    fps = int(cap.get(cv2.CAP_PROP_FPS))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    # Calculer la taille originale approximative
    original_size_mb = os.path.getsize(input_path) / (1024 * 1024)
    
    # Paramètres de compression adaptatifs
    quality_factor = 1.0
    resize_factor = 1.0
    
    if original_size_mb > max_size_mb:
        # Calculer les facteurs de compression nécessaires
        compression_ratio = max_size_mb / original_size_mb
        
        if compression_ratio < 0.3:  # Compression très forte nécessaire
            quality_factor = 0.5
            resize_factor = 0.7
        elif compression_ratio < 0.6:  # Compression modérée
            quality_factor = 0.7
            resize_factor = 0.85
        else:  # Compression légère
            quality_factor = 0.8
            resize_factor = 0.9
    
    # Nouvelles dimensions après redimensionnement
    new_width = int(width * resize_factor)
    new_height = int(height * resize_factor)
    
    # Assurer que les dimensions sont paires (requis par certains codecs)
    new_width = new_width + (new_width % 2)
    new_height = new_height + (new_height % 2)
    
    # Ajuster les dimensions de floutage proportionnellement
    blur_width = int(blur_width * resize_factor)
    blur_height = int(blur_height * resize_factor)
    
    # Configuration du codec avec compression
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (new_width, new_height))
    
    frame_count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        # Redimensionner si nécessaire
        if resize_factor != 1.0:
            frame = cv2.resize(frame, (new_width, new_height))
        
        # Créer la zone de floutage (en haut à gauche)
        blur_x1, blur_y1 = 0, 0
        blur_x2 = min(blur_width, new_width)
        blur_y2 = min(blur_height, new_height)
        
        # Extraire la région à flouter
        roi = frame[blur_y1:blur_y2, blur_x1:blur_x2]
        
        # Appliquer un flou gaussien fort
        blur_kernel = max(15, int(51 * resize_factor))
        if blur_kernel % 2 == 0:
            blur_kernel += 1
        blurred_roi = cv2.GaussianBlur(roi, (blur_kernel, blur_kernel), 0)
        
        # Remplacer la région dans l'image originale
        frame[blur_y1:blur_y2, blur_x1:blur_x2] = blurred_roi
        
        # Réduire la qualité si nécessaire
        if quality_factor < 1.0:
            # Compression JPEG pour réduire la qualité
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), int(quality_factor * 100)]
            _, frame_encoded = cv2.imencode('.jpg', frame, encode_param)
            frame = cv2.imdecode(frame_encoded, cv2.IMREAD_COLOR)
        
        # Écrire la frame
        out.write(frame)
        frame_count += 1
    
    # Libérer les ressources
    cap.release()
    out.release()
    
    # Vérifier la taille finale
    final_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"Compression: {original_size_mb:.1f}MB -> {final_size_mb:.1f}MB (facteur: {resize_factor:.2f}, qualité: {quality_factor:.2f})")
    
    return output_path

def cleanup_files(file_paths: List[str]):
    """Nettoie les fichiers temporaires"""
    for path in file_paths:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            print(f"Erreur lors du nettoyage de {path}: {e}")

async def save_video_from_attachment(attachment: discord.Attachment) -> Optional[str]:
    """Télécharge et sauvegarde une vidéo depuis un attachement Discord"""
    
    # Extensions vidéo supportées
    video_extensions = ['.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm']
    
    # Vérifier si c'est une vidéo
    if not any(attachment.filename.lower().endswith(ext) for ext in video_extensions):
        return None
    
    # Créer un fichier temporaire
    fd, temp_path = tempfile.mkstemp(suffix=os.path.splitext(attachment.filename)[1])
    os.close(fd)
    
    try:
        # Télécharger le fichier
        await attachment.save(temp_path)
        return temp_path
    except Exception as e:
        print(f"Erreur lors du téléchargement: {e}")
        cleanup_files([temp_path])
        return None

@bot.event
async def on_ready():
    print(f'{bot.user} est connecté et prêt!')
    print(f'Serveurs: {len(bot.guilds)}')

@bot.event
async def on_message(message):
    # Ignorer les messages du bot
    if message.author == bot.user:
        return
    
    # Traiter seulement les messages privés avec des attachements
    if isinstance(message.channel, discord.DMChannel) and message.attachments:
        
        # Chercher une vidéo dans les attachements
        video_attachment = None
        for attachment in message.attachments:
            video_extensions = ['.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm']
            if any(attachment.filename.lower().endswith(ext) for ext in video_extensions):
                video_attachment = attachment
                break
        
        if video_attachment:
            # Télécharger la vidéo
            await message.add_reaction('⏳')  # Réaction de traitement
            
            video_path = await save_video_from_attachment(video_attachment)
            if video_path:
                # Créer la vue de sélection de rang
                view = RankSelector(message.author.id, video_path)
                
                embed = discord.Embed(
                    title="🎮 Sélection de rang",
                    description="Choisissez votre rang dans le menu déroulant ci-dessous.\n"
                               "Votre vidéo sera ensuite postée dans le channel guess-my-rank avec un floutage.",
                    color=0x00ff00
                )
                
                await message.reply(embed=embed, view=view)
                await message.remove_reaction('⏳', bot.user)
                await message.add_reaction('✅')
            else:
                await message.reply("❌ Erreur lors du téléchargement de la vidéo. Assurez-vous que le fichier est une vidéo valide.")
        else:
            await message.reply("📹 Veuillez envoyer une vidéo (.mp4, .avi, .mov, etc.) pour utiliser le bot!")
    
    # Traiter les autres commandes
    await bot.process_commands(message)

@bot.command(name='setup')
@commands.has_permissions(manage_channels=True)
async def setup_channel(ctx):
    """Commande pour créer le channel guess-my-rank"""
    
    # Vérifier si le channel existe déjà
    existing_channel = discord.utils.get(ctx.guild.channels, name=GUESS_CHANNEL_NAME)
    if existing_channel:
        await ctx.send(f"Le channel {GUESS_CHANNEL_NAME} existe déjà!")
        return
    
    # Créer le channel
    try:
        channel = await ctx.guild.create_text_channel(
            GUESS_CHANNEL_NAME,
            topic="🎮 Devinez le rang des joueurs à partir de leurs vidéos!"
        )
        
        # Message de bienvenue
        welcome_embed = discord.Embed(
            title="🎮 Bienvenue dans Guess My Rank!",
            description="Dans ce channel, vous verrez des vidéos de gameplay avec le rang du joueur caché.\n"
                       "Essayez de deviner le rang avant de révéler la réponse!",
            color=0x00ff00
        )
        
        await channel.send(embed=welcome_embed)
        await ctx.send(f"✅ Channel {GUESS_CHANNEL_NAME} créé avec succès!")
        
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas les permissions pour créer des channels.")
    except Exception as e:
        await ctx.send(f"❌ Erreur lors de la création du channel: {str(e)}")

@bot.command(name='help_rank')
async def help_command(ctx):
    """Commande d'aide"""
    embed = discord.Embed(
        title="🤖 Bot Guess My Rank - Aide",
        description="Ce bot permet de créer des défis de devinette de rang!",
        color=0x0099ff
    )
    
    embed.add_field(
        name="📱 Comment utiliser:",
        value="1. Envoyez-moi une vidéo en message privé\n"
              "2. Sélectionnez votre rang dans le menu\n"
              "3. La vidéo sera postée avec un floutage dans #guess-my-rank",
        inline=False
    )
    
    embed.add_field(
        name="🛠️ Commandes:",
        value="`!setup` - Créer le channel guess-my-rank (Admin)\n"
              "`!help_rank` - Afficher cette aide",
        inline=False
    )
    
    embed.add_field(
        name="🎮 Formats supportés:",
        value="MP4, AVI, MOV, MKV, WMV, FLV, WEBM",
        inline=False
    )
    
    await ctx.send(embed=embed)

# Gestion des erreurs
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Vous n'avez pas les permissions nécessaires pour cette commande.")
    elif isinstance(error, commands.CommandNotFound):
        pass  # Ignorer les commandes inconnues
    else:
        await ctx.send(f"❌ Une erreur s'est produite: {str(error)}")

if __name__ == "__main__":
    # Vérifications des dépendances
    try:
        import cv2
        import numpy as np
    except ImportError:
        print("❌ Erreur: OpenCV n'est pas installé.")
        print("Installez-le avec: pip install opencv-python")
        exit(1)
    
    print("🤖 Démarrage du bot...")
    print("📝 N'oubliez pas de:")
    print("   1. Remplacer TOKEN par votre token de bot")
    print("   2. Installer les dépendances: pip install discord.py opencv-python")
    print("   3. Donner les bonnes permissions au bot sur Discord")
    
    bot.run(TOKEN)