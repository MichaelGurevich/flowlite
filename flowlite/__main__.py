"""FlowLite: local, private Wispr Flow-style dictation for Windows.

    python -m flowlite.setup      # once: download the speech model, check the Ollama model
    python -m flowlite.shortcut   # once: put a FlowLite icon on the Desktop / Start menu
    python -m flowlite            # run (Flow Bar + tray + hub window); hold Ctrl+Win and talk
"""

import argparse

from . import privacy

privacy.install()  # before anything else: this process never talks to the internet

from . import instance, store  # noqa: E402


def main():
    p = argparse.ArgumentParser(prog="flowlite")
    p.add_argument("--settings", action="store_true", help="open the settings window on start")
    args = p.parse_args()
    instance.redirect_output_if_headless(store.DATA_DIR / "flowlite.log")
    if not instance.claim_or_signal():
        print("FlowLite is already running; asked it to open its window.")
        return
    from .qtui.app import FlowLiteApp
    app = FlowLiteApp(open_settings=args.settings)
    app.run()
    print("FlowLite stopped.")


if __name__ == "__main__":
    main()
