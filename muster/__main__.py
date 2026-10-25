import argparse
from pathlib import Path

import uvicorn
from dotenv import load_dotenv


def main():
    parser = argparse.ArgumentParser(description="Start Muster on this computer.")
    parser.add_argument("--port", type=int, default=8000, help="Local port (default: 8000)")
    args = parser.parse_args()
    # Read only the launch directory's file. Explicit environment settings win;
    # values are data, never shell commands or interpolated secret references.
    load_dotenv(Path.cwd() / ".env", override=False, interpolate=False)
    uvicorn.run("muster.app:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
