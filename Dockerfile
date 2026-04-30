FROM odoo:19

USER root

RUN apt-get update && apt-get install -y --no-install-recommends unzip \
    && rm -rf /var/lib/apt/lists/*

COPY enterprise-19.0.zip /tmp/enterprise.zip
RUN unzip /tmp/enterprise.zip -d /tmp/enterprise \
    && cp -r /tmp/enterprise/enterprise-19.0/* /mnt/extra-addons/ \
    && rm -rf /tmp/enterprise /tmp/enterprise.zip

RUN pip install --no-cache-dir --break-system-packages \
    lxml-html-clean \
    phonenumbers \
    google-auth

USER odoo
