# Guess My Rank (gmr) - Strinova Edition
A discord bot allowing to create from zero a sort of guess-my-rank game on discord channels.

## How to setup
- I would recommand running a Virtual Environment for the Setup, because of the depedencies, but it's up to you.
```setup
python3 -m venv venv
source venv/bin/activate // (Linux)
venv\Scripts\Activate // (Windows)
pip install -r requirements.txt
```
If you want to use it, you have to manualla set a token. The token is read inside a .env with DISCORD_TOKEN

## Commands
- **/setup** (Admin only)
- **/results**
- **/help**
- **/cleanup** (Admin only)
- **/scoreboard**
- **/profile**

## What he can do :
- Receiving a clip under **200MB**, using either default discord embed files, or catbox website if you don't have nitro.
- The video can **ONLY** be received in 1920x1080 or 1280x720.
- The user can choose either put a blur that hide killfeed, vocal comms or replay name at the bottom, otherwise let the video as it is.
- After getting compressed using FFMPEG the clip goes to the channel that got setup by the mods.
- The clip can either be accepted or rejected, if rejected, its deleted from the channel, if accepted, its deleted and moved to guess-the-rank channel, where you can see the clip, people have 24h to lock their guesses, after locking 1 guess, the guess is locked forever.
- 24h Later, a small chart with percent is droped, showing how the rank distribution went who send the clip and the rate of sucesss.
- Admin can cleanup the oldest clip (only for cleaning the JSON, doesnt affect anything for user UI because of 25 dropdown limit)
- A scoreboard is up, allowing to see the current leaderboard of the server, with points, win streak and accuracy.
- The profile commands allows to see yours or other profile, seing ranks, last guess etc..

## Known Issues
- **ALL THE CODE** is in the same file
- Some Json shenarigans happening when deleting data, not affecting the good flow of the app but still weird to see.

## Authors
- Vapoor
*Thanks very much to Shark for allowing me to host on his server for free <3, even tho its 2 core and 1Go of VRAM :fire:*



