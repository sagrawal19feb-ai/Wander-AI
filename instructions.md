The folder is fully portable - it works on any PC with zero installs.
Nothing is ever installed on the computer.

CHAT
- Type a message and press Enter. Alt+Enter = new line.
- Pick your model from the selection screen at start.
- Your conversation continues automatically where you left off.
- Wander remembers important facts across sessions (memory).

USEFUL COMMANDS (type in the chat)
/help                 all commands
/models  /switch      list models / change model
/recommend            which model fits this pc best
/remember <text>      save a fact Wander keeps forever
/memories  /forget    list memories / remove one
/mode flash|normal|reasoning
/themes               change the look
/set key value        change any setting
/persona              show your personalization
/save  /load          sessions
/tokens  /stats       context usage / statistics
/quit                 exit

PERSONALIZE
Edit personalization.txt (created on first start) to tell Wander who
you are and how it should behave. Changes apply instantly.

INSTALLER OPTIONS
1. Base engine                       (required)
2. Turbo engine                      (faster CPU generation)
3. GPU engine                        (NVIDIA only, auto-detects the GPU)
4. Everything                        (all of the above, automated)

USING THE GPU ON ANOTHER PC
1. Make sure that PC has an NVIDIA driver installed (CUDA 12.1 or newer).
2. Plug the drive into that PC.
3. Run the installer, option 3 (GPU) - it detects the GPU automatically
   and installs the matching engine.
4. Wander uses the GPU there automatically. On PCs without a GPU it runs
   on CPU - nothing to configure.
Note: after installing the GPU engine, if you bring the pendrive back to
a PC without an NVIDIA GPU, run installer option 2 (turbo) there to
restore the fastest CPU engine.
