import sqlite3
import json
import logging
from datetime import datetime, timedelta
import io
import asyncio
from telegram import InputFile

logger = logging.getLogger(__name__)

class ReportingSystem:
    def __init__(self, db_path='marzban_bot.db', bot=None):
        self.db_path = db_path
        self.bot = bot
    
    async def generate_admin_report(self, admin_username):
        """
        Generate a detailed report for an admin
        
        :param admin_username: Marzban admin username
        :return: (success, report_text or error_message)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Get admin info
            cursor.execute("""
            SELECT a.marzban_username, a.limits, u.telegram_id
            FROM marzban_admins a
            JOIN users u ON a.telegram_id = u.telegram_id
            WHERE a.marzban_username = ?
            """, (admin_username,))
            
            result = cursor.fetchone()
            
            if not result:
                return False, "ادمین مورد نظر یافت نشد"
            
            username, limits_json, telegram_id = result
            limits = json.loads(limits_json) if limits_json else {}
            
            # Get user activity
            cursor.execute("""
            SELECT action, details, created_at
            FROM activity_log
            WHERE username = ?
            ORDER BY created_at DESC
            LIMIT 50
            """, (admin_username,))
            
            activities = cursor.fetchall()
            
            # Create report
            report = f"📊 گزارش ادمین: {username}\n\n"
            
            # Add limits info
            report += "🔹 محدودیت‌ها:\n"
            report += f"  - حداکثر پهنای باند: {limits.get('max_bandwidth_gb', 'نامحدود')} گیگابایت\n"
            report += f"  - حداکثر کاربران: {limits.get('max_users', 'نامحدود')}\n"
            report += f"  - مدت زمان: {limits.get('max_days', 'نامحدود')} روز\n\n"
            
            # Add usage info
            report += "🔹 مصرف:\n"
            report += f"  - پهنای باند مصرف شده: {limits.get('used_bandwidth_gb', 0)} گیگابایت\n"
            report += f"  - کاربران ایجاد شده: {limits.get('created_users', 0)}\n"
            
            # Add expiry info
            if limits.get('expiry_date'):
                expiry_date = datetime.fromisoformat(limits['expiry_date'])
                days_left = (expiry_date - datetime.now()).days
                report += f"  - تاریخ انقضا: {expiry_date.strftime('%Y-%m-%d')} ({days_left} روز باقی‌مانده)\n\n"
            else:
                report += "  - تاریخ انقضا: نامحدود\n\n"
            
            # Add recent activity
            report += "🔹 فعالیت‌های اخیر:\n"
            if activities:
                for i, (action, details, timestamp) in enumerate(activities[:10], 1):
                    dt = datetime.fromisoformat(timestamp)
                    report += f"  {i}. {action} - {dt.strftime('%Y-%m-%d %H:%M')}\n"
            else:
                report += "  هیچ فعالیتی ثبت نشده است.\n"
            
            return True, report
            
        except Exception as e:
            logger.error(f"خطا در ایجاد گزارش ادمین: {str(e)}")
            return False, f"خطا در ایجاد گزارش ادمین: {str(e)}"
        finally:
            conn.close()
    
    async def generate_system_report(self):
        """
        Generate a system-wide report
        
        :return: (success, report_text or error_message)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Get system stats
            cursor.execute("SELECT COUNT(*) FROM marzban_admins")
            total_admins = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM resellers")
            total_resellers = cursor.fetchone()[0]
            
            cursor.execute("""
            SELECT SUM(JSON_EXTRACT(limits, '$.used_bandwidth_gb')), 
                   SUM(JSON_EXTRACT(limits, '$.created_users'))
            FROM marzban_admins
            """)
            result = cursor.fetchone()
            total_bandwidth_used = result[0] if result[0] else 0
            total_users_created = result[1] if result[1] else 0
            
            # Get recent activities
            cursor.execute("""
            SELECT action, username, created_at
            FROM activity_log
            ORDER BY created_at DESC
            LIMIT 15
            """)
            
            activities = cursor.fetchall()
            
            # Create report
            report = "📊 گزارش وضعیت سیستم\n\n"
            
            # Add summary
            report += "🔹 خلاصه:\n"
            report += f"  - تعداد ادمین‌ها: {total_admins}\n"
            report += f"  - تعداد نمایندگان: {total_resellers}\n"
            report += f"  - کل پهنای باند مصرفی: {total_bandwidth_used} گیگابایت\n"
            report += f"  - کل کاربران ایجاد شده: {total_users_created}\n\n"
            
            # Add top admins by bandwidth
            cursor.execute("""
            SELECT marzban_username, JSON_EXTRACT(limits, '$.used_bandwidth_gb') as used_bw
            FROM marzban_admins
            ORDER BY used_bw DESC
            LIMIT 5
            """)
            
            top_admins_bw = cursor.fetchall()
            
            report += "🔹 ادمین‌های برتر (مصرف پهنای باند):\n"
            for i, (username, bandwidth) in enumerate(top_admins_bw, 1):
                report += f"  {i}. {username}: {bandwidth} گیگابایت\n"
            report += "\n"
            
            # Add top admins by users created
            cursor.execute("""
            SELECT marzban_username, JSON_EXTRACT(limits, '$.created_users') as users
            FROM marzban_admins
            ORDER BY users DESC
            LIMIT 5
            """)
            
            top_admins_users = cursor.fetchall()
            
            report += "🔹 ادمین‌های برتر (ایجاد کاربر):\n"
            for i, (username, users) in enumerate(top_admins_users, 1):
                report += f"  {i}. {username}: {users} کاربر\n"
            report += "\n"
            
            # Add recent activity
            report += "🔹 فعالیت‌های اخیر:\n"
            if activities:
                for i, (action, username, timestamp) in enumerate(activities, 1):
                    dt = datetime.fromisoformat(timestamp)
                    report += f"  {i}. {username}: {action} - {dt.strftime('%Y-%m-%d %H:%M')}\n"
            else:
                report += "  هیچ فعالیتی ثبت نشده است.\n"
            
            return True, report
            
        except Exception as e:
            logger.error(f"خطا در ایجاد گزارش سیستم: {str(e)}")
            return False, f"خطا در ایجاد گزارش سیستم: {str(e)}"
        finally:
            conn.close()
    
    async def send_scheduled_reports(self):
        """
        Send scheduled reports to admins
        
        :return: None
        """
        while True:
            try:
                # Get all super admins
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                cursor.execute("""
                SELECT telegram_id FROM users
                WHERE role = 'superadmin'
                """)
                
                super_admins = [row[0] for row in cursor.fetchall()]
                conn.close()
                
                # Generate and send system report
                success, report = await self.generate_system_report()
                
                if success and self.bot:
                    for admin_id in super_admins:
                        try:
                            await self.bot.send_message(
                                chat_id=admin_id,
                                text=f"🔔 گزارش دوره‌ای سیستم\n\n{report}"
                            )
                        except Exception as e:
                            logger.error(f"خطا در ارسال گزارش به ادمین {admin_id}: {str(e)}")
                
                # Wait for 24 hours before sending the next report
                await asyncio.sleep(86400)  # 24 hours
                
            except Exception as e:
                logger.error(f"خطا در سیستم گزارش‌دهی خودکار: {str(e)}")
                await asyncio.sleep(3600)  # Retry after 1 hour on error