import os
import sys
import time
import re
import requests
from lxml import html
import colorama

colorama.init()

# -------------------- CONSTANTS --------------------

DEF_LOG = r"C:\Program Files\Roberts Space Industries\StarCitizen\LIVE\Game.log"

# Colors i estil
BOLD = '\033[1m'
RESET = "\033[0m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
MAGENTA = '\033[35m'
PINK = BOLD + MAGENTA


# Llistes personalitzables
LLISTES_URL = "https://raw.githubusercontent.com/ildirda/Star-Citizen-Live-Log-Parser/main/llistes.txt"

def load_lists():
    try:
        resp = requests.get(LLISTES_URL, timeout=10)
        resp.raise_for_status()
        globals_dict = {}
        exec(resp.text, globals_dict)
        # Les llistes carregades estaran dins globals_dict
        PLAYERS_BLACKLIST = globals_dict.get("PLAYERS_BLACKLIST", [])
        PLAYERS_WHITELIST = globals_dict.get("PLAYERS_WHITELIST", [])
        ORGS_BLACKLIST = globals_dict.get("ORGS_BLACKLIST", [])
        ORGS_WHITELIST = globals_dict.get("ORGS_WHITELIST", [])
        return PLAYERS_BLACKLIST, PLAYERS_WHITELIST, ORGS_BLACKLIST, ORGS_WHITELIST
    except Exception as e:
        print("No s'han pogut carregar les llistes de GitHub:", e)
        # Retorna llistes buides o, si vols, unes de per defecte:
        return [], [], [], []

# Carrega llistes de GitHub!
PLAYERS_BLACKLIST, PLAYERS_WHITELIST, ORGS_BLACKLIST, ORGS_WHITELIST = load_lists()


# -------------------- CONFIG I NICKS --------------------

def get_script_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

def get_config():
    nickfile = os.path.join(get_script_dir(), "nick.txt")
    nick = None
    game_dir = None

    # Llegeix nick i directori guardat, si existeixen
    if os.path.isfile(nickfile):
        with open(nickfile, encoding="utf-8") as f:
            lines = [l.strip() for l in f.readlines()]
            if lines:
                nick = lines[0]
            if len(lines) > 1:
                game_dir = lines[1]

    # Si no hi ha nick, pregunta
    if not nick:
        nick = input("Introdueix el teu nick de Star Citizen: ").strip()

    # 1. Prova primer el log per defecte
    if os.path.isfile(DEF_LOG):
        log_path = DEF_LOG
        use_default = True
    else:
        # 2. Si tens un directori guardat a nick.txt i hi ha Game.log allà, fes-lo servir
        use_default = False
        log_path = None
        if game_dir and os.path.isdir(game_dir):
            candidate = os.path.join(game_dir, "Game.log")
            if os.path.isfile(candidate):
                log_path = candidate
        # 3. Si no, pregunta
        while not log_path or not os.path.isfile(log_path):
            game_dir = input("Indica el directori d'instal·lació. Ex: F:\\StarCitizen\\LIVE: ").strip()
            candidate = os.path.join(game_dir, "Game.log")
            if os.path.isfile(candidate):
                log_path = candidate
                break
            print("No s'ha trobat Game.log a aquest directori. Torna-ho a provar.")

    # Desa la configuració (si no és la per defecte)
    if not use_default:
        with open(nickfile, "w", encoding="utf-8") as f:
            f.write(nick + "\n" + game_dir)
    return nick, log_path

# -------- INICIALITZACIÓ --------
CURRENT_USER, LOG_FILENAME = get_config()
print(f"Usuari: {CURRENT_USER}")
print(f"Log: {LOG_FILENAME}")

CREW_NICKS = [
    # ... aquí la teva llista de nicks ...
]

citizen_cache = {}

# -------------------- COLORS i ENLLAÇOS --------------------

def supports_osc8():
    return (
        'WT_SESSION' in os.environ or
        os.environ.get('TERM_PROGRAM') in ('iTerm.app', 'WezTerm') or
        'VTE_VERSION' in os.environ or
        'TMUX' in os.environ
    )

