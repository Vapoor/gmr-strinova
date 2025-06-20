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
- **/cleanup** (Admin only)
- **/scoreboard**

## What he can do :
- Receiving a clip under **150MB**, using either default discord embed files, or catbox website.
- The video can only be received in 1920x1080 or 1280x720.
- After getting compressed using FFMPEG (3 threads max aka 3 rendering clip at the same time maximum to avoid burning GPU / RAM), the clip goes to the channel that got setup by the mods.
- The clip can either be accepted or rejected, if rejected, its deleted from the channel, if accepted, its deleted and moved to guess-the-rank channel, where you can see the clip, people have 24h to lock their guesses, after locking 1 guess, the guess is locked forever.
- 24h Later, a small chart with percent is droped, showing how the rank distribution went who send the clip and the rate of sucesss.
- Admin can cleanup the oldest clip (only for PC performance, doesnt affect anything for user UI because of 25 dropdown limit)
- A scoreboard is up, allowing to see the current leaderboard of the server, with points, win streak and accuracy.

## Known Issues
- **ALL THE CODE** is in the same file
- Some Json shenarigans happening when deleting data, not affecting the good flow of the app but still weird to see.



## Authors
- Vapoor
*Thanks very much to Shark for allowing me to host on his server for free <3*



