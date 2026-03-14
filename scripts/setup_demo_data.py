#!/usr/bin/env python
"""
Demo Data Setup Script

Creates admin account, user account, Husmerk website (similar to jadeglobal.com),
e-commerce store, blog posts, forms, and other features for testing.
"""

import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
from builder.models import (
    Site, Page, Post, PostCategory, PostTag, Product, ProductCategory,
    ProductVariant, Form, MediaFolder, NavigationMenu,
    ShippingZone, ShippingRate, TaxRate, DiscountCode, Workspace, WorkspaceMembership
)

User = get_user_model()


def create_admin():
    """Create admin superuser."""
    if User.objects.filter(username='admin').exists():
        print("Admin user already exists")
        return User.objects.get(username='admin')
    
    admin = User.objects.create_superuser(
        username='admin',
        email='admin@husmerk.com',
        password='Admin123!@#'
    )
    print(f"✓ Created admin user: admin / Admin123!@#")
    return admin


def create_user():
    """Create regular user."""
    if User.objects.filter(username='testuser').exists():
        print("Test user already exists")
        return User.objects.get(username='testuser')
    
    user = User.objects.create_user(
        username='testuser',
        email='user@husmerk.com',
        password='User123!@#'
    )
    print(f"✓ Created test user: testuser / User123!@#")
    return user


def create_workspace(admin):
    """Create workspace for the site."""
    # Try to get existing workspace first
    try:
        workspace = Workspace.objects.get(slug='husmerk-digital')
        print("Workspace already exists")
        return workspace
    except Workspace.DoesNotExist:
        pass
    
    workspace = Workspace.objects.create(
        name='Husmerk Digital',
        slug='husmerk-digital',
        owner=admin,
        description='Husmerk Digital Solutions - Enterprise Technology Consulting'
    )
    WorkspaceMembership.objects.get_or_create(
        workspace=workspace,
        user=admin,
        defaults={'role': 'owner'}
    )
    print(f"✓ Created workspace: Husmerk Digital")
    return workspace


def create_husmerk_site(admin, workspace):
    """Create Husmerk website similar to jadeglobal.com."""
    site, created = Site.objects.get_or_create(
        slug='husmerk',
        defaults={
            'name': 'Husmerk',
            'workspace': workspace,
            'tagline': 'Enterprise Technology Solutions',
            'description': 'Husmerk delivers innovative technology consulting, digital transformation, and enterprise solutions to help businesses thrive in the digital age.',
            'theme': {
                'primary_color': '#0066CC',
                'secondary_color': '#003366',
                'font_family': 'Inter, sans-serif',
            },
            'settings': {
                'enable_blog': True,
                'enable_shop': True,
                'enable_comments': True,
            },
        }
    )
    
    if created:
        print(f"✓ Created site: Husmerk")
    else:
        print("Site already exists")
    
    return site


