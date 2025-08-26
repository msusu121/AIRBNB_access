import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    SECRET_KEY = os.getenv("FLASK_SECRET", "change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URI", "sqlite:///dev.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    TESSERACT_CMD = os.getenv("TESSERACT_CMD")
    TIMEZONE = os.getenv("TZ", "Africa/Nairobi")



MPESA_BASE_URL="https://sandbox.safaricom.co.ke"
MPESA_CONSUMER_KEY="8VfQRp5SH9VGjlGiJrtGPPpfwXnMIOZBD1wV9n18ClthaDlr"
MPESA_CONSUMER_SECRET="qaXhXmjLiMGerC3eKzGnbdUAiospLgQpPGQWlV7M6nraxQ4X9axKZbIFmgoJ5Wnw"
MPESA_SHORTCODE=174379       # default test
MPESA_PASSKEY=...            # from Daraja portal
MPESA_CALLBACK_URL="https://your-ngrok-or-prod.com/billing/mpesa/callback"
BASIC_PRICE_KES=1
PREMIUM_PRICE_KES=5000      
