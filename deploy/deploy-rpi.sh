#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# CostOptimizer - Raspberry Pi Deployment Script
# Domain: www.strategybuilder.in
# Sets up: PostgreSQL DB, systemd services, nginx, SSL
# ============================================================

DOMAIN="www.strategybuilder.in"
PROJECT_NAME="costoptimizer"
DB_NAME="costoptimizer"
DB_USER="costopt"
DB_PASS="costopt_$(openssl rand -hex 8)"

# Auto-detect paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
FRONTEND_DIR="${PROJECT_DIR}/frontend"
VENV_DIR="${PROJECT_DIR}/venv"
LOG_DIR="/var/log/${PROJECT_NAME}"
RUN_USER="$(stat -c '%U' "$PROJECT_DIR" 2>/dev/null || stat -f '%Su' "$PROJECT_DIR")"
RUN_GROUP="$(stat -c '%G' "$PROJECT_DIR" 2>/dev/null || stat -f '%Sg' "$PROJECT_DIR")"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ============================================================
# Pre-flight checks
# ============================================================
preflight() {
    info "Running pre-flight checks..."

    [[ $EUID -eq 0 ]] || error "Run this script as root (sudo ./deploy-rpi.sh)"

    command -v psql   >/dev/null || error "PostgreSQL client not found. Install postgresql-17"
    command -v nginx  >/dev/null || error "nginx not found. Install with: apt install nginx"
    command -v node   >/dev/null || error "node not found. Install Node.js 18+"
    command -v npm    >/dev/null || error "npm not found"

    [[ -d "$PROJECT_DIR/src" ]]    || error "Project dir invalid: $PROJECT_DIR"
    [[ -d "$FRONTEND_DIR/src" ]]   || error "Frontend dir not found: $FRONTEND_DIR"
    [[ -d "$VENV_DIR" ]]           || error "Python venv not found at $VENV_DIR. Create with: python3 -m venv venv"
    [[ -f "$VENV_DIR/bin/python" ]] || error "venv python not found"

    info "Project dir : $PROJECT_DIR"
    info "Frontend dir: $FRONTEND_DIR"
    info "Venv dir    : $VENV_DIR"
    info "Run as      : $RUN_USER:$RUN_GROUP"
}

# ============================================================
# 1. PostgreSQL database setup
# ============================================================
setup_database() {
    info "Setting up PostgreSQL database..."

    # Create or update role with the generated password
    if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1; then
        sudo -u postgres psql -c "ALTER ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASS}';"
        info "Database role '${DB_USER}' updated with new password"
    else
        sudo -u postgres psql -c "CREATE ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASS}';"
        info "Created database role '${DB_USER}'"
    fi

    # Check if database exists
    if sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
        info "Database '${DB_NAME}' already exists"
    else
        sudo -u postgres psql -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"
        info "Created database '${DB_NAME}'"
    fi

    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};"

    # Ensure schema permissions
    sudo -u postgres psql -d "${DB_NAME}" -c "GRANT ALL ON SCHEMA public TO ${DB_USER};"

    # Configure pg_hba.conf for password auth (local + network)
    PG_HBA=$(sudo -u postgres psql -tAc "SHOW hba_file")
    PG_HBA=$(echo "$PG_HBA" | xargs)  # trim whitespace

    # Add md5 auth entries if not already present
    if ! grep -q "${DB_USER}" "$PG_HBA" 2>/dev/null; then
        info "Adding password auth rules to pg_hba.conf..."
        # Insert before the first existing rule
        cp "$PG_HBA" "${PG_HBA}.bak.$(date +%s)"
        {
            echo "# CostOptimizer - password auth for ${DB_USER}"
            echo "local   ${DB_NAME}   ${DB_USER}                          md5"
            echo "host    ${DB_NAME}   ${DB_USER}   127.0.0.1/32           md5"
            echo "host    ${DB_NAME}   ${DB_USER}   ::1/128                md5"
            echo "host    ${DB_NAME}   ${DB_USER}   0.0.0.0/0             md5"
        } | cat - "$PG_HBA" > "${PG_HBA}.tmp" && mv "${PG_HBA}.tmp" "$PG_HBA"
        chown postgres:postgres "$PG_HBA"
        chmod 640 "$PG_HBA"

        # Reload PostgreSQL to apply pg_hba changes
        systemctl reload postgresql
        info "PostgreSQL reloaded with new auth rules"
    fi

    # Verify connection works
    if PGPASSWORD="${DB_PASS}" psql -h 127.0.0.1 -U "${DB_USER}" -d "${DB_NAME}" -c "SELECT 1" >/dev/null 2>&1; then
        info "Database connection verified successfully"
    else
        warn "Database connection test failed. Check pg_hba.conf and PostgreSQL logs."
    fi
}

