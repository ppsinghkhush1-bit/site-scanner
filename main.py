import subprocess, sys, os, asyncio, aiohttp, re, random, time, sqlite3, io, json
from datetime import datetime

# --- 1. SYSTEM INITIALIZATION ---
def setup():
    required = {
        'python-telegram-bot': 'python-telegram-bot[job-queue]', 
        'aiohttp': 'aiohttp', 
        'requests': 'requests', 
        'bs4': 'beautifulsoup4'
    }
    for mod, pkg in required.items():
        try:
            if mod == 'bs4': import bs4
            elif mod == 'python-telegram-bot': import telegram
            else: __import__(mod)
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

setup()

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# --- 2. CONFIGURATION & STATE ---
TOKEN = "8568654046:AAGA-4X-CsNl7JPFMxMm8D1APFpuwhE9dVM"
ADMIN_ID = 5295792382  
DB_NAME = "janus_vault.db"
USER_PROXIES = []
EXCHANGE_RATES = {'GBP': 1.27, 'EUR': 1.09, 'CAD': 0.74, 'AUD': 0.66}

# --- 3. PROXY ENGINE (Background Loop) ---
async def proxy_scraper_loop():
    global USER_PROXIES
    sources = [
        "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000",
        "https://www.proxy-list.download/api/v1/get?type=http",
        "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt"
    ]
    while True:
        new_proxies = []
        async with aiohttp.ClientSession() as session:
            for url in sources:
                try:
                    async with session.get(url, timeout=15) as resp:
                        text = await resp.text()
                        found = [f"http://{p.strip()}" for p in text.split('\n') if ":" in p]
                        new_proxies.extend(found)
                except: continue
        if new_proxies:
            USER_PROXIES = list(set(new_proxies))
        await asyncio.sleep(1800)

# --- 4. CORE UTILITIES ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    conn.execute('CREATE TABLE IF NOT EXISTS hits (url TEXT PRIMARY KEY, timestamp DATETIME)')
    conn.close()

def is_duplicate(url):
    conn = sqlite3.connect(DB_NAME)
    res = conn.execute('SELECT 1 FROM hits WHERE url = ?', (url,)).fetchone()
    conn.close()
    return res is not None

def save_hit(url):
    conn = sqlite3.connect(DB_NAME)
    conn.execute('INSERT INTO hits VALUES (?, ?)', (url, datetime.now()))
    conn.commit()
    conn.close()

def clean_url_extractor(text):
    pattern = r'(https?://[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
    raw_found = re.findall(pattern, text)
    clean = []
    for url in raw_found:
        try:
            normalized = url.lower().split('//')[0] + "//" + url.lower().split('//')[1].split('/')[0]
            normalized = normalized.replace("http://", "https://")
            if normalized not in clean: clean.append(normalized)
        except: continue
    return sorted(clean)

def authorized_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ADMIN_ID:
            return await update.message.reply_text("🚫 Unauthorized.")
        return await func(update, context)
    return wrapper

# --- 5. AUDIT ENGINE (With Dual-Retry) ---
async def audit_engine(session, url, retries=2):
    headers = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X)'}
    for attempt in range(retries + 1):
        proxy = random.choice(USER_PROXIES) if USER_PROXIES else None
        try:
            if is_duplicate(url): return "dup"
            async with session.get(url, headers=headers, proxy=proxy, timeout=10) as resp:
                html = (await resp.text()).lower()
                if 'stripe.com' in html or ('paypal' not in html and 'shop-pay' not in html): return "fail"
                async with session.get(f"{url}/products.json?limit=1", headers=headers, proxy=proxy, timeout=8) as p_resp:
                    data = await p_resp.json()
                    price = float(data['products'][0]['variants'][0]['price'])
                    cur_match = re.search(r'"currency":"([A-Z]{3})"', html)
                    currency = cur_match.group(1).upper() if cur_match else "USD"
                    usd_val = price * EXCHANGE_RATES.get(currency, 1.0)
                    if usd_val > 20.0: return "fail"
                    save_hit(url)
                    return f"🎯 **HIT**: {url} (${usd_val:.2f} USD)"
        except:
            if attempt < retries: continue
            return "dead"
    return "dead"

# --- 6. COMMANDS ---
@authorized_only
async def hunt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2: return await update.message.reply_text("❌ `/hunt [count] [keyword]`")
    count, keyword = int(context.args[0]), context.args[1]
    targets = [f"https://{keyword}{i}.myshopify.com" for i in range(1, count + 1)]
    await run_scanner(update, targets, f"Hunt_{keyword}")

@authorized_only
async def site(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args) if context.args else ""
    if update.message.reply_to_message and update.message.reply_to_message.document:
        doc = await update.message.reply_to_message.document.get_file()
        text = (await doc.download_as_bytearray()).decode('utf-8', errors='ignore')
    targets = clean_url_extractor(text)
    if not targets: return await update.message.reply_text("❌ No URLs found.")
    await run_scanner(update, targets, "Site_Audit")

async def run_scanner(update, targets, mode):
    session_hits = []
    stats = {"hits": 0, "dead": 0, "dup": 0, "fail": 0}
    status_msg = await update.message.reply_text(f"🚀 **Batch: {mode}**")
