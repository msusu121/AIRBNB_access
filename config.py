import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    SECRET_KEY = os.getenv("FLASK_SECRET", "change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URI", "sqlite:///dev.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    TESSERACT_CMD = os.getenv("TESSERACT_CMD")
    TIMEZONE = os.getenv("TZ", "Africa/Nairobi")
