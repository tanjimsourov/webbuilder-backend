"""
Create demo account for SMC Web Builder
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth.models import User
from builder.models import Site, Workspace, WorkspaceMembership

# Create demo user
try:
    user = User.objects.get(username='demo')
    print(f"User 'demo' already exists")
except User.DoesNotExist:
    user = User.objects.create_user(
        username='demo',
        email='demo@smartmediacontrol.com',
        password='demo123',
        first_name='Demo',
        last_name='User'
    )
    print(f"✓ Created user: {user.username} (email: {user.email}, password: demo123)")

# Create workspace
try:
    workspace = Workspace.objects.get(name='Smart Media Control Demo')
except Workspace.DoesNotExist:
    workspace = Workspace.objects.create(
        name='Smart Media Control Demo',
        owner=user
    )
    print(f"✓ Created workspace: {workspace.name}")

# Create workspace membership
try:
    membership = WorkspaceMembership.objects.get(workspace=workspace, user=user)
    print(f"Membership already exists")
except WorkspaceMembership.DoesNotExist:
    membership = WorkspaceMembership.objects.create(
        workspace=workspace,
        user=user,
        role='owner'
    )
    print(f"✓ Created workspace membership: {user.username} as {membership.role}")

# Create demo site
try:
    site = Site.objects.get(name='Smart Media Control')
except Site.DoesNotExist:
    site = Site.objects.create(
        name='Smart Media Control',
        workspace=workspace,
        title='Smart Media Control - Digital Signage Solutions',
        description='SMC is the only platform that runs Digital Signage and music services directly on each screen on its SoC, such as Hisense, LG, Samsung, Philips and Viewsonic.',
        is_published=True
    )
    print(f"✓ Created site: {site.name}")

print("\n" + "="*60)
print("DEMO ACCOUNT CREATED SUCCESSFULLY")
print("="*60)
print(f"Username: demo")
print(f"Email: demo@smartmediacontrol.com")
print(f"Password: demo123")
print(f"Workspace: {workspace.name}")
print(f"Site: {site.name}")
print("="*60)
