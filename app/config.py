from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Anthropic
    anthropic_api_key: str = ""

    # GitHub
    github_token: str = ""
    github_webhook_secret: str = ""

    # HubSpot
    hubspot_api_key: str = ""

    # Jira
    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    jira_project_key: str = "DEV"

    # Google Sheets — supports both file and env var
    google_service_account_json: str = "./credentials/google_service_account.json"
    google_credentials_json: str = ""   # full JSON string for Render deployment
    google_sheet_id: str = ""
    google_sheet_tab: str = "Code Issues"

    # Email — Resend
    resend_api_key: str = ""
    smtp_from: str = "onboarding@resend.dev"

    # Legacy SMTP
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    slack_webhook_url: str = ""

    # App
    app_env: str = "development"
    secret_key: str = "change_me"
    followup_interval_hours: int = 48

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


def get_settings() -> Settings:
    return Settings()