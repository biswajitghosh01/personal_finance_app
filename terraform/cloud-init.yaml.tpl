#cloud-config
package_update: true
package_upgrade: true

packages:
  - python3-venv
  - python3-pip
  - nginx
  - git
  - certbot
  - python3-certbot-nginx
  - ufw
  - fail2ban
  - unattended-upgrades

write_files:
  - path: /opt/finance/.env
    permissions: '0600'
    content: |
      SECRET_KEY=REPLACE_ME
      DATA_KEY=REPLACE_ME
      DEFAULT_USER=admin
      DEFAULT_PASSWORD=${admin_password}
      ALLOWED_HOSTS=${domain_name},localhost,127.0.0.1
      SESSION_COOKIE_SECURE=true
      TRUSTED_PROXY_COUNT=1
      BIND_HOST=127.0.0.1
      BIND_PORT=5555

runcmd:
  # Clone repository
  - mkdir -p /opt/finance
  - chown ubuntu:ubuntu /opt/finance
  - sudo -u ubuntu git clone ${github_repo_url} /opt/finance/app
  - cd /opt/finance/app && sudo -u ubuntu cp /opt/finance/.env .env

  # Generate secrets
  - |
    cd /opt/finance/app
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(64))")
    DATA_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    sed -i "s|REPLACE_ME|$SECRET_KEY|" .env
    sed -i "s|REPLACE_ME|$DATA_KEY|" .env

  # Python environment
  - sudo -u ubuntu python3 -m venv /opt/finance/app/.venv
  - sudo -u ubuntu /opt/finance/app/.venv/bin/pip install -r /opt/finance/app/requirements.txt
  - sudo -u ubuntu /opt/finance/app/.venv/bin/python -c "import sys; sys.path.insert(0, '/opt/finance/app'); import app; app.init_db()"

  # Systemd service
  - |
    cat > /etc/systemd/system/finance.service <<EOF
    [Unit]
    Description=Finance Vault
    After=network.target

    [Service]
    User=ubuntu
    WorkingDirectory=/opt/finance/app
    ExecStart=/opt/finance/app/.venv/bin/python app.py
    Restart=on-failure

    [Install]
    WantedBy=multi-user.target
    EOF

  - systemctl daemon-reload
  - systemctl enable finance
  - systemctl start finance

  # Nginx reverse proxy
  - |
    cat > /etc/nginx/sites-available/finance <<EOF
    server {
        listen 80;
        server_name ${domain_name};
        location / {
            proxy_pass http://127.0.0.1:5555;
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;
        }
    }
    EOF

  - ln -sf /etc/nginx/sites-available/finance /etc/nginx/sites-enabled/
  - rm -f /etc/nginx/sites-enabled/default
  - nginx -t && systemctl reload nginx

  # Firewall
  - ufw allow 22/tcp
  - ufw allow 80/tcp
  - ufw allow 443/tcp
  - ufw --force enable

  # SSL certificate (works once DNS resolves)
  - certbot --nginx -d ${domain_name} --non-interactive --agree-tos -m ${letsencrypt_email} --redirect || true

  # Auto-renewal
  - systemctl enable certbot.timer
  - systemctl start certbot.timer