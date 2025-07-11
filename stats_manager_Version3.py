import sqlite3
import json
import logging
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import io
import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

class StatsManager:
    def __init__(self, db_path='marzban_bot.db', marzban_api=None):
        self.db_path = db_path
        self.marzban_api = marzban_api
    
    async def get_system_stats(self):
        """
        Get overall system statistics
        
        :return: (success, stats_dict or error_message)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Get total admins
            cursor.execute("SELECT COUNT(*) FROM marzban_admins")
            total_admins = cursor.fetchone()[0]
            
            # Get total resellers
            cursor.execute("SELECT COUNT(*) FROM resellers")
            total_resellers = cursor.fetchone()[0]
            
            # Get total users (this requires integration with Marzban API)
            total_users = 0
            total_bandwidth_gb = 0
            total_bandwidth_used_gb = 0
            
            if self.marzban_api:
                success, users = await self.marzban_api.get_all_users()
                if success:
                    total_users = len(users)
                    for user in users:
                        total_bandwidth_gb += user.get('data_limit', 0) / (1024**3)
                        total_bandwidth_used_gb += user.get('used_traffic', 0) / (1024**3)
            
            # Get recent activity
            cursor.execute("""
            SELECT action, username, created_at FROM activity_log 
            ORDER BY created_at DESC LIMIT 10
            """)
            
            recent_activity = []
            for row in cursor.fetchall():
                recent_activity.append({
                    'action': row[0],
                    'username': row[1],
                    'timestamp': row[2]
                })
            
            stats = {
                'total_admins': total_admins,
                'total_resellers': total_resellers,
                'total_users': total_users,
                'total_bandwidth_gb': round(total_bandwidth_gb, 2),
                'total_bandwidth_used_gb': round(total_bandwidth_used_gb, 2),
                'bandwidth_usage_percent': round((total_bandwidth_used_gb / total_bandwidth_gb) * 100, 2) if total_bandwidth_gb > 0 else 0,
                'recent_activity': recent_activity
            }
            
            return True, stats
            
        except Exception as e:
            logger.error(f"خطا در دریافت آمار سیستم: {str(e)}")
            return False, f"خطا در دریافت آمار سیستم: {str(e)}"
        finally:
            conn.close()
    
    async def generate_usage_chart(self, admin_username=None, days=30):
        """
        Generate usage chart for the system or a specific admin
        
        :param admin_username: Optional admin username to filter data
        :param days: Number of days to include in the chart
        :return: (success, chart_path or error_message)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Create a date range
            date_range = [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(days-1, -1, -1)]
            
            # Get daily usage data
            bandwidth_data = []
            users_data = []
            
            for date in date_range:
                # Query for that date's data
                if admin_username:
                    cursor.execute("""
                    SELECT SUM(bandwidth_added), SUM(users_added)
                    FROM usage_log 
                    WHERE admin_username = ? AND DATE(timestamp) = ?
                    """, (admin_username, date))
                else:
                    cursor.execute("""
                    SELECT SUM(bandwidth_added), SUM(users_added)
                    FROM usage_log 
                    WHERE DATE(timestamp) = ?
                    """, (date,))
                
                result = cursor.fetchone()
                bandwidth_data.append(result[0] if result[0] else 0)
                users_data.append(result[1] if result[1] else 0)
            
            # Create the chart
            plt.figure(figsize=(12, 6))
            
            # Bandwidth subplot
            plt.subplot(1, 2, 1)
            plt.plot(date_range, bandwidth_data, 'b-', marker='o')
            plt.title('مصرف روزانه پهنای باند (گیگابایت)')
            plt.xticks(rotation=45)
            plt.tight_layout()
            
            # Users subplot
            plt.subplot(1, 2, 2)
            plt.plot(date_range, users_data, 'r-', marker='o')
            plt.title('کاربران جدید روزانه')
            plt.xticks(rotation=45)
            plt.tight_layout()
            
            # Save the chart
            chart_path = f"charts/usage_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            os.makedirs(os.path.dirname(chart_path), exist_ok=True)
            plt.savefig(chart_path)
            plt.close()
            
            return True, chart_path
            
        except Exception as e:
            logger.error(f"خطا در ایجاد نمودار مصرف: {str(e)}")
            return False, f"خطا در ایجاد نمودار مصرف: {str(e)}"
        finally:
            conn.close()
    
    async def log_activity(self, action, username, details=None):
        """
        Log an activity in the database
        
        :param action: Type of action performed
        :param username: Username related to the action
        :param details: Additional details as a dictionary
        :return: (success, message)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
            INSERT INTO activity_log (action, username, details, created_at)
            VALUES (?, ?, ?, ?)
            """, (
                action,
                username,
                json.dumps(details) if details else None,
                datetime.now().isoformat()
            ))
            
            conn.commit()
            return True, "فعالیت با موفقیت ثبت شد"
            
        except Exception as e:
            logger.error(f"خطا در ثبت فعالیت: {str(e)}")
            return False, f"خطا در ثبت فعالیت: {str(e)}"
        finally:
            conn.close()
    
    async def create_dashboard_menu(self, stats):
        """
        Create a menu for the dashboard
        
        :param stats: Dictionary with system statistics
        :return: (message_text, InlineKeyboardMarkup)
        """
        # Create dashboard text
        dashboard_text = "📊 داشبورد مدیریت\n\n"
        
        dashboard_text += f"👥 تعداد کل ادمین‌ها: {stats.get('total_admins', 0)}\n"
        dashboard_text += f"🏪 تعداد کل نمایندگان: {stats.get('total_resellers', 0)}\n"
        dashboard_text += f"👤 تعداد کل کاربران: {stats.get('total_users', 0)}\n\n"
        
        dashboard_text += f"💾 حجم کل: {stats.get('total_bandwidth_gb', 0)} گیگابایت\n"
        dashboard_text += f"📈 حجم مصرفی: {stats.get('total_bandwidth_used_gb', 0)} گیگابایت\n"
        dashboard_text += f"📊 درصد مصرف: {stats.get('bandwidth_usage_percent', 0)}%\n\n"
        
        dashboard_text += "🔍 فعالیت‌های اخیر:\n"
        for i, activity in enumerate(stats.get('recent_activity', [])[:5], 1):
            dashboard_text += f"  {i}. {activity['username']}: {activity['action']}\n"
        
        # Create dashboard menu
        keyboard = [
            [InlineKeyboardButton("📈 نمودار مصرف", callback_data="usage_chart")],
            [InlineKeyboardButton("📊 گزارش کامل", callback_data="full_report")],
            [
                InlineKeyboardButton("👥 ادمین‌ها", callback_data="view_admins"),
                InlineKeyboardButton("🏪 نمایندگان", callback_data="view_resellers")
            ],
            [InlineKeyboardButton("⚙️ تنظیمات", callback_data="settings")],
            [InlineKeyboardButton("🔄 بروزرسانی", callback_data="refresh_dashboard")],
            [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="back_to_admin")]
        ]
        
        return dashboard_text, InlineKeyboardMarkup(keyboard)