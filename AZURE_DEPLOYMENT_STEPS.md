# ACCIO — Azure Deployment Steps

## Step 1: Azure Resources to Create

Create these in Azure Portal in this order:

1. **Resource Group** — e.g. `rg-accio-prod`
2. **Azure SQL Database**
   - Server: create new, e.g. `accio-sql-server`
   - Database: `accio`
   - Tier: Serverless, General Purpose (cheapest)
   - Allow Azure services to access: YES
   - Note the connection string from Portal > SQL Database > Connection strings > ODBC
3. **Azure Storage Account**
   - Name: e.g. `acciostorage`
   - Redundancy: LRS
   - After creation: Create a blob container named `accio-uploads` (access level: Private)
   - Note the connection string from Portal > Storage Account > Access keys
4. **Azure App Service**
   - Runtime: Python 3.12
   - OS: Linux
   - Plan: B1 (Basic)
   - Region: same as your SQL and Storage

## Step 2: Configure App Settings in Azure Portal

Go to App Service > Configuration > Application Settings and add ALL keys from `.azure-env-template.txt`.

Key ones:
- `SECRET_KEY` — generate a long random string
- `FLASK_ENV` = `production`
- `FLASK_DEBUG` = `false`
- `SQLALCHEMY_DATABASE_URI` — Azure SQL ODBC connection string
- `MAIL_USERNAME` and `MAIL_PASSWORD`
- `AZURE_STORAGE_CONNECTION_STRING`
- `AZURE_STORAGE_CONTAINER` = `accio-uploads`

## Step 3: Deploy the App

**Option A — ZIP Deploy (quickest for first deployment):**
```bash
# From project root
zip -r accio.zip . -x "*.pyc" -x "__pycache__/*" -x "instance/*" -x ".git/*" -x ".env"
az webapp deployment source config-zip --resource-group rg-accio-prod --name <your-app-name> --src accio.zip
```

**Option B — GitHub Actions (for ongoing CI/CD):**
- Go to App Service > Deployment Center > GitHub
- Connect your repo and branch
- Azure auto-generates a GitHub Actions workflow

## Step 4: Set Startup Command

In App Service > Configuration > General Settings:
```
gunicorn --bind=0.0.0.0:8000 --workers=2 --timeout=120 --access-logfile=- --error-logfile=- app:app
```

## Step 5: First-Time Database Initialization

The app auto-creates tables on first request via `db.create_all()` in `create_app()`.
On first load, the seed admin account is created:
- **Email:** admin@company.com
- **Password:** Admin123 (you will be forced to change this on first login)

## Step 6: Verify Everything Works

1. Visit your app URL — should see ACCIO login page
2. Login with admin@company.com / Admin123
3. Change password when prompted
4. Create a test ticket with a file attachment
5. Verify the attachment appears in your Azure Blob Storage container

## Cost Estimate (Monthly)
| Service | Tier | Est. Cost |
|---|---|---|
| App Service | B1 Linux | ~$13 |
| Azure SQL | Serverless | ~$5 |
| Azure Blob Storage | LRS | ~$1 |
| Email (Office365 SMTP) | Existing | $0 |
| **Total** | | **~$19–25/month** |