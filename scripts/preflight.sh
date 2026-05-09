#!/usr/bin/env bash
# Preflight checks for Private RAG Accelerator development environment
# Exits non-zero if any required tool is missing or not properly configured

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

ERRORS=0

echo "=========================================="
echo "Private RAG Accelerator - Preflight Check"
echo "=========================================="
echo ""

# Check Azure CLI
echo -n "Checking Azure CLI... "
if command -v az &> /dev/null; then
    AZ_VERSION=$(az version --query '"azure-cli"' -o tsv 2>/dev/null || echo "unknown")
    echo -e "${GREEN}✓${NC} Installed (v${AZ_VERSION})"
    
    # Check if logged in
    echo -n "  Checking Azure CLI login status... "
    if az account show &> /dev/null; then
        ACCOUNT=$(az account show --query name -o tsv 2>/dev/null || echo "unknown")
        echo -e "${GREEN}✓${NC} Logged in (${ACCOUNT})"
    else
        echo -e "${RED}✗${NC} Not logged in. Run 'az login' to authenticate."
        ERRORS=$((ERRORS + 1))
    fi
else
    echo -e "${RED}✗${NC} Azure CLI not found. Install from https://aka.ms/installazurecli"
    ERRORS=$((ERRORS + 1))
fi

# Check Azure Developer CLI (azd)
echo -n "Checking Azure Developer CLI (azd)... "
if command -v azd &> /dev/null; then
    AZD_VERSION=$(azd version 2>/dev/null | head -1 || echo "unknown")
    echo -e "${GREEN}✓${NC} Installed (${AZD_VERSION})"
else
    echo -e "${RED}✗${NC} azd not found. Install from https://aka.ms/azure-dev/install"
    ERRORS=$((ERRORS + 1))
fi

# Check Docker
echo -n "Checking Docker... "
if command -v docker &> /dev/null; then
    DOCKER_VERSION=$(docker --version 2>/dev/null | cut -d ' ' -f 3 | tr -d ',' || echo "unknown")
    echo -e "${GREEN}✓${NC} Installed (v${DOCKER_VERSION})"
    
    # Check if Docker daemon is running
    echo -n "  Checking Docker daemon status... "
    if docker info &> /dev/null; then
        echo -e "${GREEN}✓${NC} Running"
    else
        echo -e "${RED}✗${NC} Docker daemon not running. Start Docker Desktop or the Docker service."
        ERRORS=$((ERRORS + 1))
    fi
else
    echo -e "${RED}✗${NC} Docker not found. Install from https://docs.docker.com/get-docker/"
    ERRORS=$((ERRORS + 1))
fi

# Check Node.js (version 20+)
echo -n "Checking Node.js... "
if command -v node &> /dev/null; then
    NODE_VERSION=$(node --version 2>/dev/null | tr -d 'v' || echo "0")
    NODE_MAJOR=$(echo "$NODE_VERSION" | cut -d '.' -f 1)
    if [ "$NODE_MAJOR" -ge 20 ]; then
        echo -e "${GREEN}✓${NC} Installed (v${NODE_VERSION})"
    else
        echo -e "${YELLOW}⚠${NC} Node.js v${NODE_VERSION} found, but v20+ is required."
        ERRORS=$((ERRORS + 1))
    fi
else
    echo -e "${RED}✗${NC} Node.js not found. Install v20+ from https://nodejs.org/"
    ERRORS=$((ERRORS + 1))
fi

# Check Python (version 3.12+)
echo -n "Checking Python... "
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version 2>/dev/null | cut -d ' ' -f 2 || echo "0")
    PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d '.' -f 1)
    PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d '.' -f 2)
    if [ "$PYTHON_MAJOR" -ge 3 ] && [ "$PYTHON_MINOR" -ge 12 ]; then
        echo -e "${GREEN}✓${NC} Installed (v${PYTHON_VERSION})"
    else
        echo -e "${YELLOW}⚠${NC} Python v${PYTHON_VERSION} found, but v3.12+ is required."
        ERRORS=$((ERRORS + 1))
    fi
elif command -v python &> /dev/null; then
    PYTHON_VERSION=$(python --version 2>/dev/null | cut -d ' ' -f 2 || echo "0")
    PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d '.' -f 1)
    PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d '.' -f 2)
    if [ "$PYTHON_MAJOR" -ge 3 ] && [ "$PYTHON_MINOR" -ge 12 ]; then
        echo -e "${GREEN}✓${NC} Installed (v${PYTHON_VERSION})"
    else
        echo -e "${YELLOW}⚠${NC} Python v${PYTHON_VERSION} found, but v3.12+ is required."
        ERRORS=$((ERRORS + 1))
    fi
else
    echo -e "${RED}✗${NC} Python not found. Install v3.12+ from https://www.python.org/"
    ERRORS=$((ERRORS + 1))
fi

# Summary
echo ""
echo "=========================================="
if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}All preflight checks passed!${NC}"
    echo "You're ready to run 'azd up' to deploy the accelerator."
    exit 0
else
    echo -e "${RED}${ERRORS} check(s) failed.${NC}"
    echo "Please resolve the issues above before proceeding."
    exit 1
fi
