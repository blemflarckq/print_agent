"""Unpackaged entry point (`python main.py`). For distribution, build with:

    pyinstaller --onefile --noconsole --name BahmniPrintAgent main.py

and place the resulting BahmniPrintAgent.exe alongside a real config.json
(copied from config.example.json) on each of the clinic PCs.
"""
from print_agent.tray import run

if __name__ == "__main__":
    run()
