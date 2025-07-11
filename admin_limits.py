import sqlite3
from datetime import datetime, timedelta
import json
import logging

logger = logging.getLogger(__name__)

class AdminLimitsManager:
    def __init__(self, db_path='marzban_bot.db'):
        self.db_path = db_path
    
    async def set_admin_limits(self, admin_username, max_bandwidth=None, max_users=None, max_days=None):
        """
        Set resource limits for an admin
        
        :param admin_username: Marzban admin username
        :param max_bandwidth: Maximum bandwidth in GB
        :param max_users: Maximum number of users
        :param max_days: Maximum active days
        :return: (success, message)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Check if admin exists
            cursor.execute("SELECT admin_id FROM marzban_admins WHERE marzban_username = ?", (admin_username,))
            admin = cursor.fetchone()
            
            if not admin:
                return False, "ادمین مورد نظر یافت نشد"
            
            # Get current limits
            cursor.execute("""
            SELECT limits FROM marzban_admins WHERE marzban_username = ?
            """, (admin_username,))
            
            result = cursor.fetchone()
            current_limits = json.loads(result[0]) if result and result[0] else {}
            
            # Update limits
            if max_bandwidth is not None:
                current_limits['max_bandwidth_gb'] = max_bandwidth
            
            if max_users is not None:
                current_limits['max_users'] = max_users
            
            if max_days is not None:
                current_limits['max_days'] = max_days
                
            # Set expiry date if max_days is provided
            if max_days is not None:
                current_limits['expiry_date'] = (datetime.now() + timedelta(days=max_days)).isoformat()
            
            # Update the database
            cursor.execute("""
            UPDATE marzban_admins SET limits = ? WHERE marzban_username = ?
            """, (json.dumps(current_limits), admin_username))
            
            conn.commit()
            return True, "محدودیت‌های ادمین با موفقیت به‌روزرسانی شد"
            
        except Exception as e:
            logger.error(f"خطا در تنظیم محدودیت‌های ادمین: {str(e)}")
            return False, f"خطا در تنظیم محدودیت‌های ادمین: {str(e)}"
        finally:
            conn.close()
    
    async def get_admin_limits(self, admin_username):
        """
        Get resource limits for an admin
        
        :param admin_username: Marzban admin username
        :return: (success, limits_dict or error_message)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
            SELECT limits FROM marzban_admins WHERE marzban_username = ?
            """, (admin_username,))
            
            result = cursor.fetchone()
            
            if not result:
                return False, "ادمین مورد نظر یافت نشد"
                
            limits = json.loads(result[0]) if result[0] else {}
            
            # Add default values if not set
            default_limits = {
                'max_bandwidth_gb': 0,  # 0 means unlimited
                'max_users': 0,         # 0 means unlimited
                'max_days': 0,          # 0 means unlimited
                'used_bandwidth_gb': 0,
                'created_users': 0,
                'expiry_date': None
            }
            
            # Merge with defaults
            for key, value in default_limits.items():
                if key not in limits:
                    limits[key] = value
            
            return True, limits
            
        except Exception as e:
            logger.error(f"خطا در دریافت محدودیت‌های ادمین: {str(e)}")
            return False, f"خطا در دریافت محدودیت‌های ادمین: {str(e)}"
        finally:
            conn.close()
    
    async def update_admin_usage(self, admin_username, bandwidth_used=None, users_created=None):
        """
        Update usage statistics for an admin
        
        :param admin_username: Marzban admin username
        :param bandwidth_used: Additional bandwidth used in GB
        :param users_created: Additional users created
        :return: (success, message)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Get current limits
            success, limits = await self.get_admin_limits(admin_username)
            
            if not success:
                return False, limits  # Error message
            
            # Update usage
            if bandwidth_used is not None:
                limits['used_bandwidth_gb'] = limits.get('used_bandwidth_gb', 0) + bandwidth_used
            
            if users_created is not None:
                limits['created_users'] = limits.get('created_users', 0) + users_created
            
            # Update the database
            cursor.execute("""
            UPDATE marzban_admins SET limits = ? WHERE marzban_username = ?
            """, (json.dumps(limits), admin_username))
            
            conn.commit()
            return True, "آمار مصرف ادمین با موفقیت به‌روزرسانی شد"
            
        except Exception as e:
            logger.error(f"خطا در به‌روزرسانی آمار مصرف ادمین: {str(e)}")
            return False, f"خطا در به‌روزرسانی آمار مصرف ادمین: {str(e)}"
        finally:
            conn.close()
    
    async def check_admin_limits(self, admin_username):
        """
        Check if an admin has reached any of their limits
        
        :param admin_username: Marzban admin username
        :return: (is_limited, limit_messages)
        """
        success, limits = await self.get_admin_limits(admin_username)
        
        if not success:
            return True, [limits]  # Error message
        
        limit_messages = []
        is_limited = False
        
        # Check bandwidth limit
        if limits.get('max_bandwidth_gb', 0) > 0:
            if limits.get('used_bandwidth_gb', 0) >= limits.get('max_bandwidth_gb', 0):
                is_limited = True
                limit_messages.append(f"محدودیت حجم مصرفی ({limits['max_bandwidth_gb']} گیگابایت) به پایان رسیده است")
        
        # Check user limit
        if limits.get('max_users', 0) > 0:
            if limits.get('created_users', 0) >= limits.get('max_users', 0):
                is_limited = True
                limit_messages.append(f"محدودیت تعداد کاربران ({limits['max_users']} کاربر) به پایان رسیده است")
        
        # Check expiry date
        if limits.get('expiry_date'):
            expiry_date = datetime.fromisoformat(limits['expiry_date'])
            if datetime.now() > expiry_date:
                is_limited = True
                limit_messages.append(f"مدت زمان استفاده در تاریخ {expiry_date.strftime('%Y-%m-%d')} به پایان رسیده است")
        
        return is_limited, limit_messages