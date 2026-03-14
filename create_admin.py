#!/usr/bin/env python
"""
Quick script to create a platform admin superuser.
Run with: python create_admin.py
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()

username = "admin"
email = "admin@platform.local"
password = "admin123"

# Delete existing admin if exists
User.objects.filter(username=username).delete()

# Create new superuser
user = User.objects.create_superuser(
    username=username,
    email=email,
    password=password
)

print(f"✅ Superuser created successfully!")
print(f"   Username: {username}")
print(f"   Password: {password}")
print(f"   Email: {email}")
print(f"\n🔐 Use these credentials to login to the admin portal at http://localhost:3001")
