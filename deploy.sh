#!/bin/bash

# BST Akademi Production Deployment Script

echo "Starting BST Akademi deployment..."

# Update system packages
echo "Updating system packages..."
sudo apt-get update
sudo apt-get upgrade -y

# Install required packages
echo "Installing required packages..."
sudo apt-get install -y python3-pip python3-venv nginx

# Create system user for the application
echo "Creating system user..."
sudo useradd -r -s /bin/false bstportal

# Create directories
echo "Creating directories..."
sudo mkdir -p /var/www/bst-portal
sudo mkdir -p /var/www/bst-portal/media
sudo mkdir -p /var/www/bst-portal/staticfiles

# Clone or copy the application
echo "Setting up application..."
# If using git: sudo git clone https://github.com/yourusername/bst-portal.git /var/www/bst-portal
# If using local copy: cp -r /path/to/local/bst-portal/* /var/www/bst-portal/

# Apply least-privilege permissions after application files are in place.
echo "Setting permissions..."
sudo chown -R bstportal:www-data /var/www/bst-portal
sudo find /var/www/bst-portal -type d -exec chmod 750 {} \;
sudo find /var/www/bst-portal -type f -exec chmod 640 {} \;

# Create virtual environment
echo "Creating virtual environment..."
sudo -u bstportal python3 -m venv /var/www/bst-portal/venv

# Install dependencies
echo "Installing dependencies..."
sudo -u bstportal /var/www/bst-portal/venv/bin/pip install -r /var/www/bst-portal/requirements.txt

# Refuse deployment when effective production security settings are incomplete.
echo "Checking production security settings..."
sudo -u bstportal /var/www/bst-portal/venv/bin/python /var/www/bst-portal/manage.py check --deploy --fail-level WARNING

# Collect static files
echo "Collecting static files..."
sudo -u bstportal /var/www/bst-portal/venv/bin/python /var/www/bst-portal/manage.py collectstatic --noinput

# Run migrations
echo "Running migrations..."
sudo -u bstportal /var/www/bst-portal/venv/bin/python /var/www/bst-portal/manage.py migrate

# Create Gunicorn service file
echo "Creating Gunicorn service..."
sudo cat > /etc/systemd/system/bstportal.service << 'SERVICE'
[Unit]
Description=BST Akademi Gunicorn daemon
After=network.target

[Service]
User=bstportal
Group=www-data
UMask=0027
WorkingDirectory=/var/www/bst-portal
ExecStart=/var/www/bst-portal/venv/bin/gunicorn \
          --access-logfile - \
          --workers 3 \
          --bind unix:/var/www/bst-portal/bstportal.sock \
          bst_portal.wsgi:application

[Install]
WantedBy=multi-user.target
SERVICE

# Create Nginx configuration
echo "Creating Nginx configuration..."
sudo cat > /etc/nginx/sites-available/bstportal << 'NGINX'
server {
    listen 80;
    server_name bstakademi.com www.bstakademi.com;
    client_max_body_size 64m;
    add_header X-Content-Type-Options nosniff always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=()" always;
    
    location = /favicon.ico { access_log off; log_not_found off; }
    
    location /static/ {
        alias /var/www/bst-portal/staticfiles/;
    }
    
    location /media/ {
        alias /var/www/bst-portal/media/;
        add_header X-Content-Type-Options nosniff always;
        add_header Content-Security-Policy "default-src 'none'; sandbox" always;
    }

    location /media/projects/media/ {
        include proxy_params;
        proxy_pass http://unix:/var/www/bst-portal/bstportal.sock;
    }

    location /media/knowledge/ {
        deny all;
    }

    location ~ /\. {
        deny all;
    }
    
    location / {
        include proxy_params;
        proxy_pass http://unix:/var/www/bst-portal/bstportal.sock;
    }
}
NGINX

# Enable Nginx site
echo "Enabling Nginx site..."
sudo ln -s /etc/nginx/sites-available/bstportal /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx

# Start Gunicorn service
echo "Starting Gunicorn service..."
sudo systemctl enable bstportal
sudo systemctl start bstportal

# Set up firewall
echo "Configuring firewall..."
sudo ufw allow 'Nginx Full'
sudo ufw enable

echo "Deployment completed successfully!"
echo "Please configure SSL certificate using Certbot:"
echo "sudo certbot --nginx -d bstakademi.com -d www.bstakademi.com"
