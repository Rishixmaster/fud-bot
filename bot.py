import os, json, logging, subprocess, shutil, random, string, uuid
from pathlib import Path
from telegram import Update, Document
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Env vars
BOT_TOKEN = os.getenv('BOT_TOKEN')
KEYSTORE_PASSWORD = os.getenv('KEYSTORE_PASSWORD', 'FudPass123')
KEY_ALIAS = os.getenv('KEY_ALIAS', 'fudkey')
ALLOWED_USERS = json.loads(os.getenv('ALLOWED_USERS', '[]'))
WORK_DIR = os.getenv('WORK_DIR', '/tmp/work')
TEMP_DIR = os.getenv('TEMP_DIR', '/tmp/temp')
CRYPTER_CMD = os.getenv('CRYPTER_CMD') or None  # ab use nahi hoga

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not set")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

def ensure_dirs():
    Path(WORK_DIR).mkdir(parents=True, exist_ok=True)
    Path(TEMP_DIR).mkdir(parents=True, exist_ok=True)

def is_allowed(uid):
    return not ALLOWED_USERS or uid in ALLOWED_USERS

def run_cmd(cmd, shell=False):
    r = subprocess.run(cmd, capture_output=True, text=True, shell=shell)
    if r.returncode != 0:
        logger.error(f"Cmd failed: {' '.join(cmd) if isinstance(cmd, list) else cmd}\n{r.stderr}")
        return False, r.stderr
    return True, r.stdout

# ----------- Obfuscation functions -----------

def random_string(length=8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def obfuscate_apk(input_apk: str, output_apk: str) -> bool:
    """
    1. Apktool decode
    2. Rename package names, manifest entries, resource files
    3. Apktool build
    4. Zipalign
    5. Sign with random keystore
    """
    ensure_dirs()
    # unique folder name
    decode_dir = os.path.join(TEMP_DIR, 'decode_' + uuid.uuid4().hex[:8])
    
    # Step 1: Decode
    logger.info("Decoding APK...")
    ok, out = run_cmd(['apktool', 'd', '-f', '-o', decode_dir, input_apk])
    if not ok:
        return False

    # Step 2: Obfuscate — rename packages in manifest and smali files
    try:
        manifest_path = os.path.join(decode_dir, 'AndroidManifest.xml')
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = f.read()
        # original package name
        import re
        match = re.search(r'package="([^"]+)"', manifest)
        if match:
            old_pkg = match.group(1)
            new_pkg = 'com.' + random_string(6) + '.' + random_string(6)
            manifest = manifest.replace(old_pkg, new_pkg)
            with open(manifest_path, 'w', encoding='utf-8') as f:
                f.write(manifest)
            # rename smali folder structure
            smali_dirs = [d for d in os.listdir(decode_dir) if d.startswith('smali')]
            for d in smali_dirs:
                base = os.path.join(decode_dir, d)
                old_path = old_pkg.replace('.', '/')
                new_path = new_pkg.replace('.', '/')
                for root, dirs, files in os.walk(base):
                    if old_path in root:
                        new_root = root.replace(old_path, new_path)
                        os.makedirs(new_root, exist_ok=True)
                        for f in files:
                            src = os.path.join(root, f)
                            dst = os.path.join(new_root, f)
                            shutil.move(src, dst)
                        # remove old dirs if empty
            # replace all occurrences in smali files
            for root, dirs, files in os.walk(decode_dir):
                for file in files:
                    if file.endswith('.smali'):
                        path = os.path.join(root, file)
                        with open(path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        content = content.replace(old_pkg, new_pkg)
                        with open(path, 'w', encoding='utf-8') as f:
                            f.write(content)
        # randomize some resource file names (e.g., drawables)
        res_dir = os.path.join(decode_dir, 'res')
        if os.path.exists(res_dir):
            for root, dirs, files in os.walk(res_dir):
                for f in files:
                    ext = os.path.splitext(f)[1]
                    if ext in ('.png', '.jpg', '.xml'):
                        new_name = random_string(12) + ext
                        src = os.path.join(root, f)
                        dst = os.path.join(root, new_name)
                        shutil.move(src, dst)
    except Exception as e:
        logger.exception("Obfuscation error")
        return False

    # Step 3: Rebuild
    logger.info("Building APK...")
    rebuilt_apk = os.path.join(TEMP_DIR, 'rebuilt.apk')
    ok, out = run_cmd(['apktool', 'b', '-o', rebuilt_apk, decode_dir])
    if not ok:
        return False

    # Step 4: Zipalign
    logger.info("Aligning...")
    aligned_apk = os.path.join(TEMP_DIR, 'aligned.apk')
    ok, out = run_cmd(['zipalign', '-v', '-p', '4', rebuilt_apk, aligned_apk])
    if not ok:
        return False

    # Step 5: Generate random keystore and sign
    logger.info("Signing with random keystore...")
    ks_path = os.path.join(TEMP_DIR, 'random.keystore')
    ks_pass = random_string(16)
    alias = random_string(6)
    dname = f"CN={random_string(5)}, OU={random_string(4)}, O={random_string(5)}, L={random_string(6)}, ST={random_string(4)}, C={random.choice(['US','GB','IN'])}"
    keytool_cmd = [
        'keytool', '-genkey', '-v',
        '-keystore', ks_path,
        '-alias', alias,
        '-keyalg', 'RSA', '-keysize', '2048', '-validity', '365',
        '-storepass', ks_pass,
        '-keypass', ks_pass,
        '-dname', dname
    ]
    ok, out = run_cmd(keytool_cmd)
    if not ok:
        return False

    # sign with apksigner
    ok, out = run_cmd([
        'apksigner', 'sign',
        '--ks', ks_path,
        '--ks-pass', f'pass:{ks_pass}',
        '--ks-key-alias', alias,
        '--out', output_apk,
        aligned_apk
    ])
    if not ok:
        return False

    # cleanup temporary
    for f in [rebuilt_apk, aligned_apk, ks_path]:
        try: os.remove(f)
        except: pass
    try: shutil.rmtree(decode_dir)
    except: pass

    return True

# ----------- Telegram handlers -----------

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
    await update.message.reply_text("Processing... (obfuscation + random sign)")
    fin = os.path.join(WORK_DIR, f"{uid}_{doc.file_name}")
    await (await doc.get_file()).download_to_drive(fin)
    base, ext = os.path.splitext(doc.file_name)
    fout = os.path.join(WORK_DIR, f"{base}_obf{ext}")
    success, err = False, ""
    try:
        success = obfuscate_apk(fin, fout)
    except Exception as e:
        logger.exception("Error")
        err = str(e)
    try: os.remove(fin)
    except: pass
    if success:
        with open(fout, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=os.path.basename(fout),
                caption="Obfuscated + Random Signed APK ready."
            )
        try: os.remove(fout)
        except: pass
    else:
        await update.message.reply_text(f"Failed: {err or 'Unknown'}")
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
