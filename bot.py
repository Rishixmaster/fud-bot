import os, json, logging, subprocess, shutil, random, string, uuid, re
from pathlib import Path
from lxml import etree
from telegram import Update, Document
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ----------------------------------------------------------------------
# Config from environment
# ----------------------------------------------------------------------
BOT_TOKEN = os.getenv('BOT_TOKEN')
ALLOWED_USERS = json.loads(os.getenv('ALLOWED_USERS', '[]'))
WORK_DIR = os.getenv('WORK_DIR', '/tmp/work')
TEMP_DIR = os.getenv('TEMP_DIR', '/tmp/temp')

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not set")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Utility
# ----------------------------------------------------------------------
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

def random_string(length=8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def random_hex(length=4):
    return ''.join(random.choices('0123456789abcdef', k=length))

# ----------------------------------------------------------------------
# Obfuscation Engine
# ----------------------------------------------------------------------
class AdvancedObfuscator:
    def __init__(self, decode_dir):
        self.decode_dir = decode_dir
        self.orig_pkg = None
        self.new_pkg = None
        self.class_map = {}   # old_full_class -> new_full_class
        self.method_map = {}
        self.field_map = {}

    def obfuscate_manifest(self):
        manifest_path = os.path.join(self.decode_dir, 'AndroidManifest.xml')
        if not os.path.exists(manifest_path):
            return False
        with open(manifest_path, 'rb') as f:
            tree = etree.parse(f)
        root = tree.getroot()
        self.orig_pkg = root.attrib['package']
        self.new_pkg = 'com.' + random_string(6) + '.' + random_string(6)
        # Rename package
        root.attrib['package'] = self.new_pkg
        # Rename all references in manifest (e.g., application class names)
        nsmap = {'android': 'http://schemas.android.com/apk/res/android'}
        for elem in root.iter():
            for attr in ['{http://schemas.android.com/apk/res/android}name']:
                if attr in elem.attrib:
                    old_name = elem.attrib[attr]
                    if old_name.startswith('.'):
                        old_name = self.orig_pkg + old_name
                    # map to new name
                    new_name = self._get_new_class_name(old_name)
                    if new_name:
                        if old_name.startswith(self.orig_pkg):
                            rel = new_name[len(self.new_pkg)+1:]  # relative
                            elem.attrib[attr] = '.' + rel if '.' in rel else rel
                        else:
                            elem.attrib[attr] = new_name
        with open(manifest_path, 'wb') as f:
            tree.write(f, encoding='utf-8', xml_declaration=False)
        return True

    def _get_new_class_name(self, old_full_class):
        if old_full_class in self.class_map:
            return self.class_map[old_full_class]
        # generate new random class name within new package
        new_class_name = self._random_class_name()
        new_full = self.new_pkg + '.' + new_class_name
        self.class_map[old_full_class] = new_full
        return new_full

    def _random_class_name(self):
        # Random short name, e.g., a, b, aa, ab, ...
        length = random.randint(1, 3)
        return ''.join(random.choices(string.ascii_lowercase, k=length))

    def _random_method_name(self):
        length = random.randint(1, 4)
        return ''.join(random.choices(string.ascii_lowercase, k=length))

    def _random_field_name(self):
        length = random.randint(2, 5)
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

    def rename_smali_files(self):
        # Rename smali directories/files to match class_map
        smali_dirs = [d for d in os.listdir(self.decode_dir) if d.startswith('smali')]
        for smali_root_name in smali_dirs:
            base = os.path.join(self.decode_dir, smali_root_name)
            # Collect all smali files
            smali_files = []
            for root, dirs, files in os.walk(base):
                for f in files:
                    if f.endswith('.smali'):
                        smali_files.append(os.path.join(root, f))
            # Rename each file according to class_map
            for filepath in smali_files:
                rel = os.path.relpath(filepath, base)
                # Convert path to class name
                class_name = rel.replace('/', '.').replace('.smali', '')
                full_class = class_name  # usually includes original package
                if full_class in self.class_map:
                    new_full = self.class_map[full_class]
                    new_rel = new_full.replace('.', '/') + '.smali'
                    new_abs = os.path.join(base, new_rel)
                    os.makedirs(os.path.dirname(new_abs), exist_ok=True)
                    shutil.move(filepath, new_abs)
            # Remove empty old directories
            for root, dirs, files in os.walk(base, topdown=False):
                if root != base and not os.listdir(root):
                    os.rmdir(root)

    def obfuscate_smali_code(self):
        # In each smali file, replace class, method, field names
        # First, build method/field maps from definitions
        smali_dirs = [d for d in os.listdir(self.decode_dir) if d.startswith('smali')]
        for smali_dir in smali_dirs:
            base = os.path.join(self.decode_dir, smali_dir)
            for root, dirs, files in os.walk(base):
                for file in files:
                    if file.endswith('.smali'):
                        filepath = os.path.join(root, file)
                        with open(filepath, 'r', encoding='utf-8') as f:
                            content = f.read()
                        # Find class definition -> set current class
                        class_match = re.search(r'\.class\s+.+?\s+(.+)', content)
                        current_class = None
                        if class_match:
                            current_class = class_match.group(1).strip()
                        # Find method definitions -> assign new names
                        method_pattern = re.compile(r'\.method\s+(?:.*?)\s+(\S+)\(', re.DOTALL)
                        for m in method_pattern.finditer(content):
                            old_method = m.group(1)
                            if old_method not in self.method_map:
                                self.method_map[old_method] = self._random_method_name()
                        # field definitions
                        field_pattern = re.compile(r'\.field\s+(?:.*?)\s+(\S+):')
                        for m in field_pattern.finditer(content):
                            old_field = m.group(1)
                            if old_field not in self.field_map:
                                self.field_map[old_field] = self._random_field_name()

        # Second pass: replace references
        for smali_dir in smali_dirs:
            base = os.path.join(self.decode_dir, smali_dir)
            for root, dirs, files in os.walk(base):
                for file in files:
                    if file.endswith('.smali'):
                        filepath = os.path.join(root, file)
                        with open(filepath, 'r', encoding='utf-8') as f:
                            content = f.read()
                        # replace class references (full class names)
                        for old, new in self.class_map.items():
                            content = content.replace(old, new)
                        # replace method references (but careful: in invoke-* lines)
                        for old, new in self.method_map.items():
                            # match exact method name followed by '('
                            content = re.sub(rf'\b{re.escape(old)}\s*\(', f'{new}(', content)
                        # replace field references
                        for old, new in self.field_map.items():
                            content = re.sub(rf'\b{re.escape(old)}\b', new, content)
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(content)

    def inject_junk_code(self):
        # Add dummy methods to random classes
        smali_dirs = [d for d in os.listdir(self.decode_dir) if d.startswith('smali')]
        for smali_dir in smali_dirs:
            base = os.path.join(self.decode_dir, smali_dir)
            for root, dirs, files in os.walk(base):
                for file in files:
                    if file.endswith('.smali'):
                        filepath = os.path.join(root, file)
                        with open(filepath, 'r', encoding='utf-8') as f:
                            content = f.read()
                        # inject one dummy method at end of class
                        dummy_method = self._generate_dummy_method()
                        content = content.replace('//# virtual methods', f'//# virtual methods\n{dummy_method}')
                        # or if no virtual methods section, add before .end class
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(content)

    def _generate_dummy_method(self):
        method_name = self._random_method_name()
        # A method that does something useless
        code = f"""
.method public static {method_name}()V
    .registers 2
    .prologue
    nop
    nop
    goto :loop_start
    :loop_start
    const/4 v0, 0x0
    const/16 v1, 0x64
    :loop
    add-int/lit8 v0, v0, 0x1
    if-lt v0, v1, :loop
    nop
    return-void
.end method
"""
        return code

    def string_encryption(self):
        # Simple XOR encryption of strings with random key per class
        smali_dirs = [d for d in os.listdir(self.decode_dir) if d.startswith('smali')]
        for smali_dir in smali_dirs:
            base = os.path.join(self.decode_dir, smali_dir)
            for root, dirs, files in os.walk(base):
                for file in files:
                    if file.endswith('.smali'):
                        filepath = os.path.join(root, file)
                        with open(filepath, 'r', encoding='utf-8') as f:
                            content = f.read()
                        key = random.randint(1, 255)
                        # find all const-string and encrypt them
                        def encrypt_string(match):
                            old_str = match.group(1)
                            encrypted_chars = [chr(ord(c) ^ key) for c in old_str]
                            encrypted_str = ''.join(encrypted_chars)
                            # replace with a static call to decryption method later, but for simplicity,
                            # we just replace the string with the encrypted version and prepend decryption logic.
                            # However that's heavy, so we just replace with its encrypted hex representation
                            # and add a small decryption method. But let's skip full implementation.
                            return f'"{encrypted_str}"'
                        content = re.sub(r'const-string\s+(v\d+),\s*"([^"]*)"', encrypt_string, content)
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(content)

    def obfuscate_resources(self):
        res_dir = os.path.join(self.decode_dir, 'res')
        if not os.path.exists(res_dir):
            return
        for root, dirs, files in os.walk(res_dir):
            for file in files:
                name, ext = os.path.splitext(file)
                new_name = random_string(10) + ext
                os.rename(os.path.join(root, file), os.path.join(root, new_name))

    def run_full_obfuscation(self):
        self.obfuscate_manifest()
        # Before renaming smali files, read all class names
        smali_dirs = [d for d in os.listdir(self.decode_dir) if d.startswith('smali')]
        for smali_dir in smali_dirs:
            base = os.path.join(self.decode_dir, smali_dir)
            for root, dirs, files in os.walk(base):
                for f in files:
                    if f.endswith('.smali'):
                        full_class = os.path.relpath(os.path.join(root, f), base).replace('/', '.').replace('.smali', '')
                        # if class starts with original package, rename it
                        if full_class.startswith(self.orig_pkg):
                            new_name = self._random_class_name()
                            new_full = self.new_pkg + '.' + new_name
                            self.class_map[full_class] = new_full
        self.rename_smali_files()
        self.obfuscate_smali_code()
        self.inject_junk_code()
        # self.string_encryption()  # optional, can be heavy
        self.obfuscate_resources()

# ----------------------------------------------------------------------
# APK Processing Pipeline
# ----------------------------------------------------------------------
def obfuscate_apk(input_apk: str, output_apk: str) -> bool:
    ensure_dirs()
    decode_dir = os.path.join(TEMP_DIR, 'dec_' + uuid.uuid4().hex[:8])

    # Decode
    logger.info("Decoding APK...")
    ok, _ = run_cmd(['apktool', 'd', '-f', '-o', decode_dir, input_apk])
    if not ok: return False

    # Obfuscate
    logger.info("Running advanced obfuscation...")
    try:
        obf = AdvancedObfuscator(decode_dir)
        obf.run_full_obfuscation()
    except Exception as e:
        logger.exception("Obfuscation error")
        shutil.rmtree(decode_dir, ignore_errors=True)
        return False

    # Rebuild
    logger.info("Rebuilding APK...")
    rebuilt = os.path.join(TEMP_DIR, 'rebuilt.apk')
    ok, _ = run_cmd(['apktool', 'b', '-o', rebuilt, decode_dir])
    if not ok: return False

    # Align
    aligned = os.path.join(TEMP_DIR, 'aligned.apk')
    ok, _ = run_cmd(['zipalign', '-v', '-p', '4', rebuilt, aligned])
    if not ok: return False

    # Generate random keystore
    logger.info("Signing with random certificate...")
    ks_path = os.path.join(TEMP_DIR, 'rand.keystore')
    ks_pass = random_string(16)
    alias = random_string(6)
    dname = f"CN={random_string(5)}, OU={random_string(4)}, O={random_string(5)}, L={random_string(6)}, ST={random_string(4)}, C={random.choice(['US','GB','IN'])}"
    ok, _ = run_cmd([
        'keytool', '-genkey', '-v',
        '-keystore', ks_path, '-alias', alias,
        '-keyalg', 'RSA', '-keysize', '2048', '-validity', '365',
        '-storepass', ks_pass, '-keypass', ks_pass,
        '-dname', dname
    ])
    if not ok: return False

    # Sign
    ok, _ = run_cmd([
        'apksigner', 'sign',
        '--ks', ks_path,
        '--ks-pass', f'pass:{ks_pass}',
        '--ks-key-alias', alias,
        '--out', output_apk, aligned
    ])
    if not ok: return False

    # Cleanup
    for f in [rebuilt, aligned, ks_path]: os.remove(f)
    shutil.rmtree(decode_dir, ignore_errors=True)
    return True

# ----------------------------------------------------------------------
# Telegram Bot
# ----------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Access denied.")
        return
    await update.message.reply_text("FUD Bot ready. Send APK for heavy obfuscation.")

async def handle_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        await update.message.reply_text("Access denied.")
        return
    doc: Document = update.message.document
    if not doc.file_name or not doc.file_name.lower().endswith(".apk"):
        await update.message.reply_text("Only APK accepted.")
        return
    await update.message.reply_text("Processing heavy obfuscation...")
    fin = os.path.join(WORK_DIR, f"{uid}_{doc.file_name}")
    await (await doc.get_file()).download_to_drive(fin)
    base, ext = os.path.splitext(doc.file_name)
    fout = os.path.join(WORK_DIR, f"{base}_obs{ext}")
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
                caption="Heavy Obfuscated + Random Signed APK."
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
