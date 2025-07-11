import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters
import sqlite3
import requests
import json
import asyncio
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from admin_manager import MarzbanAdminManager
from stats_manager import StatsManager
from reporting import ReportingSystem
from user_manager import UserManager
from reseller_manager import ResellerManager
from admin_limits import AdminLimitsManager

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# States for conversation handler
(MAIN_MENU, ADMIN_MENU, RESELLER_MENU, CREATE_ADMIN, CREATE_RESELLER, 
 ADD_BANDWIDTH, ADD_TIME, ADD_USERS, WAITING_ADMIN_USERNAME, 
 WAITING_ADMIN_PASSWORD, WAITING_ADMIN_TELEGRAM_ID, WAITING_ADMIN_CONFIRM, 
 ADMIN_PERMISSIONS, WAITING_PERMISSION_SELECTION, ADMIN_PANEL_MENU,
 WAITING_RESELLER_USERNAME, WAITING_RESELLER_TELEGRAM_ID, WAITING_RESELLER_BANDWIDTH,
 WAITING_RESELLER_DAYS, WAITING_RESELLER_USERS, WAITING_RESELLER_CONFIRM,
 USER_MENU, WAITING_USER_USERNAME, WAITING_USER_BANDWIDTH, WAITING_USER_DAYS,
 WAITING_USER_CONNECTIONS, WAITING_USER_CONFIRM) = range(29)

# Initialize managers
admin_manager = MarzbanAdminManager(
    docker_name=os.getenv('MARZBAN_DOCKER_NAME', 'marzban')
)

