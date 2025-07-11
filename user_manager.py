import sqlite3
from datetime import datetime, timedelta
import json
import logging
import uuid

logger = logging.getLogger(__name__)

class UserManager:
    def __init__(self, db_path='marzban_bot.db', marzban_api=None, bot=None):
        self.db_path = db_path
        self.marzban_api = marzban_api
        self.bot = bot
    
    async def create_user(self, reseller_telegram_id, username, bandwidth_gb=50, days=30, connection_limit=3):
        """
        Create a new end-user for a reseller
        
        :param reseller_telegram_id: Telegram ID of the reseller
        :param username: Username for the end-user
        :param bandwidth_gb: Bandwidth limit in GB
        :param days: Number of days until expiry
        :param connection_limit: Maximum number of concurrent connections
        :return: (success, message)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Get reseller info
            cursor.execute("""
            SELECT reseller_id, marzban_username, current_users, max_users, bandwidth_limit, bandwidth_used
            FROM resellers WHERE telegram_id = ?
            """, (reseller_telegram_id,))
            
            result = cursor.fetchone()
            
            if not result:
                return False, "شما به عنوان نماینده شناخته نشدید"
            
            reseller_id, reseller_marzban_username, current_users, max_users, bandwidth_limit, bandwidth_used = result
            
            # Check if reseller has reached their user limit
            if current_users >= max_users:
                return False, "شما به حداکثر تعداد کاربران مجاز رسیده‌اید"
            
            # Check if reseller has enough bandwidth
            user_bandwidth_bytes = bandwidth_gb * 1024**3
            if bandwidth_used + user_bandwidth_bytes > bandwidth_limit:
                return False, "حجم شما کافی نیست"
            
            # Generate a unique user ID for Marzban
            user_marzban_username = f"user_{username}_{uuid.uuid4().hex[:8]}"
            
            # Calculate expiry date
            expiry_date = (datetime.now() + timedelta(days=days)).isoformat()
            
            # Create user in Marzban if API is available
            if self.marzban_api:
                success, result = await self.marzban_api.create_user(
                    user_marzban_username,
                    {
                        "data_limit": user_bandwidth_bytes,
                        "expire": expiry_date,
                        "connection_limit": connection_limit
                    }
                )
                
                if not success:
                    return False, f"خطا در ایجاد کاربر مرزبان: {result}"
                
                # Get subscription link if available
                subscription_url = result.get('subscription_url', '')
            else:
                subscription_url = ""
            
            # Create user record
            cursor.execute("""
            INSERT INTO end_users
            (reseller_id, username, marzban_username, bandwidth_limit, bandwidth_used,
             expiry_date, connection_limit, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                reseller_id,
                username,
                user_marzban_username,
                user_bandwidth_bytes,
                0,  # Initial bandwidth used
                expiry_date,
                connection_limit,
                datetime.now().isoformat()
            ))
            
            # Update reseller's current users count and bandwidth usage
            cursor.execute("""
            UPDATE resellers SET 
                current_users = current_users + 1,
                bandwidth_used = bandwidth_used + ?
            WHERE reseller_id = ?
            """, (user_bandwidth_bytes, reseller_id))
            
            conn.commit()
            
            return True, {
                "user_id": cursor.lastrowid,
                "username": username,
                "marzban_username": user_marzban_username,
                "bandwidth_gb": bandwidth_gb,
                "expiry_date": expiry_date,
                "connection_limit": connection_limit,
                "subscription_url": subscription_url
            }
            
        except Exception as e:
            logger.error(f"خطا در ایجاد کاربر: {str(e)}")
            return False, f"خطا در ایجاد کاربر: {str(e)}"
        finally:
            conn.close()
    
    async def get_user_info(self, user_id=None, marzban_username=None):
        """
        Get information about a user
        
        :param user_id: ID of the user in database
        :param marzban_username: Marzban username of the user
        :return: (success, user_info or error_message)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Build query based on provided parameters
            query = "SELECT * FROM end_users WHERE "
            params = []
            
            if user_id:
                query += "user_id = ?"
                params.append(user_id)
            elif marzban_username:
                query += "marzban_username = ?"
                params.append(marzban_username)
            else:
                return False, "پارامتر شناسایی کاربر ارائه نشده است"
            
            cursor.execute(query, params)
            result = cursor.fetchone()
            
            if not result:
                return False, "کاربر مورد نظر یافت نشد"
            
            # Parse result
            user_id, reseller_id, username, marzban_username, bandwidth_limit, bandwidth_used, \
                expiry_date, connection_limit, created_at = result
            
            # Update data from Marzban if API is available
            if self.marzban_api and marzban_username:
                success, user_data = await self.marzban_api.get_user_info(marzban_username)
                
                if success:
                    # Update bandwidth used from Marzban
                    bandwidth_used = user_data.get('used_traffic', bandwidth_used)
                    
                    # Update database with latest values
                    cursor.execute("""
                    UPDATE end_users SET bandwidth_used = ? WHERE user_id = ?
                    """, (bandwidth_used, user_id))
                    conn.commit()
            
            # Calculate remaining days
            expiry_datetime = datetime.fromisoformat(expiry_date)
            days_remaining = (expiry_datetime - datetime.now()).days
            
            user_info = {
                "user_id": user_id,
                "reseller_id": reseller_id,
                "username": username,
                "marzban_username": marzban_username,
                "bandwidth": {
                    "limit_bytes": bandwidth_limit,
                    "limit_gb": round(bandwidth_limit / 1024**3, 2),
                    "used_bytes": bandwidth_used,
                    "used_gb": round(bandwidth_used / 1024**3, 2),
                    "remaining_bytes": max(0, bandwidth_limit - bandwidth_used),
                    "remaining_gb": round(max(0, bandwidth_limit - bandwidth_used) / 1024**3, 2),
                    "percent_used": round((bandwidth_used / bandwidth_limit) * 100, 2) if bandwidth_limit > 0 else 0
                },
                "subscription": {
                    "expiry_date": expiry_date,
                    "days_remaining": days_remaining
                },
                "connection_limit": connection_limit,
                "created_at": created_at
            }
            
            return True, user_info
            
        except Exception as e:
            logger.error(f"خطا در دریافت اطلاعات کاربر: {str(e)}")
            return False, f"خطا در دریافت اطلاعات کاربر: {str(e)}"
        finally:
            conn.close()
    
    async def list_users_for_reseller(self, reseller_telegram_id, page=0, page_size=10):
        """
        List all users for a specific reseller with pagination
        
        :param reseller_telegram_id: Telegram ID of the reseller
        :param page: Page number (0-based)
        :param page_size: Number of items per page
        :return: (success, users_list or error_message, total_pages)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Get reseller ID
            cursor.execute("SELECT reseller_id FROM resellers WHERE telegram_id = ?", (reseller_telegram_id,))
            result = cursor.fetchone()
            
            if not result:
                return False, "شما به عنوان نماینده شناخته نشدید", 0
                
            reseller_id = result[0]
            
            # Get total count for pagination
            cursor.execute("SELECT COUNT(*) FROM end_users WHERE reseller_id = ?", (reseller_id,))
            total_count = cursor.fetchone()[0]
            total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1
            
            # Get paginated users
            cursor.execute("""
            SELECT user_id, username, marzban_username, bandwidth_limit, bandwidth_used, expiry_date, connection_limit
            FROM end_users
            WHERE reseller_id = ?
            LIMIT ? OFFSET ?
            """, (reseller_id, page_size, page * page_size))
            
            results = cursor.fetchall()
            
            users = []
            for result in results:
                user_id, username, marzban_username, bandwidth_limit, bandwidth_used, expiry_date, connection_limit = result
                
                # Calculate remaining days
                expiry_datetime = datetime.fromisoformat(expiry_date)
                days_remaining = (expiry_datetime - datetime.now()).days
                
                users.append({
                    "user_id": user_id,
                    "username": username,
                    "marzban_username": marzban_username,
                    "bandwidth_limit_gb": round(bandwidth_limit / 1024**3, 2),
                    "bandwidth_used_gb": round(bandwidth_used / 1024**3, 2),
                    "bandwidth_percent": round((bandwidth_used / bandwidth_limit) * 100, 2) if bandwidth_limit > 0 else 0,
                    "days_remaining": days_remaining,
                    "connection_limit": connection_limit
                })
            
            return True, users, total_pages
            
        except Exception as e:
            logger.error(f"خطا در دریافت لیست کاربران: {str(e)}")
            return False, f"خطا در دریافت لیست کاربران: {str(e)}", 0
        finally:
            conn.close()
    
    async def check_and_notify_users(self):
        """
        Check all users and send notifications for those approaching limits
        
        :return: None
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Get all users who are approaching bandwidth limit (300GB remaining or less)
            cursor.execute("""
            SELECT u.user_id, u.username, u.marzban_username, u.bandwidth_limit, u.bandwidth_used,
                   r.telegram_id as reseller_telegram_id
            FROM end_users u
            JOIN resellers r ON u.reseller_id = r.reseller_id
            WHERE (u.bandwidth_limit - u.bandwidth_used) <= 322122547200  -- 300GB in bytes
            AND (u.bandwidth_limit - u.bandwidth_used) > 0  -- Still has some bandwidth
            AND u.user_id NOT IN (
                SELECT user_id FROM notifications 
                WHERE notification_type = 'bandwidth_warning'
                AND sent_at > datetime('now', '-3 days')  -- Don't repeat warnings more than once every 3 days
            )
            """)
            
            bandwidth_warnings = cursor.fetchall()
            
            # Send notifications
            for user in bandwidth_warnings:
                user_id, username, marzban_username, bandwidth_limit, bandwidth_used, reseller_telegram_id = user
                remaining_gb = round((bandwidth_limit - bandwidth_used) / 1024**3, 2)
                
                if self.bot:
                    # Notify reseller
                    await self.bot.send_message(
                        chat_id=reseller_telegram_id,
                        text=f"⚠️ *هشدار حجم کاربر*\n\n"
                             f"کاربر: `{username}`\n"
                             f"حجم باقی‌مانده: *{remaining_gb} GB*\n\n"
                             f"لطفاً اقدامات لازم را انجام دهید.",
                        parse_mode='Markdown'
                    )
                
                # Log notification
                cursor.execute("""
                INSERT INTO notifications (user_id, notification_type, sent_at)
                VALUES (?, ?, ?)
                """, (user_id, 'bandwidth_warning', datetime.now().isoformat()))
            
            # Get all users who are approaching expiry (3 days or less)
            cursor.execute("""
            SELECT u.user_id, u.username, u.marzban_username, u.expiry_date,
                   r.telegram_id as reseller_telegram_id
            FROM end_users u
            JOIN resellers r ON u.reseller_id = r.reseller_id
            WHERE julianday(u.expiry_date) - julianday('now') <= 3
            AND julianday(u.expiry_date) - julianday('now') > 0
            AND u.user_id NOT IN (
                SELECT user_id FROM notifications 
                WHERE notification_type = 'expiry_warning'
                AND sent_at > datetime('now', '-1 days')  -- Don't repeat warnings more than once per day
            )
            """)
            
            expiry_warnings = cursor.fetchall()
            
            # Send notifications
            for user in expiry_warnings:
                user_id, username, marzban_username, expiry_date, reseller_telegram_id = user
                expiry_datetime = datetime.fromisoformat(expiry_date)
                days_left = (expiry_datetime - datetime.now()).days
                
                if self.bot:
                    # Notify reseller
                    await self.bot.send_message(
                        chat_id=reseller_telegram_id,
                        text=f"⚠️ *هشدار انقضای کاربر*\n\n"
                             f"کاربر: `{username}`\n"
                             f"زمان باقی‌مانده: *{days_left} روز*\n"
                             f"تاریخ انقضا: {expiry_datetime.strftime('%Y-%m-%d')}\n\n"
                             f"لطفاً اقدامات لازم را انجام دهید.",
                        parse_mode='Markdown'
                    )
                
                # Log notification
                cursor.execute("""
                INSERT INTO notifications (user_id, notification_type, sent_at)
                VALUES (?, ?, ?)
                """, (user_id, 'expiry_warning', datetime.now().isoformat()))
            
            conn.commit()
            
        except Exception as e:
            logger.error(f"خطا در بررسی و ارسال اعلان‌ها: {str(e)}")
        finally:
            conn.close()