def create_pages(site):
    """Create 5+ pages similar to jadeglobal.com structure."""
    
    pages_data = [
        {
            'title': 'Home',
            'slug': 'home',
            'path': '/',
            'is_homepage': True,
            'html': '''
<section class="hero" style="background: linear-gradient(135deg, #0066CC 0%, #003366 100%); color: white; padding: 100px 20px; text-align: center;">
    <div class="container" style="max-width: 1200px; margin: 0 auto;">
        <h1 style="font-size: 3.5rem; margin-bottom: 20px;">Transform Your Business with Technology</h1>
        <p style="font-size: 1.5rem; margin-bottom: 40px; opacity: 0.9;">Husmerk delivers innovative enterprise solutions that drive growth and efficiency</p>
        <a href="/services" style="background: white; color: #0066CC; padding: 15px 40px; border-radius: 5px; text-decoration: none; font-weight: bold; display: inline-block;">Explore Our Services</a>
    </div>
</section>

<section class="services-preview" style="padding: 80px 20px; background: #f8f9fa;">
    <div class="container" style="max-width: 1200px; margin: 0 auto;">
        <h2 style="text-align: center; font-size: 2.5rem; margin-bottom: 50px; color: #003366;">Our Expertise</h2>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 30px;">
            <div style="background: white; padding: 40px; border-radius: 10px; box-shadow: 0 5px 20px rgba(0,0,0,0.1);">
                <h3 style="color: #0066CC; margin-bottom: 15px;">Digital Transformation</h3>
                <p>Modernize your business with cutting-edge digital solutions that enhance customer experience and operational efficiency.</p>
            </div>
            <div style="background: white; padding: 40px; border-radius: 10px; box-shadow: 0 5px 20px rgba(0,0,0,0.1);">
                <h3 style="color: #0066CC; margin-bottom: 15px;">Cloud Solutions</h3>
                <p>Leverage the power of cloud computing with our expert migration, optimization, and management services.</p>
            </div>
            <div style="background: white; padding: 40px; border-radius: 10px; box-shadow: 0 5px 20px rgba(0,0,0,0.1);">
                <h3 style="color: #0066CC; margin-bottom: 15px;">Data Analytics</h3>
                <p>Turn your data into actionable insights with our advanced analytics and business intelligence solutions.</p>
            </div>
        </div>
    </div>
</section>

<section class="stats" style="padding: 60px 20px; background: #003366; color: white;">
    <div class="container" style="max-width: 1200px; margin: 0 auto; display: grid; grid-template-columns: repeat(4, 1fr); gap: 30px; text-align: center;">
        <div>
            <div style="font-size: 3rem; font-weight: bold;">500+</div>
            <div style="opacity: 0.8;">Projects Delivered</div>
        </div>
        <div>
            <div style="font-size: 3rem; font-weight: bold;">150+</div>
            <div style="opacity: 0.8;">Enterprise Clients</div>
        </div>
        <div>
            <div style="font-size: 3rem; font-weight: bold;">15+</div>
            <div style="opacity: 0.8;">Years Experience</div>
        </div>
        <div>
            <div style="font-size: 3rem; font-weight: bold;">98%</div>
            <div style="opacity: 0.8;">Client Satisfaction</div>
        </div>
    </div>
</section>

<section class="cta" style="padding: 80px 20px; text-align: center;">
    <h2 style="font-size: 2.5rem; margin-bottom: 20px; color: #003366;">Ready to Transform Your Business?</h2>
    <p style="font-size: 1.2rem; margin-bottom: 30px; color: #666;">Let's discuss how Husmerk can help you achieve your technology goals.</p>
    <a href="/contact" style="background: #0066CC; color: white; padding: 15px 40px; border-radius: 5px; text-decoration: none; font-weight: bold; display: inline-block;">Get Started Today</a>
</section>
''',
            'meta_title': 'Husmerk - Enterprise Technology Solutions',
            'meta_description': 'Husmerk delivers innovative technology consulting, digital transformation, and enterprise solutions to help businesses thrive.',
        },
        {
            'title': 'Services',
            'slug': 'services',
            'path': '/services',
            'html': '''
<section class="page-header" style="background: linear-gradient(135deg, #0066CC 0%, #003366 100%); color: white; padding: 80px 20px; text-align: center;">
    <h1 style="font-size: 3rem; margin-bottom: 15px;">Our Services</h1>
    <p style="font-size: 1.3rem; opacity: 0.9;">Comprehensive technology solutions for modern enterprises</p>
</section>

<section class="services-list" style="padding: 80px 20px;">
    <div class="container" style="max-width: 1200px; margin: 0 auto;">
        
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 60px; margin-bottom: 60px; align-items: center;">
            <div>
                <h2 style="color: #003366; font-size: 2rem; margin-bottom: 20px;">Digital Transformation</h2>
                <p style="color: #666; line-height: 1.8; margin-bottom: 20px;">We help organizations reimagine their business processes, customer experiences, and operational models through strategic technology adoption.</p>
                <ul style="color: #666; line-height: 2;">
                    <li>Business Process Automation</li>
                    <li>Customer Experience Optimization</li>
                    <li>Legacy System Modernization</li>
                    <li>Digital Strategy Consulting</li>
                </ul>
            </div>
            <div style="background: #f8f9fa; padding: 40px; border-radius: 10px;">
                <img src="https://images.unsplash.com/photo-1551434678-e076c223a692?w=500" alt="Digital Transformation" style="width: 100%; border-radius: 5px;">
            </div>
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 60px; margin-bottom: 60px; align-items: center;">
            <div style="background: #f8f9fa; padding: 40px; border-radius: 10px;">
                <img src="https://images.unsplash.com/photo-1544197150-b99a580bb7a8?w=500" alt="Cloud Solutions" style="width: 100%; border-radius: 5px;">
            </div>
            <div>
                <h2 style="color: #003366; font-size: 2rem; margin-bottom: 20px;">Cloud Solutions</h2>
                <p style="color: #666; line-height: 1.8; margin-bottom: 20px;">Accelerate your cloud journey with our comprehensive cloud services spanning strategy, migration, and ongoing management.</p>
                <ul style="color: #666; line-height: 2;">
                    <li>Cloud Migration & Strategy</li>
                    <li>Multi-Cloud Architecture</li>
                    <li>Cloud Security & Compliance</li>
                    <li>Managed Cloud Services</li>
                </ul>
            </div>
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 60px; margin-bottom: 60px; align-items: center;">
            <div>
                <h2 style="color: #003366; font-size: 2rem; margin-bottom: 20px;">Data & Analytics</h2>
                <p style="color: #666; line-height: 1.8; margin-bottom: 20px;">Unlock the power of your data with our advanced analytics solutions that drive informed decision-making.</p>
                <ul style="color: #666; line-height: 2;">
                    <li>Business Intelligence</li>
                    <li>Predictive Analytics</li>
                    <li>Data Warehousing</li>
                    <li>AI & Machine Learning</li>
                </ul>
            </div>
            <div style="background: #f8f9fa; padding: 40px; border-radius: 10px;">
                <img src="https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=500" alt="Data Analytics" style="width: 100%; border-radius: 5px;">
            </div>
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 60px; align-items: center;">
            <div style="background: #f8f9fa; padding: 40px; border-radius: 10px;">
                <img src="https://images.unsplash.com/photo-1563986768609-322da13575f3?w=500" alt="Enterprise Applications" style="width: 100%; border-radius: 5px;">
            </div>
            <div>
                <h2 style="color: #003366; font-size: 2rem; margin-bottom: 20px;">Enterprise Applications</h2>
                <p style="color: #666; line-height: 1.8; margin-bottom: 20px;">Implement and optimize enterprise applications that streamline operations and enhance productivity.</p>
                <ul style="color: #666; line-height: 2;">
                    <li>ERP Implementation</li>
                    <li>CRM Solutions</li>
                    <li>Custom Application Development</li>
                    <li>System Integration</li>
                </ul>
            </div>
        </div>

    </div>
</section>
''',
            'meta_title': 'Services - Husmerk Technology Solutions',
            'meta_description': 'Explore our comprehensive technology services including digital transformation, cloud solutions, data analytics, and enterprise applications.',
        },
        {
            'title': 'About Us',
            'slug': 'about',
            'path': '/about',
            'html': '''
<section class="page-header" style="background: linear-gradient(135deg, #0066CC 0%, #003366 100%); color: white; padding: 80px 20px; text-align: center;">
    <h1 style="font-size: 3rem; margin-bottom: 15px;">About Husmerk</h1>
    <p style="font-size: 1.3rem; opacity: 0.9;">Your trusted partner in digital innovation</p>
</section>

<section class="about-intro" style="padding: 80px 20px;">
    <div class="container" style="max-width: 1000px; margin: 0 auto; text-align: center;">
        <h2 style="color: #003366; font-size: 2.5rem; margin-bottom: 30px;">Who We Are</h2>
        <p style="font-size: 1.2rem; color: #666; line-height: 1.8;">Husmerk is a leading technology consulting firm dedicated to helping enterprises navigate the complexities of digital transformation. With over 15 years of experience, we've partnered with Fortune 500 companies and innovative startups alike to deliver solutions that drive real business value.</p>
    </div>
</section>

<section class="values" style="padding: 80px 20px; background: #f8f9fa;">
    <div class="container" style="max-width: 1200px; margin: 0 auto;">
        <h2 style="text-align: center; color: #003366; font-size: 2.5rem; margin-bottom: 50px;">Our Core Values</h2>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 30px;">
            <div style="text-align: center; padding: 30px;">
                <div style="font-size: 3rem; margin-bottom: 15px;">🎯</div>
                <h3 style="color: #003366; margin-bottom: 10px;">Excellence</h3>
                <p style="color: #666;">We strive for excellence in every project, delivering solutions that exceed expectations.</p>
            </div>
            <div style="text-align: center; padding: 30px;">
                <div style="font-size: 3rem; margin-bottom: 15px;">🤝</div>
                <h3 style="color: #003366; margin-bottom: 10px;">Partnership</h3>
                <p style="color: #666;">We build lasting relationships with our clients, becoming true partners in their success.</p>
            </div>
            <div style="text-align: center; padding: 30px;">
                <div style="font-size: 3rem; margin-bottom: 15px;">💡</div>
                <h3 style="color: #003366; margin-bottom: 10px;">Innovation</h3>
                <p style="color: #666;">We embrace new technologies and creative approaches to solve complex challenges.</p>
            </div>
            <div style="text-align: center; padding: 30px;">
                <div style="font-size: 3rem; margin-bottom: 15px;">✅</div>
                <h3 style="color: #003366; margin-bottom: 10px;">Integrity</h3>
                <p style="color: #666;">We operate with transparency and honesty in all our business dealings.</p>
            </div>
        </div>
    </div>
</section>

<section class="team" style="padding: 80px 20px;">
    <div class="container" style="max-width: 1200px; margin: 0 auto;">
        <h2 style="text-align: center; color: #003366; font-size: 2.5rem; margin-bottom: 50px;">Leadership Team</h2>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 40px;">
            <div style="text-align: center;">
                <img src="https://images.unsplash.com/photo-1560250097-0b93528c311a?w=300&h=300&fit=crop" alt="CEO" style="width: 200px; height: 200px; border-radius: 50%; object-fit: cover; margin-bottom: 20px;">
                <h3 style="color: #003366; margin-bottom: 5px;">Michael Chen</h3>
                <p style="color: #0066CC; margin-bottom: 10px;">Chief Executive Officer</p>
                <p style="color: #666; font-size: 0.9rem;">20+ years in enterprise technology leadership</p>
            </div>
            <div style="text-align: center;">
                <img src="https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=300&h=300&fit=crop" alt="CTO" style="width: 200px; height: 200px; border-radius: 50%; object-fit: cover; margin-bottom: 20px;">
                <h3 style="color: #003366; margin-bottom: 5px;">Sarah Johnson</h3>
                <p style="color: #0066CC; margin-bottom: 10px;">Chief Technology Officer</p>
                <p style="color: #666; font-size: 0.9rem;">Former VP of Engineering at Fortune 100</p>
            </div>
            <div style="text-align: center;">
                <img src="https://images.unsplash.com/photo-1472099645785-5658abf4ff4e?w=300&h=300&fit=crop" alt="COO" style="width: 200px; height: 200px; border-radius: 50%; object-fit: cover; margin-bottom: 20px;">
                <h3 style="color: #003366; margin-bottom: 5px;">David Park</h3>
                <p style="color: #0066CC; margin-bottom: 10px;">Chief Operations Officer</p>
                <p style="color: #666; font-size: 0.9rem;">Expert in scaling global operations</p>
            </div>
        </div>
    </div>
</section>
''',
            'meta_title': 'About Us - Husmerk',
            'meta_description': 'Learn about Husmerk, our mission, values, and the experienced team driving digital transformation for enterprises worldwide.',
        },
        {
            'title': 'Industries',
            'slug': 'industries',
            'path': '/industries',
            'html': '''
<section class="page-header" style="background: linear-gradient(135deg, #0066CC 0%, #003366 100%); color: white; padding: 80px 20px; text-align: center;">
    <h1 style="font-size: 3rem; margin-bottom: 15px;">Industries We Serve</h1>
    <p style="font-size: 1.3rem; opacity: 0.9;">Deep expertise across key sectors</p>
</section>

<section class="industries" style="padding: 80px 20px;">
    <div class="container" style="max-width: 1200px; margin: 0 auto;">
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 40px;">
            
            <div style="background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 5px 20px rgba(0,0,0,0.1);">
                <img src="https://images.unsplash.com/photo-1563013544-824ae1b704d3?w=500" alt="Financial Services" style="width: 100%; height: 200px; object-fit: cover;">
                <div style="padding: 30px;">
                    <h3 style="color: #003366; margin-bottom: 15px;">Financial Services</h3>
                    <p style="color: #666; line-height: 1.7;">We help banks, insurance companies, and fintech firms modernize their technology infrastructure, enhance security, and deliver superior customer experiences.</p>
                </div>
            </div>

            <div style="background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 5px 20px rgba(0,0,0,0.1);">
                <img src="https://images.unsplash.com/photo-1576091160399-112ba8d25d1f?w=500" alt="Healthcare" style="width: 100%; height: 200px; object-fit: cover;">
                <div style="padding: 30px;">
                    <h3 style="color: #003366; margin-bottom: 15px;">Healthcare</h3>
                    <p style="color: #666; line-height: 1.7;">Our healthcare solutions enable providers and payers to improve patient outcomes, streamline operations, and maintain regulatory compliance.</p>
                </div>
            </div>

            <div style="background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 5px 20px rgba(0,0,0,0.1);">
                <img src="https://images.unsplash.com/photo-1586528116311-ad8dd3c8310d?w=500" alt="Manufacturing" style="width: 100%; height: 200px; object-fit: cover;">
                <div style="padding: 30px;">
                    <h3 style="color: #003366; margin-bottom: 15px;">Manufacturing</h3>
                    <p style="color: #666; line-height: 1.7;">We drive Industry 4.0 initiatives with IoT, automation, and analytics solutions that optimize production and supply chain operations.</p>
                </div>
            </div>

            <div style="background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 5px 20px rgba(0,0,0,0.1);">
                <img src="https://images.unsplash.com/photo-1556742049-0cfed4f6a45d?w=500" alt="Retail" style="width: 100%; height: 200px; object-fit: cover;">
                <div style="padding: 30px;">
                    <h3 style="color: #003366; margin-bottom: 15px;">Retail & E-commerce</h3>
                    <p style="color: #666; line-height: 1.7;">Our retail solutions help businesses create seamless omnichannel experiences, optimize inventory, and leverage customer data for growth.</p>
                </div>
            </div>

            <div style="background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 5px 20px rgba(0,0,0,0.1);">
                <img src="https://images.unsplash.com/photo-1581091226825-a6a2a5aee158?w=500" alt="Technology" style="width: 100%; height: 200px; object-fit: cover;">
                <div style="padding: 30px;">
                    <h3 style="color: #003366; margin-bottom: 15px;">Technology</h3>
                    <p style="color: #666; line-height: 1.7;">We partner with tech companies to accelerate product development, scale infrastructure, and optimize engineering operations.</p>
                </div>
            </div>

            <div style="background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 5px 20px rgba(0,0,0,0.1);">
                <img src="https://images.unsplash.com/photo-1497366216548-37526070297c?w=500" alt="Professional Services" style="width: 100%; height: 200px; object-fit: cover;">
                <div style="padding: 30px;">
                    <h3 style="color: #003366; margin-bottom: 15px;">Professional Services</h3>
                    <p style="color: #666; line-height: 1.7;">We help consulting firms, law practices, and agencies leverage technology to improve service delivery and client engagement.</p>
                </div>
            </div>

        </div>
    </div>
</section>
''',
            'meta_title': 'Industries - Husmerk',
            'meta_description': 'Husmerk serves financial services, healthcare, manufacturing, retail, technology, and professional services industries with tailored solutions.',
        },
        {
            'title': 'Contact',
            'slug': 'contact',
            'path': '/contact',
            'html': '''
<section class="page-header" style="background: linear-gradient(135deg, #0066CC 0%, #003366 100%); color: white; padding: 80px 20px; text-align: center;">
    <h1 style="font-size: 3rem; margin-bottom: 15px;">Contact Us</h1>
    <p style="font-size: 1.3rem; opacity: 0.9;">Let's start a conversation about your technology needs</p>
</section>

<section class="contact-content" style="padding: 80px 20px;">
    <div class="container" style="max-width: 1200px; margin: 0 auto; display: grid; grid-template-columns: 1fr 1fr; gap: 60px;">
        
        <div>
            <h2 style="color: #003366; font-size: 2rem; margin-bottom: 30px;">Get in Touch</h2>
            <p style="color: #666; line-height: 1.8; margin-bottom: 30px;">Ready to transform your business? Our team of experts is here to help you navigate your digital journey. Fill out the form and we'll get back to you within 24 hours.</p>
            
            <div style="margin-bottom: 25px;">
                <h4 style="color: #003366; margin-bottom: 10px;">📍 Headquarters</h4>
                <p style="color: #666;">123 Innovation Drive, Suite 500<br>San Francisco, CA 94105</p>
            </div>
            
            <div style="margin-bottom: 25px;">
                <h4 style="color: #003366; margin-bottom: 10px;">📧 Email</h4>
                <p style="color: #666;">info@husmerk.com</p>
            </div>
            
            <div style="margin-bottom: 25px;">
                <h4 style="color: #003366; margin-bottom: 10px;">📞 Phone</h4>
                <p style="color: #666;">+1 (555) 123-4567</p>
            </div>
            
            <div>
                <h4 style="color: #003366; margin-bottom: 10px;">🕐 Business Hours</h4>
                <p style="color: #666;">Monday - Friday: 9:00 AM - 6:00 PM PST</p>
            </div>
        </div>
        
        <div style="background: #f8f9fa; padding: 40px; border-radius: 10px;">
            <h3 style="color: #003366; margin-bottom: 25px;">Send us a Message</h3>
            <form>
                <div style="margin-bottom: 20px;">
                    <label style="display: block; color: #003366; margin-bottom: 8px; font-weight: 500;">Full Name *</label>
                    <input type="text" style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 5px; font-size: 1rem;" placeholder="John Smith">
                </div>
                <div style="margin-bottom: 20px;">
                    <label style="display: block; color: #003366; margin-bottom: 8px; font-weight: 500;">Email Address *</label>
                    <input type="email" style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 5px; font-size: 1rem;" placeholder="john@company.com">
                </div>
                <div style="margin-bottom: 20px;">
                    <label style="display: block; color: #003366; margin-bottom: 8px; font-weight: 500;">Company</label>
                    <input type="text" style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 5px; font-size: 1rem;" placeholder="Your Company">
                </div>
                <div style="margin-bottom: 20px;">
                    <label style="display: block; color: #003366; margin-bottom: 8px; font-weight: 500;">How can we help? *</label>
                    <textarea style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 5px; font-size: 1rem; min-height: 120px;" placeholder="Tell us about your project..."></textarea>
                </div>
                <button type="submit" style="background: #0066CC; color: white; padding: 15px 40px; border: none; border-radius: 5px; font-size: 1rem; font-weight: bold; cursor: pointer; width: 100%;">Send Message</button>
            </form>
        </div>
        
    </div>
</section>

<section class="map" style="height: 400px; background: #e0e0e0;">
    <iframe src="https://www.google.com/maps/embed?pb=!1m18!1m12!1m3!1d3153.0977904088!2d-122.39568388468204!3d37.78779997975772!2m3!1f0!2f0!3f0!3m2!1i1024!2i768!4f13.1!3m3!1m2!1s0x8085807abad77c31%3A0x3f10d6c1c3f4e0a0!2sSan%20Francisco%2C%20CA!5e0!3m2!1sen!2sus!4v1234567890" width="100%" height="400" style="border:0;" allowfullscreen="" loading="lazy"></iframe>
</section>
''',
            'meta_title': 'Contact Us - Husmerk',
            'meta_description': 'Contact Husmerk to discuss your technology consulting needs. Our team is ready to help you transform your business.',
        },
        {
            'title': 'Careers',
            'slug': 'careers',
            'path': '/careers',
            'html': '''
<section class="page-header" style="background: linear-gradient(135deg, #0066CC 0%, #003366 100%); color: white; padding: 80px 20px; text-align: center;">
    <h1 style="font-size: 3rem; margin-bottom: 15px;">Join Our Team</h1>
    <p style="font-size: 1.3rem; opacity: 0.9;">Build your career at the forefront of technology innovation</p>
</section>

<section class="careers-intro" style="padding: 80px 20px;">
    <div class="container" style="max-width: 1000px; margin: 0 auto; text-align: center;">
        <h2 style="color: #003366; font-size: 2.5rem; margin-bottom: 30px;">Why Husmerk?</h2>
        <p style="font-size: 1.2rem; color: #666; line-height: 1.8;">At Husmerk, we believe our people are our greatest asset. We offer challenging projects, continuous learning opportunities, and a collaborative culture that celebrates innovation and diversity.</p>
    </div>
</section>

<section class="benefits" style="padding: 60px 20px; background: #f8f9fa;">
    <div class="container" style="max-width: 1200px; margin: 0 auto;">
        <h2 style="text-align: center; color: #003366; font-size: 2rem; margin-bottom: 50px;">Benefits & Perks</h2>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 30px;">
            <div style="background: white; padding: 30px; border-radius: 10px; text-align: center;">
                <div style="font-size: 2.5rem; margin-bottom: 15px;">💰</div>
                <h4 style="color: #003366;">Competitive Salary</h4>
            </div>
            <div style="background: white; padding: 30px; border-radius: 10px; text-align: center;">
                <div style="font-size: 2.5rem; margin-bottom: 15px;">🏥</div>
                <h4 style="color: #003366;">Health Insurance</h4>
            </div>
            <div style="background: white; padding: 30px; border-radius: 10px; text-align: center;">
                <div style="font-size: 2.5rem; margin-bottom: 15px;">🏠</div>
                <h4 style="color: #003366;">Remote Work</h4>
            </div>
            <div style="background: white; padding: 30px; border-radius: 10px; text-align: center;">
                <div style="font-size: 2.5rem; margin-bottom: 15px;">📚</div>
                <h4 style="color: #003366;">Learning Budget</h4>
            </div>
            <div style="background: white; padding: 30px; border-radius: 10px; text-align: center;">
                <div style="font-size: 2.5rem; margin-bottom: 15px;">🌴</div>
                <h4 style="color: #003366;">Unlimited PTO</h4>
            </div>
            <div style="background: white; padding: 30px; border-radius: 10px; text-align: center;">
                <div style="font-size: 2.5rem; margin-bottom: 15px;">📈</div>
                <h4 style="color: #003366;">Stock Options</h4>
            </div>
        </div>
    </div>
</section>

<section class="openings" style="padding: 80px 20px;">
    <div class="container" style="max-width: 1000px; margin: 0 auto;">
        <h2 style="text-align: center; color: #003366; font-size: 2rem; margin-bottom: 50px;">Open Positions</h2>
        
        <div style="border: 1px solid #e0e0e0; border-radius: 10px; margin-bottom: 20px; overflow: hidden;">
            <div style="padding: 25px; display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <h4 style="color: #003366; margin-bottom: 5px;">Senior Cloud Architect</h4>
                    <p style="color: #666; font-size: 0.9rem;">San Francisco, CA • Full-time</p>
                </div>
                <a href="/contact" style="background: #0066CC; color: white; padding: 10px 25px; border-radius: 5px; text-decoration: none;">Apply</a>
            </div>
        </div>
        
        <div style="border: 1px solid #e0e0e0; border-radius: 10px; margin-bottom: 20px; overflow: hidden;">
            <div style="padding: 25px; display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <h4 style="color: #003366; margin-bottom: 5px;">Data Engineer</h4>
                    <p style="color: #666; font-size: 0.9rem;">Remote • Full-time</p>
                </div>
                <a href="/contact" style="background: #0066CC; color: white; padding: 10px 25px; border-radius: 5px; text-decoration: none;">Apply</a>
            </div>
        </div>
        
        <div style="border: 1px solid #e0e0e0; border-radius: 10px; margin-bottom: 20px; overflow: hidden;">
            <div style="padding: 25px; display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <h4 style="color: #003366; margin-bottom: 5px;">Project Manager</h4>
                    <p style="color: #666; font-size: 0.9rem;">New York, NY • Full-time</p>
                </div>
                <a href="/contact" style="background: #0066CC; color: white; padding: 10px 25px; border-radius: 5px; text-decoration: none;">Apply</a>
            </div>
        </div>
        
    </div>
</section>
''',
            'meta_title': 'Careers - Husmerk',
            'meta_description': 'Join Husmerk and build your career in technology consulting. Explore open positions and benefits.',
        },
    ]
    
    for page_data in pages_data:
        page, created = Page.objects.get_or_create(
            site=site,
            slug=page_data['slug'],
            defaults={
                'title': page_data['title'],
                'path': page_data.get('path', f"/{page_data['slug']}"),
                'html': page_data.get('html', ''),
                'is_homepage': page_data.get('is_homepage', False),
                'seo': {
                    'title': page_data.get('meta_title', ''),
                    'description': page_data.get('meta_description', ''),
                },
                'status': 'published',
            }
        )
        if created:
            print(f"  ✓ Created page: {page_data['title']}")
    
    print(f"✓ Created {len(pages_data)} pages for Husmerk site")


