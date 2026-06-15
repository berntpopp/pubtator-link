# PubTator-Link Docker Deployment

Production-ready Docker setup for PubTator-Link with multi-stage builds and optimized configurations.

## 🚀 Quick Start

### Development Setup

```bash
# Copy environment template (if not already done)
cp .env.example .env

# Build and run development server
cd docker
docker-compose up --build
```

Server available at `http://localhost:8000` with API docs at `/docs`.

The default Compose stack also starts PostgreSQL for the review re-RAG POC. The
database is initialized from `pubtator_link/db/review_schema.sql` the first time
the `pubtator_postgres_data` volume is created.

### Production Deployment

```bash
# Build and run production server
cd docker
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## 📁 File Structure

```
docker/
├── Dockerfile                 # Multi-stage production build
├── docker-compose.yml         # Development configuration
├── docker-compose.prod.yml    # Production overrides
├── docker-compose.dev.yml     # Hot-reload development (optional)
├── gunicorn_conf.py          # Production WSGI configuration
└── README.md                 # This file

# Environment files (in project root)
├── .env.example              # Local development template
└── .dockerignore             # Build optimization
```

## 🔧 Configuration

Key environment variables (edit `.env`):

```env
# Server settings
PUBTATOR_LINK_HOST=127.0.0.1
PUBTATOR_LINK_PORT=8000
PUBTATOR_LINK_LOG_LEVEL=INFO
PUBTATOR_LINK_TRANSPORT=unified

# API settings
PUBTATOR_LINK_API_BASE_URL=https://www.ncbi.nlm.nih.gov/research/pubtator3-api
PUBTATOR_LINK_RATE_LIMIT_PER_SECOND=2.5

# CORS settings (list format required)
PUBTATOR_LINK_CORS_ORIGINS=["http://localhost:3000","http://localhost:8080"]

# Cache settings
PUBTATOR_LINK_CACHE_SIZE=1000
PUBTATOR_LINK_CACHE_TTL=3600

# Review re-RAG PostgreSQL settings
PUBTATOR_LINK_POSTGRES_DB=pubtator_link
PUBTATOR_LINK_POSTGRES_USER=pubtator_link
PUBTATOR_LINK_POSTGRES_PASSWORD=pubtator_link
PUBTATOR_LINK_POSTGRES_PORT=5434
PUBTATOR_LINK_DATABASE_URL=postgresql://pubtator_link:pubtator_link@localhost:5434/pubtator_link

# Production scaling
GUNICORN_WORKERS=4
GUNICORN_LOG_LEVEL=warning
```

## 🏗️ Architecture

**Multi-Stage Build:**
- **Builder**: Installs dependencies in virtual environment
- **Production**: Minimal runtime image with non-root user

**Development vs Production:**
- Development: Simple uvicorn server, debug logging
- Production: Gunicorn + Uvicorn workers, JSON logging, resource limits
- PostgreSQL: Compose-managed database for review re-RAG storage; production
  overlays do not publish the database port to the host

## 🐳 Deployment Options

### Local Development
```bash
docker-compose up --build
```

To apply the schema to an already existing database volume after schema changes:

```bash
PUBTATOR_LINK_DATABASE_URL=postgresql://pubtator_link:pubtator_link@localhost:5434/pubtator_link make db-init
```

### Hot-Reload Development (optional)
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

### Production (Local Server)
```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## Nginx Proxy Manager Deployment

1. Copy `.env.docker.example` to `.env.docker` and set your domain and PostgreSQL password.
2. Ensure the NPM Docker network exists. The default is `npm_default`.
3. Start PubTator-Link without publishing host ports:

```bash
docker compose -f docker/docker-compose.yml \
  -f docker/docker-compose.prod.yml \
  -f docker/docker-compose.npm.yml \
  --env-file .env.docker \
  up -d --build
```

For the Strato VPS manager in `strato_v6_docker_npm`, configure the project with
multiple compose files so the base service, production hardening, and NPM network
override are all loaded:

```yaml
compose_files:
  - docker/docker-compose.yml
  - docker/docker-compose.prod.yml
  - docker/docker-compose.npm.yml
env_file: .env.docker
containers:
  - pubtator_link_server
  - pubtator_link_postgres
health_check:
  endpoint: /health
  container: pubtator_link_server
  port: 8000
```

