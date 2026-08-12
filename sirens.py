#!/usr/bin/env python3
"""Sirens — friendly launcher.

Run this and pick a number. No commands to remember.

    python sirens.py
"""
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "sample_incidents"
PY = sys.executable


def run(args):
    print()
    subprocess.run([PY, str(ROOT / "cli.py")] + args)
    print()


def pause():
    input("\nPress Enter to return to the menu...")


def menu():
    while True:
        print("=" * 56)
        print("  SIRENS — Counter-IED Incident Link Analysis")
        print("=" * 56)
        print("  1)  Analyse the sample incidents (show link report)")
        print("  2)  Build the interactive link chart and open it")
        print("  3)  Pre-arrival brief for an area (ask me questions)")
        print("  4)  Run the tests (check everything works)")
        print("  5)  Analyse MY folder of reports (you give the path)")
        print("  6)  Generate a big synthetic dataset (100 reports + answer key)")
        print("  7)  Evaluate accuracy against the answer key (precision/recall)")
        print("  8)  Open the web console (browser UI: type reports, compare, AI)")
        print("  9)  Import a folder of reports INTO the database")
        print(" 10)  Analyse EVERYTHING saved in the database")
        print("  0)  Quit")
        choice = input("\n  Choose a number: ").strip()

        if choice == "1":
            run(["analyze", str(DATA)])
            pause()
        elif choice == "2":
            out = ROOT / "link_chart.html"
            run(["analyze", str(DATA), "--html", str(out)])
            print(f"Opening {out} in your browser...")
            try:
                webbrowser.open(out.as_uri())
            except Exception:
                print(f"(Could not auto-open. Open this file yourself: {out})")
            pause()
        elif choice == "3":
            loc = input("  Area / location (e.g. Route Copper): ").strip()
            if not loc:
                print("  Need a location."); continue
            desc = input("  Describe the object (optional, Enter to skip): ").strip()
            photo = input("  Photo filename (optional, Enter to skip): ").strip()
            args = ["brief", str(DATA), "--location", loc]
            if desc:
                args += ["--describe", desc]
            if photo:
                args += ["--photo", photo]
            run(args)
            pause()
        elif choice == "4":
            print()
            subprocess.run([PY, "-m", "pytest", str(ROOT / "tests"), "-q"])
            pause()
        elif choice == "5":
            path = input("  Path to your folder of .json/.txt reports: ").strip()
            if path:
                run(["analyze", path])
            pause()
        elif choice == "6":
            print()
            subprocess.run([PY, str(ROOT / "generate_incidents.py"),
                            "--n", "100", "--out", str(ROOT / "data" / "generated")])
            print("\nGenerated into data/generated/. Analyse it with option 5 (path: data/generated)")
            pause()
        elif choice == "7":
            print()
            subprocess.run([PY, str(ROOT / "evaluate.py"),
                            "--data", str(ROOT / "data" / "generated")])
            print("\n(If this says 'no incidents', run option 6 first to generate the data.)")
            pause()
        elif choice == "8":
            print("\n  Starting the web console at http://127.0.0.1:5000")
            print("  Your browser should open automatically.")
            print("  Press Ctrl+C in this window to stop it and return here.\n")
            try:
                subprocess.run([PY, str(ROOT / "app.py")])
            except KeyboardInterrupt:
                pass
            pause()
        elif choice == "9":
            path = input("  Path to your folder of .json/.txt reports "
                         "(Enter for the samples): ").strip()
            run(["import", path or str(DATA)])
            pause()
        elif choice == "10":
            out = ROOT / "link_chart.html"
            run(["db", "--html", str(out)])
            if out.exists():
                print(f"Opening {out} in your browser...")
                try:
                    webbrowser.open(out.as_uri())
                except Exception:
                    print(f"(Open this file yourself: {out})")
            pause()
        elif choice == "0":
            print("  Bye.")
            return
        else:
            print("  Please type one of the numbers shown.\n")


if __name__ == "__main__":
    try:
        menu()
    except KeyboardInterrupt:
        print("\n  Bye.")
