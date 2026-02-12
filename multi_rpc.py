import time
import requests
import subprocess
import urllib3
import base64
import os
import sys
from pypresence import Presence
from PIL import Image
import pystray
import threading
import logging
import ctypes
import atexit

running = True  # global flag to control main loop

# ------------------ SINGLE INSTANCE LOCK ------------------
mutex = ctypes.windll.kernel32.CreateMutexW(
    None, False, "Global\\GameRPC_Discord"
)
last_error = ctypes.windll.kernel32.GetLastError()

if last_error == 183:  # ERROR_ALREADY_EXISTS
    logging.error("Another instance is already running")

    ctypes.windll.user32.MessageBoxW(
        0,
        "Discord Game RPC is already running.",
        "Already Running",
        0x10
    )
    sys.exit(0)


def release_mutex():
    try:
        ctypes.windll.kernel32.ReleaseMutex(mutex)
    except:
        pass


atexit.register(release_mutex)


# ------------------ CONFIG ------------------
DISCORD_APP_ID_LOL = "1470362824315371616"
DISCORD_APP_ID_VALO = "1470363079949680711"
LOL_API = "https://127.0.0.1:2999/liveclientdata/allgamedata"
REFRESH_INTERVAL = 10  # seconds

# SSL warnings off (local Riot API)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Logging setup
logging.basicConfig(level=logging.INFO)

# Connect to Discord RPC for each game
rpc_lol = Presence(DISCORD_APP_ID_LOL)
rpc_valo = Presence(DISCORD_APP_ID_VALO)

try:
    rpc_lol.connect()
except Exception as e:
    logging.error(f"Failed to connect to LoL RPC: {e}")

try:
    rpc_valo.connect()
except Exception as e:
    logging.error(f"Failed to connect to Valorant RPC: {e}")

# ------------------ HELPER FOR PYINSTALLER RESOURCES ------------------