def format_link(nick, url):
    if supports_osc8():
        ESC = '\033'
        BEL = '\a'
        return f"{ESC}]8;;{url}{BEL}{nick}{ESC}]8;;{BEL}"
    else:
        return f"{nick} ({url})"

# -------------------- LÒGICA DE COLORS PER NICKS --------------------

def color_nick(nick, org=""):
    u_nick = nick.lower()
    u_org = org.lower()
    if u_nick == CURRENT_USER.lower():
        return f"{PINK}{nick}{RESET}"
    if u_nick in (n.lower() for n in PLAYERS_WHITELIST) or u_org in (o.lower() for o in ORGS_WHITELIST):
        return f"{GREEN}{nick}{RESET}"
    if u_nick in (n.lower() for n in CREW_NICKS):
        return f"{GREEN}{nick}{RESET}"
    if u_nick == "unknown":
        return f"{YELLOW}{nick}{RESET}"
    if u_nick in (n.lower() for n in PLAYERS_BLACKLIST) or u_org in (o.lower() for o in ORGS_BLACKLIST):
        return f"{RED}{nick}{RESET}"
    return f"{YELLOW}{nick}{RESET}"

# -------------------- OBTENCIÓ INFO CIUTADÀ RSI --------------------

def clean_text(nodes):
    return ' '.join(nodes[0].text_content().split()) if nodes else ""

def get_citizen_info_xpath(nick):
    if nick in citizen_cache:
        return citizen_cache[nick]
    url = f"https://robertsspaceindustries.com/en/citizens/{nick}"
    try:
        resp = requests.get(url, timeout=5)
        doc = html.fromstring(resp.content)
        enlist = clean_text(doc.xpath('//*[@id="public-profile"]/div[2]/div[2]/div/p[1]/strong'))
        # Nova gestió location/fluency:
        p2 = doc.xpath('//*[@id="public-profile"]/div[2]/div[2]/div/p[2]')
        location = ""
        if p2:
            is_fluency = any("Fluency" in (span.text_content() or "") for span in p2[0].xpath('.//span'))
            if not is_fluency:
                strongs = p2[0].xpath('.//strong')
                location = clean_text(strongs)
        org = ""
        org_nodes = doc.xpath('//*[@id="public-profile"]/div[2]/div[1]/div/div[2]/div/div[2]/p[1]/a')
        if org_nodes:
            org = org_nodes[0].text_content().strip()
        citizen_cache[nick] = (enlist, org, location)
        return enlist, org, location
    except Exception:
        citizen_cache[nick] = ("", "", "")
        return "", "", ""

def format_info(enlist, org, location):
    import re
    year = ""
    if enlist:
        match = re.search(r"\b(19|20)\d{2}\b", enlist)
        if match:
            year = match.group(0)
    country = ""
    if location:
        fragments = [frag.strip() for frag in location.split(',')]
        if fragments:
            country = fragments[0]
    fields = [year, org, country]
    result = " · ".join([x for x in fields if x])
    return f" ({result})" if result else ""

# -------------------- DETECCIÓ I FORMAT DE MISSATGES --------------------

def is_npc_or_vehicle(nick):
    nick = nick.strip()
    # ID numèric llarg al final de qualsevol fragment separada per "_"
    if re.search(r"_\d{6,}", nick):
        return True
    # O patró d’IA/human/vehicle típic
    npc_keywords = ["PU_", "AI_", "NPC_", "Pilot_", "Human_", "Ship_", "Vehicle_"]
    for kw in npc_keywords:
        if nick.startswith(kw):
            return True
    return False

def highlight_external_nick(nick):
    if is_npc_or_vehicle(nick):
        return nick

    if nick.lower() == CURRENT_USER.lower():
        return color_nick(nick)
    if nick in CREW_NICKS:
        return color_nick(nick, crew=True)

    enlist, org, location = get_citizen_info_xpath(nick)
    nick_colored = color_nick(nick, org)
    url = f"https://robertsspaceindustries.com/en/citizens/{nick}"
    linked_nick = format_link(nick_colored, url)
    info_text = format_info(enlist, org, location)
    return f"{linked_nick}{info_text}"


