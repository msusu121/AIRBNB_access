import sys, os
# Ensure app directory is on the path
sys.path.insert(0, os.path.dirname(__file__))

from app import app as application  # 'application' is required by Passenger
