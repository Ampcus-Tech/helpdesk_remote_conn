import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.config import setup_logging
from client.gui import ClientGUI

def main():
    setup_logging()
    
    # Launch GUI
    app = ClientGUI()
    app.run()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Client terminated by user")