def create_navigation(site):
    """Create navigation menu."""
    nav, created = NavigationMenu.objects.get_or_create(
        site=site,
        name='Main Navigation',
        defaults={
            'location': 'header',
            'items': [
                {'label': 'Home', 'url': '/', 'order': 1},
                {'label': 'Services', 'url': '/services', 'order': 2},
                {'label': 'Industries', 'url': '/industries', 'order': 3},
                {'label': 'About', 'url': '/about', 'order': 4},
                {'label': 'Careers', 'url': '/careers', 'order': 5},
                {'label': 'Shop', 'url': '/shop', 'order': 6},
                {'label': 'Blog', 'url': '/blog', 'order': 7},
                {'label': 'Contact', 'url': '/contact', 'order': 8},
            ]
        }
    )
    if created:
        print(f"✓ Created navigation menu")


def create_blog_content(site):
    """Create blog categories, tags, and posts."""
    
    # Categories
    categories_data = [
        {'name': 'Technology Insights', 'slug': 'technology-insights'},
        {'name': 'Digital Transformation', 'slug': 'digital-transformation'},
        {'name': 'Cloud Computing', 'slug': 'cloud-computing'},
        {'name': 'Data & Analytics', 'slug': 'data-analytics'},
        {'name': 'Industry News', 'slug': 'industry-news'},
    ]
    
    categories = {}
    for cat_data in categories_data:
        cat, created = PostCategory.objects.get_or_create(
            site=site,
            slug=cat_data['slug'],
            defaults={'name': cat_data['name']}
        )
        categories[cat_data['slug']] = cat
    
    # Tags
    tags_data = ['AI', 'Machine Learning', 'Cloud', 'AWS', 'Azure', 'DevOps', 'Security', 'Innovation', 'Strategy', 'Leadership']
    tags = {}
    for tag_name in tags_data:
        tag, created = PostTag.objects.get_or_create(
            site=site,
            slug=tag_name.lower().replace(' ', '-'),
            defaults={'name': tag_name}
        )
        tags[tag_name] = tag
    
    # Posts
    posts_data = [
        {
            'title': '5 Key Trends Shaping Enterprise Technology in 2026',
            'slug': '5-key-trends-enterprise-technology-2026',
            'excerpt': 'Explore the top technology trends that are transforming how enterprises operate and compete in the digital age.',
            'content': '''
<p>The enterprise technology landscape continues to evolve at an unprecedented pace. As we move through 2026, several key trends are reshaping how organizations approach digital transformation.</p>

<h2>1. AI-Powered Automation</h2>
<p>Artificial intelligence is no longer just a buzzword—it's becoming the backbone of enterprise operations. From intelligent document processing to predictive maintenance, AI is automating complex tasks that previously required human intervention.</p>

<h2>2. Multi-Cloud Strategies</h2>
<p>Organizations are increasingly adopting multi-cloud approaches to avoid vendor lock-in and optimize costs. This trend requires sophisticated cloud management tools and expertise.</p>

<h2>3. Zero Trust Security</h2>
<p>With remote work becoming permanent for many organizations, zero trust security models are essential. Every access request is verified, regardless of where it originates.</p>

<h2>4. Edge Computing</h2>
<p>As IoT devices proliferate, processing data at the edge reduces latency and bandwidth costs while enabling real-time decision making.</p>

<h2>5. Sustainable IT</h2>
<p>Environmental concerns are driving organizations to optimize their IT infrastructure for energy efficiency and reduced carbon footprint.</p>

<p>At Husmerk, we help enterprises navigate these trends and implement solutions that drive real business value. Contact us to learn how we can support your digital transformation journey.</p>
''',
            'category': 'technology-insights',
            'tags': ['AI', 'Cloud', 'Innovation'],
        },
        {
            'title': 'The Complete Guide to Cloud Migration',
            'slug': 'complete-guide-cloud-migration',
            'excerpt': 'A comprehensive guide to planning and executing a successful cloud migration strategy for your organization.',
            'content': '''
<p>Cloud migration is one of the most significant technology initiatives an organization can undertake. Done right, it can transform your business. Done wrong, it can be costly and disruptive.</p>

<h2>Planning Your Migration</h2>
<p>Before moving a single workload, you need a comprehensive assessment of your current infrastructure, applications, and data. This includes understanding dependencies, compliance requirements, and business priorities.</p>

<h2>Choosing the Right Approach</h2>
<p>Not all applications should be migrated the same way. The "6 Rs" framework helps categorize your approach:</p>
<ul>
<li><strong>Rehost</strong> - Lift and shift</li>
<li><strong>Replatform</strong> - Lift and optimize</li>
<li><strong>Repurchase</strong> - Move to SaaS</li>
<li><strong>Refactor</strong> - Re-architect for cloud</li>
<li><strong>Retire</strong> - Decommission</li>
<li><strong>Retain</strong> - Keep on-premises</li>
</ul>

<h2>Managing the Migration</h2>
<p>Successful migrations require strong project management, clear communication, and robust testing. Plan for rollback scenarios and ensure your team is trained on new tools and processes.</p>

<p>Husmerk has helped dozens of enterprises successfully migrate to the cloud. Our proven methodology minimizes risk while maximizing the benefits of cloud computing.</p>
''',
            'category': 'cloud-computing',
            'tags': ['Cloud', 'AWS', 'Azure', 'Strategy'],
        },
        {
            'title': 'How Data Analytics is Transforming Healthcare',
            'slug': 'data-analytics-transforming-healthcare',
            'excerpt': 'Discover how healthcare organizations are leveraging data analytics to improve patient outcomes and operational efficiency.',
            'content': '''
<p>The healthcare industry is experiencing a data revolution. From electronic health records to wearable devices, the volume of healthcare data is growing exponentially—and organizations that can harness this data are gaining significant competitive advantages.</p>

<h2>Predictive Analytics for Patient Care</h2>
<p>Machine learning models can now predict patient deterioration, readmission risk, and disease progression with remarkable accuracy. This enables proactive interventions that improve outcomes and reduce costs.</p>

<h2>Operational Optimization</h2>
<p>Analytics is helping healthcare organizations optimize staffing, reduce wait times, and improve resource utilization. Real-time dashboards give administrators visibility into operations across multiple facilities.</p>

<h2>Population Health Management</h2>
<p>By analyzing data across patient populations, healthcare systems can identify at-risk groups and implement targeted prevention programs.</p>

<h2>The Path Forward</h2>
<p>While the potential is enormous, healthcare organizations face unique challenges including data privacy regulations, interoperability issues, and the need for clinical validation of AI models.</p>

<p>Husmerk's healthcare practice combines deep industry expertise with cutting-edge analytics capabilities to help organizations realize the full potential of their data.</p>
''',
            'category': 'data-analytics',
            'tags': ['AI', 'Machine Learning', 'Innovation'],
        },
    ]
    
    for post_data in posts_data:
        post, created = Post.objects.get_or_create(
            site=site,
            slug=post_data['slug'],
            defaults={
                'title': post_data['title'],
                'excerpt': post_data['excerpt'],
                'body_html': post_data['content'],
                'status': 'published',
            }
        )
        if created:
            post.categories.add(categories[post_data['category']])
            for tag_name in post_data['tags']:
                post.tags.add(tags[tag_name])
            print(f"  ✓ Created blog post: {post_data['title']}")
    
    print(f"✓ Created blog content: {len(categories_data)} categories, {len(tags_data)} tags, {len(posts_data)} posts")


