FROM python:3.11-slim-bookworm

ENV LANG=C.UTF-8 \
    ODOO_VERSION=19.0

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libxml2-dev \
    libxslt1-dev \
    libldap2-dev \
    libsasl2-dev \
    libssl-dev \
    libjpeg-dev \
    libpq-dev \
    libffi-dev \
    node-less \
    npm \
    git \
    curl \
    unzip \
    wkhtmltopdf \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Create odoo user
RUN useradd -m -d /odoo -U -r -s /bin/bash odoo

# Copy and install enterprise
COPY enterprise-19.0.zip /tmp/enterprise.zip
RUN unzip /tmp/enterprise.zip -d /odoo/enterprise && rm /tmp/enterprise.zip

# Copy upgraded addons (from upgrade.zip)
COPY upgraded.zip /tmp/upgraded.zip
RUN unzip /tmp/upgraded.zip -d /odoo/upgraded && rm /tmp/upgraded.zip

# Copy custom addons
COPY addons/ /odoo/addons/

# Install Odoo python deps from enterprise
RUN pip install --no-cache-dir \
    -r /odoo/enterprise/odoo-19.0/requirements.txt \
    lxml-html-clean \
    phonenumbers

# Odoo config
COPY odoo.conf /etc/odoo/odoo.conf

RUN chown -R odoo:odoo /odoo /etc/odoo

VOLUME ["/var/lib/odoo"]
EXPOSE 8069

USER odoo
CMD ["python3", "/odoo/enterprise/odoo-19.0/odoo-bin", "-c", "/etc/odoo/odoo.conf"]