4. In Nginx Proxy Manager, create a Proxy Host:
   - Domain Names: your `PUBTATOR_LINK_PUBLIC_DOMAIN`
   - Scheme: `http`
   - Forward Hostname / IP: `pubtator_link_server`
   - Forward Port: `8000`
   - Enable Websockets Support
   - Enable Block Common Exploits
   - Request a Let's Encrypt certificate and force SSL

The MCP endpoint is available at `https://your-domain.example/mcp`.

### Container Registry
```bash
# Build and push
docker build -f docker/Dockerfile -t your-registry/pubtator-link:latest .
docker push your-registry/pubtator-link:latest

# Run from registry
docker run -d --name pubtator-link -p 8000:8000 --env-file .env your-registry/pubtator-link:latest
```

## 🔍 Monitoring

- **Health Check**: `curl http://localhost:8000/health`
- **API Documentation**: `http://localhost:8000/docs`
- **Container Logs**: `docker-compose logs -f pubtator-link`
- **Database Logs**: `docker-compose logs -f pubtator-postgres`
- **MCP Status**: Available at `/mcp` endpoint when using unified transport

## 🛠️ Development Workflow

1. Edit source code in `../pubtator_link/`
2. For simple changes: `docker-compose restart pubtator-link`
3. For dependency changes: `docker-compose up --build`

Review re-RAG data lives in the PostgreSQL volume. Rebuilding the image does not
reset or migrate an existing volume. From the repository root, run
`make db-migrate` after pulling review-index schema changes, then restart the
server. If the MCP reports `index_review_evidence` unavailable, call
`diagnostics` and use `get_publication_passages` with the same
PMIDs until `/ready` reports a current schema.

## 🚨 Troubleshooting

**Port conflicts:**
```bash
# Change port in .env
PUBTATOR_LINK_PORT=8001
```

**Permission errors:**
```bash
# Clean build cache
docker system prune -a
docker-compose build --no-cache
```

**CORS configuration:**
- Must use JSON array format in environment variables
- Example: `["http://localhost:3000","http://localhost:8080"]`

**Rate limiting issues:**
- Ensure `PUBTATOR_LINK_RATE_LIMIT_PER_SECOND` is ≤ 3.0 per PubTator3 guidelines
- Default is 2.5 for safety margin

**MCP connection issues:**
```bash
# Check MCP endpoint availability
curl http://localhost:8000/mcp

# Verify transport mode
docker-compose logs pubtator-link | grep transport
```

## 🔐 Security Features

- Non-root container user (`app:app`)
- Minimal base image (Python 3.11 slim)
- No secrets in image layers
- Resource limits and health checks
- Production-grade process management
- Rate limiting compliance with PubTator3 API

## 🧪 Testing Docker Setup

### Test Development Container
```bash
cd docker
docker-compose up --build

# In another terminal
curl http://localhost:8000/health
curl http://localhost:8000/docs

# Confirm the review schema exists
docker-compose exec pubtator-postgres \
  psql -U pubtator_link -d pubtator_link \
  -c "select column_name from information_schema.columns where table_name='reviews' order by ordinal_position;"
```

### Test Production Container
```bash
cd docker
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Test endpoints
curl http://localhost:8000/health
curl http://localhost:8000/api/publications/export?pmids=29355051,32511357
```

### Test Hot-Reload Development
```bash
cd docker
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --build

# Edit a file in ../pubtator_link/ and see auto-reload
```

## 🌐 Production Deployment Guide

### Prerequisites

1. **Server Requirements**:
   - Ubuntu 20.04+ or similar Linux distribution
   - 2GB+ RAM, 1+ CPU cores
   - 20GB+ storage space
   - Root or sudo access

2. **Docker Installation**:
   ```bash
   # Update system packages
   sudo apt update && sudo apt upgrade -y

   # Install Docker and Docker Compose
   sudo apt install -y docker.io docker-compose git

   # Start and enable Docker
   sudo systemctl start docker
   sudo systemctl enable docker

   # Add user to docker group (logout/login required)
   sudo usermod -aG docker $USER
   ```

### Step-by-Step Deployment

#### 1. Project Setup
```bash
# Clone the repository
git clone https://github.com/your-org/pubtator-link.git
cd pubtator-link

# Create production environment file
cp .env.example .env

# Edit environment with your settings
nano .env
```