def create_ecommerce(site):
    """Create e-commerce store with products."""
    
    # Product Categories
    categories_data = [
        {'name': 'Technology Books', 'slug': 'technology-books', 'description': 'Essential reading for technology professionals'},
        {'name': 'Online Courses', 'slug': 'online-courses', 'description': 'Self-paced learning programs'},
        {'name': 'Consulting Packages', 'slug': 'consulting-packages', 'description': 'Professional consulting services'},
        {'name': 'Software Tools', 'slug': 'software-tools', 'description': 'Productivity and development tools'},
    ]
    
    categories = {}
    for cat_data in categories_data:
        cat, created = ProductCategory.objects.get_or_create(
            site=site,
            slug=cat_data['slug'],
            defaults={
                'name': cat_data['name'],
                'description': cat_data['description'],
            }
        )
        categories[cat_data['slug']] = cat
    
    # Products
    products_data = [
        {
            'name': 'Digital Transformation Playbook',
            'slug': 'digital-transformation-playbook',
            'description': 'A comprehensive guide to leading digital transformation initiatives in your organization. Includes frameworks, case studies, and practical tools.',
            'price': '49.99',
            'category': 'technology-books',
            'sku': 'BOOK-DT-001',
            'stock': 100,
            'image_url': 'https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?w=500',
        },
        {
            'name': 'Cloud Architecture Masterclass',
            'slug': 'cloud-architecture-masterclass',
            'description': '20-hour online course covering cloud architecture patterns, best practices, and hands-on labs. Includes AWS and Azure modules.',
            'price': '299.00',
            'category': 'online-courses',
            'sku': 'COURSE-CA-001',
            'stock': 999,
            'image_url': 'https://images.unsplash.com/photo-1516321318423-f06f85e504b3?w=500',
        },
        {
            'name': 'Data Analytics Fundamentals',
            'slug': 'data-analytics-fundamentals',
            'description': '15-hour course on data analytics essentials. Learn SQL, Python basics, and visualization tools.',
            'price': '199.00',
            'category': 'online-courses',
            'sku': 'COURSE-DA-001',
            'stock': 999,
            'image_url': 'https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=500',
        },
        {
            'name': 'Technology Strategy Assessment',
            'slug': 'technology-strategy-assessment',
            'description': '2-week engagement to assess your current technology landscape and develop a strategic roadmap. Includes stakeholder interviews and detailed report.',
            'price': '5000.00',
            'category': 'consulting-packages',
            'sku': 'CONSULT-TSA-001',
            'stock': 10,
            'image_url': 'https://images.unsplash.com/photo-1552664730-d307ca884978?w=500',
        },
        {
            'name': 'Cloud Migration Planning Package',
            'slug': 'cloud-migration-planning',
            'description': '4-week engagement to plan your cloud migration. Includes application assessment, cost modeling, and migration roadmap.',
            'price': '15000.00',
            'category': 'consulting-packages',
            'sku': 'CONSULT-CMP-001',
            'stock': 5,
            'image_url': 'https://images.unsplash.com/photo-1544197150-b99a580bb7a8?w=500',
        },
        {
            'name': 'Enterprise Architecture Toolkit',
            'slug': 'enterprise-architecture-toolkit',
            'description': 'Collection of templates, frameworks, and tools for enterprise architects. Includes TOGAF-aligned artifacts.',
            'price': '149.00',
            'category': 'software-tools',
            'sku': 'TOOL-EAT-001',
            'stock': 999,
            'image_url': 'https://images.unsplash.com/photo-1460925895917-afdab827c52f?w=500',
        },
        {
            'name': 'DevOps Automation Scripts Bundle',
            'slug': 'devops-automation-scripts',
            'description': 'Ready-to-use automation scripts for CI/CD pipelines, infrastructure provisioning, and monitoring setup.',
            'price': '79.00',
            'category': 'software-tools',
            'sku': 'TOOL-DAS-001',
            'stock': 999,
            'image_url': 'https://images.unsplash.com/photo-1618401471353-b98afee0b2eb?w=500',
        },
        {
            'name': 'AI/ML Implementation Guide',
            'slug': 'ai-ml-implementation-guide',
            'description': 'Practical guide to implementing AI and machine learning in enterprise environments. Covers use case identification, model development, and deployment.',
            'price': '59.99',
            'category': 'technology-books',
            'sku': 'BOOK-AI-001',
            'stock': 75,
            'image_url': 'https://images.unsplash.com/photo-1677442136019-21780ecad995?w=500',
        },
    ]
    
    for prod_data in products_data:
        product, created = Product.objects.get_or_create(
            site=site,
            slug=prod_data['slug'],
            defaults={
                'title': prod_data['name'],
                'excerpt': prod_data['description'][:200],
                'description_html': f"<p>{prod_data['description']}</p>",
                'status': 'published',
            }
        )
        if created:
            product.categories.add(categories[prod_data['category']])
            # Create default variant with pricing
            ProductVariant.objects.get_or_create(
                product=product,
                sku=prod_data['sku'],
                defaults={
                    'title': 'Default',
                    'price': prod_data['price'],
                    'inventory': prod_data['stock'],
                    'is_default': True,
                }
            )
            print(f"  ✓ Created product: {prod_data['name']} - ${prod_data['price']}")
    
    # Shipping Zones
    zone, created = ShippingZone.objects.get_or_create(
        site=site,
        name='Worldwide',
        defaults={
            'countries': ['US', 'CA', 'GB', 'DE', 'FR', 'AU'],
        }
    )
    if created:
        ShippingRate.objects.create(
            zone=zone,
            name='Standard Shipping',
            method_code='standard',
            price='9.99',
        )
        ShippingRate.objects.create(
            zone=zone,
            name='Express Shipping',
            method_code='express',
            price='19.99',
            estimated_days_min=1,
            estimated_days_max=3,
        )
        print(f"  ✓ Created shipping zone with rates")
    
    # Tax Rates
    TaxRate.objects.get_or_create(
        site=site,
        name='US Sales Tax',
        defaults={
            'rate': '0.0825',
            'countries': ['US'],
        }
    )
    
    # Discount Codes
    discounts = [
        {'code': 'WELCOME10', 'discount_type': 'percentage', 'value': '10.00'},
        {'code': 'SAVE20', 'discount_type': 'percentage', 'value': '20.00'},
        {'code': 'FLAT50', 'discount_type': 'fixed', 'value': '50.00', 'min_purchase': '200.00'},
    ]
    
    for disc_data in discounts:
        DiscountCode.objects.get_or_create(
            site=site,
            code=disc_data['code'],
            defaults={
                'discount_type': disc_data['discount_type'],
                'value': disc_data['value'],
                'min_purchase': disc_data.get('min_purchase', '0'),
            }
        )
    
    print(f"✓ Created e-commerce: {len(categories_data)} categories, {len(products_data)} products, {len(discounts)} discount codes")


