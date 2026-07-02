import os, json, logging, subprocess, shutil, random, string, uuid, re
from pathlib import Path
from telegram import Update, Document
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN = os.getenv('BOT_TOKEN')
ALLOWED_USERS = json.loads(os.getenv('ALLOWED_USERS', '[]'))
WORK_DIR = os.getenv('WORK_DIR', '/tmp/work')
TEMP_DIR = os.getenv('TEMP_DIR', '/tmp/temp')

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not set")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

def ensure_dirs():
    Path(WORK_DIR).mkdir(parents=True, exist_ok=True)
    Path(TEMP_DIR).mkdir(parents=True, exist_ok=True)

def is_allowed(uid):
    return not ALLOWED_USERS or uid in ALLOWED_USERS

def run_cmd(cmd, timeout=120):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            logger.error(f"Cmd failed: {' '.join(cmd)}\n{r.stderr}")
            return False, r.stderr
        return True, r.stdout
    except subprocess.TimeoutExpired:
        logger.error("Command timed out")
        return False, "timeout"

def random_string(length=8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def fast_obfuscate(input_apk: str, output_apk: str) -> bool:
    ensure_dirs()
    dec_dir = os.path.join(TEMP_DIR, 'dec_' + uuid.uuid4().hex[:6])
    
    # Decode
    logger.info("Decoding...")
    ok, _ = run_cmd(['apktool', 'd', '-f', '-o', dec_dir, input_apk], timeout=180)
    if not ok:
        return False

    # 1. Change package name in AndroidManifest.xml using simple regex (fast)
    manifest_path = os.path.join(dec_dir, 'AndroidManifest.xml')
    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = f.read()
        old_pkg = re.search(r'package="([^"]+)"', manifest).group(1)
        new_pkg = 'com.' + random_string(6) + '.' + random_string(6)
        manifest = manifest.replace(old_pkg, new_pkg)
        with open(manifest_path, 'w', encoding='utf-8') as f:
            f.write(manifest)
    except Exception as e:
        logger.exception("Manifest edit failed")
        shutil.rmtree(dec_dir, ignore_errors=True)
        return False

    # 2. Rename smali folder structure (old_pkg -> new_pkg) – simple path replace
    smali_dirs = [d for d in os.listdir(dec_dir) if d.startswith('smali')]
    for smali in smali_dirs:
        base = os.path.join(dec_dir, smali)
        old_path = old_pkg.replace('.', '/')
        new_path = new_pkg.replace('.', '/')
        # Move files if old_path exists
        for root, dirs, files in os.walk(base):
            if old_path in root:
                new_root = root.replace(old_path, new_path)
                os.makedirs(new_root, exist_ok=True)
                for file in files:
                    src = os.path.join(root, file)
                    dst = os.path.join(new_root, file)
                    shutil.move(src, dst)
        # Remove empty old directories
        for root, dirs, files in os.walk(base, topdown=False):
            if root != base and not os.listdir(root):
                os.rmdir(root)

    # Rebuild
    logger.info("Rebuilding...")
    rebuilt = os.path.join(TEMP_DIR, 'rebuilt.apk')
    ok, _ = run_cmd(['apktool', 'b', '-o', rebuilt, dec_dir], timeout=180)
    if not ok:
        return False

    # Zipalign
    aligned = os.path.join(TEMP_DIR, 'aligned.apk')
    ok, _ = run_cmd(['zipalign', '-v', '-p', '4', rebuilt, aligned], timeout=60)
    if not ok:
        return False

    # Sign with random keystore
    ks_path = os.path.join(TEMP_DIR, 'rand.keystore')
    ks_pass = random_string(12)
    alias = random_string(6)
    dname = f"CN={random_string(5)}, OU={random_string(4)}, O={random_string(5)}, L={random_string(6)}, ST={random_string(4)}, C={random.choice(['US','GB','IN'])}"
    ok, _ = run_cmd([
        'keytool', '-genkey', '-v',
        '-keystore', ks_path, '-alias', alias,
        '-keyalg', 'RSA', '-keysize', '2048', '-validity', '365',
        '-storepass', ks_pass, '-keypass', ks_pass,
        '-dname', dname
    ], timeout=30)
    if not ok:
        return False

    ok, _ = run_cmd([
        'apksigner', 'sign',
        '--ks', ks_path,
        '--ks-pass', f'pass:{ks_pass}',
        '--ks-key-alias', alias,
        '--out', output_apk, aligned
    ], timeout=30)
    if not ok:
        return False

    # Cleanup
    for f in [rebuilt, aligned, ks_path]: os.remove(f)
    shutil.rmtree(dec_dir, ignore_errors=True)
    return True

# Telegram handlers same as before
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Access denied.")
        return
    await update.message.reply_text("FUD Bot ready. Send APK.")

async def handle_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        await update.message.reply_text("Access denied.")
        return
    doc: Document = update.message.document
    if not doc.file_name or not doc.file_name.lower().endswith(".apk"):
        await update.message.reply_text("Only APK accepted.")
        return
    await update.message.reply_text("Processing... (fast obfuscation)")
    fin = os.path.join(WORK_DIR, f"{uid}_{doc.file_name}")
    await (await doc.get_file()).download_to_drive(fin)
    base, ext = os.path.splitext(doc.file_name)
    fout = os.path.join(WORK_DIR, f"{base}_obs{ext}")
    success, err = False, ""
    try:
        success = fast_obfuscate(fin, fout)
    except Exception as e:
        logger.exception("Error")
        err = str(e)
    try: os.remove(fin)
    except: pass
    if success:
        with open(fout, "rb") as f:
            await update.message.reply_document(document=f, filename=os.path.basename(fout), caption="APK obfuscated.")
        try: os.remove(fout)
        except: pass
    else:
        await update.message.reply_text(f"Failed: {err or 'Unknown error'}")
        if os.path.exists(fout): os.remove(fout)

async def err_handler(update, context):
    logger.error(context.error)

def main():
    ensure_dirs()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_doc))
    app.add_error_handler(err_handler)
    logger.info("Bot starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
