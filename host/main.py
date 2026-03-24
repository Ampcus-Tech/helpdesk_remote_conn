import asyncio
import random
import string
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.config import setup_logging
from host.gui import HostGUI

def generate_host_id(length=6):
    return ''.join(random.choices(string.digits, k=length))

def main():
    setup_logging()
    
    # Launch GUI
    app = HostGUI()
    app.run()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Host terminated by user")