# Database setup
def setup_database():
    conn = sqlite3.connect('marzban_bot.db')
    cursor = conn.cursor()
    
    # Create tables for users, admins, resellers, and notifications
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        telegram_id INTEGER UNIQUE,
        username TEXT,
        role TEXT,
        created_at TEXT
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS marzban_admins (
        admin_id INTEGER PRIMARY KEY,
        telegram_id INTEGER,
        username TEXT,
        marzban_username TEXT UNIQUE,
        permissions TEXT,
        limits TEXT,
        created_at TEXT,
        FOREIGN KEY (telegram_id) REFERENCES users (telegram_id)
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS resellers (
        reseller_id INTEGER PRIMARY KEY,
        telegram_id INTEGER,
        username TEXT,
        marzban_username TEXT UNIQUE,
        bandwidth_limit INTEGER,
        bandwidth_used INTEGER,
        expiry_date TEXT,
        max_users INTEGER,
        current_users INTEGER,
        created_at TEXT,
        FOREIGN KEY (telegram_id) REFERENCES users (telegram_id)
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS end_users (
        user_id INTEGER PRIMARY KEY,
        reseller_id INTEGER,
        username TEXT,
        marzban_username TEXT UNIQUE,
        bandwidth_limit INTEGER,
        bandwidth_used INTEGER,
        expiry_date TEXT,
        connection_limit INTEGER,
        created_at TEXT,
        FOREIGN KEY (reseller_id) REFERENCES resellers (reseller_id)
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS notifications (
        notification_id INTEGER PRIMARY KEY,
        user_id INTEGER,
        notification_type TEXT,
        sent_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS activity_log (
        log_id INTEGER PRIMARY KEY,
        action TEXT,
        username TEXT,
        details TEXT,
        created_at TEXT
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS usage_log (
        log_id INTEGER PRIMARY KEY,
        admin_username TEXT,
        bandwidth_added INTEGER,
        users_added INTEGER,
        timestamp TEXT
    )
    ''')
    
    conn.commit()
    conn.close()

# Marzban API integration
class MarzbanAPI:
    def __init__(self):
        self.base_url = os.getenv('MARZBAN_API_URL')
        self.username = os.getenv('MARZBAN_USERNAME')
        self.password = os.getenv('MARZBAN_PASSWORD')
        self.token = None
    
    async def login(self):
        try:
            response = requests.post(
                f"{self.base_url}/admin/token",
                data={"username": self.username, "password": self.password}
            )
            data = response.json()
            self.token = data.get("access_token")
            return self.token is not None
        except Exception as e:
            logger.error(f"خطا در ورود به API مرزبان: {e}")
            return False
    
    async def create_user(self, username, data):
        if not self.token:
            if not await self.login():
                return False, "خطا در احراز هویت با API مرزبان"
        
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            response = requests.post(
                f"{self.base_url}/user/{username}",
                headers=headers,
                json=data
            )
            if response.status_code == 200:
                return True, response.json()
            return False, f"خطای API: {response.status_code} - {response.text}"
        except Exception as e:
            logger.error(f"خطا در ایجاد کاربر: {e}")
            return False, str(e)
    
    async def get_user_info(self, username):
        if not self.token:
            if not await self.login():
                return False, "خطا در احراز هویت با API مرزبان"
        
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            response = requests.get(
                f"{self.base_url}/user/{username}",
                headers=headers
            )
            if response.status_code == 200:
                return True, response.json()
            return False, f"خطای API: {response.status_code} - {response.text}"
        except Exception as e:
            logger.error(f"خطا در دریافت اطلاعات کاربر: {e}")
            return False, str(e)
    
    async def update_user(self, username, data):
        if not self.token:
            if not await self.login():
                return False, "خطا در احراز هویت با API مرزبان"
        
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            response = requests.put(
                f"{self.base_url}/user/{username}",
                headers=headers,
                json=data
            )
            if response.status_code == 200:
                return True, response.json()
            return False, f"خطای API: {response.status_code} - {response.text}"
        except Exception as e:
            logger.error(f"خطا در بروزرسانی کاربر: {e}")
            return False, str(e)
    
    async def delete_user(self, username):
        if not self.token:
            if not await self.login():
                return False, "خطا در احراز هویت با API مرزبان"
        
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            response = requests.delete(
                f"{self.base_url}/user/{username}",
                headers=headers
            )
            if response.status_code == 200:
                return True, "کاربر با موفقیت حذف شد"
            return False, f"خطای API: {response.status_code} - {response.text}"
        except Exception as e:
            logger.error(f"خطا در حذف کاربر: {e}")
            return False, str(e)
    
    async def get_all_users(self):
        if not self.token:
            if not await self.login():
                return False, "خطا در احراز هویت با API مرزبان"
        
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            response = requests.get(
                f"{self.base_url}/users",
                headers=headers
            )
            if response.status_code == 200:
                return True, response.json().get("users", [])
            return False, f"خطای API: {response.status_code} - {response.text}"
        except Exception as e:
            logger.error(f"خطا در دریافت لیست کاربران: {e}")
            return False, str(e)

# Initialize API and managers
marzban_api = MarzbanAPI()
admin_limits_manager = AdminLimitsManager()
stats_manager = StatsManager(marzban_api=marzban_api)
reporting_system = None  # Will be initialized after bot is created

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"کاربر {user.id} ربات را شروع کرد")
    
    # Check if user exists in database
    conn = sqlite3.connect('marzban_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE telegram_id = ?", (user.id,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        role = result[0]
        if role == "superadmin":
            await update.message.reply_text(
                f"سلام {user.first_name}!\n\n"
                "شما به عنوان سوپر ادمین وارد شدید."
            )
            return await admin_menu(update, context)
        elif role == "admin":
            await update.message.reply_text(
                f"سلام {user.first_name}!\n\n"
                "به پنل مدیریت ادمین خوش آمدید."
            )
            return await admin_panel_menu(update, context)
        elif role == "reseller":
            return await reseller_menu(update, context)
    
    # Super admin IDs from environment
    super_admin_ids = [int(id.strip()) for id in os.getenv('SUPER_ADMIN_IDS', '').split(',') if id.strip()]
    
    if user.id in super_admin_ids:
        # Register super admin
        conn = sqlite3.connect('marzban_bot.db')
        cursor = conn.cursor()
        cursor.execute("""
        INSERT OR REPLACE INTO users (telegram_id, username, role, created_at)
        VALUES (?, ?, ?, ?)
        """, (user.id, user.username or f"user_{user.id}", "superadmin", datetime.now().isoformat()))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(
            f"سلام {user.first_name}!\n\n"
            "شما به عنوان سوپر ادمین وارد شدید."
        )
        return await admin_menu(update, context)
    
    # New user or no role assigned
    await update.message.reply_text(
        f"سلام {user.first_name} به ربات مدیریت پنل مرزبان خوش آمدید!\n\n"
        "لطفاً با مدیر سیستم تماس بگیرید تا به شما دسترسی داده شود."
    )
    return ConversationHandler.END

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("ایجاد ادمین جدید", callback_data="create_admin")],
        [InlineKeyboardButton("مشاهده ادمین‌ها", callback_data="view_admins")],
        [InlineKeyboardButton("ایجاد نماینده جدید", callback_data="create_reseller")],
        [InlineKeyboardButton("مشاهده نمایندگان", callback_data="view_resellers")],
        [InlineKeyboardButton("📊 داشبورد سیستم", callback_data="system_dashboard")],
        [InlineKeyboardButton("⚙️ تنظیمات ربات", callback_data="bot_settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text("منوی مدیریت:", reply_markup=reply_markup)
    else:
        await update.callback_query.edit_message_text("منوی مدیریت:", reply_markup=reply_markup)
    
    return ADMIN_MENU

async def reseller_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("اطلاعات حساب من", callback_data="account_info")],
        [InlineKeyboardButton("ایجاد کاربر", callback_data="create_user")],
        [InlineKeyboardButton("مشاهده کاربران", callback_data="view_users")],
        [InlineKeyboardButton("تمدید سرویس", callback_data="renew_services")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text("منوی نماینده:", reply_markup=reply_markup)
    else:
        await update.callback_query.edit_message_text("منوی نماینده:", reply_markup=reply_markup)
    
    return RESELLER_MENU

async def admin_panel_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Display the admin panel menu for admins to see their own panel details
    """
    user = update.effective_user
    
    # Get admin info from database
    conn = sqlite3.connect('marzban_bot.db')
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT marzban_username, permissions, limits FROM marzban_admins
    WHERE telegram_id = ?
    """, (user.id,))
    
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        await update.message.reply_text(
            "❌ شما به عنوان ادمین در سیستم ثبت نشده‌اید."
        )
        return ConversationHandler.END
    
    marzban_username, permissions_json, limits_json = result
    permissions = json.loads(permissions_json) if permissions_json else []
    limits = json.loads(limits_json) if limits_json else {}
    
    # Get admin usage from Marzban API
    admin_stats = "در حال دریافت..."
    if marzban_api:
        # This would need implementation in the MarzbanAPI class
        # For now we'll just show placeholder data
        admin_stats = "اطلاعات آماری از API مرزبان در دسترس نیست."
    
    # Format permissions
    formatted_permissions = []
    for perm in permissions:
        if perm == "user_create":
            formatted_permissions.append("ایجاد کاربر")
        elif perm == "user_read":
            formatted_permissions.append("مشاهده کاربران")
        elif perm == "user_update":
            formatted_permissions.append("ویرایش کاربران")
        elif perm == "user_delete":
            formatted_permissions.append("حذف کاربران")
        else:
            formatted_permissions.append(perm)
    
    # Format limits
    bandwidth_limit = limits.get('max_bandwidth_gb', 'نامحدود')
    bandwidth_used = limits.get('used_bandwidth_gb', 0)
    user_limit = limits.get('max_users', 'نامحدود')
    users_created = limits.get('created_users', 0)
    expiry_date = limits.get('expiry_date', None)
    
    days_remaining = "نامحدود"
    if expiry_date:
        try:
            expiry = datetime.fromisoformat(expiry_date)
            days_left = (expiry - datetime.now()).days
            days_remaining = f"{days_left} روز"
        except:
            days_remaining = "نامشخص"
    
    # Generate panel URL
    panel_url = os.getenv('MARZBAN_PANEL_URL', 'https://your-panel-url')
    
    # Create message
    message = f"👤 *پنل مدیریت ادمین*\n\n"
    message += f"🔹 *نام کاربری:* `{marzban_username}`\n"
    message += f"🔹 *آدرس پنل:* {panel_url}\n\n"
    
    message += "📊 *آمار مصرف:*\n"
    message += f"  - حجم مصرفی: {bandwidth_used} از {bandwidth_limit} گیگابایت\n"
    message += f"  - کاربران ایجاد شده: {users_created} از {user_limit}\n"
    message += f"  - زمان باقی‌مانده: {days_remaining}\n\n"
    
    message += "🔐 *دسترسی‌ها:*\n"
    if formatted_permissions:
        for i, perm in enumerate(formatted_permissions, 1):
            message += f"  {i}. {perm}\n"
    else:
        message += "  بدون دسترسی\n"
    
    # Create keyboard
    keyboard = [
        [InlineKeyboardButton("📈 نمودار مصرف", callback_data="my_usage_chart")],
        [InlineKeyboardButton("👥 مشاهده کاربران من", callback_data="my_users")],
        [InlineKeyboardButton("📝 درخواست تمدید", callback_data="request_renewal")],
        [InlineKeyboardButton("🔄 بروزرسانی اطلاعات", callback_data="refresh_my_panel")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    return ADMIN_PANEL_MENU

# Admin creation process
async def create_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "ایجاد ادمین جدید برای پنل مرزبان\n\n"
        "لطفاً نام کاربری ادمین را وارد کنید:"
    )
    
    return WAITING_ADMIN_USERNAME

async def admin_username_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip()
    
    # Validate username
    if not username or ' ' in username:
        await update.message.reply_text(
            "نام کاربری نامعتبر است. نام کاربری نباید خالی باشد یا فاصله داشته باشد.\n"
            "لطفاً دوباره وارد کنید:"
        )
        return WAITING_ADMIN_USERNAME
    
    # Store username in context
    context.user_data['admin_username'] = username
    
    await update.message.reply_text(
        f"نام کاربری: {username}\n\n"
        "لطفاً رمز عبور ادمین را وارد کنید:"
    )
    
    return WAITING_ADMIN_PASSWORD

async def admin_password_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    
    # Validate password
    if not password or len(password) < 6:
        await update.message.reply_text(
            "رمز عبور نامعتبر است. رمز عبور باید حداقل 6 کاراکتر باشد.\n"
            "لطفاً دوباره وارد کنید:"
        )
        return WAITING_ADMIN_PASSWORD
    
    # Store password in context
    context.user_data['admin_password'] = password
    
    await update.message.reply_text(
        f"نام کاربری: {context.user_data['admin_username']}\n"
        f"رمز عبور: {'*' * len(password)}\n\n"
        "لطفاً آیدی عددی تلگرام ادمین را وارد کنید:\n"
        "(برای پیدا کردن آیدی عددی تلگرام می‌توانید از @userinfobot استفاده کنید)"
    )
    
    return WAITING_ADMIN_TELEGRAM_ID

async def admin_telegram_id_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.message.text.strip()
    
    # Validate telegram_id
    try:
        telegram_id = int(telegram_id)
    except ValueError:
        await update.message.reply_text(
            "آیدی تلگرام باید یک عدد باشد.\n"
            "لطفاً دوباره وارد کنید:"
        )
        return WAITING_ADMIN_TELEGRAM_ID
    
    # Store telegram_id in context
    context.user_data['admin_telegram_id'] = telegram_id
    
    # Get permission presets
    permission_presets = await admin_manager.get_permission_presets()
    
    # Create keyboard with permission presets
    keyboard = []
    for preset_name in permission_presets.keys():
        keyboard.append([InlineKeyboardButton(preset_name, callback_data=f"preset_{preset_name}")])
    
    keyboard.append([InlineKeyboardButton("دسترسی سفارشی", callback_data="custom_permissions")])
    keyboard.append([InlineKeyboardButton("انصراف", callback_data="cancel_admin")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    username = context.user_data['admin_username']
    await update.message.reply_text(
        f"لطفاً سطح دسترسی برای '{username}' را انتخاب کنید:",
        reply_markup=reply_markup
    )
    
    return ADMIN_PERMISSIONS

async def admin_permissions_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_admin":
        await query.edit_message_text("عملیات ایجاد ادمین لغو شد.")
        return await admin_menu(update, context)
    
    if query.data == "custom_permissions":
        # Show custom permission selection
        all_permissions = await admin_manager.get_all_permissions()
        
        # Create keyboard with all permissions
        keyboard = []
        for perm in all_permissions:
            keyboard.append([InlineKeyboardButton(
                f"{perm['description']} ({perm['key']})", 
                callback_data=f"perm_{perm['key']}"
            )])
        
        keyboard.append([InlineKeyboardButton("تأیید و ادامه", callback_data="confirm_permissions")])
        keyboard.append([InlineKeyboardButton("انصراف", callback_data="cancel_admin")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Initialize selected permissions
        if 'selected_permissions' not in context.user_data:
            context.user_data['selected_permissions'] = []
        
        await query.edit_message_text(
            "لطفاً دسترسی‌های مورد نظر را انتخاب کنید:\n"
            "(برای انتخاب یا لغو انتخاب هر دسترسی، روی آن کلیک کنید)\n\n"
            f"دسترسی‌های انتخاب شده: {', '.join(context.user_data['selected_permissions'])}",
            reply_markup=reply_markup
        )
        
        return WAITING_PERMISSION_SELECTION
    
    # Handle preset selection
    if query.data.startswith("preset_"):
        preset_name = query.data[7:]  # Remove "preset_" prefix
        permission_presets = await admin_manager.get_permission_presets()
        
        if preset_name in permission_presets:
            context.user_data['selected_permissions'] = permission_presets[preset_name]
            
            # Show confirmation
            username = context.user_data['admin_username']
            password = context.user_data['admin_password']
            telegram_id = context.user_data['admin_telegram_id']
            permissions = context.user_data['selected_permissions']
            
            keyboard = [
                [
                    InlineKeyboardButton("تأیید", callback_data="confirm_admin"),
                    InlineKeyboardButton("انصراف", callback_data="cancel_admin")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"اطلاعات ادمین جدید:\n\n"
                f"نام کاربری: {username}\n"
                f"رمز عبور: {'*' * len(password)}\n"
                f"آیدی تلگرام: {telegram_id}\n"
                f"سطح دسترسی: {preset_name}\n"
                f"دسترسی‌ها: {', '.join(permissions)}\n\n"
                "آیا از ایجاد این ادمین اطمینان دارید؟",
                reply_markup=reply_markup
            )
            
            return WAITING_ADMIN_CONFIRM
    
    return ADMIN_PERMISSIONS

async def handle_permission_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_admin":
        await query.edit_message_text("عملیات ایجاد ادمین لغو شد.")
        return await admin_menu(update, context)
    
    if query.data == "confirm_permissions":
        # Proceed to confirmation
        username = context.user_data['admin_username']
        password = context.user_data['admin_password']
        telegram_id = context.user_data['admin_telegram_id']
        permissions = context.user_data.get('selected_permissions', [])
        
        keyboard = [
            [
                InlineKeyboardButton("تأیید", callback_data="confirm_admin"),
                InlineKeyboardButton("انصراف", callback_data="cancel_admin")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"اطلاعات ادمین جدید:\n\n"
            f"نام کاربری: {username}\n"
            f"رمز عبور: {'*' * len(password)}\n"
            f"آیدی تلگرام: {telegram_id}\n"
            f"دسترسی‌ها: {', '.join(permissions) if permissions else 'بدون دسترسی'}\n\n"
            "آیا از ایجاد این ادمین اطمینان دارید؟",
            reply_markup=reply_markup
        )
        
        return WAITING_ADMIN_CONFIRM
    
    # Handle individual permission selection
    if query.data.startswith("perm_"):
        perm_key = query.data[5:]  # Remove "perm_" prefix
        
        # Toggle permission selection
        if 'selected_permissions' not in context.user_data:
            context.user_data['selected_permissions'] = []
            
        if perm_key in context.user_data['selected_permissions']:
            context.user_data['selected_permissions'].remove(perm_key)
        else:
            context.user_data['selected_permissions'].append(perm_key)
        
        # Update message with current selections
        all_permissions = await admin_manager.get_all_permissions()
        
        # Create keyboard with all permissions
        keyboard = []
        for perm in all_permissions:
            # Mark selected permissions
            prefix = "✅ " if perm['key'] in context.user_data['selected_permissions'] else "❌ "
            keyboard.append([InlineKeyboardButton(
                f"{prefix}{perm['description']} ({perm['key']})", 
                callback_data=f"perm_{perm['key']}"
            )])
        
        keyboard.append([InlineKeyboardButton("تأیید و ادامه", callback_data="confirm_permissions")])
        keyboard.append([InlineKeyboardButton("انصراف", callback_data="cancel_admin")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "لطفاً دسترسی‌های مورد نظر را انتخاب کنید:\n"
            "(برای انتخاب یا لغو انتخاب هر دسترسی، روی آن کلیک کنید)\n\n"
            f"دسترسی‌های انتخاب شده: {', '.join(context.user_data['selected_permissions']) if context.user_data['selected_permissions'] else 'هیچ دسترسی انتخاب نشده'}",
            reply_markup=reply_markup
        )
        
        return WAITING_PERMISSION_SELECTION
    
    return WAITING_PERMISSION_SELECTION

async def create_admin_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_admin":
        await query.edit_message_text("عملیات ایجاد ادمین لغو شد.")
        return await admin_menu(update, context)
    
    # Get admin info from context
    username = context.user_data['admin_username']
    password = context.user_data['admin_password']
    telegram_id = context.user_data['admin_telegram_id']
    permissions = context.user_data.get('selected_permissions', [])
    
    # Create the admin in Marzban
    success, message = await admin_manager.create_admin(username, password)
    
    if success:
        # Set permissions if specified
        if permissions:
            perm_success, perm_message = await admin_manager.update_admin_permissions(username, permissions)
            if not perm_success:
                message += f"\nاما تنظیم دسترسی‌ها با خطا مواجه شد: {perm_message}"
        
        # Save admin in local database
        conn = sqlite3.connect('marzban_bot.db')
        cursor = conn.cursor()
        
        try:
            # Create user entry if doesn't exist
            cursor.execute("""
            INSERT OR IGNORE INTO users (telegram_id, username, role, created_at)
            VALUES (?, ?, ?, ?)
            """, (
                telegram_id,
                f"tg_user_{telegram_id}",
                "admin",
                datetime.now().isoformat()
            ))
            
            # Add the admin to database
            cursor.execute("""
            INSERT INTO marzban_admins 
            (telegram_id, username, marzban_username, permissions, created_at)
            VALUES (?, ?, ?, ?, ?)
            """, (
                telegram_id, 
                f"tg_user_{telegram_id}", 
                username, 
                json.dumps(permissions), 
                datetime.now().isoformat()
            ))
            
            conn.commit()
            
            # Generate panel URL
            panel_url = os.getenv('MARZBAN_PANEL_URL', 'https://your-panel-url')
            
            # Try to notify the admin directly
            try:
                if telegram_id != update.effective_user.id:  # Don't send if it's the same person
                    await context.bot.send_message(
                        chat_id=telegram_id,
                        text=f"🎉 *به پنل مرزبان خوش آمدید!*\n\n"
                             f"شما به عنوان ادمین اضافه شده‌اید. اطلاعات حساب شما:\n\n"
                             f"🔹 *نام کاربری:* `{username}`\n"
                             f"🔹 *رمز عبور:* `{password}`\n"
                             f"🔹 *آدرس پنل:* {panel_url}\n\n"
                             f"برای مشاهده اطلاعات پنل و آمار مصرف، از دستور /start استفاده کنید.",
                        parse_mode='Markdown'
                    )
                    message += "\n✅ پیام خوش‌آمدگویی به ادمین ارسال شد."
                    
            except Exception as e:
                message += f"\n❌ ارسال پیام به ادمین با خطا مواجه شد: {str(e)}"
            
            # Log activity
            await stats_manager.log_activity(
                "create_admin",
                username,
                {"creator": update.effective_user.id, "permissions": permissions}
            )
            
        except Exception as e:
            message += f"\n❌ ذخیره در پایگاه داده محلی با خطا مواجه شد: {str(e)}"
        finally:
            conn.close()
        
        await query.edit_message_text(
            f"✅ ادمین با موفقیت ایجاد شد!\n\n"
            f"نام کاربری: {username}\n"
            f"رمز عبور: {password}\n"
            f"آیدی تلگرام: {telegram_id}\n"
            f"دسترسی‌ها: {', '.join(permissions) if permissions else 'بدون دسترسی'}\n\n"
            f"آدرس پنل: {panel_url}\n\n"
            f"{message}"
        )
    else:
        await query.edit_message_text(
            f"❌ خطا در ایجاد ادمین:\n{message}"
        )
    
    # Clear user data
    context.user_data.clear()
    
    # Return to admin menu
    keyboard = [[InlineKeyboardButton("بازگشت به منوی مدیریت", callback_data="back_to_admin")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        query.message.text + "\n\n" +
        "برای بازگشت به منوی مدیریت، روی دکمه زیر کلیک کنید.",
        reply_markup=reply_markup
    )
    
    return ADMIN_MENU

async def view_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Get admins from Marzban
    success, admin_list = await admin_manager.list_admins()
    
    if success:
        admin_text = "📋 لیست ادمین‌های پنل مرزبان:\n\n"
        
        if not admin_list:
            admin_text += "هیچ ادمینی یافت نشد."
        else:
            for i, admin in enumerate(admin_list, 1):
                sudo_status = "✅ سوپر ادمین" if admin.get("is_sudo") else "👤 ادمین معمولی"
                admin_text += f"{i}. {admin['username']} - {sudo_status}\n"
    else:
        admin_text = f"❌ خطا در دریافت لیست ادمین‌ها:\n{admin_list}"
    
    keyboard = []
    
    # Add a button for each admin to manage them
    if success and admin_list:
        for admin in admin_list:
            keyboard.append([
                InlineKeyboardButton(
                    f"مدیریت {admin['username']}", 
                    callback_data=f"manage_admin_{admin['username']}"
                )
            ])
    
    keyboard.append([InlineKeyboardButton("بازگشت به منوی مدیریت", callback_data="back_to_admin")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(admin_text, reply_markup=reply_markup)
    
    return ADMIN_MENU

async def handle_admin_panel_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle button clicks in admin panel menu
    """
    query = update.callback_query
    await query.answer()
    
    if query.data == "my_usage_chart":
        # Generate and send usage chart
        await query.edit_message_text(
            "📊 در حال تهیه نمودار مصرف شما...\n"
            "لطفاً صبر کنید."
        )
        
        user = update.effective_user
        
        # Get admin username
        conn = sqlite3.connect('marzban_bot.db')
        cursor = conn.cursor()
        
        cursor.execute("""
        SELECT marzban_username FROM marzban_admins
        WHERE telegram_id = ?
        """, (user.id,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            admin_username = result[0]
            success, chart_path = await stats_manager.generate_usage_chart(admin_username)
            
            if success:
                # Send chart image
                with open(chart_path, 'rb') as photo:
                    await context.bot.send_photo(
                        chat_id=user.id,
                        photo=photo,
                        caption=f"📊 نمودار مصرف برای {admin_username}"
                    )
                
                # Remove temporary file
                os.remove(chart_path)
            else:
                await query.edit_message_text(
                    f"❌ خطا در تهیه نمودار: {chart_path}"
                )
        else:
            await query.edit_message_text(
                "❌ نام کاربری ادمین شما یافت نشد."
            )
        
        # Return to admin panel menu after a delay
        await asyncio.sleep(2)
        return await admin_panel_menu(update, context)
        
    elif query.data == "my_users":
        # Show users created by this admin
        await query.edit_message_text(
            "👥 در حال دریافت لیست کاربران شما...\n"
            "لطفاً صبر کنید."
        )
        
        user = update.effective_user
        
        # Get admin username
        conn = sqlite3.connect('marzban_bot.db')
        cursor = conn.cursor()
        
        cursor.execute("""
        SELECT marzban_username FROM marzban_admins
        WHERE telegram_id = ?
        """, (user.id,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result and marzban_api:
            admin_username = result[0]
            
            # This would need implementation in the MarzbanAPI class
            # For now we'll just show placeholder message
            
            await query.edit_message_text(
                f"👥 *کاربران ادمین {admin_username}*\n\n"
                "این قابلیت در حال توسعه است و به زودی فعال می‌شود.",
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text(
                "❌ اطلاعات ادمین شما یافت نشد یا API مرزبان در دسترس نیست."
            )
        
        # Return to admin panel menu after a delay
        await asyncio.sleep(3)
        return await admin_panel_menu(update, context)
        
    elif query.data == "request_renewal":
        # Send renewal request to super admins
        user = update.effective_user
        
        # Get all super admins
        conn = sqlite3.connect('marzban_bot.db')
        cursor = conn.cursor()
        
        cursor.execute("""
        SELECT telegram_id FROM users
        WHERE role = 'superadmin'
        """)
        
        super_admins = [row[0] for row in cursor.fetchall()]
        
        cursor.execute("""
        SELECT marzban_username FROM marzban_admins
        WHERE telegram_id = ?
        """, (user.id,))
        
        result = cursor.fetchone()
        admin_username = result[0] if result else "ناشناس"
        
        conn.close()
        
        # Send request to super admins
        for admin_id in super_admins:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"🔔 *درخواست تمدید*\n\n"
                         f"ادمین `{admin_username}` (با نام کاربری {user.username or user.id}) "
                         f"درخواست تمدید حساب خود را دارد.\n\n"
                         f"لطفاً با ایشان تماس بگیرید.",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"خطا در ارسال درخواست تمدید به ادمین {admin_id}: {str(e)}")
        
        await query.edit_message_text(
            "✅ درخواست تمدید شما با موفقیت ارسال شد.\n"
            "مدیر سیستم در اسرع وقت با شما تماس خواهد گرفت."
        )
        
        # Return to admin panel menu after a delay
        await asyncio.sleep(3)
        return await admin_panel_menu(update, context)
        
    elif query.data == "refresh_my_panel":
        # Refresh admin panel
        return await admin_panel_menu(update, context)
    
    return ADMIN_PANEL_MENU

# Callback query handler
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "create_admin":
        return await create_admin_start(update, context)
    elif query.data == "back_to_admin":
        return await admin_menu(update, context)
    elif query.data == "view_admins":
        return await view_admins(update, context)
    # Add handlers for other buttons
    
    return ADMIN_MENU

# System dashboard
async def system_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "📊 در حال بارگذاری داشبورد سیستم...\n"
        "لطفاً صبر کنید."
    )
    
    # Get system stats
    success, stats = await stats_manager.get_system_stats()
    
    if success:
        dashboard_text, reply_markup = await stats_manager.create_dashboard_menu(stats)
        await query.edit_message_text(dashboard_text, reply_markup=reply_markup)
    else:
        await query.edit_message_text(
            f"❌ خطا در دریافت آمار سیستم:\n{stats}"
        )
        # Return to admin menu
        keyboard = [[InlineKeyboardButton("بازگشت به منوی مدیریت", callback_data="back_to_admin")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "❌ خطا در دریافت آمار سیستم.\n"
            "لطفاً بعداً دوباره تلاش کنید.",
            reply_markup=reply_markup
        )
    
    return ADMIN_MENU

# Notification system
async def check_notifications(bot):
    """Periodic task to check and send notifications"""
    while True:
        try:
            # Initialize user manager if not already done
            user_manager = UserManager(db_path='marzban_bot.db', marzban_api=marzban_api, bot=bot)
            
            # Check for user notifications
            await user_manager.check_and_notify_users()
            
            # Also check for admin notifications
            # TODO: Implement admin notifications
            
            # Wait for notification interval
            notification_interval = int(os.getenv('NOTIFICATION_INTERVAL', 3600))
            await asyncio.sleep(notification_interval)
            
        except Exception as e:
            logger.error(f"Error in notification system: {str(e)}")
            await asyncio.sleep(300)  # Wait 5 minutes before retrying on error

# Main function
async def main():
    # Setup database
    setup_database()
    
    # Initialize bot
    application = Application.builder().token(os.getenv('TELEGRAM_BOT_TOKEN')).build()
    
    # Initialize reporting system with bot instance
    global reporting_system
    reporting_system = ReportingSystem(db_path='marzban_bot.db', bot=application.bot)
    
    # Add handlers
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(admin_menu, pattern="^admin$"),
                CallbackQueryHandler(reseller_menu, pattern="^reseller$")
            ],
            ADMIN_MENU: [
                CallbackQueryHandler(create_admin_start, pattern="^create_admin$"),
                CallbackQueryHandler(view_admins, pattern="^view_admins$"),
                CallbackQueryHandler(system_dashboard, pattern="^system_dashboard$"),
                CallbackQueryHandler(admin_menu, pattern="^back_to_admin$"),
                # Add more handlers for admin menu
            ],
            WAITING_ADMIN_USERNAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_username_received)
            ],
            WAITING_ADMIN_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_password_received)
            ],
            WAITING_ADMIN_TELEGRAM_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_telegram_id_received)
            ],
            ADMIN_PERMISSIONS: [
                CallbackQueryHandler(admin_permissions_selected)
            ],
            WAITING_PERMISSION_SELECTION: [
                CallbackQueryHandler(handle_permission_selection)
            ],
            WAITING_ADMIN_CONFIRM: [
                CallbackQueryHandler(create_admin_confirmed)
            ],
            ADMIN_PANEL_MENU: [
                CallbackQueryHandler(handle_admin_panel_buttons)
            ],
            RESELLER_MENU: [
                # Add handlers for reseller menu
            ],
            # Add more states as needed
        },
        fallbacks=[CommandHandler("start", start)],
    )
    
    application.add_handler(conv_handler)
    
    # Start the Bot
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    # Start notification checker in background
    asyncio.create_task(check_notifications(application.bot))
    
    # Start scheduled reports
    asyncio.create_task(reporting_system.send_scheduled_reports())
    
    # Run the bot until the user presses Ctrl-C
    await application.idle()

if __name__ == '__main__':
    asyncio.run(main())