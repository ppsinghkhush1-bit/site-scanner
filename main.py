import os
import sys
import subprocess
import time
import random
import threading

# ==========================================
# 0. SELF-INSTALLATION SYSTEM
# ==========================================
def install_dependencies():
    """Checks and installs missing libraries automatically."""
    required = {
        "pyTelegramBotAPI": "telebot",
        "requests": "requests"
    }
    
    restart_needed = False
    
    for package, import_name in required.items():
        try:
            __import__(import_name)
        except ImportError:
            print(f"⚙️ Installing {package}...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", package])
                restart_needed = True
            except Exception as e:
                print(f"❌ Failed to install {package}: {e}")
                sys.exit(1)
                
    if restart_needed:
        print("✅ Dependencies installed. Restarting...")
        os.execv(sys.executable, ['python'] + sys.argv)

# Run installation check immediately
install_dependencies()

# ==========================================
# 1. IMPORTS & CONFIGURATION
# ==========================================
import telebot
import requests

# --- [ CONFIGURATION AREA ] ---
BOT_TOKEN = "8568654046:AAGI6rVGsO_0h8qHxGP6BXQDdQMEuMkACgk"
ADMIN_ID = 5295792382
AUTHORIZED_USERS = {ADMIN_ID}

OUTPUT_FILE = "IndoGlobal_Stores.txt"   # Stores found in this session
HISTORY_FILE = "History.txt"            # Permanent database

PROXY_LIST = []
STOP_FLAG = False

# ==========================================
# 2. WORDLISTS (Generator Engine)
# ==========================================
NOUNS = [
    "shop", "store", "boutique", "market", "outlet", "supply", "fashion", 
    "tech", "gear", "wear", "fit", "gym", "apparel", "club", "hub", 
    "zone", "world", "box", "crate", "spot", "place", "mart", "center",
    "gifts", "goods", "deals", "finds", "picks", "trends", "styles"
]

ADJECTIVES = [
    "the", "my", "your", "our", "pro", "top", "best", "super", "ultra", 
    "mega", "hyper", "daily", "urban", "modern", "retro", "vintage", 
    "pure", "eco", "bio", "fresh", "prime", "elite", "royal", "luxe",
    "golden", "silver", "blue", "red", "black", "white", "green", "desi",
    "global", "rapid", "fast", "smart", "cool", "hot"
]

ITEMS = [
    "clothing", "jewelry", "shoes", "sneakers", "boots", "socks", 
    "watches", "glasses", "shades", "hats", "caps", "bags", "packs",
    "phone", "case", "skin", "led", "lamp", "decor", "art", "print",
    "poster", "sticker", "toy", "game", "hobby", "craft", "tool",
    "pet", "dog", "cat", "fish", "bird", "baby", "kid", "mom", "dad",
    "saree", "kurta", "ethnic", "silk", "cotton", "spice", "tea", "tech"
]

# --- FILTER 1: LOGISTICS (India or Worldwide) ---
SHIPPING_MARKERS = [
    "india", "shipping to india", "ships to india", "delivery to india",
    "delivers to india", "worldwide shipping", "international shipping", 
    "ships worldwide", "global delivery", "free shipping worldwide"
]

# --- FILTER 2: ECONOMY (USD or INR) ---
CURRENCY_MARKERS = [
    "usd", "$", "us dollar", "united states", # USD Group
    "inr", "₹", "rupee", "rs."                # INR Group
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15"
]

# Initialize Bot
try:
    bot = telebot.TeleBot(BOT_TOKEN)
except Exception as e:
    print(f"❌ Bot Token Error: {e}")
    sys.exit()

# ==========================================
# 3. CORE FUNCTIONS
# ==========================================
def is_auth(uid):
    return int(uid) in AUTHORIZED_USERS

def get_random_ua():
    return random.choice(USER_AGENTS)

def load_history():
    if not os.path.exists(HISTORY_FILE): return set()
    with open(HISTORY_FILE, "r") as f:
        return set(line.strip() for line in f)

def save_history(url):
    with open(HISTORY_FILE, "a") as f:
        f.write(url + "\n")

def generate_domain():
    """Generates a random Shopify domain."""
    adj = random.choice(ADJECTIVES)
    item = random.choice(ITEMS)
    noun = random.choice(NOUNS)
    
    p = random.randint(1, 5)
    if p == 1: name = f"{adj}{item}"
    elif p == 2: name = f"{item}{noun}"
    elif p == 3: name = f"{adj}-{item}"
    elif p == 4: name = f"{item}-{noun}"
    elif p == 5: name = f"{adj}{item}{noun}"
    
    return f"https://{name}.myshopify.com"

