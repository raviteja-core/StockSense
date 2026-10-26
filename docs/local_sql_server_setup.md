# Local SQL Server 2022 Setup Guide (Docker on WSL2 / Linux)

This guide provides instructions for provisioning, configuring, and connecting to a local Microsoft SQL Server 2022 Developer edition instance in Docker on WSL2 (Ubuntu 22.04) for **StockSense**.

---

## 1. Run SQL Server 2022 in Docker

Run the official Microsoft SQL Server 2022 Linux container:

```bash
docker run -e "ACCEPT_EULA=Y" \
   -e "MSSQL_SA_PASSWORD=YourStrongSA_Password123!" \
   -p 1433:1433 \
   --name sqlserver2022 \
   --hostname sqlserver2022 \
   --restart unless-stopped \
   -d mcr.microsoft.com/mssql/server:2022-latest
```

Verify the container is healthy:
```bash
docker ps
docker logs sqlserver2022 | grep "Recovery is complete"
```

---

## 2. Install ODBC Driver 18 and sqlcmd on Ubuntu 22.04 (WSL2)

If not already installed on your WSL2 distribution:

```bash
# Import Microsoft repository GPG keys and list
curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | sudo gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg
curl -fsSL https://packages.microsoft.com/config/ubuntu/22.04/prod.list | sudo tee /etc/apt/sources.list.d/mssql-release.list

sudo apt-get update
sudo ACCEPT_EULA=Y apt-get install -y msodbcsql18 mssql-tools18 unixodbc-dev

# Add sqlcmd to PATH
echo 'export PATH="$PATH:/opt/mssql-tools18/bin"' >> ~/.bashrc
source ~/.bashrc
```

---

## 3. Create the Database and Dedicated Login

Connect using `sqlcmd` as `sa` and create the `stocksense` database and the application user `stocksense_user`:

```bash
sqlcmd -S localhost,1433 -U sa -P 'YourStrongSA_Password123!' -C -Q "
CREATE DATABASE stocksense;
GO
USE stocksense;
GO
CREATE LOGIN stocksense_user WITH PASSWORD = 'YourStrongUserPassword!';
GO
CREATE USER stocksense_user FOR LOGIN stocksense_user;
GO
ALTER ROLE db_owner ADD MEMBER stocksense_user;
GO
"
```

Test the connection with the application user:
```bash
sqlcmd -S localhost,1433 -U stocksense_user -P 'YourStrongUserPassword!' -C -d stocksense -Q "SELECT DB_NAME(), SUSER_NAME();"
```

---

## 4. Environment Configuration (.env)

Set the credentials in `.env` (this file is excluded by `.gitignore`):

```env
DB_SERVER=localhost,1433
DB_NAME=stocksense
DB_USER=stocksense_user
DB_PASSWORD=YourStrongUserPassword!
DB_DRIVER=ODBC Driver 18 for SQL Server
DB_TRUST_SERVER_CERT=yes
DB_CONNECTION_TIMEOUT=30
```

---

## 5. Troubleshooting Common Issues

1. **SSL / Certificate Validation (`SSL Provider: [error:0A000086:...]`):**
   ODBC Driver 18 enables encryption by default. For local development with self-signed container certificates, pass `TrustServerCertificate=yes` (handled automatically via `DB_TRUST_SERVER_CERT=yes` in `src/config.py`).

2. **Special Characters in Passwords (`@`, `#`, etc.):**
   Do not interpolate passwords directly into raw connection strings. StockSense uses `sqlalchemy.engine.URL.create(...)` which automatically escapes all special characters safely.

3. **Port Binding / WSL2:**
   If running Docker inside WSL2, `localhost,1433` is directly accessible from within the WSL2 terminal and Windows host via WSL2 localhost mirroring.
