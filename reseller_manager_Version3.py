import sqlite3
from datetime import datetime, timedelta
import json
import logging
import uuid

logger = logging.getLogger(__name__)

class ResellerManager:
    def __init__(self, db_path='marzban_bot.db', marzban_api=None):
        self.db_path = db_path
        self.marzban_api = marzban_api
    
    async def create_reseller(self, telegram_id, username, bandwidth_gb=100, days=30, max_users=10, subscription_url=None):
        """
        Create a new reseller
        
        :param telegram_id: Telegram ID of the reseller
        :param username: Username for the reseller
        :param bandwidth_gb: Bandwidth limit in GB
        :param days: Number of days until expiry
        :param max_users: Maximum number of users allowed
        :param subscription_url: Optional subscription URL for the reseller
        :return: (success, message)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Check if user exists
            cursor.execute("SELECT user_id, role FROM users WHERE telegram_id = ?", (telegram_id,))
            user = cursor.fetchone()
            
            if not user:
                # Create user if doesn't exist
                cursor.execute("""
                INSERT INTO users (telegram_id, username, role, created_at)
                VALUES (?, ?, ?, ?)
                """, (telegram_id, username, "reseller", datetime.now().isoformat()))
                user_id = cursor.lastrowid
            else:
                user_id, role = user
                if role != "reseller":
                    # Update role to reseller
                    cursor.execute("""
                    UPDATE users SET role = ? WHERE telegram_id = ?
                    """, ("reseller", telegram_id))
            
            # Generate a unique marzban username for the reseller
            marzban_username = f"reseller_{username}_{uuid.uuid4().hex[:8]}"
            
            # Calculate expiry date
            expiry_date = (datetime.now() + timedelta(days=days)).isoformat()
            
            # Create Marzban user for the reseller if API is available
            if self.marzban_api:
                success, result = await self.marzban_api.create_user(
                    marzban_username,
                    {
                        "data_limit": bandwidth_gb * 1024**3,  # Convert GB to bytes
                        "expire": expiry_date
                    }
                )
                
                if not success:
                    return False, f"خطا در ایجاد کاربر مرزبان: {result}"
            
            # Create reseller record
            cursor.execute("""
            INSERT INTO resellers
            (telegram_id, username, marzban_username, bandwidth_limit, bandwidth_used,
             expiry_date, max_users, current_users, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                telegram_id,
                username,
                marzban_username,
                bandwidth_gb * 1024**3,  # Convert GB to bytes
                0,  # Initial bandwidth used
                expiry_date,
                max_users,
                0,  # Initial current users
                datetime.now().isoformat()
            ))
            
            conn.commit()
            
            return True, {
                "reseller_id": cursor.lastrowid,
                "telegram_id": telegram_id,
                "username": username,
                "marzban_username": marzban_username,
                "bandwidth_gb": bandwidth_gb,
                "expiry_date": expiry_date,
                "max_users": max_users,
                "subscription_url": subscription_url
            }
            
        except Exception as e:
            logger.error(f"خطا در ایجاد نماینده: {str(e)}")
            return False, f"خطا در ایجاد نماینده: {str(e)}"
        finally:
            conn.close()
    
    async def get_reseller_info(self, telegram_id=None, reseller_id=None, marzban_username=None):
        """
        Get information about a reseller
        
        :param telegram_id: Telegram ID of the reseller
        :param reseller_id: ID of the reseller in database
        :param marzban_username: Marzban username of the reseller
        :return: (success, reseller_info or error_message)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Build query based on provided parameters
            query = "SELECT * FROM resellers WHERE "
            params = []
            
            if telegram_id:
                query += "telegram_id = ?"
                params.append(telegram_id)
            elif reseller_id:
                query += "reseller_id = ?"
                params.append(reseller_id)
            elif marzban_username:
                query += "marzban_username = ?"
                params.append(marzban_username)
            else:
                return False, "پارامتر شناسایی نماینده ارائه نشده است"
            
            cursor.execute(query, params)
            result = cursor.fetchone()
            
            if not result:
                return False, "نماینده مورد نظر یافت نشد"
            
            # Parse result
            reseller_id, telegram_id, username, marzban_username, bandwidth_limit, bandwidth_used, \
                expiry_date, max_users, current_users, created_at = result
            
            # Update data from Marzban if API is available
            if self.marzban_api and marzban_username:
                success, user_data = await self.marzban_api.get_user_info(marzban_username)
                
                if success:
                    # Update bandwidth used from Marzban
                    bandwidth_used = user_data.get('used_traffic', bandwidth_used)
                    
                    # Update database with latest values
                    cursor.execute("""
                    UPDATE resellers SET bandwidth_used = ? WHERE reseller_id = ?
                    """, (bandwidth_used, reseller_id))
                    conn.commit()
            
            # Calculate remaining days
            expiry_datetime = datetime.fromisoformat(expiry_date)
            days_remaining = (expiry_datetime - datetime.now()).days
            
            reseller_info = {
                "reseller_id": reseller_id,
                "telegram_id": telegram_id,
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
                "users": {
                    "max": max_users,
                    "current": current_users,
                    "remaining": max(0, max_users - current_users)
                },
                "created_at": created_at
            }
            
            return True, reseller_info
            
        except Exception as e:
            logger.error(f"خطا در دریافت اطلاعات نماینده: {str(e)}")
            return False, f"خطا در دریافت اطلاعات نماینده: {str(e)}"
        finally:
            conn.close()
    
    async def list_resellers(self, page=0, page_size=10):
        """
        Get a list of resellers with pagination
        
        :param page: Page number (0-based)
        :param page_size: Number of items per page
        :return: (success, resellers_list or error_message, total_pages)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Get total count for pagination
            cursor.execute("SELECT COUNT(*) FROM resellers")
            total_count = cursor.fetchone()[0]
            total_pages = (total_count + page_size - 1) // page_size
            
            # Get paginated resellers
            cursor.execute("""
            SELECT reseller_id, telegram_id, username, marzban_username, 
                   bandwidth_limit, bandwidth_used, expiry_date, max_users, current_users
            FROM resellers
            LIMIT ? OFFSET ?
            """, (page_size, page * page_size))
            
            results = cursor.fetchall()
            
            resellers = []
            for result in results:
                reseller_id, telegram_id, username, marzban_username, bandwidth_limit, bandwidth_used, \
                    expiry_date, max_users, current_users = result
                
                # Calculate remaining days
                expiry_datetime = datetime.fromisoformat(expiry_date)
                days_remaining = (expiry_datetime - datetime.now()).days
                
                resellers.append({
                    "reseller_id": reseller_id,
                    "telegram_id": telegram_id,
                    "username": username,
                    "marzban_username": marzban_username,
                    "bandwidth_limit_gb": round(bandwidth_limit / 1024**3, 2),
                    "bandwidth_used_gb": round(bandwidth_used / 1024**3, 2),
                    "bandwidth_percent": round((bandwidth_used / bandwidth_limit) * 100, 2) if bandwidth_limit > 0 else 0,
                    "days_remaining": days_remaining,
                    "max_users": max_users,
                    "current_users": current_users
                })
            
            return True, resellers, total_pages
            
        except Exception as e:
            logger.error(f"خطا در دریافت لیست نمایندگان: {str(e)}")
            return False, f"خطا در دریافت لیست نمایندگان: {str(e)}", 0
        finally:
            conn.close()
    
    async def update_reseller_limits(self, reseller_id=None, telegram_id=None, marzban_username=None, 
                                   add_bandwidth_gb=0, add_days=0, add_users=0):
        """
        Update a reseller's limits by adding to current values
        
        :param reseller_id: ID of the reseller in database
        :param telegram_id: Telegram ID of the reseller
        :param marzban_username: Marzban username of the reseller
        :param add_bandwidth_gb: Additional bandwidth in GB
        :param add_days: Additional days
        :param add_users: Additional users
        :return: (success, message)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Get reseller info
            success, reseller = await self.get_reseller_info(
                telegram_id=telegram_id, 
                reseller_id=reseller_id,
                marzban_username=marzban_username
            )
            
            if not success:
                return False, reseller  # Error message
            
            # Calculate new values
            new_bandwidth = reseller["bandwidth"]["limit_bytes"] + (add_bandwidth_gb * 1024**3)
            
            expiry_datetime = datetime.fromisoformat(reseller["subscription"]["expiry_date"])
            new_expiry = (expiry_datetime + timedelta(days=add_days)).isoformat()
            
            new_max_users = reseller["users"]["max"] + add_users
            
            # Update Marzban if API available
            if self.marzban_api:
                success, result = await self.marzban_api.update_user(
                    reseller["marzban_username"],
                    {
                        "data_limit": new_bandwidth,
                        "expire": new_expiry
                    }
                )
                
                if not success:
                    return False, f"خطا در بروزرسانی کاربر مرزبان: {result}"
            
            # Update database
            cursor.execute("""
            UPDATE resellers 
            SET bandwidth_limit = ?, expiry_date = ?, max_users = ?
            WHERE reseller_id = ?
            """, (new_bandwidth, new_expiry, new_max_users, reseller["reseller_id"]))
            
            conn.commit()
            
            # Create response message
            update_message = "🔄 نماینده با موفقیت بروزرسانی شد:\n\n"
            
            if add_bandwidth_gb > 0:
                update_message += f"➕ {add_bandwidth_gb} گیگابایت به حجم اضافه شد\n"
            
            if add_days > 0:
                update_message += f"➕ {add_days} روز به مدت زمان اضافه شد\n"
            
            if add_users > 0:
                update_message += f"➕ {add_users} کاربر به ظرفیت اضافه شد\n"
            
            return True, update_message
            
        except Exception as e:
            logger.error(f"خطا در بروزرسانی محدودیت‌های نماینده: {str(e)}")
            return False, f"خطا در بروزرسانی محدودیت‌های نماینده: {str(e)}"
        finally:
            conn.close()