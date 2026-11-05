"""Command line:  python -m fixflow "my laptop won't charge past 80%" --serial PF3K9X21"""

from __future__ import annotations

import argparse

from .agent import FixFlowAgent
from .config import Settings
from .schemas import SupportRequest
from .tools import Store


def main() -> None:
    parser = argparse.ArgumentParser(prog="fixflow", description="Triage one IT-support request.")
    parser.add_argument("text", help="the problem, in the user's words")
    parser.add_argument("--serial", default=None, help="device serial number")
    parser.add_argument("--trace", action="store_true", help="show every step the agent took")
    parser.add_argument("--save", action="store_true", help="write tickets to the database (default: in memory)")
    args = parser.parse_args()

    settings = Settings()
    store = None if args.save else Store(":memory:", settings.devices_csv)
    result = FixFlowAgent(settings, store=store).handle(SupportRequest(text=args.text, serial=args.serial))

    print(f"Action:     {result.action}")
    print(f"Category:   {result.category}  ->  team: {result.team}")
    print(f"Urgency:    {result.urgency}   confidence: {result.confidence:.2f}")
    print(f"Why:        {' '.join(result.reasons)}")
    if result.ticket_id:
        print(f"Ticket:     {result.ticket_id}")
    print("\n" + result.answer)
    if args.trace:
        print("\nTrace:")
        for step in result.trace:
            print("  - " + step)


if __name__ == "__main__":
    main()