def create_forms(site):
    """Create contact and newsletter forms."""
    
    # Contact Form
    contact_form, created = Form.objects.get_or_create(
        site=site,
        slug='contact-form',
        defaults={
            'name': 'Contact Form',
            'description': 'Main contact form for inquiries',
            'success_message': 'Thank you for your message. We will get back to you within 24 hours.',
            'notify_emails': ['info@husmerk.com'],
            'status': 'active',
            'fields': [
                {'id': 'name', 'type': 'text', 'label': 'Full Name', 'name': 'name', 'required': True},
                {'id': 'email', 'type': 'email', 'label': 'Email Address', 'name': 'email', 'required': True},
                {'id': 'company', 'type': 'text', 'label': 'Company', 'name': 'company', 'required': False},
                {'id': 'phone', 'type': 'tel', 'label': 'Phone Number', 'name': 'phone', 'required': False},
                {'id': 'message', 'type': 'textarea', 'label': 'How can we help?', 'name': 'message', 'required': True},
            ],
        }
    )
    
    if created:
        print(f"  ✓ Created contact form with 5 fields")
    
    # Newsletter Form
    newsletter_form, created = Form.objects.get_or_create(
        site=site,
        slug='newsletter',
        defaults={
            'name': 'Newsletter Signup',
            'description': 'Subscribe to our newsletter',
            'success_message': 'Thank you for subscribing! You will receive our latest insights in your inbox.',
            'notify_emails': ['marketing@husmerk.com'],
            'status': 'active',
            'fields': [
                {'id': 'email', 'type': 'email', 'label': 'Email Address', 'name': 'email', 'required': True},
            ],
        }
    )
    
    if created:
        print(f"  ✓ Created newsletter form")
    
    print(f"✓ Created forms")