# ============================================================
# 2. Production .env file
# ============================================================
setup_env() {
    info "Configuring production .env..."

    ENV_FILE="${PROJECT_DIR}/.env.production"

    cat > "$ENV_FILE" <<EOF
# CostOptimizer Production Config - Generated $(date -Iseconds)

# App
COSTOPT_ENVIRONMENT=production
COSTOPT_DEBUG=false
COSTOPT_SECRET_KEY=$(openssl rand -hex 32)

# Database (PostgreSQL 17 on localhost)
COSTOPT_DATABASE_URL=postgresql+asyncpg://${DB_USER}:${DB_PASS}@localhost:5432/${DB_NAME}

# Redis (disabled - no Celery workers on RPi)
# COSTOPT_REDIS_URL=redis://localhost:6379/0

# AWS
COSTOPT_AWS_EXTERNAL_ID_PREFIX=costopt

# Azure
COSTOPT_AZURE_TENANT_ID=
COSTOPT_AZURE_CLIENT_ID=
COSTOPT_AZURE_CLIENT_SECRET=

# GCP
COSTOPT_GCP_CREDENTIALS_PATH=

# LLM - External API only (no local Ollama)
COSTOPT_LLM_PROVIDER=claude
COSTOPT_ANTHROPIC_API_KEY=
COSTOPT_ANTHROPIC_MODEL=claude-sonnet-4-20250514
COSTOPT_LOCAL_LLM_URL=
COSTOPT_LOCAL_LLM_MODEL=

# Features
COSTOPT_ENABLE_AUTO_REMEDIATION=false
COSTOPT_ENABLE_ML_PREDICTIONS=true
EOF

    # Symlink as .env
    ln -sf "$ENV_FILE" "${PROJECT_DIR}/.env"
    chown "$RUN_USER:$RUN_GROUP" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    info "Production .env written (LLM provider set to 'claude' - no local AI)"
}

# ============================================================
# 3. Install Python dependencies & run migrations
# ============================================================
setup_backend() {
    info "Installing backend dependencies..."

    sudo -u "$RUN_USER" bash -c "
        source '${VENV_DIR}/bin/activate'
        pip install --quiet --upgrade pip
        pip install --quiet -r '${PROJECT_DIR}/requirements.txt'
    "

    info "Running database migrations..."
    sudo -u "$RUN_USER" bash -c "
        cd '${PROJECT_DIR}'
        source '${VENV_DIR}/bin/activate'
        alembic upgrade head
    "
}

# ============================================================
# 4. Build frontend for production
# ============================================================
build_frontend() {
    info "Building frontend for production..."

    sudo -u "$RUN_USER" bash -c "
        cd '${FRONTEND_DIR}'
        npm ci --silent
        npm run build
    "

    DIST_DIR="${FRONTEND_DIR}/dist"
    [[ -d "$DIST_DIR" ]] || error "Frontend build failed - dist/ not found"
    info "Frontend built at $DIST_DIR"
}

# ============================================================
# 5. Log directory
# ============================================================
setup_logs() {
    info "Setting up log directory at ${LOG_DIR}..."
    mkdir -p "$LOG_DIR"
    chown "$RUN_USER:$RUN_GROUP" "$LOG_DIR"

    # Logrotate
    cat > /etc/logrotate.d/${PROJECT_NAME} <<EOF
${LOG_DIR}/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 ${RUN_USER} ${RUN_GROUP}
    postrotate
        systemctl reload ${PROJECT_NAME}-api 2>/dev/null || true
    endscript
}
EOF
    info "Logrotate configured (14 days retention)"
}

# ============================================================
# 6. Systemd service - Backend API
# ============================================================
install_backend_service() {
    info "Installing systemd service: ${PROJECT_NAME}-api"

    cat > /etc/systemd/system/${PROJECT_NAME}-api.service <<EOF
[Unit]
Description=CostOptimizer FastAPI Backend
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=exec
User=${RUN_USER}
Group=${RUN_GROUP}
WorkingDirectory=${PROJECT_DIR}
EnvironmentFile=${PROJECT_DIR}/.env.production
ExecStart=${VENV_DIR}/bin/uvicorn src.api.main:app \\
    --host 127.0.0.1 \\
    --port 8000 \\
    --workers 2 \\
    --log-level info \\
    --access-log
StandardOutput=append:${LOG_DIR}/api.log
StandardError=append:${LOG_DIR}/api-error.log
Restart=always
RestartSec=5

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=${PROJECT_DIR} ${LOG_DIR}
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
}

