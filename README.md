# Guess My Rank (gmr) - Strinova Edition
A discord bot allowing to create from zero a sort of guess-my-rank game on discord channels.

## How to setup
- I would recommand running a Virtual Environment for the Setup, but it's up to you.
```setup
python3 -m venv venv
source venv/bin/activate // (Linux)
venv\Scripts\Activate // (Windows)
pip install -r requirements.txt
```

- ## NO TOKEN = NO BOT :)

## Commands
- **/setup** (Admin only)
- **/results**
- **/help**

## What he can do :
- Receiving a clip until **200MB**, using either default discord embed files, or catbox website
- If the video is detected 1920x1080, the blur is automatic on all the voice chat / banner / replay names etc
- After getting compressed using FFMPEG (3 threads max aka 3 rendering clip at the same time maximum to avoid burning GPU / RAM), the clip goes to the channel that got setup by the mods.
- The clip can either be accepted or rejected, if rejected, its deleted from the channel, if accepted, its deleted and moved to guess-the-rank channel, where you can see the clip, people have 24h to lock their guesses, after locking 1 guess, the guess is locked forever, the user instantly have the rank after the 1st guess.
- 24h Later, a small chart with percent is droped, showing how the rank distribution went.

## Known Issues
- For mods, when rejecting / accepting clips, the user at the start has no clue if its was accepted or not, or still waiting, I can maybe create a command /status that would show for each id all theirs current clip, with status Accepted / Refused / In process
- No CDN handling for clips but its not that important for now
- **ALL THE CODE** is in the same file
- @ROTD not getting pinged somehow

## What Im working On soon
- /cleanup for admins to delete old clips, because for now all the clips datas are saved in a file, its not that heavy because its only text with json, but can grow quickly

## Authors
- Vapoor
- Help of Walerchik


