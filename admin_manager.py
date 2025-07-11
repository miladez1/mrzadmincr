import subprocess
import logging
import os
import json

logger = logging.getLogger(__name__)

class MarzbanAdminManager:
    def __init__(self, docker_name="marzban"):
        """
        Initialize the admin manager for Marzban panel
        
        :param docker_name: Name of the Docker container running Marzban
        """
        self.docker_name = docker_name
        
    def _execute_command(self, command):
        """
        Execute a Marzban CLI command through Docker
        
        :param command: The command to execute (without prefix)
        :return: (success, output or error)
        """
        try:
            full_command = f"docker exec {self.docker_name} marzban-cli {command}"
            result = subprocess.run(
                full_command, 
                shell=True, 
                capture_output=True, 
                text=True
            )
            
            if result.returncode == 0:
                return True, result.stdout.strip()
            else:
                return False, result.stderr.strip()
                
        except Exception as e:
            logger.error(f"خطا در اجرای دستور: {str(e)}")
            return False, f"خطا در اجرای دستور: {str(e)}"
    
    async def create_admin(self, username, password, sudo=False):
        """
        Create a new admin user in Marzban panel
        
        :param username: Admin username
        :param password: Admin password
        :param sudo: Whether the admin has sudo privileges
        :return: (success, message)
        """
        sudo_flag = "--sudo" if sudo else ""
        cmd = f"admin create --username {username} --password {password} {sudo_flag}"
        
        success, output = self._execute_command(cmd)
        
        if success:
            return True, f"ادمین '{username}' با موفقیت ایجاد شد"
        else:
            return False, f"خطا در ایجاد ادمین: {output}"

    async def list_admins(self):
        """
        List all admins in Marzban panel
        
        :return: (success, list of admins or error message)
        """
        cmd = "admin list"
        
        success, output = self._execute_command(cmd)
        
        if success:
            # Parse the output to get admin list
            lines = output.strip().split('\n')
            # Remove header line if exists
            if lines and "USERNAME" in lines[0]:
                lines = lines[1:]
            
            admins = []
            for line in lines:
                if line.strip():
                    # Parse fields from each line
                    parts = line.split()
                    if parts:
                        admins.append({
                            "username": parts[0],
                            "is_sudo": "Yes" in line or "True" in line
                        })
            
            return True, admins
        else:
            return False, f"خطا در دریافت لیست ادمین‌ها: {output}"

    async def delete_admin(self, username):
        """
        Delete an admin from Marzban panel
        
        :param username: Admin username to delete
        :return: (success, message)
        """
        cmd = f"admin delete {username} -y"
        
        success, output = self._execute_command(cmd)
        
        if success:
            return True, f"ادمین '{username}' با موفقیت حذف شد"
        else:
            return False, f"خطا در حذف ادمین: {output}"

    async def update_admin_password(self, username, new_password):
        """
        Update an admin's password
        
        :param username: Admin username
        :param new_password: New password for the admin
        :return: (success, message)
        """
        cmd = f"admin update {username} --password {new_password}"
        
        success, output = self._execute_command(cmd)
        
        if success:
            return True, f"رمز عبور ادمین '{username}' با موفقیت بروزرسانی شد"
        else:
            return False, f"خطا در بروزرسانی رمز عبور ادمین: {output}"

    async def update_admin_permissions(self, username, permissions=None):
        """
        Update an admin's permissions
        
        :param username: Admin username
        :param permissions: List of permission keys (None or empty list for no permissions)
        :return: (success, message)
        """
        permissions_str = " ".join(permissions) if permissions else ""
        cmd = f"admin update {username} --permissions {permissions_str}"
        
        success, output = self._execute_command(cmd)
        
        if success:
            return True, f"دسترسی‌های ادمین '{username}' با موفقیت بروزرسانی شد"
        else:
            return False, f"خطا در بروزرسانی دسترسی‌های ادمین: {output}"
            
    async def get_all_permissions(self):
        """
        Returns a list of all available permissions
        
        :return: List of permission objects with key and description
        """
        permissions = [
            {"key": "dashboard_read", "description": "مشاهده داشبورد و آمار کلی"},
            {"key": "user_create", "description": "ایجاد کاربران جدید"},
            {"key": "user_read", "description": "مشاهده لیست و جزئیات کاربران"},
            {"key": "user_update", "description": "ویرایش کاربران (تمدید اشتراک، تغییر ترافیک و...)"},
            {"key": "user_delete", "description": "حذف کاربران"},
            {"key": "user_reset", "description": "ریست کردن مصرف ترافیک کاربران"},
            {"key": "node_create", "description": "اضافه کردن سرورهای جدید (نودها)"},
            {"key": "node_read", "description": "مشاهده لیست سرورها (نودها)"},
            {"key": "node_update", "description": "ویرایش تنظیمات سرورها (نودها)"},
            {"key": "node_delete", "description": "حذف سرورها (نودها)"},
            {"key": "template_create", "description": "ایجاد قالب‌های کاربری جدید"},
            {"key": "template_read", "description": "مشاهده قالب‌های کاربری"},
            {"key": "template_update", "description": "ویرایش قالب‌های کاربری"},
            {"key": "template_delete", "description": "حذف قالب‌های کاربری"},
            {"key": "admin_create", "description": "ایجاد کاربران ادمین"},
            {"key": "admin_read", "description": "مشاهده لیست ادمین‌ها"},
            {"key": "admin_update", "description": "ویرایش ادمین‌ها"},
            {"key": "admin_delete", "description": "حذف ادمین‌ها"},
            {"key": "settings_read", "description": "مشاهده تنظیمات اصلی پنل"},
            {"key": "settings_write", "description": "ویرایش تنظیمات اصلی پنل"}
        ]
        return permissions
        
    async def get_permission_presets(self):
        """
        Returns predefined permission sets for common roles
        
        :return: Dictionary of preset roles with their permissions
        """
        presets = {
            "مدیر کامل": [
                "dashboard_read", "user_create", "user_read", "user_update", 
                "user_delete", "user_reset", "admin_read", "admin_update",
                "settings_read"
            ],
            "نماینده": [
                "dashboard_read", "user_create", "user_read", "user_update", 
                "user_delete", "user_reset"
            ],
            "فقط مشاهده": [
                "dashboard_read", "user_read"
            ]
        }
        return presets