#### 2. Environment Configuration
Edit `.env` with your specific settings:

```env
# Critical settings to customize:
PUBTATOR_LINK_HOST=0.0.0.0
PUBTATOR_LINK_PORT=8000
PUBTATOR_LINK_LOG_LEVEL=INFO
PUBTATOR_LINK_LOG_FORMAT=json

# API settings (keep defaults unless needed)
PUBTATOR_LINK_RATE_LIMIT_PER_SECOND=2.5

# Production CORS (customize for your domain)
PUBTATOR_LINK_CORS_ORIGINS=["https://yourdomain.com"]

# Production optimizations:
GUNICORN_WORKERS=4
GUNICORN_LOG_LEVEL=warning
```

#### 3. Deploy PubTator-Link
```bash
# Build and deploy with production configuration
cd docker
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# Verify deployment
docker-compose logs -f pubtator-link
```

#### 4. Verification and Testing
```bash
# Check container health
docker exec pubtator_link_server curl -f http://localhost:8000/health

# Test external access
curl http://your-server-ip:8000/health

# Check logs
docker-compose -f docker-compose.yml -f docker-compose.prod.yml logs pubtator-link
```

### Production Monitoring

#### Log Management
```bash
# View real-time logs
docker-compose -f docker-compose.yml -f docker-compose.prod.yml logs -f pubtator-link

# View specific time range
docker-compose logs --since=1h pubtator-link

# Check log file sizes (automatic rotation configured)
docker exec pubtator_link_server ls -la /var/log/
```

#### Health Monitoring
```bash
# Create health check script
cat > /opt/pubtator-health-check.sh << 'EOF'
#!/bin/bash
HEALTH_URL="http://localhost:8000/health"
if curl -f -s "$HEALTH_URL" > /dev/null; then
    echo "$(date): PubTator-Link is healthy"
else
    echo "$(date): PubTator-Link health check failed" >&2
    # Optional: restart container
    # docker-compose -f /path/to/docker-compose.yml restart pubtator-link
fi
EOF

chmod +x /opt/pubtator-health-check.sh

# Add to crontab for periodic checking
(crontab -l ; echo "*/5 * * * * /opt/pubtator-health-check.sh >> /var/log/pubtator-health.log") | crontab -
```

#### Resource Monitoring
```bash
# Monitor container resources
docker stats pubtator_link_server

# Check disk usage
docker system df

# Monitor logs size
docker-compose config | grep max-size
```

### Maintenance and Updates

#### Update Deployment
```bash
# Pull latest changes
git pull origin main

# Rebuild and redeploy
docker-compose -f docker-compose.yml -f docker-compose.prod.yml down
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# Verify health
curl http://localhost:8000/health
```

#### Backup Configuration
```bash
# Backup environment and configs
tar -czf pubtator-backup-$(date +%Y%m%d).tar.gz .env docker/

# Backup to remote location (optional)
scp pubtator-backup-*.tar.gz user@backup-server:/backups/
```

### Troubleshooting Production Deployment

#### Common Issues

**Container won't start:**
```bash
# Check Docker daemon
sudo systemctl status docker

# Check container logs
docker-compose logs pubtator-link

# Verify environment file
cat .env | grep -v "^#" | grep -v "^$"
```

**API rate limiting errors:**
```bash
# Check rate limit settings
docker-compose logs pubtator-link | grep -i rate

# Verify rate limit configuration
curl http://localhost:8000/health
```

**Performance issues:**
```bash
# Monitor resource usage
htop
docker stats

# Check PubTator3 API response times
docker-compose logs pubtator-link | grep -i timeout

# Adjust worker count in .env
# GUNICORN_WORKERS=2  # For lower-spec servers
```

### Security Hardening

#### Firewall Configuration
```bash
# Configure UFW firewall
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 8000/tcp  # PubTator-Link port
sudo ufw enable
```

#### Regular Updates
```bash
# System updates
sudo apt update && sudo apt upgrade -y

# Docker updates
sudo apt update docker.io docker-compose

# Container updates (schedule monthly)
docker-compose pull && docker-compose up -d
```

This comprehensive deployment guide provides everything needed to run PubTator-Link in production with Docker containerization.