def resource_path(relative_path):
    """ Get absolute path to resource, works for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# ------------------ PROCESS DETECTION ------------------


def is_running(process_name):
    try:
        tasks = subprocess.check_output(
            ["tasklist"], creationflags=subprocess.CREATE_NO_WINDOW
        ).decode().lower()
        return process_name.lower() in tasks
    except Exception as e:
        logging.error(f"Process check failed: {e}")
        return False


def is_lol_ingame():
    try:
        r = requests.get(LOL_API, verify=False, timeout=2)
        return r.status_code == 200
    except:
        return False


def is_valo_ingame():
    port, auth = get_riot_auth()
    if not port:
        return False

    try:
        headers = {"Authorization": f"Basic {auth}"}
        r = requests.get(
            f"https://127.0.0.1:{port}/core-game/v1/match-details",
            headers=headers, verify=False, timeout=2
        )
        return r.status_code == 200
    except:
        return False

# ------------------ RIOT AUTH (Valorant) ------------------


def get_riot_auth():
    try:
        path = os.path.join(os.getenv("LOCALAPPDATA"),
                            "Riot Games", "Riot Client", "Config", "lockfile")
        with open(path) as f:
            data = f.read().split(":")
        port = data[2]
        token = data[3]
        auth = base64.b64encode(f"riot:{token}".encode()).decode()
        return port, auth
    except Exception as e:
        logging.info(f"Riot lockfile not found yet: {e}")
        return None, None

# ------------------ LEAGUE HANDLER ------------------


def handle_lol():
    try:
        r = requests.get(LOL_API, verify=False, timeout=2)
        if r.status_code != 200:
            return False
        data = r.json()
    except Exception as e:
        logging.info(f"League API not available: {e}")
        return False

    active_name = data["activePlayer"]["summonerName"]
    player = next((p for p in data["allPlayers"]
                  if p["summonerName"] == active_name), None)
    if not player:
        return True

    game_time = int(data["gameData"]["gameTime"])
    if game_time < 5:
        return True

    k = player["scores"]["kills"]
    d = player["scores"]["deaths"]
    a = player["scores"]["assists"]
    cs = player["scores"]["creepScore"]
    champ = player["championName"]
    mode = data["gameData"]["gameMode"]

    minutes = game_time // 60
    seconds = game_time % 60

    try:
        rpc_lol.update(
            details=f"{champ} | {mode}",
            state=f"{minutes}:{seconds:02d} | {k}/{d}/{a} | {cs} CS",
            large_image="cat",
            large_text="League of Legends",
            start=int(time.time()) - game_time
        )
    except Exception as e:
        logging.error(f"Failed to update RPC for LoL: {e}")
    return True

# ------------------ VALORANT HANDLER ------------------


def handle_valorant():
    if not is_valo_ingame():
        try:
            rpc_valo.clear()
        except:
            pass
        return False

    port, auth = get_riot_auth()
    if not port:
        try:
            rpc_valo.update(
                details="Protecting his kitten",
                state="Fighting his darkside 😈",
                large_image="valoapp",
                large_text="Valorant"
            )
        except Exception as e:
            logging.info(f"Fallback RPC update failed: {e}")
        return True

    headers = {"Authorization": f"Basic {auth}"}
    try:
        response = requests.get(
            f"https://127.0.0.1:{port}/core-game/v1/match-details",
            headers=headers, verify=False, timeout=2
        )
        data = response.json()

        me = next((p for p in data.get('Players', []) if p.get(
            'Subject') == data.get('LocalPlayer', {}).get('Subject')), None)
        if not me:
            raise ValueError("Local player not found")

        agent = me.get('CharacterName', 'Unknown')
        k = me.get('Stats', {}).get('Kills', 0)
        d = me.get('Stats', {}).get('Deaths', 0)
        a = me.get('Stats', {}).get('Assists', 0)

        my_team_score = sum(p.get('Stats', {}).get('Score', 0) for p in data.get(
            'Players', []) if p.get('TeamID') == me.get('TeamID'))
        enemy_team_score = sum(p.get('Stats', {}).get('Score', 0) for p in data.get(
            'Players', []) if p.get('TeamID') != me.get('TeamID'))

        map_name = data.get('MapInfo', {}).get('MapDisplayName', 'Unknown')

        rpc_valo.update(
            details=f"{agent} | {map_name}",
            state=f"{k}/{d}/{a} | Score: {my_team_score}-{enemy_team_score}",
            large_image="valoapp",
            large_text="Valorant"
        )

    except Exception as e:
        logging.info(f"Valorant API not ready or failed: {e}")
        try:
            rpc_valo.update(
                details="Fighting his dark side",
                state="In Game",
                large_image="valoapp",
                large_text="Valorant"
            )
        except Exception as e2:
            logging.info(f"Fallback RPC update failed: {e2}")

    return True

# ------------------ MAIN LOOP ------------------


def main_loop():
    global running
    while running:
        lol_ingame = is_lol_ingame()
        valo_ingame = is_valo_ingame()

        if lol_ingame:
            handle_lol()
        else:
            try:
                rpc_lol.clear()
            except:
                pass

        if valo_ingame:
            handle_valorant()
        else:
            try:
                rpc_valo.clear()
            except:
                pass

        time.sleep(REFRESH_INTERVAL)

# ------------------ SYSTEM TRAY ICON ------------------


def create_tray_icon():
    icon = pystray.Icon("GameRPC")
    try:
        # Load the icon correctly for PyInstaller
        icon.icon = Image.open(resource_path("game-controller.png"))
    except Exception as e:
        logging.error(f"Failed to load tray icon: {e}")
    icon.title = "Discord Game RPC"

    # Quit menu now fully stops the script
    def quit_app(icon, item):
        global running
        running = False  # signal main loop to stop
        try:
            rpc_lol.clear()
        except:
            pass
        try:
            rpc_valo.clear()
        except:
            pass
        icon.stop()  # stops the tray icon

    icon.menu = pystray.Menu(
        pystray.MenuItem("Quit", quit_app)
    )

    icon.run()  # run in the main thread


# ------------------ START SCRIPT ------------------

if __name__ == "__main__":
    # Start the main loop in a separate thread
    threading.Thread(target=main_loop, daemon=True).start()

    # Run the tray icon in the main thread
    create_tray_icon()