def main():
    print("=" * 60)
    print("SMC Web Builder - Demo Data Setup")
    print("=" * 60)
    print()
    
    # Create users
    admin = create_admin()
    user = create_user()
    
    # Create workspace
    workspace = create_workspace(admin)
    
    # Create Husmerk site
    site = create_husmerk_site(admin, workspace)
    
    # Create pages
    create_pages(site)
    
    # Create navigation
    create_navigation(site)
    
    # Create blog content
    create_blog_content(site)
    
    # Create e-commerce
    create_ecommerce(site)
    
    # Create forms
    create_forms(site)
    
    print()
    print("=" * 60)
    print("SETUP COMPLETE!")
    print("=" * 60)
    print()
    print("CREDENTIALS:")
    print(f"  Admin: admin / Admin123!@#")
    print(f"  User:  testuser / User123!@#")
    print()
    print("PREVIEW LINKS:")
    print(f"  Frontend: http://localhost:3000")
    print(f"  Editor:   http://localhost:3000/editor")
    print(f"  Admin:    http://localhost:3000/platform-admin")
    print(f"  Backend:  http://localhost:8000/admin/")
    print()
    print("HUSMERK SITE:")
    print(f"  Site Slug: husmerk")
    print(f"  Pages: Home, Services, About, Industries, Contact, Careers")
    print(f"  Blog: 3 posts with categories and tags")
    print(f"  Shop: 8 products in 4 categories")
    print(f"  Discount Codes: WELCOME10, SAVE20, FLAT50")
    print()


if __name__ == '__main__':
    main()
