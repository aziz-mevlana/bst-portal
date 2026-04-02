# BST Akademi Deployment Checklist

## Before Deployment

### 1. Environment Configuration
- [ ] Set `DEBUG=False` in production
- [ ] Configure `ALLOWED_HOSTS` with production domain
- [ ] Set up secure `SECRET_KEY` in environment variables
- [ ] Configure database connection (PostgreSQL recommended)
- [ ] Set up email backend credentials

### 2. Security Settings
- [ ] Enable `SECURE_SSL_REDIRECT`
- [ ] Set `SESSION_COOKIE_SECURE=True`
- [ ] Set `CSRF_COOKIE_SECURE=True`
- [ ] Enable `SECURE_BROWSER_XSS_FILTER`
- [ ] Enable `SECURE_CONTENT_TYPE_NOSNIFF`
- [ ] Set `X_FRAME_OPTIONS=DENY`

### 3. Static and Media Files
- [ ] Configure `STATIC_ROOT` and `MEDIA_ROOT`
- [ ] Set up WhiteNoise for static files
- [ ] Configure file permissions (755 for directories, 644 for files)

### 4. Database
- [ ] Backup existing database
- [ ] Run migrations: `python manage.py migrate`
- [ ] Create superuser: `python manage.py createsuperuser`
- [ ] Test database connection

### 5. Email Configuration
- [ ] Set up SMTP credentials
- [ ] Test email sending functionality
- [ ] Configure `DEFAULT_FROM_EMAIL`

## Server Setup

### 1. System Requirements
- [ ] Install Python 3.11+
- [ ] Install PostgreSQL (or use SQLite for small sites)
- [ ] Install Nginx
- [ ] Install Certbot for SSL

### 2. Application Setup
- [ ] Create virtual environment
- [ ] Install dependencies: `pip install -r requirements.txt`
- [ ] Collect static files: `python manage.py collectstatic`
- [ ] Set up Gunicorn service
- [ ] Configure Nginx

### 3. SSL Certificate
- [ ] Install Certbot: `sudo apt install certbot python3-certbot-nginx`
- [ ] Obtain certificate: `sudo certbot --nginx -d bstakademi.com -d www.bstakademi.com`
- [ ] Set up auto-renewal

## Post-Deployment

### 1. Testing
- [ ] Test all pages load correctly
- [ ] Test user registration/login
- [ ] Test file uploads (media files)
- [ ] Test email sending
- [ ] Test admin interface

### 2. Monitoring
- [ ] Set up log monitoring
- [ ] Configure error tracking
- [ ] Set up backup schedule

### 3. Maintenance
- [ ] Regular database backups
- [ ] Update dependencies regularly
- [ ] Monitor disk space
- [ ] Review security logs

## Environment Variables Template

Create a `.env` file in the project root:

```bash
# Django Settings
DJANGO_SECRET_KEY=your-secret-key-here
DEBUG=False
ALLOWED_HOSTS=bstakademi.com,www.bstakademi.com

# Database (PostgreSQL)
DATABASE_URL=postgresql://user:password@localhost:5432/bstakademi

# Email Settings
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=noreply@bstakademi.com

# Security Settings
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True

# File Paths
STATIC_ROOT=/var/www/bstakademi/static
MEDIA_ROOT=/var/www/bstakademi/media

# Logging
LOG_LEVEL=INFO
```

## Troubleshooting

### Common Issues

1. **Static files not loading**
   - Run `python manage.py collectstatic`
   - Check Nginx static file configuration
   - Verify file permissions

2. **Database connection errors**
   - Check database credentials in `.env`
   - Verify PostgreSQL is running: `sudo systemctl status postgresql`
   - Check database user permissions

3. **Gunicorn service not starting**
   - Check logs: `sudo journalctl -u bstakademi`
   - Verify virtual environment path
   - Check socket file permissions

4. **Nginx 502 Bad Gateway**
   - Check if Gunicorn is running: `sudo systemctl status bstakademi`
   - Verify socket file exists: `ls -la /var/www/bstakademi/bstakademi.sock`
   - Check Nginx error logs: `sudo tail -f /var/log/nginx/error.log`

### Useful Commands

```bash
# View Gunicorn logs
sudo journalctl -u bstakademi -f

# View Nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log

# Restart services
sudo systemctl restart bstakademi
sudo systemctl restart nginx

# Check service status
sudo systemctl status bstakademi
sudo systemctl status nginx

# Run Django management commands
sudo -u bstakademi /var/www/bstakademi/venv/bin/python /var/www/bstakademi/manage.py <command>
```

## Security Best Practices

1. **Keep Django updated** to the latest version
2. **Use strong passwords** for all accounts
3. **Enable two-factor authentication** for admin accounts
4. **Regularly backup** your database and media files
5. **Monitor logs** for suspicious activity
6. **Use HTTPS** everywhere (already configured)
7. **Disable debug mode** in production (already configured)
8. **Use environment variables** for sensitive data (already configured)

## Contact Support

For issues or questions, please refer to:
- Django documentation: https://docs.djangoproject.com/
- BST Akademi documentation: [Add your documentation link]