def highlight_all(msg):
    # Usuari actual primer
    msg = re.sub(rf'\b{re.escape(CURRENT_USER)}\b', f"{PINK}{CURRENT_USER}{RESET}", msg)
    # Després la resta de crew nicks
    for crew_nick in sorted(CREW_NICKS, key=len, reverse=True):
        if crew_nick.lower() == CURRENT_USER.lower():
            continue
        pattern = rf'\b{re.escape(crew_nick)}\b'
        msg = re.sub(pattern, color_nick(crew_nick), msg)
    return msg


def highlight_murder(msg, victim, killer):
    out = msg.replace("assassinat per", f"{BOLD}assassinat per{RESET}")
    out = out.replace("ha destruït una", f"{BOLD}ha destruït una{RESET}")
    out = out.replace("apunta míssils", f"{BOLD}apunta míssils{RESET}")
    out = out.replace("Ha aparegut", f"{BOLD}Ha aparegut{RESET}")
    # Coloreja nicks
    out = highlight_all(out)
    # Enllaça el killer
    if killer != CURRENT_USER and len(killer) < 20:
        out = re.sub(rf"{re.escape(killer)}(\s*\(.*?\))?", highlight_external_nick(killer), out, count=1)
    return out

def highlight_user(msg, *args):
    out = msg.replace("assassinat per", f"{BOLD}assassinat per{RESET}")
    out = out.replace("ha destruït una", f"{BOLD}ha destruït una{RESET}")
    out = out.replace("apunta míssils", f"{BOLD}apunta míssils{RESET}")
    out = out.replace("Ha aparegut", f"{BOLD}Ha aparegut{RESET}")
    return highlight_all(out)

# -------------------- PARSEJADOR DE LOG --------------------

def detect_actor_death(line):
    if "<Actor Death> CActor::Kill:" not in line: return None, None, None
    pattern = r"<(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})\.\d{3}Z> \[Notice\] <Actor Death> CActor::Kill: '([\w-]+)' \[\d+\] in zone '([\w-]+)' killed by '([\w-]+)' \[\d+\] using '([\w-]+)' \[Class ([\w-]+)\] with damage type '([\w-]+)'.*"
    match = re.search(pattern, line)
    if match:
        d = match.group
        msg = f"{d(1)[8:10]}/{d(1)[5:7]}/{d(1)[2:4]} · {d(2)} - {d(3)} assassinat per {d(5)}"
        return msg, d(3), d(5)
    return None, None, None

def detect_missile_target(line):
    if "<Debug Hostility Events>" not in line: return None
    pattern = r"<(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})\.\d{3}Z> (\[SPAM \d+\])?\[Notice\] <Debug Hostility Events> \[(\w+)\] Fake hit FROM ([\w-]+) TO ([\w-]+)\. Being sent to child ([\w-]+) \[Team_MissionFeatures\]\[HitInfo\].*"
    match = re.search(pattern, line)
    if match:
        d = match.group
        target = "PU_Pilots-Human-Criminal" if d(7).startswith("PU_Pilots-Human-Criminal") else d(7)
        msg = f"{d(1)[8:10]}/{d(1)[5:7]}/{d(1)[2:4]} · {d(2)} - {highlight_external_nick(d(5))} apunta míssils 🚀 a {highlight_external_nick(target)}"
        return msg
    return None

def detect_vehicle_destruction(line):
    if "<Vehicle Destruction>" not in line: return None
    pattern = r"<(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})\.\d{3}Z> \[Notice\] <Vehicle Destruction> CVehicle::OnAdvanceDestroyLevel: Vehicle '([\w-]+)_\d+' \[\d+\] in zone '([\w-]+)' \[.+\] driven by '([\w-]+)' \[\d*\] advanced from destroy level \d to \d caused by '([\w-]+)' \[\d+\] with '([\w-]+)' \[[\w-]+\]\[[\w-]+\].*"
    match = re.search(pattern, line)
    if match:
        d = match.group
        destroyed_by_print = highlight_external_nick(d(6))
        msg = f"{d(1)[8:10]}/{d(1)[5:7]}/{d(1)[2:4]} · {d(2)} - {destroyed_by_print} ha destruït una {d(3)}"
        if d(5) != "unknown":
            msg += f" a ( {d(5)} )"
        return msg
    return None