# ============================================================
# 7. Nginx config (multi-project friendly)
# ============================================================
install_nginx() {
    info "Configuring nginx for ${DOMAIN}..."

    DIST_DIR="${FRONTEND_DIR}/dist"

    cat > /etc/nginx/sites-available/${PROJECT_NAME} <<EOF
server {
    listen 80;
    server_name ${DOMAIN};

    # Frontend - serve built React app
    root ${DIST_DIR};
    index index.html;

    # Logs
    access_log ${LOG_DIR}/nginx-access.log;
    error_log  ${LOG_DIR}/nginx-error.log;

    # API proxy
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
        proxy_connect_timeout 10s;
    }

    # WebSocket support (for real-time updates)
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_read_timeout 86400;
    }

    # Health check endpoint
    location /health {
        proxy_pass http://127.0.0.1:8000/health;
    }

    # SPA fallback - all non-file routes serve index.html
    location / {
        try_files \$uri \$uri/ /index.html;
    }

    # Cache static assets
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff2?)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
}
EOF

    # Enable site
    ln -sf /etc/nginx/sites-available/${PROJECT_NAME} /etc/nginx/sites-enabled/

    # Remove default site if it exists (won't conflict with other projects)
    rm -f /etc/nginx/sites-enabled/default

    nginx -t || error "Nginx config test failed"
    info "Nginx configured for ${DOMAIN}"
}

# ============================================================
# 8. SSL with Let's Encrypt
# ============================================================
setup_ssl() {
    info "Setting up SSL with Let's Encrypt..."

    if ! command -v certbot >/dev/null; then
        apt-get install -y certbot python3-certbot-nginx
    fi

    certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos \
        --email "admin@${DOMAIN}" --redirect \
        || warn "Certbot failed - ensure DNS points to this server. Run manually later:
         sudo certbot --nginx -d ${DOMAIN}"
}

# ============================================================
# 9. Enable and start services
# ============================================================
start_services() {
    info "Enabling and starting services..."

    systemctl daemon-reload
    systemctl enable --now ${PROJECT_NAME}-api
    systemctl reload nginx

    # Verify
    sleep 3
    if systemctl is-active --quiet ${PROJECT_NAME}-api; then
        info "Backend API: RUNNING"
    else
        warn "Backend API failed to start. Check: journalctl -u ${PROJECT_NAME}-api -n 50"
    fi
}

# ============================================================
# 10. Print summary
# ============================================================
print_summary() {
    echo ""
    echo "============================================================"
    echo -e "${GREEN} CostOptimizer Deployment Complete${NC}"
    echo "============================================================"
    echo ""
    echo "  Domain     : https://${DOMAIN}"
    echo "  Backend    : http://127.0.0.1:8000 (proxied via nginx)"
    echo "  Frontend   : Served from ${FRONTEND_DIR}/dist"
    echo ""
    echo "  Database   : ${DB_NAME} (PostgreSQL 17)"
    echo "  DB User    : ${DB_USER}"
    echo "  DB Password: ${DB_PASS}"
    echo "  LLM        : External API only (Anthropic Claude)"
    echo ""
    echo "  Logs       : ${LOG_DIR}/"
    echo "    api.log        - Backend stdout"
    echo "    api-error.log  - Backend stderr"
    echo "    nginx-access.log"
    echo "    nginx-error.log"
    echo ""
    echo "  Services:"
    echo "    sudo systemctl status ${PROJECT_NAME}-api"
    echo "    sudo journalctl -u ${PROJECT_NAME}-api -f"
    echo ""
    echo "  IMPORTANT:"
    echo "    1. Set COSTOPT_ANTHROPIC_API_KEY in ${PROJECT_DIR}/.env.production"
    echo "    2. Set cloud credentials (AWS/Azure/GCP) as needed"
    echo "    3. Ensure DNS A record for ${DOMAIN} points to this RPi"
    echo "    4. DB password saved in .env.production (chmod 600)"
    echo ""
    echo "============================================================"
}

# ============================================================
# Main
# ============================================================
main() {
    info "Starting CostOptimizer deployment to Raspberry Pi..."
    echo ""

    preflight
    setup_database
    setup_env
    setup_backend
    build_frontend
    setup_logs
    install_backend_service
    install_nginx
    setup_ssl
    start_services
    print_summary
}

main "$@"