def check_target_criteria(url):
    """
    DOUBLE LOCK FILTER:
    1. Must be LIVE (200 OK)
    2. Must ship to INDIA (or Worldwide)
    3. Must use USD ($) or INR (₹)
    """
    current_proxy = None
    proxies = None
    
    if PROXY_LIST:
        current_proxy = random.choice(PROXY_LIST)
        proxies = {"http": current_proxy, "https": current_proxy}

    try:
        r = requests.get(url, 
                         headers={'User-Agent': get_random_ua()}, 
                         proxies=proxies, 
                         timeout=5)
        
        # --- A. LIVENESS CHECK ---
        if r.status_code != 200: return False
        if "/password" in r.url: return False
        text_lower = r.text.lower()
        if "opening soon" in text_lower or "be right back" in text_lower: return False
        
        # --- B. LOGISTICS CHECK (India/Global) ---
        has_shipping = False
        for s_marker in SHIPPING_MARKERS:
            if s_marker in text_lower:
                has_shipping = True
                break
        if not has_shipping: return False # Fail if no shipping match
        
        # --- C. CURRENCY CHECK (USD/INR) ---
        has_currency = False
        for c_marker in CURRENCY_MARKERS:
            if c_marker in text_lower:
                has_currency = True
                break
        if not has_currency: return False # Fail if no currency match
        
        # Passed all 3 gates
        return True

    except Exception:
        # Auto-remove dead proxy
        if current_proxy and current_proxy in PROXY_LIST:
            try: PROXY_LIST.remove(current_proxy)
            except: pass
        return False

# ==========================================
# 4. SCANNER LOOP
# ==========================================
def scanner(cid, limit):
    global STOP_FLAG
    STOP_FLAG = False
    
    bot.send_message(cid, f"[*] **MULTI-VECTOR SCAN STARTED**\nTarget: {limit} Stores\nReq: Live + India Shipping + USD/INR")
    
    history = load_history()
    
    # Clear session file
    with open(OUTPUT_FILE, "w") as f: f.write("")
    
    new_found = 0
    checked = 0
    
    while new_found < limit:
        if STOP_FLAG: break
        
        # Generate batch
        batch = [generate_domain() for _ in range(10)]
        
        for url in batch:
            if new_found >= limit: break
            if STOP_FLAG: break
            
            checked += 1
            
            if url in history: continue
            
            # RUN THE DOUBLE LOCK FILTER
            if check_target_criteria(url):
                new_found += 1
                
                # Save
                history.add(url)
                save_history(url)
                
                # Write
                with open(OUTPUT_FILE, "a") as f: f.write(url + "\n")
                
                # Notify
                try: bot.send_message(cid, f"🟢 {url} (Valid)")
                except: time.sleep(1)
            
            time.sleep(0.05)
            
    msg = "🛑 STOPPED" if STOP_FLAG else "✅ COMPLETED"
    bot.send_message(cid, f"{msg}\nChecked: {checked}\nFound: {new_found} (India + USD/INR)")
    
    # Auto-Send File
    if os.path.exists(OUTPUT_FILE) and os.path.getsize(OUTPUT_FILE) > 0:
        with open(OUTPUT_FILE, "rb") as f:
            bot.send_document(cid, f, caption="Targeted Live Stores")

# ==========================================
# 5. COMMANDS
# ==========================================
@bot.message_handler(commands=['start'])
def start(m):
    if is_auth(m.from_user.id):
        text = (
            "🌍 **INDO-GLOBAL HUNTER**\n\n"
            "1. `/scan 100` - Find stores shipping to India with USD/INR\n"
            "2. `/stop` - Stop scanning\n"
            "3. `/setpx IP:PORT` - Add Proxy (Optional)"
        )
        bot.reply_to(m, text, parse_mode="Markdown")

@bot.message_handler(commands=['setpx'])
def setpx(m):
    if is_auth(m.from_user.id):
        try:
            raw = m.text.split()[1]
            if '@' not in raw and len(raw.split(':')) == 4:
                p = raw.split(':')
                fmt = f"http://{p[2]}:{p[3]}@{p[0]}:{p[1]}"
            elif '@' in raw or 'http' in raw:
                fmt = raw if 'http' in raw else f"http://{raw}"
            else:
                fmt = f"http://{raw}"
            
            PROXY_LIST.append(fmt)
            bot.reply_to(m, f"✅ Proxy Added. Total: {len(PROXY_LIST)}")
        except:
            bot.reply_to(m, "Format: /setpx IP:PORT")

@bot.message_handler(commands=['scan'])
def scan(m):
    if is_auth(m.from_user.id):
        try: limit = int(m.text.split()[1])
        except: limit = 100
        threading.Thread(target=scanner, args=(m.chat.id, limit)).start()
        bot.reply_to(m, f"🚀 Hunting {limit} targets...")

@bot.message_handler(commands=['stop'])
def stop(m):
    global STOP_FLAG
    STOP_FLAG = True
    bot.reply_to(m, "Stopping...")

# ==========================================
# 6. RUN LOOP
# ==========================================
if __name__ == "__main__":
    print("--- INDO-GLOBAL HUNTER RUNNING ---")
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)
