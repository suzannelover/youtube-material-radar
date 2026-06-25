"""
scripts/add_user.py
管理员命令行工具：添加登录用户
用法：python scripts/add_user.py <用户名> <密码>
示例：python scripts/add_user.py admin mypassword123
"""

import sys
import os

# 确保能从项目根目录运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.user import create_user, init_db


def main():
    if len(sys.argv) != 3:
        print("用法：python scripts/add_user.py <用户名> <密码>")
        print("示例：python scripts/add_user.py admin mypassword123")
        sys.exit(1)

    username = sys.argv[1].strip()
    password = sys.argv[2]

    if not username or len(password) < 4:
        print("错误：用户名不能为空，密码至少 4 位")
        sys.exit(1)

    init_db()
    try:
        user = create_user(username, password)
        print(f"✓ 用户 '{username}' 创建成功 (ID: {user.id})")
    except ValueError as e:
        print(f"✗ {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
