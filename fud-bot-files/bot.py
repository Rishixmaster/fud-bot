import os, json, logging, subprocess, shutil
from pathlib import Path
from telegram import Update, Document
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN = os.getenv('BOT_TOKEN')
KEYSTORE_PATH = os.getenv('KEYSTORE_PATH', '/app/signer.keystore')
KEYSTORE_PASSWORD = os.getenv('KEYSTORE_PASSWORD')
KEY_ALIAS = os.getenv('KEY_ALIAS', 'fudkey')
CRYPTER_CMD = os.getenv('CRYPTER_CMD') or None
ALLOWED_USERS = json.loads(os.getenv('ALLOWED_USERS', '[]'))
WORK_DIR = os.getenv('WORK_DIR', '/tmp/work')
TEMP_DIR = os.getenv('TEMP_DIR', '/tmp/temp')

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable not set")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def ensure_dirs():
    Path(WORK_DIR).mkdir(parents=True, exist_ok=True)
    Path(TEMP_DIR).mkdir(parents=True, exist_ok=True)

def is_allowed(uid):
    return not ALLOWED_USERS or uid in ALLOWED_USERS

def sign_apk(inp, out):
    # apksigner will be at /usr/local/bin/apksigner (Dockerfile puts it there)
    cmd = [
        "apksigner", "sign",
        "--ks", KEYSTORE_PATH,
        "--ks-pass", f"pass:{KEYSTORE_PASSWORD}",
        "--ks-key-alias", KEY_ALIAS,
        "--out", out, inp
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        logger.error(f"Sign failed: {r.stderr}")
        return False
    v = subprocess.run(["apksigner", "verify", "--verbose", out], capture_output=True, text=True)
    if v.returncode != 0:
        logger.error(f"Verify failed: {v.stderr}")
        return False
    return True

def run_crypter(inp, out):
    if not CRYPTER_CMD:
        shutil.copy2(inp, out)
        return True
    cmd = CRYPTER_CMD.format(input=inp, output=out)
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        logger.error(f"Crypter failed: {r.stderr}")
        return False
    return os.path.exists(out)

def process_apk(inp, out):
    ensure_dirs()
    s = os.path.join(TEMP_DIR, "signed.apk")
    c = os.path.join(TEMP_DIR, "crypted.apk")
    if not sign_apk(inp, s):
        return False
    if not run_crypter(s, c):
        return False
    shutil.move(c, out)
    try: os.remove(s)
    except: pass
    return True

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
    await update.message.reply_text("Processing...")
    fin = os.path.join(WORK_DIR, f"{uid}_{doc.file_name}")
    await (await doc.get_file()).download_to_drive(fin)
    base, ext = os.path.splitext(doc.file_name)
    fout = os.path.join(WORK_DIR, f"{base}_fud{ext}")
    ok, err = False, ""
    try:
        ok = process_apk(fin, fout)
    except Exception as e:
        logger.exception("Error")
        err = str(e)
    try: os.remove(fin)
    except: pass
    if ok:
        with open(fout, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=os.path.basename(fout),
                caption="FUD APK ready."
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