def detect_player_spawned(line):
    if "<[ActorState] Corpse>" not in line: return None
    pattern = r"<(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})\.\d{3}Z> \[Notice\] <\[ActorState\] Corpse> \[ACTOR STATE\]\[SSCActorStateCVars::LogCorpse\] Player '([\w-]+)' <(remote|local) client>: Running corpsify for corpse\. .*"
    match = re.search(pattern, line)
    if match:
        d = match.group
        player_print = highlight_external_nick(d(3))
        return f"{d(1)[8:10]}/{d(1)[5:7]}/{d(1)[2:4]} · {d(2)} - Ha aparegut a ({d(4)}) en {player_print}"
    return None

def strip_datetime(line):
    return line.split(' - ', 1)[-1] if ' - ' in line else line

def process_line(line):
    msg, func, args = None, None, None
    msg = detect_missile_target(line)
    if msg:
        return msg, highlight_user, None
    msg2, victim, killer = detect_actor_death(line)
    if msg2:
        return msg2, highlight_murder if victim == CURRENT_USER else highlight_user, (victim, killer)
    for detector in [detect_vehicle_destruction, detect_player_spawned]:
        msg3 = detector(line)
        if msg3:
            return msg3, highlight_user, None
    return None, None, None

def get_output_filename():
    import datetime
    return f"partida {datetime.datetime.now().strftime('%Y-%m-%d')}.txt"

# -------------------- MAIN LOOP --------------------

def main():
    output_filename = get_output_filename()
    messages_shown = set()
    last_msg, last_msg_core, last_highlight_func, last_args, repeat_count = None, None, None, None, 0

    with open(LOG_FILENAME, 'r', encoding="latin1") as log_file:

        def flush_last():
            nonlocal last_msg, last_msg_core, repeat_count, last_highlight_func, last_args
            if last_msg is not None and last_msg_core not in messages_shown:
                if repeat_count > 0:
                    if last_highlight_func:
                        print(last_highlight_func(last_msg, *(last_args if last_args else ())) + " ...")
                    else:
                        print(highlight_all(last_msg) + " ...")
                else:
                    if last_highlight_func:
                        print(last_highlight_func(last_msg, *(last_args if last_args else ())))
                    else:
                        print(highlight_all(last_msg))
                messages_shown.add(last_msg_core)
            last_msg, last_msg_core, repeat_count, last_highlight_func, last_args = None, None, 0, None, None

        for line in log_file:
            msg_out, highlight_func, args = process_line(line)
            msg_out_core = strip_datetime(msg_out) if msg_out else None

            if msg_out is not None:
                if last_msg_core is not None and msg_out_core == last_msg_core:
                    repeat_count += 1
                else:
                    flush_last()
                    last_msg, last_msg_core = msg_out, msg_out_core
                    repeat_count = 0
                    last_highlight_func = highlight_func
                    last_args = args
            else:
                flush_last()

        flush_last()

        try:
            while True:
                where = log_file.tell()
                line = log_file.readline()
                if not line:
                    time.sleep(1)
                    log_file.seek(where)
                else:
                    msg_out, highlight_func, args = process_line(line)
                    msg_out_core = strip_datetime(msg_out) if msg_out else None

                    if msg_out is not None and msg_out_core not in messages_shown:
                        if repeat_count > 0:
                            if highlight_func:
                                print(highlight_func(msg_out, *(args if args else ())) + " ...")
                            else:
                                print(highlight_all(msg_out) + " ...")
                        else:
                            if highlight_func:
                                print(highlight_func(msg_out, *(args if args else ())))
                            else:
                                print(highlight_all(msg_out))
                        messages_shown.add(msg_out_core)
                        last_msg_core = msg_out_core
                        repeat_count = 0
                        last_highlight_func = highlight_func
                        last_args = args
                    else:
                        flush_last()
        except KeyboardInterrupt:
            flush_last()
            print("Aturat per l'usuari.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print()
        print("ERROR: " + str(e))
        print()
        input("Prem qualsevol tecla per sortir...")
